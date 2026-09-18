"""Quality gates: parsed measurements -> clean section samples with numpy arrays."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np


class SectionQualityError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class QualityOptions:
    min_lines: int = 8
    max_target_velocity: float = 5.633   # [0, mu+4sigma] cleaned range from the V3 report
    max_zero_fraction: float = 0.85
    min_nonzero_lines: int = 3
    max_duplicate_x: float = 1e-6
    max_dominant_value_fraction: float = 0.8


def _finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SectionQualityError("nonfinite", f"value is not numeric: {value!r}") from exc
    if not np.isfinite(result):
        raise SectionQualityError("nonfinite", f"value is not finite: {value!r}")
    return result


def clean_measurement(
    measurement: dict[str, Any],
    options: QualityOptions = QualityOptions(),
) -> dict[str, Any]:
    """Validate one parsed measurement and convert it to numpy arrays.

    Returns a section dict whose ``v_surface`` column is the reconstruction
    target and whose ``raw_*`` arrays are the per-video-segment observations.
    """
    lines = measurement.get("lines") or []
    if len(lines) < options.min_lines:
        raise SectionQualityError("too_few_lines", f"only {len(lines)} speed lines")

    station = str(measurement.get("station") or "")
    device = str(measurement.get("device") or "")
    time = str(measurement.get("time") or "")
    if not station or not device or not time:
        raise SectionQualityError("missing_identity", "station, device and time are required")

    water_level = measurement.get("water_level")
    if water_level is None or not np.isfinite(float(water_level)):
        raise SectionQualityError("bad_water_level", "water level is missing or non-finite")

    # -- order lines by start distance ------------------------------------
    order = sorted(lines, key=lambda item: _finite(item.get("x")))
    x = np.asarray([_finite(item.get("x")) for item in order], dtype=np.float64)
    if np.any(np.diff(x) <= options.max_duplicate_x):
        raise SectionQualityError("duplicate_x", "line positions are not strictly increasing")

    line_num = np.asarray([float(item.get("line_num", -1)) for item in order])
    depth = np.asarray([_finite_or_nan(item.get("depth")) for item in order])
    bed = np.asarray([_finite_or_nan(item.get("bed_elevation")) for item in order])
    # depth fallback: water level minus bed elevation
    missing = ~np.isfinite(depth)
    if missing.any():
        if not np.isfinite(bed[missing]).all():
            raise SectionQualityError("bad_depth", "line depth missing and bed elevation unavailable")
        depth[missing] = float(water_level) - bed[missing]
    if (depth < 0).any():
        depth = depth.clip(min=0.0)

    v_surface = np.asarray([_finite_or_nan(item.get("v_surface")) for item in order])
    if not np.isfinite(v_surface).all():
        raise SectionQualityError("bad_velocity", "line surface velocity has non-finite values")
    if float(v_surface.max()) > options.max_target_velocity:
        raise SectionQualityError(
            "velocity_out_of_range",
            f"max surface velocity {v_surface.max():.3f} exceeds {options.max_target_velocity}",
        )

    nonzero = np.abs(v_surface) > 1e-9
    if int(nonzero.sum()) < options.min_nonzero_lines:
        raise SectionQualityError("mostly_zero", "too few nonzero target velocities")
    if float((~nonzero).mean()) > options.max_zero_fraction:
        raise SectionQualityError("mostly_zero", "target zero fraction is too high")
    unique, counts = np.unique(v_surface, return_counts=True)
    if len(v_surface) >= 5 and float(counts.max() / len(v_surface)) >= options.max_dominant_value_fraction:
        raise SectionQualityError("dominant_value", "one exact velocity value dominates the section")

    confidence = np.asarray([_finite_or_nan(item.get("confidence")) for item in order])
    angle = np.asarray([_finite_or_nan(item.get("angle")) for item in order])
    is_algo = np.asarray([bool(item.get("is_algo")) for item in order], dtype=bool)
    if not is_algo.any():
        raise SectionQualityError("no_algorithm_lines", "section has no algorithm-given lines")

    # -- align raw STIV segments to lines ----------------------------------
    raw_v, raw_conf, raw_angle, raw_valid, raw_t0, raw_t1, raw_seg = _align_raw(
        measurement.get("raw_stiv") or [], line_num, x
    )

    return {
        "station": station,
        "device": device,
        "time": time,
        "station_name": str(measurement.get("station_name") or ""),
        "water_level": float(water_level),
        "water_width": _finite_or_nan(measurement.get("water_width")),
        "section_area": _finite_or_nan(measurement.get("section_area")),
        "surface_avg_velocity": _finite_or_nan(measurement.get("surface_avg_velocity")),
        "max_depth": _finite_or_nan(measurement.get("max_depth")),
        "aver_depth": _finite_or_nan(measurement.get("aver_depth")),
        "original_value_prop": _finite_or_nan(measurement.get("original_value_prop")),
        "version": str(measurement.get("version") or ""),
        "x": x.astype(np.float32),
        "depth": depth.astype(np.float32),
        "bed_elevation": bed.astype(np.float32),
        "v_surface": v_surface.astype(np.float32),
        "confidence": confidence.astype(np.float32),
        "angle": angle.astype(np.float32),
        "is_algo": is_algo,
        "line_num": line_num.astype(np.float32),
        "raw_v": raw_v.astype(np.float32),
        "raw_conf": raw_conf.astype(np.float32),
        "raw_angle": raw_angle.astype(np.float32),
        "raw_valid": raw_valid,
        "raw_t_start": raw_t0.astype(np.float32),
        "raw_t_end": raw_t1.astype(np.float32),
        "raw_segment_id": raw_seg.astype(np.float32),
        "raw_pixel_length": _align_line_scalar(
            measurement.get("raw_stiv") or [], line_num, "pixel_length"),
        "raw_physical_length": _align_line_scalar(
            measurement.get("raw_stiv") or [], line_num, "physical_length"),
        "n_raw_of_traj": len(measurement.get("raw_of_traj") or []),
        "n_raw_of": len(measurement.get("raw_of") or []),
    }


def _finite_or_nan(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if np.isfinite(result) else float("nan")


def _align_raw(
    raw_rows: list[dict[str, Any]],
    line_num: np.ndarray,
    x: np.ndarray,
) -> tuple[np.ndarray, ...]:
    """Group raw rows by line number and pad to [K, S_max]."""
    by_line: dict[float, list[dict[str, Any]]] = {}
    for row in raw_rows:
        key = float(row.get("line_num", -1))
        by_line.setdefault(key, []).append(row)

    counts = [len(by_line.get(float(ln), [])) for ln in line_num]
    s_max = max(counts) if counts else 0
    k = len(line_num)
    shape = (k, max(s_max, 1))
    raw_v = np.full(shape, np.nan, dtype=np.float64)
    raw_conf = np.full(shape, np.nan, dtype=np.float64)
    raw_angle = np.full(shape, np.nan, dtype=np.float64)
    raw_valid = np.zeros(shape, dtype=bool)
    raw_t0 = np.full(shape, np.nan, dtype=np.float64)
    raw_t1 = np.full(shape, np.nan, dtype=np.float64)
    raw_seg = np.full(shape, np.nan, dtype=np.float64)

    for i, ln in enumerate(line_num):
        rows = sorted(by_line.get(float(ln), []), key=lambda r: (
            _finite_or_nan(r.get("video_segment_id")),
            _finite_or_nan(r.get("t_start")),
        ))
        for j, row in enumerate(rows[: s_max]):
            raw_v[i, j] = _finite_or_nan(row.get("raw_v"))
            raw_conf[i, j] = _finite_or_nan(row.get("confidence"))
            raw_angle[i, j] = _finite_or_nan(row.get("angle"))
            raw_t0[i, j] = _finite_or_nan(row.get("t_start"))
            raw_t1[i, j] = _finite_or_nan(row.get("t_end"))
            raw_seg[i, j] = _finite_or_nan(row.get("video_segment_id"))
            raw_valid[i, j] = np.isfinite(raw_v[i, j])
    return raw_v, raw_conf, raw_angle, raw_valid, raw_t0, raw_t1, raw_seg


def _align_line_scalar(raw_rows: list[dict[str, Any]], line_num: np.ndarray, key: str) -> np.ndarray:
    first: dict[float, float] = {}
    for row in raw_rows:
        ln = float(row.get("line_num", -1))
        if ln not in first:
            first[ln] = _finite_or_nan(row.get(key))
    out = np.full(len(line_num), np.nan, dtype=np.float64)
    for i, ln in enumerate(line_num):
        out[i] = first.get(float(ln), float("nan"))
    return out.astype(np.float32)
