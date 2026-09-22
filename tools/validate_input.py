"""Validate the input-construction fix before committing to the full pull.

Two things changed in ``quality.py`` and both need evidence before a ~100k
fetch:

1. raw observations are matched to target lines by 起点距 instead of by
   测速线序号 (which is a global row counter in the raw sheets, not a line
   index - the old join produced a median of ~1 observation per line where
   6-10 were expected);
2. the input table is chosen per measurement (STIV first, else whichever
   optical-flow table has more rows) and a section with no surviving raw
   observations is rejected outright.

The decisive test is agreement: if observations are attached to the right
lines, a line's mean raw velocity should track its target surface velocity.
This tool exports a fresh sample, runs both joins over the same rows and
reports the correlation side by side, plus the S distribution, the raw-source
mix and the rejection reasons.

Usage:
    python tools/validate_input.py --output data/validate.json --devices 25 --per-cell 12
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
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from rebuild_vel.accounts import AccountPool
from rebuild_vel.client import FlowClient, PermanentAPIError, RemoteAPIError
from rebuild_vel.parse import parse_merged_export
from rebuild_vel.quality import (
    RAW_SOURCES,
    QualityOptions,
    SectionQualityError,
    clean_measurement,
    _finite_or_nan,
)
from rebuild_vel.sampling import month_bounds

logger = logging.getLogger("validate")

STATION_INFO = r"D:\chengs\vmodel\v_data\read_data\station_info_view.csv"
FLOW_CONFIG = r"D:\chengs\vmodel\v_data\read_data\calibration_fore_config_flow_view.csv"


def old_join_mean(raw_rows: list[dict[str, Any]], line_num: np.ndarray) -> np.ndarray:
    """The previous join: group by 测速线序号 and average each group."""
    by_line: dict[float, list[float]] = defaultdict(list)
    for row in raw_rows:
        value = _finite_or_nan(row.get("raw_v"))
        if np.isfinite(value):
            by_line[float(row.get("line_num", -1))].append(float(value))
    out = np.full(len(line_num), np.nan)
    for i, ln in enumerate(line_num):
        values = by_line.get(float(ln))
        if values:
            out[i] = float(np.mean(values))
    return out


def pearson(a: np.ndarray, b: np.ndarray) -> float | None:
    mask = np.isfinite(a) & np.isfinite(b)
    if int(mask.sum()) < 3:
        return None
    av, bv = a[mask], b[mask]
    if av.std() < 1e-9 or bv.std() < 1e-9:
        return None
    return float(np.corrcoef(av, bv)[0, 1])


def describe(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=np.float64)
    return {
        "n": len(arr),
        "mean": round(float(arr.mean()), 3),
        "p10": round(float(np.percentile(arr, 10)), 3),
        "median": round(float(np.median(arr)), 3),
        "p90": round(float(np.percentile(arr, 90)), 3),
        "max": round(float(arr.max()), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--probe", default="data/probe.json",
                        help="probe_devices.py output; its usable devices are sampled")
    parser.add_argument("--devices", type=int, default=25)
    parser.add_argument("--months", type=int, default=4)
    parser.add_argument("--per-cell", type=int, default=12)
    parser.add_argument("--begin-time", default="2024-09-01 00:00:00.000")
    parser.add_argument("--end-time", default="2026-08-31 23:59:59.999")
    parser.add_argument("--reliability", type=int, default=1, choices=[0, 1, 2])
    parser.add_argument("--night-mark", type=int, default=-1, choices=[-1, 0, 1])
    parser.add_argument("--raw-tolerance", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    payload = json.loads(Path(args.probe).read_text(encoding="utf-8"))
    usable = sorted(
        key for key, entry in (payload.get("devices") or {}).items()
        if any(m.get("usable") for m in (entry.get("months") or {}).values())
    )
    rng = random.Random(args.seed)
    rng.shuffle(usable)
    devices = [tuple(key.split("|", 1)) for key in usable[: args.devices]]
    devices.sort()

    all_months = month_bounds(args.begin_time, args.end_time)
    step = max(1, len(all_months) // args.months)
    months = all_months[::step][: args.months]
    logger.info("devices=%d months=%s reliability=%s nightMark=%s",
                len(devices), [m[0] for m in months], args.reliability, args.night_mark)

    request_filter: dict[str, Any] = {"measureResult": 1}
    if args.reliability in (1, 2):
        request_filter["reliability"] = args.reliability
    if args.night_mark in (0, 1):
        request_filter["nightMark"] = args.night_mark

    quality = QualityOptions(raw_tolerance=args.raw_tolerance)
    local = threading.local()

    def client_for() -> FlowClient:
        if not hasattr(local, "client"):
            local.client = FlowClient(AccountPool("accounts.json"), timeout=120,
                                      request_delay=0.05)
        return local.client

    def run_cell(device: tuple[str, str]) -> dict[str, Any]:
        station, dev = device
        client = client_for()
        rows: list[dict[str, Any]] = []
        for label, begin, end in months:
            request = {"beginTime": begin, "endTime": end,
                       "stationCode": station, "deviceCode": dev, **request_filter}
            try:
                listing = client.post("/flow/originalDataFilterPage", {
                    "count": args.per_cell, "page": 1, "request": request})
            except (RemoteAPIError, PermanentAPIError) as exc:
                rows.append({"station": station, "device": dev, "month": label,
                             "error": f"list: {exc}"})
                continue
            times = [str(r.get("measureTime")) for r in (listing.get("data") or [])
                     if r.get("measureTime")]
            attrs = {str(r.get("measureTime")): r for r in (listing.get("data") or [])}
            parsed: dict[str, dict[str, Any]] = {}
            for start in range(0, len(times), 20):
                chunk = times[start:start + 20]
                try:
                    body = client.get_bytes("/flow/procedureDataMergeExport", {
                        "stationCode": station, "deviceCode": dev,
                        "measureTimeList": chunk})
                except (RemoteAPIError, PermanentAPIError):
                    continue
                if not body:
                    continue
                for m in parse_merged_export(body).measurements:
                    parsed[m["time"][:19]] = m
            for when in times:
                meta = attrs.get(when, {})
                base = {"station": station, "device": dev, "month": label,
                        "time": when, "nightMark": meta.get("nightMark"),
                        "reliability": meta.get("reliability")}
                measurement = parsed.get(when[:19])
                if measurement is None:
                    base.update(accepted=False, reason="missing_in_export")
                    rows.append(base)
                    continue
                measurement["station"] = station
                base["counts"] = {name: len(measurement.get(key) or [])
                                  for name, key in (("stiv", "raw_stiv"),
                                                    ("of", "raw_of"),
                                                    ("of_traj", "raw_of_traj"))}
                base["populated"] = "+".join(
                    name for name, n in base["counts"].items() if n > 0) or "NONE"
                try:
                    section = clean_measurement(measurement, quality)
                except SectionQualityError as exc:
                    base.update(accepted=False, reason=exc.reason)
                    rows.append(base)
                    continue
                base["accepted"] = True
                base["source"] = section["raw_source"]
                base["tol"] = round(float(section["raw_tolerance"]), 3)
                base["s_raw"] = int(section["raw_v"].shape[1])
                base["n_used"] = int(section["n_raw_used"])
                base["n_dropped"] = int(section["n_raw_dropped"])
                valid = np.asarray(section["raw_valid"], dtype=bool)
                base["lines_with_raw"] = round(float(valid.any(axis=1).mean()), 3)
                base["per_line_counts"] = valid.sum(axis=1).tolist()
                is_algo = np.asarray(section["is_algo"], dtype=bool)
                base["algo_frac"] = round(float(is_algo.mean()), 3)

                # agreement: mean raw velocity per line vs the target
                target = np.asarray(section["v_surface"], dtype=np.float64)
                raw_v = np.asarray(section["raw_v"], dtype=np.float64)
                with np.errstate(invalid="ignore"):
                    new_mean = np.where(valid.any(axis=1),
                                        np.nanmean(np.where(valid, raw_v, np.nan), axis=1),
                                        np.nan)
                base["r_new"] = pearson(new_mean, target)
                # restricted to algorithm-given lines: interpolated target lines
                # carry no independent information, so they only dilute r
                if is_algo.any():
                    base["r_algo"] = pearson(
                        np.where(is_algo, new_mean, np.nan), target)
                source_name, source_rows = None, []
                for name in RAW_SOURCES:
                    key = {"stiv": "raw_stiv", "of": "raw_of",
                           "of_traj": "raw_of_traj"}[name]
                    if measurement.get(key):
                        source_name, source_rows = name, measurement[key]
                        break
                if source_rows:
                    base["r_old"] = pearson(old_join_mean(source_rows,
                                                          np.asarray(section["line_num"])),
                                            target)
                # raw vs target on the shared lines, for a scale sanity check
                both = np.isfinite(new_mean) & np.isfinite(target)
                if both.any():
                    base["raw_mean"] = round(float(new_mean[both].mean()), 3)
                    base["tgt_mean"] = round(float(target[both].mean()), 3)
                rows.append(base)
        return {"station": station, "device": dev, "rows": rows}

    results: list[dict[str, Any]] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_cell, d) for d in devices]
        for done, future in enumerate(as_completed(futures), 1):
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                logger.warning("cell crashed: %s", exc)
            if done % 5 == 0:
                logger.info("cells %d/%d (%.0fs)", done, len(devices), time.time() - started)

    flat = [row for device in results for row in device["rows"]]
    accepted = [row for row in flat if row.get("accepted")]

    reasons = Counter(row.get("reason") for row in flat if not row.get("accepted"))
    sources = Counter(row.get("source") for row in accepted)
    per_device_sources: dict[str, Counter] = defaultdict(Counter)
    for row in accepted:
        per_device_sources[row["device"]][row["source"]] += 1
    mixed = {d: dict(c) for d, c in per_device_sources.items() if len(c) > 1}

    s_raw = describe([row["s_raw"] for row in accepted])
    lines_with_raw = describe([row["lines_with_raw"] for row in accepted])
    per_line = describe([c for row in accepted for c in row["per_line_counts"]])
    r_new = describe([r for r in (row.get("r_new") for row in accepted) if r is not None])
    r_old = describe([r for r in (row.get("r_old") for row in accepted) if r is not None])
    wins = sum(1 for row in accepted
               if row.get("r_new") is not None
               and (row.get("r_old") is None or row["r_new"] > row["r_old"]))

    # per-source breakdown: the three raw tables behave differently, so the
    # aggregate hides which ones are actually usable
    per_source: dict[str, dict[str, Any]] = {}
    for name in sources:
        group = [row for row in accepted if row.get("source") == name]
        per_source[name] = {
            "n": len(group),
            "s_raw": describe([row["s_raw"] for row in group]),
            "obs_per_line": describe([c for row in group for c in row["per_line_counts"]]),
            "lines_with_any_raw": describe([row["lines_with_raw"] for row in group]),
            "algo_frac": describe([row["algo_frac"] for row in group]),
            "r_new_join": describe([r for r in (row.get("r_new") for row in group)
                                    if r is not None]),
            "r_algo_only": describe([r for r in (row.get("r_algo") for row in group)
                                     if r is not None]),
            "dropped": sum(row.get("n_dropped", 0) for row in group),
            "used": sum(row.get("n_used", 0) for row in group),
        }

    # which raw tables the platform actually populates, over every measurement
    # seen (accepted or not) - this decides whether of_traj is ever usable alone
    populated = Counter(row.get("populated") for row in flat)
    by_populated_reason: dict[str, Counter] = defaultdict(Counter)
    for row in flat:
        by_populated_reason[row.get("populated")][
            "accepted" if row.get("accepted") else row.get("reason")] += 1

    logger.info("exported=%d accepted=%d (%.1f%%)", len(flat), len(accepted),
                100.0 * len(accepted) / max(1, len(flat)))
    logger.info("rejection reasons: %s", reasons.most_common())
    logger.info("populated raw tables: %s", populated.most_common())
    for combo, counter in sorted(by_populated_reason.items(), key=lambda x: -sum(x[1].values())):
        logger.info("   %-22s -> %s", combo, dict(counter.most_common(3)))
    logger.info("raw source mix: %s", dict(sources))
    logger.info("S (raw columns): %s", s_raw)
    logger.info("observations per line: %s", per_line)
    logger.info("share of lines with any raw input: %s", lines_with_raw)
    logger.info("agreement r (start-distance join): %s", r_new)
    logger.info("agreement r (line-number join): %s", r_old)
    logger.info("sections where the new join agrees better: %d/%d", wins, len(accepted))
    for name, stats in sorted(per_source.items()):
        logger.info("  [%s] n=%d obs/line median=%s lines-with-raw=%s algo_frac=%s",
                    name, stats["n"],
                    (stats["obs_per_line"] or {}).get("median"),
                    (stats["lines_with_any_raw"] or {}).get("mean"),
                    (stats["algo_frac"] or {}).get("mean"))
        logger.info("       r(all lines) median=%s | r(algo lines only) median=%s | "
                    "used %d, out-of-range dropped %d",
                    (stats["r_new_join"] or {}).get("median"),
                    (stats["r_algo_only"] or {}).get("median"),
                    stats["used"], stats["dropped"])
    if mixed:
        logger.info("devices mixing raw tables: %s", dict(list(mixed.items())[:5]))

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps({
        "n_requested": len(flat),
        "n_accepted": len(accepted),
        "accept_rate": round(len(accepted) / max(1, len(flat)), 4),
        "reasons": dict(reasons),
        "sources": dict(sources),
        "populated_tables": dict(populated),
        "populated_outcomes": {k: dict(v) for k, v in by_populated_reason.items()},
        "per_source": per_source,
        "mixed_source_devices": mixed,
        "s_raw": s_raw,
        "per_line_observations": per_line,
        "lines_with_any_raw": lines_with_raw,
        "r_new_join": r_new,
        "r_old_join": r_old,
        "new_join_wins": wins,
        "filter": request_filter,
        "devices": results,
        "seconds": time.time() - started,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    logger.info("wrote %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
