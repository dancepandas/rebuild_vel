"""Dump the raw->target alignment for a few real measurements.

Answers the question the aggregate correlation cannot: are raw observations
*exactly* at target line positions (a subset grid), or on an independent
finer grid that needs a tolerance? Also shows what the old 测速线序号 join
was actually pairing up.
"""
from __future__ import annotations
import json, sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from rebuild_vel.accounts import AccountPool
from rebuild_vel.client import FlowClient
from rebuild_vel.parse import parse_merged_export

probe = json.loads(Path("data/probe.json").read_text(encoding="utf-8"))
usable = sorted(k for k, v in probe["devices"].items()
                if any(m.get("usable") for m in (v.get("months") or {}).values()))
random.Random(3).shuffle(usable)

client = FlowClient(AccountPool("accounts.json"), timeout=120, request_delay=0.05)
shown = 0
for key in usable:
    station, device = key.split("|", 1)
    try:
        listing = client.post("/flow/originalDataFilterPage", {
            "count": 3, "page": 1, "request": {
                "beginTime": "2025-09-01 00:00:00.000", "endTime": "2026-08-31 23:59:59.999",
                "stationCode": station, "deviceCode": device,
                "measureResult": 1, "reliability": 1}})
    except Exception:
        continue
    times = [str(r["measureTime"]) for r in (listing.get("data") or []) if r.get("measureTime")]
    if not times:
        continue
    try:
        body = client.get_bytes("/flow/procedureDataMergeExport", {
            "stationCode": station, "deviceCode": device, "measureTimeList": times[:1]})
    except Exception:
        continue
    if not body:
        continue
    m = parse_merged_export(body).measurements
    if not m:
        continue
    m = m[0]
    src = None
    for name, k in (("stiv", "raw_stiv"), ("of", "raw_of"), ("of_traj", "raw_of_traj")):
        if m.get(k):
            src, rows = name, m[k]
            break
    if not src:
        continue
    tx = np.array(sorted(float(l["x"]) for l in m["lines"] if np.isfinite(l["x"])))
    rx = np.array([float(r["x"]) for r in rows if np.isfinite(r["x"])])
    dist = np.abs(rx[:, None] - tx[None, :]).min(axis=1)
    exact = float(np.mean(dist < 1e-6))
    print(f"\n=== {station}|{device} {m['time']}  source={src}")
    print(f"    target lines={len(tx)}  raw rows={len(rx)}")
    print(f"    target x: {np.round(tx[:8],2)} ... {np.round(tx[-4:],2)}")
    print(f"    raw    x: {np.round(np.unique(rx)[:8],2)} ... ({len(np.unique(rx))} distinct)")
    print(f"    nearest-target distance: exact={exact:.0%}  median={np.median(dist):.3f} "
          f" p90={np.percentile(dist,90):.3f}  max={dist.max():.3f}")
    # what the OLD join paired: raw row's line_num -> target line with that line_num
    by_ln = {}
    for r in m["lines"]:
        by_ln.setdefault(float(r["line_num"]), float(r["x"]))
    pairs = [(float(r["x"]), by_ln.get(float(r["line_num"]))) for r in rows]
    pairs = [(a, b) for a, b in pairs if b is not None and np.isfinite(b)]
    if pairs:
        gaps = np.abs(np.array([a for a, _ in pairs]) - np.array([b for _, b in pairs]))
        print(f"    OLD join (测速线序号): {len(pairs)} pairs, "
              f"median |x_raw - x_line| = {np.median(gaps):.2f} m, exact={np.mean(gaps<1e-6):.0%}")
    shown += 1
    if shown >= 4:
        break
