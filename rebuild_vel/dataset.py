"""Turn cleaned section shards into model-ready tensors.

Per measurement (one cross-section at one time) a sample carries:

* ``morphology``     [K, 4]  x_norm, d_norm, bank, grad (section-normalized)
* ``raw_stats``      [K, F]  aggregated per-line raw-segment statistics
* ``raw_seq_v``      [K, S]  raw per-segment velocities (standardized)
* ``raw_seq_valid``  [K, S]  True where a segment exists
* ``raw_seq_dx``     [K, S]  (raw_x - line_x) / line_gap, NaN where no obs
* ``raw_seq_t``      [K, S]  t_start normalized to [0, 1] within the section
* ``global_features``[G]     water level, max depth, width, original-value proportion
* ``target``         [K]     standardized surface velocity (the rebuild target)
* ``target_physical``[K]     unstandardized target, for metric reporting
* ``line_mask``      [K]     padding mask (batching only, carries no semantics)

The shard-level ``raw_aux`` / ``raw_source`` fields stay on the shard; the
model consumes one shared encoder regardless of source (quality.py already
resolves one raw table per measurement, STIV taking priority), so the batch
tensors above carry no source identity.

The S axis is fully dynamic - one section may carry 9 STIV video segments per
line while the next carries a single optical-flow estimate.  Nothing in this
module hard-codes S; it is always derived from the shard's own ``raw_valid``.
"""

from __future__ import annotations

import pickle
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np

STATE_ALGO = 0
STATE_INTERP = 1

#: number of aggregated per-line raw statistics (confidence is deliberately
#: excluded: the platform's confidence criterion is known to fail, e.g.
#: sections where 31.6% of segments exceed the section max while the
#: original-value proportion is rated the station's highest)
N_RAW_STATS = 11

#: global section features
N_GLOBAL = 4

#: per-observation optical-flow region channels packed in ``raw_aux``
#: (must match ``quality.RAW_AUX_KEYS``); kept on the shard but unused by the
#: model - the single shared raw encoder dispatches on no source id
N_RAW_AUX = 7

#: which raw table fed this section; recorded per sample for diagnostics and
#: stratification, but the model no longer dispatches on it
SOURCE_IDS = {"stiv": 0, "of": 1, "of_traj": 2}
N_SOURCES = 3


@dataclass
class NormStats:
    """Standardization statistics computed on the training split only."""

    v_mu: float
    v_sd: float
    raw_v_max: float
    global_mu: np.ndarray  # [N_GLOBAL]
    global_sd: np.ndarray  # [N_GLOBAL]

    def to_dict(self) -> dict[str, Any]:
        return {
            "v_mu": self.v_mu,
            "v_sd": self.v_sd,
            "raw_v_max": self.raw_v_max,
            "global_mu": self.global_mu.tolist(),
            "global_sd": self.global_sd.tolist(),
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "NormStats":
        return NormStats(
            v_mu=float(payload["v_mu"]),
            v_sd=float(payload["v_sd"]),
            raw_v_max=float(payload.get("raw_v_max", 6.0)),
            global_mu=np.asarray(payload["global_mu"], dtype=np.float64),
            global_sd=np.asarray(payload["global_sd"], dtype=np.float64),
        )


def load_shards(root: str | Path) -> list[dict[str, Any]]:
    """Load every cleaned section from a fetch output directory."""
    root = Path(root)
    sections: list[dict[str, Any]] = []
    for shard in sorted((root / "sections").glob("*.pkl")):
        with shard.open("rb") as handle:
            sections.extend(pickle.load(handle))
    return sections


def compute_bank_and_grad(
    x_norm: np.ndarray, d_norm: np.ndarray, eps: float = 1e-6
) -> tuple[np.ndarray, np.ndarray]:
    """Same morphology formulas as the V3 pretraining project."""
    bank = np.clip(2.0 * np.minimum(x_norm, 1.0 - x_norm), 0.0, 1.0)
    k = len(x_norm)
    grad = np.zeros(k, dtype=np.float64)
    if k >= 2:
        grad[0] = abs(d_norm[1] - d_norm[0]) / (abs(x_norm[1] - x_norm[0]) + eps)
        grad[-1] = abs(d_norm[-1] - d_norm[-2]) / (abs(x_norm[-1] - x_norm[-2]) + eps)
    if k >= 3:
        dx = np.abs(x_norm[2:] - x_norm[:-2]) + eps
        grad[1:-1] = np.abs(d_norm[2:] - d_norm[:-2]) / dx
    grad_max = float(grad.max())
    grad_norm = grad / (grad_max + eps) if grad_max > 0 else grad
    return bank.astype(np.float32), np.clip(grad_norm, 0.0, 1.0).astype(np.float32)


def compute_norm_stats(sections: Sequence[dict[str, Any]]) -> NormStats:
    """Training-split standardization for velocity and global features."""
    targets = np.concatenate([np.asarray(s["v_surface"], dtype=np.float64) for s in sections])
    raw_vals = []
    for section in sections:
        valid = np.asarray(section["raw_valid"], dtype=bool)
        raw_vals.append(np.asarray(section["raw_v"], dtype=np.float64)[valid])
    raw = np.concatenate(raw_vals) if raw_vals else np.asarray([0.0])
    globals_ = np.stack([_global_features(s) for s in sections]).astype(np.float64)
    return NormStats(
        v_mu=float(targets.mean()),
        v_sd=float(targets.std()) or 1.0,
        raw_v_max=float(max(np.percentile(np.abs(raw), 99.5), 1.0)),
        global_mu=globals_.mean(axis=0),
        global_sd=globals_.std(axis=0) + 1e-6,
    )


def _global_features(section: dict[str, Any]) -> np.ndarray:
    return np.asarray([
        section.get("water_level", np.nan),
        section.get("max_depth", np.nan),
        section.get("water_width", np.nan),
        section.get("original_value_prop", np.nan),
    ], dtype=np.float32)


def _nan_to_num(value: float, default: float = 0.0) -> float:
    return default if not np.isfinite(value) else float(value)


def _line_raw_stats(
    raw_v: np.ndarray,      # [S]
    raw_angle: np.ndarray,  # [S]
    valid: np.ndarray,      # [S]
    s_total: int,
) -> np.ndarray:
    """Aggregate one line's raw segments into a fixed-size feature vector.

    Confidence is intentionally not part of the feature set (unreliable
    criterion); robust statistics carry the outlier-resistance burden.
    """
    stats = np.zeros(N_RAW_STATS, dtype=np.float32)
    if not valid.any():
        return stats
    v = raw_v[valid].astype(np.float64)
    a = raw_angle[valid].astype(np.float64)
    stats[0] = valid.sum() / max(s_total, 1)          # coverage
    stats[1] = v.mean()
    stats[2] = v.std()
    stats[3] = v.min()
    stats[4] = v.max()
    stats[5] = np.median(v)
    stats[6] = np.percentile(v, 25)
    stats[7] = np.percentile(v, 75)
    # the optical-flow sheets carry no 流向夹角 column, so angle statistics are
    # taken over the finite entries only; an all-NaN angle block stays zero
    rad = np.deg2rad(a)
    rad = rad[np.isfinite(rad)]
    if len(rad):
        stats[8] = np.cos(rad).mean()
        stats[9] = np.sin(rad).mean()
        stats[10] = np.abs(np.sin(rad)).mean()        # perpendicularity indicator
    return stats


def build_sample(
    section: dict[str, Any],
    norm: NormStats,
) -> dict[str, np.ndarray]:
    """Convert one cleaned section dict into model tensors."""
    x = np.asarray(section["x"], dtype=np.float64)
    depth = np.asarray(section["depth"], dtype=np.float64)
    k = len(x)
    width = float(x[-1] - x[0]) if k >= 2 else 1.0
    h_max = float(depth.max()) if k else 1.0
    x_norm = (x - x[0]) / (width if width > 0 else 1.0)
    d_norm = depth / (h_max if h_max > 0 else 1.0)
    bank, grad = compute_bank_and_grad(x_norm.astype(np.float32), d_norm.astype(np.float32))
    morphology = np.column_stack([x_norm, d_norm, bank, grad]).astype(np.float32)

    raw_v = np.asarray(section["raw_v"], dtype=np.float64)
    raw_angle = np.asarray(section["raw_angle"], dtype=np.float64)
    valid = np.asarray(section["raw_valid"], dtype=bool) & np.isfinite(raw_v)
    s_total = raw_v.shape[1] if raw_v.ndim == 2 else 0

    stats = np.stack([
        _line_raw_stats(raw_v[i], raw_angle[i], valid[i], s_total)
        for i in range(k)
    ])

    # raw velocities standardized with the same scale as the target; clip the
    # extreme tail so a single 50 m/s glitch cannot dominate the embedding
    raw_seq_v = np.clip(raw_v / norm.v_sd, -norm.raw_v_max, norm.raw_v_max)
    raw_seq_v = np.where(np.isfinite(raw_seq_v), raw_seq_v, 0.0).astype(np.float32)

    # per-observation offset from the owning line, normalized by the local line
    # gap so the same relative displacement has the same scale on wide and
    # narrow sections; NaN where there is no observation
    if "raw_x" in section and section["raw_x"] is not None:
        raw_x = np.asarray(section["raw_x"], dtype=np.float64)
        gap = _local_line_gaps(x)
        dx = np.where(valid, (raw_x - x[:, None]) / gap[:, None], np.nan)
        raw_seq_dx = np.nan_to_num(dx, nan=0.0).astype(np.float32)
    else:
        raw_seq_dx = np.zeros((k, max(s_total, 1)), dtype=np.float32)

    # observation time normalized to [0, 1] within the measurement so the
    # model can tell an early from a late reading without a positional encoding
    if "raw_t_start" in section and section["raw_t_start"] is not None:
        t0 = np.asarray(section["raw_t_start"], dtype=np.float64)
        finite_t = t0[np.isfinite(t0)]
        t_lo = float(finite_t.min()) if finite_t.size else 0.0
        t_hi = float(finite_t.max()) if finite_t.size else 1.0
        span = t_hi - t_lo if t_hi > t_lo else 1.0
        t_norm = np.where(valid, (t0 - t_lo) / span, 0.0)
        raw_seq_t = t_norm.astype(np.float32)
    else:
        raw_seq_t = np.zeros((k, max(s_total, 1)), dtype=np.float32)

    raw_seq_aux = (
        np.nan_to_num(np.asarray(section["raw_aux"], dtype=np.float64), nan=0.0)
        if "raw_aux" in section and section["raw_aux"] is not None
        else np.zeros((k, max(s_total, 1), N_RAW_AUX), dtype=np.float32)
    ).astype(np.float32)

    source_name = str(section.get("raw_source") or "")
    raw_source_id = SOURCE_IDS.get(source_name, N_SOURCES - 1)

    target_physical = np.asarray(section["v_surface"], dtype=np.float32)
    target = ((target_physical - norm.v_mu) / norm.v_sd).astype(np.float32)

    globals_ = (_global_features(section).astype(np.float64) - norm.global_mu) / norm.global_sd
    globals_ = np.where(np.isfinite(globals_), globals_, 0.0).astype(np.float32)

    return {
        "station": str(section.get("station", "")),
        "device": str(section.get("device", "")),
        "time": str(section.get("time", "")),
        "morphology": morphology,
        "raw_stats": stats,
        "raw_seq_v": raw_seq_v,
        "raw_seq_valid": valid.astype(np.float32),
        "raw_seq_dx": raw_seq_dx,
        "raw_seq_t": raw_seq_t,
        "raw_seq_aux": raw_seq_aux,
        "raw_source_id": np.int64(raw_source_id),
        "global_features": globals_,
        "target": target,
        "target_physical": target_physical,
        "line_mask": np.ones(k, dtype=np.float32),
    }


def _local_line_gaps(x: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Local line spacing used to normalize per-observation offsets."""
    k = len(x)
    if k < 2:
        return np.ones(k, dtype=np.float64)
    gaps = np.full(k, float(x[-1] - x[0]) / max(k - 1, 1), dtype=np.float64)
    inner = np.diff(x)
    gaps[1:-1] = np.minimum(inner[:-1], inner[1:])
    gaps[0] = inner[0]
    gaps[-1] = inner[-1]
    return np.maximum(gaps, eps)


def split_stations(
    sections: Sequence[dict[str, Any]],
    seed: int = 42,
    train_fraction: float = 0.7,
    val_fraction: float = 0.15,
    n_strata: int = 10,
) -> dict[str, list[str]]:
    """Station-level split stratified by station mean velocity.

    Plain random shuffling of 200+ stations can deal a whole velocity regime
    into one split (the test set of the first run held twice the fast-line
    share of train).  Sorting stations by mean target velocity, cutting them
    into quantile strata and splitting 70/15/15 *within* every stratum keeps
    each split exposed to slow, mid and fast stations alike, while stations
    still never cross splits.
    """
    by_station: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        by_station.setdefault(str(section["station"]), []).append(section)
    stats = []
    for station, secs in by_station.items():
        v = np.concatenate([np.asarray(s["v_surface"], dtype=np.float64) for s in secs])
        stats.append((station, float(v.mean())))
    stats.sort(key=lambda t: t[1])  # ascending station mean velocity
    n = len(stats)
    n_strata = max(1, min(n_strata, n))
    rng = random.Random(seed)
    assignment: dict[str, str] = {}
    for si in range(n_strata):
        lo, hi = si * n // n_strata, (si + 1) * n // n_strata
        stratum = [t[0] for t in stats[lo:hi]]
        rng.shuffle(stratum)
        n_train = max(1, int(round(len(stratum) * train_fraction)))
        n_val = max(1, int(round(len(stratum) * val_fraction))) if len(stratum) > 2 else 0
        for j, station in enumerate(stratum):
            if j < n_train:
                assignment[station] = "train"
            elif j < n_train + n_val:
                assignment[station] = "val"
            else:
                assignment[station] = "test"
    return {
        name: sorted(st for st, a in assignment.items() if a == name)
        for name in ("train", "val", "test")
    }


class SectionDataset:
    """List-backed dataset with station-level train/val/test splits."""

    def __init__(
        self,
        sections: Sequence[dict[str, Any]],
        norm: NormStats,
        *,
        seed: int = 42,
        split: str = "train",
        train_fraction: float = 0.7,
        val_fraction: float = 0.15,
    ) -> None:
        station_splits = split_stations(
            sections, seed=seed, train_fraction=train_fraction,
            val_fraction=val_fraction,
        )
        chosen = station_splits[split]
        self.stations = chosen
        by_station: dict[str, list[dict[str, Any]]] = {}
        for section in sections:
            by_station.setdefault(str(section["station"]), []).append(section)
        split_sections = [
            section for station in chosen for section in by_station[station]
        ]
        self.samples = [build_sample(section, norm) for section in split_sections]
        # eval-only metadata: per-line source, never fed to the model
        self.line_states = [
            np.where(np.asarray(section["is_algo"], dtype=bool),
                     STATE_ALGO, STATE_INTERP).astype(np.int64)
            for section in split_sections
        ]
        # eval-only metadata: which raw table this section's input came from
        self.sources = [str(section.get("raw_source") or "") for section in split_sections]
        self.source_ids = [int(s["raw_source_id"]) for s in self.samples]
        self.norm = norm

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict[str, np.ndarray]:
        return self.samples[index]


def collate_sections(batch: Sequence[dict[str, np.ndarray]]) -> dict[str, Any]:
    """Pad a list of variable-length sections to a dense batch."""
    import torch

    k_max = max(int(item["line_mask"].sum()) for item in batch)
    s_max = max(item["raw_seq_v"].shape[1] for item in batch)
    b = len(batch)

    morphology = torch.zeros(b, k_max, 4, dtype=torch.float32)
    raw_stats = torch.zeros(b, k_max, N_RAW_STATS, dtype=torch.float32)
    raw_seq_v = torch.zeros(b, k_max, s_max, dtype=torch.float32)
    raw_seq_valid = torch.zeros(b, k_max, s_max, dtype=torch.float32)
    raw_seq_dx = torch.zeros(b, k_max, s_max, dtype=torch.float32)
    raw_seq_t = torch.zeros(b, k_max, s_max, dtype=torch.float32)
    target = torch.zeros(b, k_max, dtype=torch.float32)
    target_physical = torch.zeros(b, k_max, dtype=torch.float32)
    line_mask = torch.zeros(b, k_max, dtype=torch.float32)
    global_features = torch.zeros(b, N_GLOBAL, dtype=torch.float32)

    for i, item in enumerate(batch):
        k = int(item["line_mask"].sum())
        s = item["raw_seq_v"].shape[1]
        morphology[i, :k] = torch.from_numpy(item["morphology"][:k])
        raw_stats[i, :k] = torch.from_numpy(item["raw_stats"][:k])
        raw_seq_v[i, :k, :s] = torch.from_numpy(item["raw_seq_v"][:k, :s])
        raw_seq_valid[i, :k, :s] = torch.from_numpy(item["raw_seq_valid"][:k, :s])
        raw_seq_dx[i, :k, :s] = torch.from_numpy(item["raw_seq_dx"][:k, :s])
        raw_seq_t[i, :k, :s] = torch.from_numpy(item["raw_seq_t"][:k, :s])
        target[i, :k] = torch.from_numpy(item["target"][:k])
        target_physical[i, :k] = torch.from_numpy(item["target_physical"][:k])
        line_mask[i, :k] = 1.0
        global_features[i] = torch.from_numpy(item["global_features"])

    return {
        "morphology": morphology,
        "raw_stats": raw_stats,
        "raw_seq_v": raw_seq_v,
        "raw_seq_valid": raw_seq_valid,
        "raw_seq_dx": raw_seq_dx,
        "raw_seq_t": raw_seq_t,
        "target": target,
        "target_physical": target_physical,
        "line_mask": line_mask,
        "global_features": global_features,
    }
