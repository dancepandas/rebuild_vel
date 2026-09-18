"""Turn cleaned section shards into model-ready tensors.

Per measurement (one cross-section at one time) a sample carries:

* ``morphology``     [K, 4]  x_norm, d_norm, bank, grad (section-normalized)
* ``raw_stats``      [K, F]  aggregated per-line raw-segment statistics
* ``raw_seq_v``      [K, S]  raw per-segment velocities (standardized)
* ``raw_seq_valid``  [K, S]  True where a segment exists
* ``global_features``[G]     water level, max depth, width, original-value proportion
* ``target``         [K]     standardized surface velocity (the rebuild target)
* ``target_physical``[K]     unstandardized target, for metric reporting
* ``line_mask``      [K]     padding mask (batching only, carries no semantics)

Line source (algorithm vs interpolated) is deliberately NOT a model input:
it is an internal artifact of the processing chain and carries no information
for reconstruction - whatever raw observations exist are the input.
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
    rad = np.deg2rad(a)
    stats[8] = np.cos(rad).mean()
    stats[9] = np.sin(rad).mean()
    stats[10] = np.abs(np.sin(rad)).mean()            # perpendicularity indicator
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

    target_physical = np.asarray(section["v_surface"], dtype=np.float32)
    target = ((target_physical - norm.v_mu) / norm.v_sd).astype(np.float32)

    globals_ = (_global_features(section).astype(np.float64) - norm.global_mu) / norm.global_sd
    globals_ = np.where(np.isfinite(globals_), globals_, 0.0).astype(np.float32)

    return {
        "morphology": morphology,
        "raw_stats": stats,
        "raw_seq_v": raw_seq_v,
        "raw_seq_valid": valid.astype(np.float32),
        "global_features": globals_,
        "target": target,
        "target_physical": target_physical,
        "line_mask": np.ones(k, dtype=np.float32),
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
        by_station: dict[str, list[dict[str, Any]]] = {}
        for section in sections:
            by_station.setdefault(str(section["station"]), []).append(section)
        stations = sorted(by_station)
        rng = random.Random(seed)
        rng.shuffle(stations)
        n = len(stations)
        n_train = max(1, int(round(n * train_fraction)))
        n_val = max(1, int(round(n * val_fraction))) if n > 2 else 0
        if split == "train":
            chosen = stations[:n_train]
        elif split == "val":
            chosen = stations[n_train:n_train + n_val]
        elif split == "test":
            chosen = stations[n_train + n_val:]
        else:
            raise ValueError(f"unknown split: {split}")
        self.stations = chosen
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
        target[i, :k] = torch.from_numpy(item["target"][:k])
        target_physical[i, :k] = torch.from_numpy(item["target_physical"][:k])
        line_mask[i, :k] = 1.0
        global_features[i] = torch.from_numpy(item["global_features"])

    return {
        "morphology": morphology,
        "raw_stats": raw_stats,
        "raw_seq_v": raw_seq_v,
        "raw_seq_valid": raw_seq_valid,
        "target": target,
        "target_physical": target_physical,
        "line_mask": line_mask,
        "global_features": global_features,
    }
