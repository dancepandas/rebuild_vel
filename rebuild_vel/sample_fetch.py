"""Budget-driven stratified fetch: ~N quality-passing sections spread over
(usable device x month) cells.

``rebuild_vel.fetch`` sweeps every measurement in a time range, which is the
wrong shape for the training-set build: the platform lists millions of
measurements, most devices have no procedure file at all, and a range sweep
would let hourly stations dominate while contributing no seasonal breadth.

This module targets a *usable* (quality-passing) count instead. Chunk
processing, quality gates, the no-procedure-data circuit breaker and the
resume ledger are all imported from ``fetch`` so both paths behave identically.

Usage:
    python -m rebuild_vel.sample_fetch \
        --probe data/probe.json --output data/vel \
        --begin-time "2024-09-01 00:00:00.000" --end-time "2026-08-31 23:59:59.999" \
        --target 100000
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from .accounts import AccountPool
from .catalog import StationDevice, load_catalog
from .client import FlowClient, PermanentAPIError, RemoteAPIError
from .dataset import load_shards
from .fetch import Ledger, _log_rejected, _process_chunk
from .quality import QualityOptions
from .sampling import DevicePlan, SpreadCursor, build_plans, month_bounds

logger = logging.getLogger(__name__)

DEFAULT_STATION_INFO = r"D:\chengs\vmodel\v_data\read_data\station_info_view.csv"
DEFAULT_FLOW_CONFIG = r"D:\chengs\vmodel\v_data\read_data\calibration_fore_config_flow_view.csv"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stratified training-set fetch")
    parser.add_argument("--station-info", default=DEFAULT_STATION_INFO)
    parser.add_argument("--flow-config", default=DEFAULT_FLOW_CONFIG)
    parser.add_argument("--probe", required=True, help="probe_devices.py output JSON")
    parser.add_argument("--begin-time", required=True)
    parser.add_argument("--end-time", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target", type=int, default=100_000,
                        help="quality-passing sections to collect")
    parser.add_argument("--step", type=int, default=5,
                        help="measurement times requested per stratum per round")
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--max-rounds", type=int, default=12)
    parser.add_argument("--per-stratum-cap", type=int, default=60,
                        help="max measurement times taken from one (device, month) cell")
    parser.add_argument("--stations", default="", help="comma-separated station-code filter")
    parser.add_argument("--request-delay", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--accounts-file", default=None)
    parser.add_argument("--min-lines", type=int, default=8)
    parser.add_argument("--max-target-velocity", type=float, default=5.633)
    parser.add_argument("--reliability", type=int, default=1, choices=[0, 1, 2],
                        help="1=可靠 only (the sampled accept rate is ~5x the "
                             "unfiltered rate), 2=不可靠 only, 0=no filter")
    parser.add_argument("--night-mark", type=int, default=-1, choices=[-1, 0, 1],
                        help="0=day only, 1=night only, -1=no filter. Night is not "
                             "excluded by default: the input-side gate now drops "
                             "sections without raw observations on its own")
    parser.add_argument("--raw-tolerance", type=float, default=0.0,
                        help="metres for raw->line matching; <=0 derives it from line spacing")
    return parser.parse_args(argv)


def load_usable_devices(probe_path: str | Path) -> set[tuple[str, str]]:
    """Devices the probe saw returning a real procedure-data export."""
    payload = json.loads(Path(probe_path).read_text(encoding="utf-8"))
    usable: set[tuple[str, str]] = set()
    for key, entry in (payload.get("devices") or {}).items():
        months = entry.get("months") or {}
        if any(month.get("usable") for month in months.values()):
            station, _, device = key.partition("|")
            usable.add((station, device))
    return usable


def query_filter(args: argparse.Namespace) -> dict[str, Any]:
    """Server-side filters applied to every list request.

    ``reliability=1`` is the accept-rate lever: the sampled pass rate is ~68%
    against ~13% unfiltered. ``nightMark`` is left unset by default because the
    input-side quality gate already drops sections with no raw observations.
    """
    filters: dict[str, Any] = {}
    if args.reliability in (1, 2):
        filters["reliability"] = args.reliability
    if args.night_mark in (0, 1):
        filters["nightMark"] = args.night_mark
    return filters


def list_times(
    client: FlowClient,
    plan: DevicePlan,
    stratum,
    page: int,
    count: int,
    filters: Optional[dict[str, Any]] = None,
) -> tuple[list[str], int]:
    """One page of measurement times for a stratum, plus the month's total."""
    request = {
        "beginTime": stratum.begin, "endTime": stratum.end,
        "stationCode": plan.station_code, "deviceCode": plan.device_code,
        "measureResult": 1,
    }
    request.update(filters or {})
    payload = client.post("/flow/originalDataFilterPage", {
        "count": max(1, count), "page": max(1, page),
        "request": request,
    })
    rows = payload.get("data") or []
    total = int((payload.get("pageInfo") or {}).get("total") or 0)
    times = [str(row["measureTime"]) for row in rows if row.get("measureTime")]
    return times, total


def flush(
    client: FlowClient,
    entry: StationDevice,
    times: list[str],
    *,
    quality: QualityOptions,
    root: Path,
    ledger: Ledger,
    no_proc_streak: list[int],
    chunk_size: int,
) -> dict[str, int]:
    """Send a device's times through the shared chunk pipeline."""
    stats = {"accepted": 0, "rejected": 0, "parse_error": 0}
    for start in range(0, len(times), chunk_size):
        chunk = times[start:start + chunk_size]
        for attempt in range(3):
            try:
                result = _process_chunk(client, entry, chunk, quality=quality,
                                        root=root, no_proc_streak=no_proc_streak)
                break
            except RemoteAPIError as exc:
                if attempt == 2:
                    logger.warning("chunk dropped for %s|%s: %s",
                                   entry.station_code, entry.device_code, exc)
                    result = {"accepted": 0, "rejected": len(chunk), "parse_error": 0}
                    break
                time.sleep(5 * (attempt + 1))
        for name, value in result.items():
            stats[name] = stats.get(name, 0) + value
        for when in chunk:
            ledger.add(f"{entry.station_code}|{entry.device_code}|{when}")
    return stats


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root / "ledger.jsonl")

    wanted = {value.strip() for value in args.stations.split(",") if value.strip()}
    catalog = load_catalog(args.station_info, args.flow_config,
                           station_codes=sorted(wanted) or None)
    by_key = {(entry.station_code, entry.device_code): entry for entry in catalog}
    usable = load_usable_devices(args.probe)
    if wanted:
        usable = {key for key in usable if key[0] in wanted}

    devices = [
        (station, device, by_key[(station, device)].station_name)
        for station, device in sorted(usable) if (station, device) in by_key
    ]
    if not devices:
        raise SystemExit("no usable devices; run tools/probe_devices.py first")

    months = month_bounds(args.begin_time, args.end_time)
    plans = build_plans(devices, months)
    active_cells = sum(1 for plan in plans for stratum in plan.strata)
    logger.info("target=%d sections; %d usable devices x %d months = %d cells",
                args.target, len(devices), len(months), active_cells)

    client = FlowClient(AccountPool(args.accounts_file), timeout=args.timeout,
                        max_attempts=6, request_delay=args.request_delay)
    quality = QualityOptions(min_lines=args.min_lines,
                             max_target_velocity=args.max_target_velocity,
                             raw_tolerance=args.raw_tolerance)
    filters = query_filter(args)
    logger.info("server-side filters: %s", filters or "none")

    cursors: dict[tuple[str, str, str], SpreadCursor] = {}
    streaks: dict[tuple[str, str], list[int]] = {key: [0] for key in usable}
    totals = {"accepted": 0, "rejected": 0, "parse_error": 0}
    per_month: dict[str, int] = {}
    per_station: dict[str, int] = {}
    started = time.time()
    accept_rate = 0.5

    for round_index in range(1, args.max_rounds + 1):
        if totals["accepted"] >= args.target:
            break
        remaining = args.target - totals["accepted"]
        cells_left = sum(1 for plan in plans for s in plan.strata if not s.exhausted)
        if cells_left == 0:
            logger.info("all cells exhausted")
            break
        # how many times to take from each cell this round to hit the target
        want_per_cell = max(1, math.ceil(remaining / max(1, cells_left) / max(accept_rate, 0.05)))
        want_per_cell = min(want_per_cell, args.per_stratum_cap)
        step = max(1, min(args.step, want_per_cell))

        round_stats = {"accepted": 0, "rejected": 0, "parse_error": 0, "requested": 0}
        for plan in plans:
            if totals["accepted"] >= args.target:
                break
            entry = by_key.get((plan.station_code, plan.device_code))
            if entry is None:
                continue
            batch: list[str] = []
            for stratum in plan.strata:
                if stratum.exhausted:
                    continue
                if stratum.taken >= args.per_stratum_cap:
                    stratum.exhausted = True
                    continue
                cursor_key = (plan.station_code, plan.device_code, stratum.month)
                cursor = cursors.get(cursor_key)
                if cursor is None:
                    cursor = cursors[cursor_key] = SpreadCursor(
                        step, want_pages=max(1, math.ceil(args.per_stratum_cap / step)))
                try:
                    page = cursor.next_page()
                    if page is None:
                        stratum.exhausted = True
                        continue
                    times, total = list_times(client, plan, stratum, page, step, filters)
                except (RemoteAPIError, PermanentAPIError) as exc:
                    logger.debug("list failed %s|%s %s: %s",
                                 plan.station_code, plan.device_code, stratum.month, exc)
                    stratum.exhausted = True
                    continue
                if stratum.total < 0:
                    stratum.total = total
                    cursor.set_total(total)
                    if total == 0:
                        stratum.exhausted = True
                        continue
                if not times:
                    stratum.exhausted = True
                    continue
                fresh = [when for when in times
                         if f"{plan.station_code}|{plan.device_code}|{when}" not in ledger]
                stratum.taken += len(times)
                batch.extend(fresh)
            if not batch:
                continue
            stats = flush(client, entry, batch, quality=quality, root=root,
                          ledger=ledger, no_proc_streak=streaks[
                              (plan.station_code, plan.device_code)],
                          chunk_size=args.chunk_size)
            for name in round_stats:
                if name in stats:
                    round_stats[name] += stats[name]
            round_stats["requested"] += len(batch)
            for name, value in stats.items():
                totals[name] = totals.get(name, 0) + value

        decided = round_stats["accepted"] + round_stats["rejected"]
        if decided > 0:
            accept_rate = round_stats["accepted"] / decided
        logger.info("round %d: requested=%d accepted=%d rejected=%d | total accepted=%d/%d "
                    "(accept %.2f, %d cells left, %.0fs)",
                    round_index, round_stats["requested"], round_stats["accepted"],
                    round_stats["rejected"], totals["accepted"], args.target,
                    accept_rate, cells_left, time.time() - started)
        if round_stats["requested"] == 0:
            # a resume run re-lists already-taken pages before reaching fresh
            # ones (the first probe of a stratum is always page 1), so an empty
            # round must not stop while any stratum still has pages to probe
            still_probing = sum(
                1 for plan in plans for stratum in plan.strata if not stratum.exhausted)
            if still_probing == 0:
                logger.info("no measurements requested and all cells exhausted; stopping")
                break
            logger.info("no fresh measurements this round; %d cells still probing",
                        still_probing)

    # -- distribution report, tallied from the shards themselves so it counts
    #    exactly what survived the quality gates rather than what was requested
    per_source: dict[str, int] = {}
    per_device_source: dict[str, dict[str, int]] = {}
    tol_sum = tol_n = 0
    for section in load_shards(root):
        month = str(section.get("time", ""))[:7]
        station = str(section.get("station", ""))
        source = str(section.get("raw_source") or "unknown")
        device = str(section.get("device", ""))
        if month:
            per_month[month] = per_month.get(month, 0) + 1
        if station:
            per_station[station] = per_station.get(station, 0) + 1
        per_source[source] = per_source.get(source, 0) + 1
        per_device_source.setdefault(device, {})
        per_device_source[device][source] = per_device_source[device].get(source, 0) + 1
        tol = float(section.get("raw_tolerance") or 0.0)
        if tol > 0:
            tol_sum += tol
            tol_n += 1
    stored = sum(per_month.values())
    # devices whose sections came from more than one raw table
    mixed = {d: c for d, c in per_device_source.items() if len(c) > 1}

    logger.info("done: %s over %.0fs", totals, time.time() - started)
    logger.info("shards hold %d sections across %d stations and %d months",
                stored, len(per_station), len(per_month))
    logger.info("raw source mix: %s (mean tolerance %.2f m)",
                per_source, (tol_sum / tol_n) if tol_n else 0.0)
    if mixed:
        logger.info("%d devices drew from more than one raw table: %s",
                    len(mixed), dict(list(mixed.items())[:5]))
    (root / "fetch_summary.json").write_text(json.dumps({
        "totals": totals,
        "stored_sections": stored,
        "target": args.target,
        "usable_devices": len(devices),
        "months": len(months),
        "server_filters": filters,
        "accept_rate": accept_rate,
        "raw_sources": dict(sorted(per_source.items())),
        "mixed_source_devices": len(mixed),
        "mean_raw_tolerance": round(tol_sum / tol_n, 3) if tol_n else 0.0,
        "per_month": dict(sorted(per_month.items())),
        "per_station": dict(sorted(per_station.items())),
        "seconds": time.time() - started,
        "ledger_entries": len(ledger.completed),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if totals["accepted"] < args.target:
        logger.warning("target not reached: %d/%d - raise --per-stratum-cap or --max-rounds",
                       totals["accepted"], args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
