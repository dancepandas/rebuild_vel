"""Quantify two emergent behaviours of the rebuild models.

B1  高流速压制: lines with extreme raw observations (raw >= RAW_HI) — how far
    does each model compress the observation toward the plausible range?
    Reported as compression ratio (pred/raw) and absolute pull toward target.
B2  零标定流速恢复: lines whose manual target is ~zero (target <= 0.2) while
    raw observations are significant (raw >= RAW_LO) — does the model keep the
    flow signal the manual calibration zeroed out, and how much?

Also: per-line fusion weight of raw in pred on contradicted lines, and the
distribution of pred position between target and raw (0 = target, 1 = raw).

    python tools/behaviour_analysis.py --data data/vel --device cuda \
        --checkpoint runs/v1/attempt5_ep70gate/best.pt:物理版 \
        --checkpoint runs/v1_mse/best.pt:纯净版 \
        --output runs/v1/behaviour.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RAW_HI = 3.0   # m/s, "extreme raw observation"
RAW_LO = 0.5   # m/s, "significant raw observation on a ~zero-target line"
T_ZERO = 0.2   # m/s, "manual target ~ zero"


def collect(checkpoint: str, data: str, device: str):
    import torch
    from torch.utils.data import DataLoader

    from rebuild_vel.dataset import NormStats, SectionDataset, collate_sections, load_shards
    from rebuild_vel.model.rebuild import RebuildVelocityModel

    ckpt = torch.load(checkpoint, map_location=device, weights_only=False)
    cfg = ckpt["config"]
    norm = NormStats.from_dict(cfg["norm"])
    dataset = SectionDataset(load_shards(data), norm, split="test", seed=42)
    model = RebuildVelocityModel(
        d_model=cfg.get("d_model", 768), num_heads=cfg.get("num_heads", 12),
        num_layers=cfg.get("num_layers", 14), ffn_dim=cfg.get("ffn_dim", 2304),
        dropout=0.0, raw_hidden=cfg.get("raw_hidden", 64),
        pure_attention=cfg.get("pure_attention", False)).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    loader = DataLoader(dataset, batch_size=64, shuffle=False, collate_fn=collate_sections)
    preds = []
    with torch.no_grad():
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            preds.append(model.forward_batch(batch)["velocity_pred"].cpu().numpy())
    pred_chunks, offset = [], 0
    for pb in preds:
        for row, s in zip(pb, dataset.samples[offset:offset + len(pb)]):
            k = int(np.asarray(s["line_mask"]).sum())
            pred_chunks.append(row[:k])
        offset += len(pb)
    pred = np.concatenate(pred_chunks) * norm.v_sd + norm.v_mu

    raw_mean, valid_cnt, target = [], [], []
    for s in dataset.samples:
        k = int(np.asarray(s["line_mask"]).sum())
        raw = np.asarray(s["raw_seq_v"], dtype=np.float64)[:k] * norm.v_sd
        valid = np.asarray(s["raw_seq_valid"], dtype=bool)[:k]
        cnt = valid.sum(axis=1)
        raw_mean.append(np.where(cnt > 0, (raw * valid).sum(axis=1) / np.maximum(cnt, 1), np.nan))
        valid_cnt.append(cnt)
        target.append(np.asarray(s["target_physical"])[:k])
    return (pred, np.concatenate(target),
            np.concatenate(raw_mean), np.concatenate(valid_cnt))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/vel")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--checkpoint", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    results = {}
    for spec in args.checkpoint:
        path, _, tag = spec.partition(":")
        tag = tag or Path(path).parent.name
        pred, target, raw_mean, cnt = collect(path, args.data, args.device)
        has_raw = (cnt > 0) & np.isfinite(raw_mean)
        res = {}

        # ---- B1: extreme raw observations ----
        m1 = has_raw & (raw_mean >= RAW_HI)
        res["B1_高流速压制"] = {
            "n": int(m1.sum()),
            "raw_mean": float(np.nanmean(raw_mean[m1])),
            "pred_mean": float(pred[m1].mean()),
            "target_mean": float(target[m1].mean()),
            "compression_pred_over_raw": float(pred[m1].mean() / np.nanmean(raw_mean[m1])),
            "raw_above_3_share": float((raw_mean[m1] > 3).mean()),
        }

        # ---- B2: manual-zero sections with significant raw flow ----
        m2 = has_raw & (target <= T_ZERO) & (raw_mean >= RAW_LO)
        res["B2_零标定流速恢复"] = {
            "n": int(m2.sum()),
            "target_mean": float(target[m2].mean()),
            "raw_mean": float(np.nanmean(raw_mean[m2])),
            "pred_mean": float(pred[m2].mean()),
            "recovery_pred_over_raw": float(pred[m2].mean() / np.nanmean(raw_mean[m2])),
            "frac_pred_gt_target": float((pred[m2] > target[m2] + 0.05).mean()),
        }

        # ---- B3: fusion position on contradicted lines ----
        m3 = has_raw & (np.abs(raw_mean - target) > np.maximum(0.5, 0.5 * (raw_mean + target)))
        pos = (pred[m3] - target[m3]) / (raw_mean[m3] - target[m3])
        pos = pos[np.isfinite(pos)]
        res["B3_矛盾线融合位置"] = {
            "n": int(len(pos)),
            "position_median": float(np.median(pos)),
            "position_p25": float(np.quantile(pos, 0.25)),
            "position_p75": float(np.quantile(pos, 0.75)),
            "note": "0=完全随目标, 1=完全随原始观测",
        }
        results[tag] = res

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    tags = list(results)
    print(f"\n{'行为量化':<26}" + "".join(f"{t:>16}" for t in tags))
    for block in ("B1_高流速压制", "B2_零标定流速恢复", "B3_矛盾线融合位置"):
        keys = results[tags[0]][block].keys()
        for k in keys:
            vals = [results[t][block][k] for t in tags]
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
                print(f"  {block} / {k:<24}" + "".join(f"{v:>16.3f}" for v in vals))
            else:
                print(f"  {block} / {k:<24}" + "".join(f"{str(v):>16}" for v in vals))
    print("written", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
