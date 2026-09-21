"""Evaluate a trained checkpoint against raw-aggregation baselines.

Baselines (per speed line, using only raw segment velocities - no confidence,
matching the model's input policy):
* ``raw_median``    - median of valid raw segment velocities
* ``raw_clip_mean`` - mean after clipping raw to the training 99.5 percentile

Metrics are reported in physical m/s, overall and split by line state
(algorithm-given vs interpolated).
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from .dataset import SectionDataset, STATE_ALGO, STATE_INTERP, collate_sections, compute_norm_stats, load_shards
from .model.rebuild import RebuildVelocityModel

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate reconstruction model")
    parser.add_argument("--data", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--split", default="test", choices=["val", "test"])
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", default=None, help="metrics json path")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args(argv)


def _regression_metrics(pred: np.ndarray, target: np.ndarray) -> dict[str, float]:
    diff = pred - target
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    mae = float(np.mean(np.abs(diff)))
    bias = float(np.mean(diff))
    denom = float(np.sum((target - target.mean()) ** 2))
    nse = 1.0 - float(np.sum(diff ** 2)) / denom if denom > 0 else float("nan")
    return {"rmse": rmse, "mae": mae, "bias": bias, "nse": nse, "count": float(len(target))}


def _baseline_predictions(sample: dict[str, np.ndarray], raw_v_max_sd: float, v_sd: float) -> dict[str, np.ndarray]:
    raw = np.asarray(sample["raw_seq_v"], dtype=np.float64) * v_sd  # back to physical
    valid = np.asarray(sample["raw_seq_valid"], dtype=bool) & np.isfinite(raw)
    k = raw.shape[0]
    median = np.zeros(k)
    clip_mean = np.zeros(k)
    cap = raw_v_max_sd * v_sd
    for i in range(k):
        v = raw[i][valid[i]]
        if len(v) == 0:
            continue
        median[i] = np.median(v)
        clip_mean[i] = np.clip(v, -cap, cap).mean()
    return {"raw_median": median, "raw_clip_mean": clip_mean}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import torch
    from torch.utils.data import DataLoader

    checkpoint = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
    config = checkpoint["config"]
    from .dataset import NormStats

    norm = NormStats.from_dict(config["norm"])
    sections = load_shards(args.data)
    dataset = SectionDataset(sections, norm, split=args.split, seed=args.seed)
    logger.info("evaluating %d sections (%d lines) on split=%s",
                len(dataset), sum(int(s["line_mask"].sum()) for s in dataset.samples),
                args.split)
    if not len(dataset):
        raise SystemExit("empty evaluation split")

    model = RebuildVelocityModel(
        d_model=config.get("d_model", 768),
        num_heads=config.get("num_heads", 12),
        num_layers=config.get("num_layers", 14),
        ffn_dim=config.get("ffn_dim", 2304),
        dropout=config.get("dropout", 0.0),
        raw_hidden=config.get("raw_hidden", 64),
        pure_attention=config.get("pure_attention", False),
    ).to(args.device)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    loader = DataLoader(dataset, batch_size=32, shuffle=False, collate_fn=collate_sections)
    batch_preds: list[np.ndarray] = []
    with torch.no_grad():
        for batch in loader:
            batch = {key: value.to(args.device) for key, value in batch.items()}
            output = model.forward_batch(batch)
            batch_preds.append(output["velocity_pred"].cpu().numpy())
    # slice per sample: batches pad K to the batch max, so the flat arrays
    # cannot be masked with one concatenated boolean vector
    pred_chunks: list[np.ndarray] = []
    target_chunks: list[np.ndarray] = []
    state_chunks: list[np.ndarray] = []
    offset = 0
    for pred in batch_preds:
        for row, sample, line_state in zip(
            pred, dataset.samples[offset:offset + len(pred)],
            dataset.line_states[offset:offset + len(pred)],
        ):
            mask = sample["line_mask"].astype(bool)
            k = int(mask.sum())
            pred_chunks.append(row[:len(mask)][:k] * norm.v_sd + norm.v_mu)
            target_chunks.append(np.asarray(sample["target_physical"])[:k])
            state_chunks.append(line_state[:k])
        offset += len(pred)
    pred = np.concatenate(pred_chunks)
    target = np.concatenate(target_chunks)
    state = np.concatenate(state_chunks)

    metrics: dict[str, Any] = {
        "model_overall": _regression_metrics(pred, target),
        "model_algo_lines": _regression_metrics(pred[state == STATE_ALGO], target[state == STATE_ALGO]),
        "model_interp_lines": _regression_metrics(pred[state == STATE_INTERP], target[state == STATE_INTERP]),
    }

    # baselines per section (line-aligned, raw values only - no confidence)
    base_preds: dict[str, list[np.ndarray]] = {"raw_median": [], "raw_clip_mean": []}
    base_targets: list[np.ndarray] = []
    base_states: list[np.ndarray] = []
    for sample, line_states in zip(dataset.samples, dataset.line_states):
        baselines = _baseline_predictions(sample, norm.raw_v_max, norm.v_sd)
        mask = sample["line_mask"].astype(bool)
        base_targets.append(np.asarray(sample["target_physical"])[mask])
        base_states.append(line_states[mask])
        for name, values in baselines.items():
            base_preds[name].append(values[mask])
    base_target = np.concatenate(base_targets)
    base_state = np.concatenate(base_states)
    for name, chunks in base_preds.items():
        values = np.concatenate(chunks)
        metrics[f"baseline_{name}_overall"] = _regression_metrics(values, base_target)
        metrics[f"baseline_{name}_algo"] = _regression_metrics(
            values[base_state == STATE_ALGO], base_target[base_state == STATE_ALGO])

    rmse_model = metrics["model_overall"]["rmse"]
    for name in base_preds:
        base_rmse = metrics[f"baseline_{name}_overall"]["rmse"]
        metrics[f"skill_vs_{name}"] = 1.0 - rmse_model / base_rmse if base_rmse > 0 else float("nan")

    text = json.dumps(metrics, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
