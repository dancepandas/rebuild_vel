"""Alignment check restricted to the optical-flow raw tables.

The STIV sheet turns out to sit exactly on the target line grid, so matching it
is unambiguous. The optical-flow sheets need their own look: do their 起点距
values land on the target grid, and is their 测速线序号 a real line index?
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
random.Random(9).shuffle(usable)

client = FlowClient(AccountPool("accounts.json"), timeout=120, request_delay=0.05)
found = {"stiv": 0, "of": 0, "of_traj": 0}
scanned = 0
for key in usable:
    if found["of"] >= 4 and found["of_traj"] >= 3 and found["stiv"] >= 2:
        break
    if scanned >= 60:
        break
    station, device = key.split("|", 1)
    try:
        listing = client.post("/flow/originalDataFilterPage", {
            "count": 4, "page": 1, "request": {
                "beginTime": "2024-09-01 00:00:00.000", "endTime": "2026-08-31 23:59:59.999",
                "stationCode": station, "deviceCode": device,
                "measureResult": 1, "reliability": 1}})
        body = client.get_bytes("/flow/procedureDataMergeExport", {
            "stationCode": station, "deviceCode": device,
            "measureTimeList": [str(r["measureTime"]) for r in (listing.get("data") or [])
                                if r.get("measureTime")][:2]})
    except Exception:
        continue
    if not body:
        continue
    scanned += 1
    for m in parse_merged_export(body).measurements:
        for src, k in (("stiv", "raw_stiv"), ("of", "raw_of"), ("of_traj", "raw_of_traj")):
            rows = m.get(k) or []
            if not rows:
                continue
            if src == "stiv" and found["stiv"] >= 2: continue
            if src == "of" and found["of"] >= 4: continue
            if src == "of_traj" and found["of_traj"] >= 3: continue
            tx = np.array(sorted(float(l["x"]) for l in m["lines"] if np.isfinite(l["x"])))
            by_ln = {float(l["line_num"]): float(l["x"]) for l in m["lines"]}
            rx = np.array([float(r["x"]) for r in rows if np.isfinite(r["x"])])
            if len(tx) < 2 or len(rx) < 2:
                continue
            dist = np.abs(rx[:, None] - tx[None, :]).min(axis=1)
            # does 测速线序号 point at the right line?
            ln_pairs = [(float(r["line_num"]), by_ln.get(float(r["line_num"]))) for r in rows]
            ln_pairs = [(a, b) for a, b in ln_pairs if b is not None and np.isfinite(b)]
            found[src] += 1
            print(f"\n=== [{src}] {station}|{device} {m['time']}")
            print(f"    targets={len(tx)} span={tx[0]:.2f}..{tx[-1]:.2f} (gap~{np.median(np.diff(tx)):.2f})"
                  f"  raw rows={len(rx)}  distinct raw x={len(np.unique(rx))}"
                  f"  raw span={rx.min():.2f}..{rx.max():.2f}")
            ln_nums = sorted({float(r["line_num"]) for r in rows})
            print(f"    raw 测速线序号 values: {ln_nums[:12]}{' ...' if len(ln_nums)>12 else ''}"
                  f"  (target line_num {sorted(by_ln)[:6]}...)")
            print(f"    x-align: exact={np.mean(dist<1e-6):.0%} median={np.median(dist):.3f} "
                  f"p90={np.percentile(dist,90):.3f}")
            if ln_pairs:
                gaps = np.abs(np.array([a for a,_ in ln_pairs]) - np.array([b for _,b in ln_pairs]))
                print(f"    line_num-align: {len(ln_pairs)} pairs exact={np.mean(gaps<1e-6):.0%} "
                      f"median_gap={np.median(gaps):.2f} m")
