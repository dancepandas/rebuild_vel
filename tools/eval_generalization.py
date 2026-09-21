"""Cross-station / cross-device generalization report for a trained checkpoint.

The test split is station-disjoint by construction (SectionDataset splits by
station before assigning sections), so pooled test metrics already measure
cross-station generalization.  This script breaks those metrics down per
station and per device, and also by raw source (stiv vs optical-flow-only
measurements), because those are the axes on which the model could be
secretly relying on memorized device idiosyncrasies.

Usage:
    python tools/eval_generalization.py --data data/vel \
        --checkpoint runs/v1/best.pt --device cuda
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rebuild_vel.dataset import NormStats, SectionDataset, collate_sections, load_shards
from rebuild_vel.evaluate import _regression_metrics
from rebuild_vel.model.rebuild import RebuildVelocityModel

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Per-group generalization report")
    parser.add_argument("--data", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--split", default="test", choices=["val", "test"])
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None, help="json path for the full report")
    return parser.parse_args()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import torch
    from torch.utils.data import DataLoader

    checkpoint = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
    config = checkpoint["config"]
    norm = NormStats.from_dict(config["norm"])

    sections = load_shards(args.data)
    dataset = SectionDataset(sections, norm, split=args.split, seed=args.seed)
    if not len(dataset):
        raise SystemExit(f"empty {args.split} split")
    logger.info("evaluating %d sections on split=%s", len(dataset), args.split)

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

    loader = DataLoader(dataset, batch_size=64, shuffle=False, collate_fn=collate_sections)
    preds: list[np.ndarray] = []
    with torch.no_grad():
        for batch in loader:
            batch = {key: value.to(args.device) for key, value in batch.items()}
            output = model.forward_batch(batch)
            preds.append(output["velocity_pred"].cpu().numpy())

    # align per-line values with their group identity (per-sample slicing, so
    # per-batch K padding never needs to line up across batches)
    groups_station: list[str] = []
    groups_device: list[str] = []
    groups_source: list[str] = []
    pred_lines: list[np.ndarray] = []
    target_lines: list[np.ndarray] = []
    offset = 0
    for batch_pred in preds:
        for row, sample in zip(batch_pred, dataset.samples[offset:offset + len(batch_pred)]):
            mask = sample["line_mask"].astype(bool)
            row = row[: len(mask)]  # collate pads K to the batch max; real lines come first
            station = sample.get("station", "?")
            device = sample.get("device", "?")
            source = "stiv" if int(sample.get("raw_source_id", 0)) == 0 else "optical_flow"
            n = int(mask.sum())
            groups_station.extend([station] * n)
            groups_device.extend([f"{station}|{device}"] * n)
            groups_source.extend([source] * n)
            pred_lines.append(row[mask] * norm.v_sd + norm.v_mu)
            target_lines.append(np.asarray(sample["target_physical"])[mask])
        offset += len(batch_pred)
    pred = np.concatenate(pred_lines)
    target = np.concatenate(target_lines)

    def by_group(names: np.ndarray) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in sorted(set(names)):
            sel = names == name
            out[name] = _regression_metrics(pred[sel], target[sel])
        return out

    report: dict[str, Any] = {
        "checkpoint": str(args.checkpoint),
        "split": args.split,
        "n_sections": len(dataset),
        "n_lines": int(len(pred)),
        "overall": _regression_metrics(pred, target),
        "by_source": by_group(np.array(groups_source)),
        "by_station": by_group(np.array(groups_station)),
        "by_device": by_group(np.array(groups_device)),
    }
    for axis in ("by_station", "by_device"):
        rmses = [m["rmse"] for m in report[axis].values()]
        report[axis + "_summary"] = {
            "n_groups": len(rmses),
            "rmse_min": float(np.min(rmses)),
            "rmse_median": float(np.median(rmses)),
            "rmse_max": float(np.max(rmses)),
            "rmse_p90": float(np.quantile(rmses, 0.9)),
            "nse_median": float(np.median([m["nse"] for m in report[axis].values()])),
        }

    print(json.dumps({k: v for k, v in report.items() if k != "by_device"},
                     ensure_ascii=False, indent=2))
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logger.info("full report (incl. per-device) written to %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
