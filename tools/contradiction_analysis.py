"""Universal raw-vs-target contradiction analysis + model behaviour.

Questions answered:
1. How common are "raw observation contradicts target" lines? (both directions)
2. Is the contradiction concentrated in a few stations or universal?
3. When raw and target disagree, does the model follow raw or target?
4. What does the contradiction cost in RMSE (contradiction vs consistent lines)?

    python tools/contradiction_analysis.py --data data/vel --device cuda \
        --checkpoint runs/v1/attempt5_ep70gate/best.pt:物理版 \
        --checkpoint runs/v1_mse/best.pt:纯净MSE版 \
        --output runs/v1/contradiction.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def w_follow(pred, raw, target):
    """Least-squares weight of raw in pred, after removing the target component."""
    d_r = raw - target
    d_p = pred - target
    den = float(np.var(d_r))
    return float(np.cov(d_p, d_r)[0, 1] / den) if den > 0 else float("nan")


def line_table(dataset, norm):
    """Flatten samples to per-line arrays: raw mean, target, station, has_raw."""
    raw_mean, target, stations, has_raw = [], [], [], []
    for s in dataset.samples:
        m = np.asarray(s["line_mask"], bool)
        k = int(m.sum())
        raw = np.asarray(s["raw_seq_v"], dtype=np.float64)[:k] * norm.v_sd
        valid = np.asarray(s["raw_seq_valid"], dtype=bool)[:k]
        cnt = valid.sum(axis=1)
        rm = np.where(cnt > 0, (raw * valid).sum(axis=1) / np.maximum(cnt, 1), np.nan)
        raw_mean.append(rm)
        target.append(np.asarray(s["target_physical"])[:k])
        stations.extend([s.get("station", "?")] * k)
        has_raw.append(cnt > 0)
    return (np.concatenate(raw_mean), np.concatenate(target),
            np.array(stations), np.concatenate(has_raw))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/vel")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--checkpoint", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    import torch
    from torch.utils.data import DataLoader

    from rebuild_vel.dataset import NormStats, SectionDataset, collate_sections, load_shards
    from rebuild_vel.model.rebuild import RebuildVelocityModel

    out = {}
    shared = None
    for spec in args.checkpoint:
        path, _, tag = spec.partition(":")
        tag = tag or Path(path).parent.name
        ckpt = torch.load(path, map_location=args.device, weights_only=False)
        cfg = ckpt["config"]
        norm = NormStats.from_dict(cfg["norm"])
        dataset = SectionDataset(load_shards(args.data), norm, split="test", seed=42)
        raw_mean, target, stations, has_raw = line_table(dataset, norm)
        if shared is None:
            shared = (raw_mean, target, stations, has_raw)
        raw_mean, target, stations, has_raw = shared

        model = RebuildVelocityModel(
            d_model=cfg.get("d_model", 768), num_heads=cfg.get("num_heads", 12),
            num_layers=cfg.get("num_layers", 14), ffn_dim=cfg.get("ffn_dim", 2304),
            dropout=0.0, raw_hidden=cfg.get("raw_hidden", 64),
            pure_attention=cfg.get("pure_attention", False)).to(args.device)
        model.load_state_dict(ckpt["model"])
        model.eval()
        loader = DataLoader(dataset, batch_size=64, shuffle=False, collate_fn=collate_sections)
        preds = []
        with torch.no_grad():
            for batch in loader:
                batch = {k: v.to(args.device) for k, v in batch.items()}
                preds.append(model.forward_batch(batch)["velocity_pred"].cpu().numpy())
        pred_chunks = []
        offset = 0
        for pb in preds:
            for row, s in zip(pb, dataset.samples[offset:offset + len(pb)]):
                k = int(np.asarray(s["line_mask"]).sum())
                pred_chunks.append(row[:k])
            offset += len(pb)
        pred = np.concatenate(pred_chunks) * norm.v_sd + norm.v_mu

        obs = has_raw & np.isfinite(raw_mean)
        rm, tg, st, pd_ = raw_mean[obs], target[obs], stations[obs], pred[obs]
        r = float(np.corrcoef(rm, tg)[0, 1])
        up = (rm - tg) > np.maximum(0.5, 1.5 * tg)
        down = (tg - rm) > np.maximum(0.5, 1.5 * rm)
        consistent = ~up & ~down

        rate = {}
        for s_ in set(st):
            msk = st == s_
            if msk.sum() >= 50:
                rate[s_] = float(up[msk].mean())
        rates = np.array(sorted(rate.values()))

        entry = {
            "obs_line_share": float(obs.mean()),
            "raw_target_corr": r,
            "contradiction_up": {"n": int(up.sum()), "frac": float(up.mean()),
                                 "raw_median": float(np.median(rm[up])) if up.any() else None,
                                 "target_median": float(np.median(tg[up])) if up.any() else None},
            "contradiction_down": {"n": int(down.sum()), "frac": float(down.mean())},
            "consistent_lines": int(consistent.sum()),
            "station_contradiction_rate": {
                "median": float(np.median(rates)), "p90": float(np.quantile(rates, 0.9)),
                "max": float(rates.max()), "stations_gt_20pct": int((rates > 0.2).sum()),
                "n_stations": len(rates),
            },
            "model": {
                "pred_on_up_lines": float(pd_[up].mean()) if up.any() else None,
                "target_on_up_lines": float(tg[up].mean()) if up.any() else None,
                "raw_on_up_lines": float(rm[up].mean()) if up.any() else None,
                "follow_weight_all": w_follow(pd_, rm, tg),
                "follow_weight_up": w_follow(pd_[up], rm[up], tg[up]) if up.any() else None,
                "rmse_consistent": rmse(pd_[consistent], tg[consistent]),
                "rmse_contradiction": (rmse(pd_[up | down], tg[up | down])
                                       if (up | down).any() else None),
            },
        }
        out[tag] = entry
        m = entry["model"]
        print(f"[{tag}] r={r:.3f} 矛盾线 {entry['contradiction_up']['frac']:.1%}+"
              f"{entry['contradiction_down']['frac']:.1%} | "
              f"RMSE 一致 {m['rmse_consistent']:.3f} vs 矛盾 {m['rmse_contradiction']:.3f} | "
              f"追随权重 全体 {m['follow_weight_all']:.2f} / 上行矛盾 {m['follow_weight_up']:.2f} | "
              f"分站矛盾率中位 {entry['station_contradiction_rate']['median']:.1%}, "
              f">20%的站 {entry['station_contradiction_rate']['stations_gt_20pct']}/{len(rates)}",
              flush=True)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written", args.output)
    return 0


def rmse(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


if __name__ == "__main__":
    raise SystemExit(main())
