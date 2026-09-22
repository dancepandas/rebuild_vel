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
    min_raw_rows: int = 1                # input-side gate: a section with no raw
                                         # observations is unusable as training data
    raw_tolerance: float = 0.0           # metres; <=0 derives it from line spacing
    require_algorithm_lines: bool = True  # the training corpus keeps only sections
                                          # the instrument actually measured lines on

    @classmethod
    def for_inference(cls) -> "QualityOptions":
        """The gate for showing a measurement, as opposed to training on it.

        The default values above are corpus filters: they decide whether a
        measurement is a *good training example*, and they throw away most of a
        real device-day (a section whose lines all read zero at night teaches
        the model nothing, so it is dropped).  Showing one is a different
        question - a reviewer looking at a live timestamp wants to see what the
        model does with that measurement, including the degenerate ones, and
        answering "rejected" hides the very case they came to look at.

        So this keeps only the checks that are structurally necessary to build
        a drawable section, and drops every threshold.  Kept: at least one line,
        identity, a water level, strictly increasing x, a resolvable depth,
        finite target values, and at least one raw observation - without any of
        these there is no section to draw, or the model has no input at all.
        Dropped: min_lines 8, max_target_velocity 5.633, min_nonzero_lines 3,
        max_zero_fraction 0.85, max_dominant_value_fraction 0.8, and the
        requirement that the instrument have measured some lines itself.

        The thresholds are disabled with values the comparisons cannot reach,
        rather than by branching inside clean_measurement - one code path stays
        one code path, so an inference section and a training section are built
        by exactly the same code.
        """
        return cls(
            min_lines=1,
            max_target_velocity=float("inf"),
            max_zero_fraction=float("inf"),
            min_nonzero_lines=0,
            max_dominant_value_fraction=float("inf"),
            require_algorithm_lines=False,
        )

#: raw-velocity tables in the procedure workbook, in priority order. Devices
#: differ in which one they populate; STIV wins when more than one has rows.
RAW_SOURCES = ("stiv", "of", "of_traj")

#: per-observation auxiliary channels packed alongside the velocity sequence;
#: only the optical-flow sheets carry these columns, STIV rows leave them NaN
RAW_AUX_KEYS = ("region_mean", "std", "max_v", "min_v",
                "direction_ratio", "pixel_scale", "vertical_v")
RAW_AUX_CHANNELS = len(RAW_AUX_KEYS)

_RAW_MEASUREMENT_KEY = {
    "stiv": "raw_stiv",
    "of": "raw_of",
    "of_traj": "raw_of_traj",
}


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
    if options.require_algorithm_lines and not is_algo.any():
        raise SectionQualityError("no_algorithm_lines", "section has no algorithm-given lines")

    # -- pick the raw source and align its observations to the lines --------
    # Devices differ in which raw table they fill; take the one that has data,
    # preferring STIV when more than one does. Raw positions are a finer,
    # differently-spaced grid than the target lines, so observations are
    # matched by start distance rather than by 测速线序号 (which is a global row
    # counter in the raw sheets, not a line index).
    source, raw_rows = _select_raw_source(measurement, options)
    if not raw_rows:
        raise SectionQualityError(
            "no_raw_input", "no raw velocity observations in any of the three raw tables")

    tolerance = options.raw_tolerance if options.raw_tolerance > 0 else _default_tolerance(x)
    raw_v, raw_conf, raw_angle, raw_valid, raw_t0, raw_t1, raw_seg, raw_x, raw_aux, dropped = _align_raw(
        raw_rows, x, tolerance
    )
    if not raw_valid.any():
        raise SectionQualityError(
            "no_raw_input",
            f"{source} rows exist but none lie within {tolerance:.2f} m of a target line")

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
        "raw_x": raw_x.astype(np.float32),
        "raw_aux": raw_aux.astype(np.float32),
        "raw_source": source,
        "raw_tolerance": tolerance,
        "raw_pixel_length": _align_line_scalar(raw_rows, x, tolerance, "pixel_length"),
        "raw_physical_length": _align_line_scalar(raw_rows, x, tolerance, "physical_length"),
        "n_raw_stiv": len(measurement.get("raw_stiv") or []),
        "n_raw_of_traj": len(measurement.get("raw_of_traj") or []),
        "n_raw_of": len(measurement.get("raw_of") or []),
        "n_raw_used": int(raw_valid.sum()),
        "n_raw_dropped": int(dropped),
    }


def _finite_or_nan(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if np.isfinite(result) else float("nan")


def _select_raw_source(
    measurement: dict[str, Any],
    options: QualityOptions,
) -> tuple[str, list[dict[str, Any]]]:
    """Choose which raw table feeds the model input for this measurement.

    Some devices populate only STIV, others only one of the optical-flow
    tables. Whichever has rows is the input; when more than one does, STIV wins;
    when STIV is empty the optical-flow table with more rows is used.
    """
    tables = {name: measurement.get(_RAW_MEASUREMENT_KEY[name]) or [] for name in RAW_SOURCES}
    counts = {name: len(rows) for name, rows in tables.items()}
    if counts["stiv"] >= options.min_raw_rows:
        return "stiv", tables["stiv"]
    best = max(RAW_SOURCES[1:], key=lambda name: counts[name])
    if counts[best] >= options.min_raw_rows:
        return best, tables[best]
    return "", []


def _default_tolerance(line_x: np.ndarray) -> float:
    """Half the typical spacing between target lines, clamped to a sane range."""
    if len(line_x) < 2:
        return 1.0
    gaps = np.diff(np.sort(line_x))
    gaps = gaps[gaps > 1e-6]
    if not len(gaps):
        return 1.0
    return float(np.clip(float(np.median(gaps)) / 2.0, 0.5, 5.0))


def _assign_raw(
    raw_rows: list[dict[str, Any]],
    line_x: np.ndarray,
    tolerance: float,
) -> tuple[dict[int, list[dict[str, Any]]], int]:
    """Bucket raw observations onto the nearest target line within ``tolerance``.

    The raw grid is finer and differently spaced than the target lines, so a
    line can collect several observations (different video segments, or the
    same position seen from different work points).

    Observations outside the span of the target lines are dropped rather than
    clamped to the edge lines: the optical-flow trajectory table describes its
    own sub-range of the cross-section, and folding a point that is metres
    beyond the last line onto that line would fabricate input. Returns the
    buckets and the number of dropped out-of-range rows.
    """
    assigned: dict[int, list[dict[str, Any]]] = {}
    if not len(line_x):
        return assigned, len(raw_rows)
    lo = float(line_x.min()) - tolerance
    hi = float(line_x.max()) + tolerance
    dropped = 0
    for row in raw_rows:
        rx = _finite_or_nan(row.get("x"))
        if not np.isfinite(rx) or rx < lo or rx > hi:
            dropped += 1
            continue
        index = int(np.argmin(np.abs(line_x - rx)))
        if abs(float(line_x[index]) - rx) <= tolerance:
            assigned.setdefault(index, []).append(row)
        else:
            dropped += 1
    return assigned, dropped


def _align_raw(
    raw_rows: list[dict[str, Any]],
    line_x: np.ndarray,
    tolerance: float,
) -> tuple[np.ndarray, ...]:
    """Assign raw rows to target lines by start distance and pad to [K, S_max]."""
    assigned, dropped = _assign_raw(raw_rows, line_x, tolerance)

    counts = [len(assigned.get(i, [])) for i in range(len(line_x))]
    s_max = max(counts) if counts else 0
    k = len(line_x)
    shape = (k, max(s_max, 1))
    raw_v = np.full(shape, np.nan, dtype=np.float64)
    raw_conf = np.full(shape, np.nan, dtype=np.float64)
    raw_angle = np.full(shape, np.nan, dtype=np.float64)
    raw_valid = np.zeros(shape, dtype=bool)
    raw_t0 = np.full(shape, np.nan, dtype=np.float64)
    raw_t1 = np.full(shape, np.nan, dtype=np.float64)
    raw_seg = np.full(shape, np.nan, dtype=np.float64)
    raw_x = np.full(shape, np.nan, dtype=np.float64)
    raw_aux = np.full((k, max(s_max, 1), RAW_AUX_CHANNELS), np.nan, dtype=np.float64)

    for i in range(k):
        rows = assigned.get(i)
        if not rows:
            continue
        rows.sort(key=lambda r: (
            _finite_or_nan(r.get("t_start")),
            _finite_or_nan(r.get("video_segment_id")),
        ))
        for j, row in enumerate(rows[: s_max]):
            raw_v[i, j] = _finite_or_nan(row.get("raw_v"))
            raw_conf[i, j] = _finite_or_nan(row.get("confidence"))
            raw_angle[i, j] = _finite_or_nan(row.get("angle"))
            raw_t0[i, j] = _finite_or_nan(row.get("t_start"))
            raw_t1[i, j] = _finite_or_nan(row.get("t_end"))
            raw_seg[i, j] = _finite_or_nan(row.get("video_segment_id"))
            raw_x[i, j] = _finite_or_nan(row.get("x"))
            for c, key in enumerate(RAW_AUX_KEYS):
                raw_aux[i, j, c] = _finite_or_nan(row.get(key))
            raw_valid[i, j] = np.isfinite(raw_v[i, j])
    return raw_v, raw_conf, raw_angle, raw_valid, raw_t0, raw_t1, raw_seg, raw_x, raw_aux, dropped


def _align_line_scalar(
    raw_rows: list[dict[str, Any]],
    line_x: np.ndarray,
    tolerance: float,
    key: str,
) -> np.ndarray:
    """First observation's ``key`` per line (NaN where the table lacks the column)."""
    assigned, _ = _assign_raw(raw_rows, line_x, tolerance)
    out = np.full(len(line_x), np.nan, dtype=np.float64)
    for i, rows in assigned.items():
        out[i] = _finite_or_nan(rows[0].get(key))
    return out.astype(np.float32)
