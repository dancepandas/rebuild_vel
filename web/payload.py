"""Turn one cleaned measurement + model predictions into the panel payload.

Everything the panel draws comes from here, in either physical units (metres,
m/s, metres above datum) or line indices - never in normalized model units, so
the frontend never has to know the standardization scheme.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from .infer import DISAGREEMENT_THRESHOLD, VALVE_MAX_DEPTH

#: raw observations per line are capped for display; a line can carry dozens of
#: 30 s video segments and the panel only needs to show the distribution
MAX_RAW_PER_LINE = 24


def _num(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _regression_metrics(pred: np.ndarray, target: np.ndarray) -> dict[str, float]:
    diff = pred - target
    denom = float(np.sum((target - target.mean()) ** 2))
    # _num, not the raw float: a section whose platform values are all identical
    # has no variance, so NSE is 0/0 and comes out NaN - which json.dumps writes
    # as a bare NaN, which JSON.parse refuses.  One such section would take the
    # whole panel down with a parse error instead of drawing.  Null is the honest
    # encoding: the statistic is undefined here, not zero.
    return {
        "rmse": _num(np.sqrt(np.mean(diff ** 2))),
        "mae": _num(np.mean(np.abs(diff))),
        "bias": _num(np.mean(diff)),
        "nse": _num(1.0 - float(np.sum(diff ** 2)) / denom) if denom > 0 else None,
        "max_abs": _num(np.max(np.abs(diff))) if diff.size else 0.0,
    }


def build_payload(
    section: dict[str, Any],
    predictions: dict[str, np.ndarray],
    *,
    line_states: Optional[np.ndarray] = None,
    source: str = "cache",
) -> dict[str, Any]:
    x = np.asarray(section["x"], dtype=np.float64)
    k = len(x)
    depth = np.asarray(section["depth"], dtype=np.float64)
    water_level = _num(section.get("water_level"))
    target = np.asarray(section["v_surface"], dtype=np.float64)
    is_algo = np.asarray(section.get("is_algo", np.zeros(k, bool)), dtype=bool)
    confidence = np.asarray(section.get("confidence", np.full(k, np.nan)), dtype=np.float64)
    angle = np.asarray(section.get("angle", np.full(k, np.nan)), dtype=np.float64)

    bed = np.asarray(section.get("bed_elevation", np.full(k, np.nan)), dtype=np.float64)
    if water_level is not None:
        missing = ~np.isfinite(bed)
        bed[missing] = water_level - depth[missing]

    raw_v = np.asarray(section["raw_v"], dtype=np.float64)
    raw_valid = np.asarray(section["raw_valid"], dtype=bool)
    raw_x = np.asarray(section["raw_x"], dtype=np.float64)
    raw_conf = np.asarray(section.get("raw_conf", np.full(raw_v.shape, np.nan)), dtype=np.float64)
    raw_angle = np.asarray(section.get("raw_angle", np.full(raw_v.shape, np.nan)), dtype=np.float64)
    raw_t0 = np.asarray(section.get("raw_t_start", np.full(raw_v.shape, np.nan)), dtype=np.float64)
    raw_seg = np.asarray(section.get("raw_segment_id", np.full(raw_v.shape, np.nan)), dtype=np.float64)

    finite_t = raw_t0[np.isfinite(raw_t0) & raw_valid]
    t_lo = float(finite_t.min()) if finite_t.size else 0.0

    lines: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    # lines with no water column: their reconstruction was forced to zero by the
    # valve in infer.apply_dry_valve.  Counted here so the panel can say so out
    # loud rather than let a row of zeros look like a model that got them right.
    valved = ~(depth > VALVE_MAX_DEPTH)
    for i in range(k):
        valid_idx = np.nonzero(raw_valid[i])[0]
        if valid_idx.size > MAX_RAW_PER_LINE:
            # keep the spread, not an arbitrary prefix: stride the sample
            stride = int(np.ceil(valid_idx.size / MAX_RAW_PER_LINE))
            shown = valid_idx[::stride][:MAX_RAW_PER_LINE]
        else:
            shown = valid_idx
        for j in shown:
            observations.append({
                "line": i,
                "x": _num(raw_x[i, j]),
                "v": _num(raw_v[i, j]),
                "confidence": _num(raw_conf[i, j]),
                "angle": _num(raw_angle[i, j]),
                "t": _num(raw_t0[i, j] - t_lo) if np.isfinite(raw_t0[i, j]) else None,
                "segment": _num(raw_seg[i, j]),
            })
        entry: dict[str, Any] = {
            "i": i,
            "x": _num(x[i]),
            "depth": _num(depth[i]),
            "bed": _num(bed[i]),
            "target": _num(target[i]),
            "algo": bool(is_algo[i]),
            "confidence": _num(confidence[i]),
            "angle": _num(angle[i]),
            "n_raw": int(valid_idx.size),
            "n_raw_total": int(raw_valid[i].sum()),
            "valved": bool(valved[i]),
        }
        for arm_id, values in predictions.items():
            entry[f"pred_{arm_id}"] = _num(values[i]) if i < len(values) else None
        lines.append(entry)

    metrics: dict[str, Any] = {}
    for arm_id, values in predictions.items():
        if len(values) < k:
            continue
        block = _regression_metrics(np.asarray(values[:k], dtype=np.float64), target)
        pred = np.asarray(values[:k], dtype=np.float64)
        block["disagreement"] = int(np.sum(np.abs(pred - target) > DISAGREEMENT_THRESHOLD))
        block["zero_lines_pred_positive"] = int(
            np.sum((target == 0) & (pred > 0.1)))
        metrics[arm_id] = block

    raw_pos = np.asarray([o["x"] for o in observations if o["x"] is not None], dtype=np.float64)
    raw_vals = np.asarray([o["v"] for o in observations if o["v"] is not None], dtype=np.float64)
    return {
        "source": source,
        "station": str(section.get("station") or ""),
        "station_name": str(section.get("station_name") or ""),
        "device": str(section.get("device") or ""),
        "time": str(section.get("time") or ""),
        "disagreement_threshold": DISAGREEMENT_THRESHOLD,
        "meta": {
            "water_level": water_level,
            "water_width": _num(section.get("water_width")),
            "section_area": _num(section.get("section_area")),
            "surface_avg_velocity": _num(section.get("surface_avg_velocity")),
            "max_depth": _num(section.get("max_depth")),
            "aver_depth": _num(section.get("aver_depth")),
            "raw_source": str(section.get("raw_source") or ""),
            "raw_tolerance": _num(section.get("raw_tolerance")),
            "n_raw_used": int(section.get("n_raw_used") or 0),
            "n_raw_stiv": int(section.get("n_raw_stiv") or 0),
            "n_raw_of": int(section.get("n_raw_of") or 0),
            "version": str(section.get("version") or ""),
            "n_lines": k,
            "n_algo": int(is_algo.sum()),
            "n_dry": int((depth < 0.01).sum()),
            "n_valved": int(valved.sum()),
            "valve_max_depth": VALVE_MAX_DEPTH,
        },
        "lines": lines,
        "observations": observations,
        "observations_summary": {
            "n": int(len(observations)),
            "median": _num(np.median(raw_vals)) if raw_vals.size else None,
            "p05": _num(np.percentile(raw_vals, 5)) if raw_vals.size else None,
            "p95": _num(np.percentile(raw_vals, 95)) if raw_vals.size else None,
            "min_x": _num(raw_pos.min()) if raw_pos.size else None,
            "max_x": _num(raw_pos.max()) if raw_pos.size else None,
        },
        "metrics": metrics,
    }
