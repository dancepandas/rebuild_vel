"""Station/device catalog from the two platform view CSV exports."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class StationDevice:
    station_code: str
    station_name: str
    device_code: str
    province: str = ""
    city: str = ""
    county: str = ""
    longitude: float = float("nan")
    latitude: float = float("nan")
    calculation_mode: str = ""  # 1 常规; 2 多摄像头; 3 光流场; 4 双向流向; 21/22 融合
    measure_mode: str = ""


def _float_or_nan(value: Optional[str]) -> float:
    try:
        return float(value) if value not in (None, "") else float("nan")
    except ValueError:
        return float("nan")


def load_catalog(
    station_info_csv: str | Path,
    flow_config_csv: str | Path,
    *,
    station_codes: Optional[Sequence[str]] = None,
) -> list[StationDevice]:
    """Join station metadata with flow devices.

    Only ``(station_code, device_code)`` pairs present in the flow-config CSV are
    returned; the station CSV enriches them with names and geography.
    """
    info_by_station: dict[str, dict[str, str]] = {}
    with open(station_info_csv, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            code = (row.get("station_code") or "").strip()
            if code:
                info_by_station[code] = row

    wanted = set(station_codes or [])
    entries: list[StationDevice] = []
    seen: set[tuple[str, str]] = set()
    with open(flow_config_csv, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            station = (row.get("station_code") or "").strip()
            device = (row.get("device_code") or "").strip()
            if not station or not device:
                continue
            if wanted and station not in wanted:
                continue
            key = (station, device)
            if key in seen:
                continue
            seen.add(key)
            info = info_by_station.get(station, {})
            entries.append(StationDevice(
                station_code=station,
                station_name=(info.get("station_name") or "").strip(),
                device_code=device,
                province=(info.get("province") or "").strip(),
                city=(info.get("city") or "").strip(),
                county=(info.get("county_area") or "").strip(),
                longitude=_float_or_nan(info.get("longitude")),
                latitude=_float_or_nan(info.get("latitude")),
                calculation_mode=(row.get("calculation_mode") or "").strip(),
                measure_mode=(row.get("measure_mode") or "").strip(),
            ))
    entries.sort(key=lambda entry: (entry.station_code, entry.device_code))
    return entries


def summarize(entries: Iterable[StationDevice]) -> str:
    entries = list(entries)
    stations = {entry.station_code for entry in entries}
    return f"{len(entries)} devices across {len(stations)} stations"
