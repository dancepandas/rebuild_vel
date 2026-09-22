"""Section index and shard cache behind the web service.

The fetch pipeline writes one pickle per ``(station, device)`` pair holding
every cleaned measurement ever collected for it.  Opening all of them to answer
"which stations do I have" would cost minutes and gigabytes, so the metadata
that the picker needs (station code, name, measurement times) is extracted once
into a small JSON index and reused from then on.  The pickles themselves stay
on disk and are opened on demand, least-recently-used, because a single shard
can reach 800 MB.

    python -m web.index --build          # (re)build data/web_index.json
"""
from __future__ import annotations

import argparse
import gc
import json
import pickle
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

DEFAULT_DATA_ROOT = "data/vel"
DEFAULT_INDEX_PATH = "data/web_index.json"
INDEX_VERSION = 4


def _shard_path(root: Path, shard: str) -> Path:
    return root / "sections" / shard


def build_index(
    data_root: str | Path = DEFAULT_DATA_ROOT,
    index_path: str | Path = DEFAULT_INDEX_PATH,
    *,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Walk every shard once and record station / device / measurement times.

Each measurement is recorded as ``[time, n_lines, mean_velocity]``.  The two
numbers cost a few megabytes in the index and buy the picker a way to tell a
flood from a dry spell before opening anything - which matters here because
roughly a third of all lines in this corpus are dry.
"""
    root = Path(data_root)
    shards = sorted((root / "sections").glob("*.pkl"))
    if not shards:
        raise SystemExit(f"no shards under {root / 'sections'}")

    stations: dict[str, dict[str, Any]] = {}
    n_sections = 0
    started = time.time()
    for i, shard in enumerate(shards, 1):
        with shard.open("rb") as handle:
            sections = pickle.load(handle)
        for section in sections:
            code = str(section.get("station") or "")
            device = str(section.get("device") or "")
            when = str(section.get("time") or "")
            if not code or not device or not when:
                continue
            entry = stations.setdefault(code, {
                "code": code,
                "name": str(section.get("station_name") or "") or code,
                "devices": {},
            })
            if not entry["name"] or entry["name"] == code:
                name = str(section.get("station_name") or "")
                if name:
                    entry["name"] = name
            bucket = entry["devices"].setdefault(device, {
                "device": device, "shard": shard.name, "rows": {},
            })
            try:
                velocity = np.asarray(section["v_surface"], dtype=np.float64)
                mean_v = round(float(velocity.mean()), 4)
                n_lines = int(velocity.size)
            except (KeyError, TypeError, ValueError):
                mean_v, n_lines = None, 0
            bucket["rows"][when] = [when, n_lines, mean_v]
            n_sections += 1
        # a shard can be 800 MB; drop it before the next one so peak memory
        # stays at one shard rather than the whole corpus
        del sections
        if i % 10 == 0 or i == len(shards):
            gc.collect()
            log(f"  indexed {i}/{len(shards)} shards  "
                f"({n_sections:,} measurements, {time.time() - started:.0f}s)")

    out_stations = []
    for entry in stations.values():
        devices = []
        for bucket in entry["devices"].values():
            rows = [row for row in bucket["rows"].values() if row[0]]
            rows.sort(key=lambda r: r[0], reverse=True)
            devices.append({
                "device": bucket["device"],
                "shard": bucket["shard"],
                "n": len(rows),
                "measurements": rows,
            })
        devices.sort(key=lambda d: -d["n"])
        out_stations.append({
            "code": entry["code"],
            "name": entry["name"],
            "n": sum(d["n"] for d in devices),
            "devices": devices,
        })
    out_stations.sort(key=lambda s: s["code"])

    payload = {
        "version": INDEX_VERSION,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data_root": str(root).replace("\\", "/"),
        "n_shards": len(shards),
        "n_sections": n_sections,
        "n_stations": len(out_stations),
        "stations": out_stations,
    }
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    log(f"index written: {path}  "
        f"({len(out_stations)} stations / {n_sections:,} measurements, "
        f"{time.time() - started:.0f}s)")
    return payload


def load_index(
    index_path: str | Path = DEFAULT_INDEX_PATH,
    data_root: str | Path = DEFAULT_DATA_ROOT,
    *,
    rebuild: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    path = Path(index_path)
    if not rebuild and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("version") == INDEX_VERSION:
                return payload
            log(f"index at {path} is version {payload.get('version')}, rebuilding")
        except (OSError, json.JSONDecodeError) as exc:
            log(f"index at {path} unreadable ({exc}), rebuilding")
    return build_index(data_root, path, log=log)


class SectionStore:
    """Random access to cleaned measurements, backed by an LRU of open shards."""

    def __init__(self, index: dict[str, Any], *, max_open_shards: int = 2) -> None:
        self.index = index
        self.root = Path(index.get("data_root") or DEFAULT_DATA_ROOT)
        self.max_open_shards = max(1, max_open_shards)
        self._cache: OrderedDict[str, dict[str, dict[str, Any]]] = OrderedDict()
        self._by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for station in index["stations"]:
            for device in station["devices"]:
                self._by_key[(station["code"], device["device"])] = device

    # -- lookups ----------------------------------------------------------
    def stations(self) -> list[dict[str, Any]]:
        return self.index["stations"]

    def devices(self, station: str) -> list[dict[str, Any]]:
        return self._devices(station)

    def _devices(self, station: str) -> list[dict[str, Any]]:
        for entry in self.index["stations"]:
            if entry["code"] == station:
                return entry["devices"]
        return []

    def measurements(self, station: str, device: Optional[str] = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entry in self._devices(station):
            if device and entry["device"] != device:
                continue
            rows.extend({
                "device": entry["device"],
                "time": row[0],
                "n_lines": row[1],
                "mean_velocity": row[2],
            } for row in entry["measurements"])
        rows.sort(key=lambda r: r["time"], reverse=True)
        return rows

    # -- shard access -----------------------------------------------------
    def _shard(self, station: str, device: str) -> dict[str, dict[str, Any]]:
        meta = self._by_key.get((station, device))
        if meta is None:
            raise KeyError(f"unknown station/device {station}/{device}")
        name = meta["shard"]
        if name in self._cache:
            self._cache.move_to_end(name)
            return self._cache[name]
        path = _shard_path(self.root, name)
        if not path.is_file():
            raise KeyError(f"shard missing on disk: {path}")
        with path.open("rb") as handle:
            sections = pickle.load(handle)
        by_time = {str(s.get("time") or ""): s for s in sections}
        del sections
        self._cache[name] = by_time
        while len(self._cache) > self.max_open_shards:
            self._cache.popitem(last=False)
        gc.collect()
        return by_time

    def get(self, station: str, device: str, when: str) -> dict[str, Any]:
        shard = self._shard(station, device)
        if when not in shard:
            raise KeyError(f"no measurement {when} for {station}/{device}")
        return shard[when]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the web service section index")
    parser.add_argument("--build", action="store_true", help="force a rebuild")
    parser.add_argument("--data", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--index", default=DEFAULT_INDEX_PATH)
    args = parser.parse_args(argv)
    payload = load_index(args.index, args.data, rebuild=args.build)
    print(f"{payload['n_stations']} stations, {payload['n_sections']:,} measurements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
