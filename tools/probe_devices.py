"""Probe which (station, device, month) cells actually have procedure data.

The list endpoint (``originalDataFilterPage``) reports measurements for devices
that have no procedure-data file at all, so it overcounts badly - the pilot
showed only ~1/3 of devices export successfully. This probe spends a handful of
cheap export calls per device to classify it, so the sampler can aim at the
devices that will actually yield sections.

Output: JSON {device_key: {"months": {label: {measurements, usable, sample_time}}}}

Usage:
    python tools/probe_devices.py --output data/probe.json [--per-device 3] [--workers 6]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rebuild_vel.accounts import AccountPool
from rebuild_vel.catalog import load_catalog
from rebuild_vel.client import FlowClient, PermanentAPIError, RemoteAPIError
from rebuild_vel.sampling import month_bounds

logger = logging.getLogger("probe")

STATION_INFO = r"D:\chengs\vmodel\v_data\read_data\station_info_view.csv"
FLOW_CONFIG = r"D:\chengs\vmodel\v_data\read_data\calibration_fore_config_flow_view.csv"


def month_count(client: FlowClient, station: str, device: str, begin: str, end: str) -> int:
    payload = client.post("/flow/originalDataFilterPage", {
        "count": 1, "page": 1,
        "request": {"beginTime": begin, "endTime": end,
                    "stationCode": station, "deviceCode": device, "measureResult": 1},
    })
    return int((payload.get("pageInfo") or {}).get("total") or 0)


def sample_times(client: FlowClient, station: str, device: str, begin: str, end: str,
                 count: int) -> list[str]:
    payload = client.post("/flow/originalDataFilterPage", {
        "count": max(1, count), "page": 1,
        "request": {"beginTime": begin, "endTime": end,
                    "stationCode": station, "deviceCode": device, "measureResult": 1},
    })
    return [str(row.get("measureTime")) for row in (payload.get("data") or []) if row.get("measureTime")]


def prose_usable(client: FlowClient, station: str, device: str, when: str) -> bool:
    try:
        return bool(client.get_bytes("/flow/procedureDataMergeExport", {
            "stationCode": station, "deviceCode": device, "measureTimeList": [when],
        }))
    except (PermanentAPIError, RemoteAPIError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--begin-time", default="2025-09-01 00:00:00.000")
    parser.add_argument("--end-time", default="2026-08-31 23:59:59.999")
    parser.add_argument("--months-per-device", type=int, default=3,
                        help="spread this many monthly probes across the window")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    MONTHS = month_bounds(args.begin_time, args.end_time)

    entries = load_catalog(STATION_INFO, FLOW_CONFIG)
    if args.limit:
        entries = entries[: args.limit]
    # probe evenly spaced months: e.g. 3 -> Sep, Feb, Jun
    step = max(1, len(MONTHS) // args.months_per_device)
    probe_months = [MONTHS[i] for i in range(0, len(MONTHS), step)][: args.months_per_device]
    logger.info("probing %d devices x %d months with %d workers",
                len(entries), len(probe_months), args.workers)

    local = threading.local()
    counter = {"lists": 0, "exports": 0}

    def client_for() -> FlowClient:
        if not hasattr(local, "client"):
            local.client = FlowClient(AccountPool("accounts.json"), timeout=90, request_delay=0.05)
        return local.client

    def probe_device(entry) -> tuple[str, dict]:
        client = client_for()
        key = f"{entry.station_code}|{entry.device_code}"
        months: dict[str, dict] = {}
        for label, begin, end in probe_months:
            try:
                total = month_count(client, entry.station_code, entry.device_code, begin, end)
                counter["lists"] += 1
                if total <= 0:
                    months[label] = {"measurements": 0, "usable": False}
                    continue
                times = sample_times(client, entry.station_code, entry.device_code,
                                     begin, end, 2)
                counter["lists"] += 1
                usable = False
                for when in times[:1]:
                    counter["exports"] += 1
                    if prose_usable(client, entry.station_code, entry.device_code, when):
                        usable = True
                        break
                months[label] = {"measurements": total, "usable": usable}
            except (RemoteAPIError, PermanentAPIError) as exc:
                logger.debug("probe failed %s %s: %s", key, label, exc)
                months[label] = {"measurements": -1, "usable": False}
        return key, {
            "station_name": entry.station_name,
            "device_code": entry.device_code,
            "calculation_mode": entry.calculation_mode,
            "months": months,
        }

    results: dict[str, dict] = {}
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(probe_device, e) for e in entries]
        for done, future in enumerate(as_completed(futures), 1):
            try:
                key, payload = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("device probe crashed: %s", exc)
                continue
            results[key] = payload
            if done % 50 == 0:
                logger.info("probed %d/%d (%.0fs) requests=%s",
                            done, len(entries), time.time() - started, counter)

    usable = sum(1 for v in results.values()
                 if any(m.get("usable") for m in v["months"].values()))
    with_data = sum(1 for v in results.values()
                    if any(m.get("measurements", 0) > 0 for m in v["months"].values()))
    logger.info("devices=%d measured=%d usable=%d", len(results), with_data, usable)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "months": [m[0] for m in MONTHS],
        "probed_months": [m[0] for m in probe_months],
        "devices": results,
        "seconds": time.time() - started,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    logger.info("wrote %s", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
