"""Bulk-fetch merged procedure exports and build cleaned section shards.

Usage:
    python -m rebuild_vel.fetch \
        --station-info station_info_view.csv --flow-config calibration_fore_config_flow_view.csv \
        --begin-time "2025-09-01 00:00:00.000" --end-time "2025-09-30 23:59:59.999" \
        --output data/raw [--stations 00620,00319] [--chunk-size 20] [--max-measurements N]

Resume: re-running the same command continues from ``fetch_state.json`` / the
append-only ledger; already-completed measurements are skipped.
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from .accounts import AccountPool
from .catalog import StationDevice, load_catalog, summarize
from .client import FlowClient, PermanentAPIError, RemoteAPIError
from .parse import parse_merged_export
from .quality import QualityOptions, SectionQualityError, clean_measurement

logger = logging.getLogger(__name__)

DEFAULT_STATION_INFO = r"F:\测算一体预报智能体\read_data\station_info_view.csv"
DEFAULT_FLOW_CONFIG = r"F:\测算一体预报智能体\read_data\calibration_fore_config_flow_view.csv"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch merged procedure exports")
    parser.add_argument("--station-info", default=DEFAULT_STATION_INFO)
    parser.add_argument("--flow-config", default=DEFAULT_FLOW_CONFIG)
    parser.add_argument("--begin-time", required=True)
    parser.add_argument("--end-time", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stations", default="", help="comma-separated station codes")
    parser.add_argument("--chunk-size", type=int, default=20,
                        help="measurements per procedureDataMergeExport call")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-measurements", type=int, default=None)
    parser.add_argument("--request-delay", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--accounts-file", default=None)
    parser.add_argument("--min-lines", type=int, default=8)
    parser.add_argument("--max-target-velocity", type=float, default=5.633)
    return parser.parse_args(argv)


class Ledger:
    """Append-only completion ledger with an in-memory set."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.completed: set[str] = set()
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.completed.add(line.strip())

    def add(self, key: str) -> None:
        if key in self.completed:
            return
        self.completed.add(key)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(key + "\n")

    def __contains__(self, key: str) -> bool:
        return key in self.completed


def _shard_path(root: Path, station: str, device: str) -> Path:
    safe = lambda s: s.replace("|", "_").replace("/", "_")
    return root / "sections" / f"{safe(station)}_{safe(device)}.pkl"


def _append_sections(path: Path, sections: list[dict[str, Any]]) -> None:
    if not sections:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if path.is_file():
        with path.open("rb") as handle:
            existing = pickle.load(handle)
    existing.extend(sections)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        pickle.dump(existing, handle, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(path)


def _log_rejected(root: Path, record: dict[str, Any]) -> None:
    path = root / "rejected.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _process_chunk(
    client: FlowClient,
    entry: StationDevice,
    times: list[str],
    *,
    quality: QualityOptions,
    root: Path,
    no_proc_streak: list[int],
) -> dict[str, int]:
    """Download one merged export, clean it, append to the device shard.

    Some measurements have no procedure-data file on the platform; the export
    endpoint rejects a whole chunk if ANY of them is missing. Bisect down to
    single-measurement chunks and mark the offenders as rejected. When a
    device keeps returning "no procedure data", a circuit breaker stops
    querying it and rejects the remainder without further API calls.
    """
    try:
        payload = client.get_bytes("/flow/procedureDataMergeExport", {
            "stationCode": entry.station_code,
            "deviceCode": entry.device_code,
            "measureTimeList": times,
        })
    except PermanentAPIError as exc:
        if no_proc_streak[0] >= 5:
            for t in times:
                _log_rejected(root, {
                    "station": entry.station_code, "device": entry.device_code,
                    "time": t, "reason": "no_procedure_data",
                    "message": "circuit breaker (device lacks procedure files)",
                })
            return {"accepted": 0, "rejected": len(times), "parse_error": 0}
        if len(times) > 1:
            half = len(times) // 2
            stats = _process_chunk(client, entry, times[:half], quality=quality,
                                   root=root, no_proc_streak=no_proc_streak)
            other = _process_chunk(client, entry, times[half:], quality=quality,
                                   root=root, no_proc_streak=no_proc_streak)
            for key, value in other.items():
                stats[key] = stats.get(key, 0) + value
            return stats
        no_proc_streak[0] += 1
        stats = {"accepted": 0, "rejected": 1, "parse_error": 0}
        _log_rejected(root, {
            "station": entry.station_code, "device": entry.device_code,
            "time": times[0], "reason": "no_procedure_data", "message": str(exc),
        })
        return stats
    no_proc_streak[0] = 0  # a successful export proves the device has files
    stats = {"accepted": 0, "rejected": 0, "parse_error": 0}
    if not payload:
        for t in times:
            stats["rejected"] += 1
            _log_rejected(root, {
                "station": entry.station_code, "device": entry.device_code,
                "time": t, "reason": "empty_export",
            })
        return stats
    parsed = parse_merged_export(payload)
    by_key = {(m["station"], m["device"], m["time"]): m for m in parsed.measurements}
    sections: list[dict[str, Any]] = []
    for t in times:
        # export times come back without milliseconds
        key = next((k for k in by_key if k[2] == t[:19]), None)
        measurement = by_key.get(key) if key else None
        if measurement is None:
            stats["rejected"] += 1
            _log_rejected(root, {
                "station": entry.station_code, "device": entry.device_code,
                "time": t, "reason": "missing_in_export",
            })
            continue
        # the export sheets carry the station *name*, not the code
        measurement["station"] = entry.station_code
        if not measurement.get("station_name"):
            measurement["station_name"] = entry.station_name
        try:
            sections.append(clean_measurement(measurement, quality))
            stats["accepted"] += 1
        except SectionQualityError as exc:
            stats["rejected"] += 1
            _log_rejected(root, {
                "station": entry.station_code, "device": entry.device_code,
                "time": t, "reason": exc.reason, "message": str(exc),
            })
    _append_sections(_shard_path(root, entry.station_code, entry.device_code), sections)
    return stats


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    stations = [value.strip() for value in args.stations.split(",") if value.strip()]
    catalog = load_catalog(args.station_info, args.flow_config, station_codes=stations or None)
    if not catalog:
        raise SystemExit("catalog is empty; check station codes and CSV paths")
    logger.info("catalog: %s", summarize(catalog))

    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root / "ledger.jsonl")
    client = FlowClient(
        AccountPool(args.accounts_file),
        timeout=args.timeout,
        request_delay=args.request_delay,
    )
    quality = QualityOptions(
        min_lines=args.min_lines,
        max_target_velocity=args.max_target_velocity,
    )

    total = {"accepted": 0, "rejected": 0, "parse_error": 0}
    accepted_total = 0
    for entry in catalog:
        buffer: list[str] = []
        last_page = 0
        no_proc_streak = [0]

        def flush() -> None:
            nonlocal buffer
            if not buffer:
                return
            for attempt in range(3):
                try:
                    stats = _process_chunk(client, entry, buffer, quality=quality,
                                           root=root, no_proc_streak=no_proc_streak)
                    break
                except RemoteAPIError as exc:
                    if attempt == 2:
                        raise
                    logger.warning("chunk retry %s for %s|%s (%s): %s",
                                   attempt + 1, entry.station_code, entry.device_code,
                                   len(buffer), exc)
                    time.sleep(5 * (attempt + 1))
            for key_time in buffer:
                ledger.add(f"{entry.station_code}|{entry.device_code}|{key_time}")
            for name, value in stats.items():
                total[name] += value
            buffer = []

        try:
            for page, measurement in client.iter_measurements(
                entry.station_code, entry.device_code,
                args.begin_time, args.end_time,
                page_size=args.page_size,
            ):
                last_page = page
                measure_time = str(measurement.get("measureTime") or "")
                if not measure_time:
                    continue
                key = f"{entry.station_code}|{entry.device_code}|{measure_time}"
                if key in ledger:
                    continue
                buffer.append(measure_time)
                if len(buffer) >= args.chunk_size:
                    flush()
                if args.max_measurements and total["accepted"] >= args.max_measurements:
                    break
        except (RemoteAPIError, PermanentAPIError) as exc:
            logger.error("device %s|%s failed at page %d: %s",
                         entry.station_code, entry.device_code, last_page, exc)
        flush()
        accepted_total = total["accepted"]
        logger.info("[%s|%s] cumulative: %s", entry.station_code, entry.device_code, total)
        if args.max_measurements and accepted_total >= args.max_measurements:
            logger.info("max-measurements reached, stopping")
            break

    logger.info("done: %s", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
