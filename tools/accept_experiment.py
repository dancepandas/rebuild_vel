"""Measure how the quality-gate acceptance rate depends on server-side filters.

``originalDataFilterPage`` exposes per-row ``nightMark``, ``reliability``,
``dataType`` and ``originalValueProp``, and accepts ``nightMark``/``reliability``
as query filters. Since the export cost scales with *requested* measurements,
knowing which filter maximises accepted-per-request is the difference between a
one-hour and a five-hour fetch.

Each sampled measurement is exported once and pushed through the real
``clean_measurement`` gate, then acceptance is cross-tabulated by the row
attributes - so one export pass answers every filter question.

Usage:
    python tools/accept_experiment.py --output data/accept.json --stations 8 --per-cell 15
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rebuild_vel.accounts import AccountPool
from rebuild_vel.catalog import load_catalog
from rebuild_vel.client import FlowClient, PermanentAPIError, RemoteAPIError
from rebuild_vel.parse import parse_merged_export
from rebuild_vel.quality import QualityOptions, SectionQualityError, clean_measurement
from rebuild_vel.sampling import month_bounds

logger = logging.getLogger("accept")

STATION_INFO = r"D:\chengs\vmodel\v_data\read_data\station_info_view.csv"
FLOW_CONFIG = r"D:\chengs\vmodel\v_data\read_data\calibration_fore_config_flow_view.csv"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--stations", type=int, default=8)
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--per-cell", type=int, default=15)
    parser.add_argument("--begin-time", default="2025-09-01 00:00:00.000")
    parser.add_argument("--end-time", default="2026-08-31 23:59:59.999")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=5)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    probe = json.loads(Path("data/probe.json").read_text(encoding="utf-8"))
    usable = sorted({k.split("|")[0] for k, v in probe["devices"].items()
                     if any(m.get("usable") for m in v["months"].values())})
    rng = random.Random(args.seed)
    rng.shuffle(usable)
    stations = set(usable[: args.stations])
    devices = [(k.split("|")[0], k.split("|")[1])
               for k, v in probe["devices"].items()
               if k.split("|")[0] in stations
               and any(m.get("usable") for m in v["months"].values())]
    devices.sort()

    all_months = month_bounds(args.begin_time, args.end_time)
    step = max(1, len(all_months) // args.months)
    months = all_months[::step][: args.months]
    logger.info("stations=%d devices=%d months=%s", len(stations), len(devices),
                [m[0] for m in months])

    local = threading.local()

    def client_for() -> FlowClient:
        if not hasattr(local, "client"):
            local.client = FlowClient(AccountPool("accounts.json"), timeout=120,
                                      request_delay=0.05)
        return local.client

    quality = QualityOptions()

    def run_cell(device) -> list[dict]:
        station, dev = device
        client = client_for()
        out = []
        for label, begin, end in months:
            try:
                payload = client.post("/flow/originalDataFilterPage", {
                    "count": args.per_cell, "page": 1,
                    "request": {"beginTime": begin, "endTime": end,
                                "stationCode": station, "deviceCode": dev,
                                "measureResult": 1}})
            except (RemoteAPIError, PermanentAPIError) as exc:
                out.append({"station": station, "device": dev, "month": label,
                            "error": f"list: {exc}"})
                continue
            rows = payload.get("data") or []
            # batch the export for this cell
            times = [str(r.get("measureTime")) for r in rows if r.get("measureTime")]
            attrs = {str(r.get("measureTime")): r for r in rows}
            sections = {}
            for start in range(0, len(times), 20):
                chunk = times[start:start + 20]
                try:
                    body = client.get_bytes("/flow/procedureDataMergeExport", {
                        "stationCode": station, "deviceCode": dev, "measureTimeList": chunk})
                except (RemoteAPIError, PermanentAPIError) as exc:
                    for when in chunk:
                        out.append({"station": station, "device": dev, "month": label,
                                    "time": when, "error": f"export: {exc}",
                                    **{k: attrs.get(when, {}).get(k)
                                       for k in ("nightMark", "reliability",
                                                 "dataType", "originalValueProp")}})
                    continue
                if not body:
                    for when in chunk:
                        out.append({"station": station, "device": dev, "month": label,
                                    "time": when, "error": "empty export",
                                    **{k: attrs.get(when, {}).get(k)
                                       for k in ("nightMark", "reliability",
                                                 "dataType", "originalValueProp")}})
                    continue
                parsed = parse_merged_export(body)
                for m in parsed.measurements:
                    sections[m["time"][:19]] = m
            for when in times:
                row = attrs.get(when, {})
                base = {"station": station, "device": dev, "month": label, "time": when,
                        "nightMark": row.get("nightMark"),
                        "reliability": row.get("reliability"),
                        "dataType": row.get("dataType"),
                        "originalValueProp": row.get("originalValueProp")}
                measurement = sections.get(when[:19])
                if measurement is None:
                    base["accepted"] = False
                    base["reason"] = "missing_in_export"
                    out.append(base)
                    continue
                measurement["station"] = station
                try:
                    clean_measurement(measurement, quality)
                    base["accepted"] = True
                except SectionQualityError as exc:
                    base["accepted"] = False
                    base["reason"] = exc.reason
                out.append(base)
        return out

    results: list[dict] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_cell, d) for d in devices]
        for done, future in enumerate(as_completed(futures), 1):
            try:
                results.extend(future.result())
            except Exception as exc:  # noqa: BLE001
                logger.warning("cell crashed: %s", exc)
            if done % 5 == 0:
                logger.info("cells %d/%d (%.0fs)", done, len(devices), time.time() - started)

    # -- cross-tabulate ----------------------------------------------------
    def rate(rows):
        if not rows:
            return None
        acc = sum(1 for r in rows if r.get("accepted"))
        return {"n": len(rows), "accepted": acc, "rate": round(acc / len(rows), 3)}

    buckets = {
        "ALL": results,
        "day (nightMark=0)": [r for r in results if r.get("nightMark") == 0],
        "night (nightMark=1)": [r for r in results if r.get("nightMark") == 1],
        "reliable=1": [r for r in results if r.get("reliability") == 1],
        "reliable=2": [r for r in results if r.get("reliability") == 2],
        "dataType=0 realtime": [r for r in results if r.get("dataType") == 0],
        "dataType=1 add": [r for r in results if r.get("dataType") == 1],
        "day+reliable=1": [r for r in results
                           if r.get("nightMark") == 0 and r.get("reliability") == 1],
    }
    summary = {name: rate(rows) for name, rows in buckets.items()}
    for name, value in summary.items():
        logger.info("%-22s %s", name, value)

    reasons = Counter(r.get("reason") for r in results if not r.get("accepted"))
    logger.info("rejection reasons: %s", reasons.most_common())

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps({
        "summary": summary,
        "reasons": dict(reasons),
        "rows": results,
        "seconds": time.time() - started,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    logger.info("wrote %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
