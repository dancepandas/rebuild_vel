"""Deep comparison of two rebuild checkpoints on the station-level test set.

For each checkpoint: overall + per-velocity-bin metrics, behaviour on zero /
low / high targets, disagreement (red-flag) rates, algo vs interp split, and
per-source breakdown. Writes a json + prints a side-by-side table.

    python tools/compare_models.py --data data/vel --device cuda \
        --checkpoint runs/v1/attempt5_ep70gate/best.pt:物理版 \
        --checkpoint runs/v1_mse/best.pt:纯净版 \
        --output runs/v1/comparison.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BINS = [0.0, 0.2, 0.5, 1.0, 2.0, 3.0, 100.0]
BIN_NAMES = ["[0,0.2)", "[0.2,0.5)", "[0.5,1)", "[1,2)", "[2,3)", "[3+)"]


def rmse(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


def mae(a, b):
    return float(np.mean(np.abs(a - b)))


def nse(a, b):
    denom = float(np.sum((b - b.mean()) ** 2))
    return 1.0 - float(np.sum((a - b) ** 2)) / denom if denom > 0 else float("nan")


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
    rows = []
    off = 0
    global_idx = 0
    for pred in preds:
        for row, sample in zip(pred, dataset.samples[off:off + len(pred)]):
            mask = sample["line_mask"].astype(bool)
            k = int(mask.sum())
            p = row[:len(mask)][:k] * norm.v_sd + norm.v_mu
            t = np.asarray(sample["target_physical"])[:k]
            line_state = np.asarray(dataset.line_states[global_idx])[:k]
            algo = line_state == 0  # STATE_ALGO
            stiv_line = np.full(k, int(sample.get("raw_source_id", 0)) == 0, bool)
            rows.append((p, t, algo, stiv_line))
            global_idx += 1
        off += len(pred)
    return rows


def summarize(rows, tag):
    pred = np.concatenate([r[0] for r in rows])
    true = np.concatenate([r[1] for r in rows])
    algo = np.concatenate([r[2] for r in rows])
    stiv = np.concatenate([r[3] for r in rows])
    out = {
        "n_lines": int(len(true)),
        "overall": {"rmse": rmse(pred, true), "mae": mae(pred, true), "nse": nse(pred, true),
                    "bias": float(np.mean(pred - true))},
        "algo": {"rmse": rmse(pred[algo], true[algo]), "nse": nse(pred[algo], true[algo]),
                 "n": int(algo.sum())},
        "interp": {"rmse": rmse(pred[~algo], true[~algo]), "nse": nse(pred[~algo], true[~algo]),
                   "n": int((~algo).sum())},
        "stiv": {"rmse": rmse(pred[stiv], true[stiv]), "n": int(stiv.sum())},
        "of_only": {"rmse": rmse(pred[~stiv], true[~stiv]), "n": int((~stiv).sum())},
        "bins": {}, "zero_lines": {}, "high_lines": {}, "disagreement": {},
    }
    for i, name in enumerate(BIN_NAMES):
        m = (true >= BINS[i]) & (true < BINS[i + 1])
        if m.any():
            out["bins"][name] = {
                "rmse": rmse(pred[m], true[m]), "mae": mae(pred[m], true[m]),
                "bias": float(np.mean(pred[m] - true[m])), "n": int(m.sum()),
            }
    z = true == 0
    out["zero_lines"] = {
        "n": int(z.sum()), "mean_pred": float(pred[z].mean()),
        "rmse": rmse(pred[z], true[z]),
        "frac_pred_gt_0p1": float((pred[z] > 0.1).mean()),
    }
    h = true >= 2.0
    out["high_lines"] = {
        "n": int(h.sum()), "mean_pred": float(pred[h].mean()), "mean_true": float(true[h].mean()),
        "bias": float(np.mean(pred[h] - true[h])), "rmse": rmse(pred[h], true[h]),
        "frac_under_0p5": float((pred[h] < true[h] - 0.5).mean()),
    }
    for thr in (0.3, 0.5, 1.0):
        d = np.abs(pred - true) > thr
        out["disagreement"][f"gt_{thr}"] = {"frac": float(d.mean()), "n": int(d.sum())}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/vel")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--checkpoint", action="append", required=True,
                    help="path[:label], repeatable")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    results = {}
    for spec in args.checkpoint:
        path, _, label = spec.partition(":")
        label = label or Path(path).parent.name
        print(f"[compare] collecting {label}: {path}", flush=True)
        rows = collect(path, args.data, args.device)
        results[label] = summarize(rows, label)
        print(f"[compare] {label}: rmse {results[label]['overall']['rmse']:.4f}", flush=True)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    labels = list(results)
    a, b = results[labels[0]], results[labels[1]]
    print(f"\n{'指标':<28}{labels[0]:>16}{labels[1]:>16}")
    def line(name, va, vb, fmt="{:.4f}"):
        print(f"{name:<28}{fmt.format(va):>16}{fmt.format(vb):>16}")
    line("总体 RMSE", a["overall"]["rmse"], b["overall"]["rmse"])
    line("总体 MAE", a["overall"]["mae"], b["overall"]["mae"])
    line("总体 NSE", a["overall"]["nse"], b["overall"]["nse"])
    line("总体 bias", a["overall"]["bias"], b["overall"]["bias"])
    for name in BIN_NAMES:
        ba, bb = a["bins"].get(name), b["bins"].get(name)
        if ba and bb:
            line(f"  分段 {name} RMSE", ba["rmse"], bb["rmse"])
            line(f"  分段 {name} bias", ba["bias"], bb["bias"])
    line("零速线平均预测", a["zero_lines"]["mean_pred"], b["zero_lines"]["mean_pred"])
    line("零速线 RMSE", a["zero_lines"]["rmse"], b["zero_lines"]["rmse"])
    line("零速线 pred>0.1 占比", a["zero_lines"]["frac_pred_gt_0p1"], b["zero_lines"]["frac_pred_gt_0p1"])
    line("高速线(≥2) bias", a["high_lines"]["bias"], b["high_lines"]["bias"])
    line("高速线严重低估占比", a["high_lines"]["frac_under_0p5"], b["high_lines"]["frac_under_0p5"])
    line("分歧>0.5 占比", a["disagreement"]["gt_0.5"]["frac"], b["disagreement"]["gt_0.5"]["frac"])
    line("算法线 RMSE", a["algo"]["rmse"], b["algo"]["rmse"])
    line("插值线 RMSE", a["interp"]["rmse"], b["interp"]["rmse"])
    line("光流-only RMSE", a["of_only"]["rmse"], b["of_only"]["rmse"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
