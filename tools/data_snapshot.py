"""Snapshot the fetched shard pool: size, coverage, and shape distributions.

Writes a json record used as the honest "what data was this model trained on"
evidence for a run. Read-only: never touches the API.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Snapshot shard-pool statistics")
    parser.add_argument("--data", required=True, help="fetch output directory")
    parser.add_argument("--output", required=True, help="json path")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    shard_dir = Path(args.data) / "sections"
    shards = sorted(shard_dir.glob("*.pkl"))
    if not shards:
        raise SystemExit(f"no shards under {shard_dir}")

    n_sections = 0
    stations: set[str] = set()
    devices: set[str] = set()
    months: set[str] = set()
    sources: Counter[str] = Counter()
    lines: list[int] = []
    obs_per_line: list[float] = []
    gaps_empty_cells = 0

    for shard in shards:
        with open(shard, "rb") as fh:
            sections = pickle.load(fh)
        for section in sections:
            n_sections += 1
            stations.add(str(section.get("station", "")))
            devices.add(str(section.get("device", "")))
            time = str(section.get("time", ""))
            if len(time) >= 7:
                months.add(time[:7])
            sources[str(section.get("raw_source") or "unknown")] += 1
            valid = np.asarray(section["raw_valid"], dtype=bool)
            lines.append(int(valid.shape[0]))
            obs_per_line.extend(valid.sum(axis=1).tolist())

    lines_arr = np.asarray(lines, dtype=float)
    obs_arr = np.asarray(obs_per_line, dtype=float)
    snapshot = {
        "data_dir": str(args.data),
        "n_shards": len(shards),
        "n_sections": n_sections,
        "n_stations": len(stations),
        "n_devices": len(devices),
        "month_span": sorted(months),
        "n_months": len(months),
        "sources": dict(sources),
        "lines_per_section": {
            "min": int(lines_arr.min()),
            "p10": float(np.quantile(lines_arr, 0.1)),
            "median": float(np.median(lines_arr)),
            "p90": float(np.quantile(lines_arr, 0.9)),
            "max": int(lines_arr.max()),
        },
        "obs_per_line": {
            "min": int(obs_arr.min()),
            "p10": float(np.quantile(obs_arr, 0.1)),
            "median": float(np.median(obs_arr)),
            "p90": float(np.quantile(obs_arr, 0.9)),
            "max": int(obs_arr.max()),
            "frac_zero": float((obs_arr == 0).mean()),
        },
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
