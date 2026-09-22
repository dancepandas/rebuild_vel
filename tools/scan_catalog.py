"""Scan the catalog: per device x month measurement counts + procedure-data availability.

Writes a JSON summary so sampling budgets can be planned from real numbers
instead of guesses.

Usage:
    python tools/scan_catalog.py --output data/scan.json [--limit 30] [--probe N]
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rebuild_vel.accounts import AccountPool
from rebuild_vel.catalog import load_catalog
from rebuild_vel.client import FlowClient, PermanentAPIError, RemoteAPIError

logger = logging.getLogger("scan")

STATION_INFO = r"D:\chengs\vmodel\v_data\read_data\station_info_view.csv"
FLOW_CONFIG = r"D:\chengs\vmodel\v_data\read_data\calibration_fore_config_flow_view.csv"

MONTHS = [
    ("2025-09", "2025-09-01 00:00:00.000", "2025-09-30 23:59:59.999"),
    ("2025-10", "2025-10-01 00:00:00.000", "2025-10-31 23:59:59.999"),
    ("2025-11", "2025-11-01 00:00:00.000", "2025-11-30 23:59:59.999"),
    ("2025-12", "2025-12-01 00:00:00.000", "2025-12-31 23:59:59.999"),
    ("2026-01", "2026-01-01 00:00:00.000", "2026-01-31 23:59:59.999"),
    ("2026-02", "2026-02-01 00:00:00.000", "2026-02-28 23:59:59.999"),
    ("2026-03", "2026-03-01 00:00:00.000", "2026-03-31 23:59:59.999"),
    ("2026-04", "2026-04-01 00:00:00.000", "2026-04-30 23:59:59.999"),
    ("2026-05", "2026-05-01 00:00:00.000", "2026-05-31 23:59:59.999"),
    ("2026-06", "2026-06-01 00:00:00.000", "2026-06-30 23:59:59.999"),
    ("2026-07", "2026-07-01 00:00:00.000", "2026-07-31 23:59:59.999"),
    ("2026-08", "2026-08-01 00:00:00.000", "2026-08-31 23:59:59.999"),
]


def month_count(client: FlowClient, station: str, device: str, begin: str, end: str) -> int:
    payload = client.post("/flow/originalDataFilterPage", {
        "count": 1, "page": 1,
        "request": {"beginTime": begin, "endTime": end,
                    "stationCode": station, "deviceCode": device, "measureResult": 1},
    })
    return int((payload.get("pageInfo") or {}).get("total") or 0)


def has_procedure_data(client: FlowClient, station: str, device: str, when: str) -> bool:
    """Probe the export endpoint once: does this device have procedure files?"""
    try:
        body = client.get_bytes("/flow/procedureDataMergeExport", {
            "stationCode": station, "deviceCode": device, "measureTimeList": [when],
        })
        return bool(body)
    except (PermanentAPIError, RemoteAPIError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=None, help="scan only N devices")
    parser.add_argument("--probe", type=int, default=0,
                        help="probe the export endpoint for the first N devices of each month")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    entries = load_catalog(STATION_INFO, FLOW_CONFIG)
    if args.limit:
        rng = random.Random(args.seed)
        entries = rng.sample(entries, args.limit)
    logger.info("scanning %d devices x %d months", len(entries), len(MONTHS))

    local = threading.local()

    def client_for() -> FlowClient:
        if not hasattr(local, "client"):
            local.client = FlowClient(AccountPool("accounts.json"), timeout=60, request_delay=0.05)
        return local.client

    results: dict[str, dict] = {}
    counts: dict[str, dict[str, int]] = {}

    def scan_device(entry) -> tuple[str, dict[str, int]]:
        client = client_for()
        per_month: dict[str, int] = {}
        for label, begin, end in MONTHS:
            try:
                per_month[label] = month_count(client, entry.station_code, entry.device_code, begin, end)
            except (RemoteAPIError, PermanentAPIError) as exc:
                logger.warning("count failed %s|%s %s: %s", entry.station_code,
                               entry.device_code, label, exc)
                per_month[label] = -1
        return f"{entry.station_code}|{entry.device_code}", per_month

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scan_device, e): e for e in entries}
        done = 0
        for future in as_completed(futures):
            key, per_month = future.result()
            counts[key] = per_month
            done += 1
            if done % 25 == 0:
                logger.info("counted %d/%d devices (%.0fs)", done, len(entries), time.time() - started)

    # procedure-data probe: one representative measurement per device per month
    probe: dict[str, dict[str, bool]] = {}
    if args.probe:
        def probe_device(entry) -> tuple[str, dict[str, bool]]:
            client = client_for()
            available: dict[str, bool] = {}
            for label, begin, end in MONTHS:
                if counts.get(f"{entry.station_code}|{entry.device_code}", {}).get(label, 0) <= 0:
                    continue
                try:
                    payload = client.post("/flow/originalDataFilterPage", {
                        "count": 1, "page": 1,
                        "request": {"beginTime": begin, "endTime": end,
                                    "stationCode": entry.station_code,
                                    "deviceCode": entry.device_code, "measureResult": 1},
                    })
                    row = (payload.get("data") or [{}])[0]
                    when = str(row.get("measureTime") or "")
                    available[label] = bool(when) and has_procedure_data(
                        client, entry.station_code, entry.device_code, when)
                except Exception:  # noqa: BLE001
                    available[label] = False
            return f"{entry.station_code}|{entry.device_code}", available

        probe_entries = entries[: args.probe]
        logger.info("probing procedure data for %d devices", len(probe_entries))
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(probe_device, e): e for e in probe_entries}
            for future in as_completed(futures):
                key, available = future.result()
                probe[key] = available
        logger.info("probe done")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "months": [m[0] for m in MONTHS],
        "counts": counts,
        "procedure_probe": probe,
        "scanned_devices": len(entries),
        "seconds": time.time() - started,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    total = sum(v for m in counts.values() for v in m.values() if v > 0)
    logger.info("wrote %s; total measurements=%d over %d devices", output, total, len(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
