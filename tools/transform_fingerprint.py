"""Does the Yeo-Johnson transform leave a measurable fingerprint in preds?

The transform is not a neutral reparameterisation: it rewrites the L2 loss with
a Jacobian weight w(v) = (dy/dx)^2, so an error at velocity v costs w(v) times
what it cost under the plain z-score target.  For the lambda fitted here
(-0.0519, essentially log-like) that is

    v = 0.00 m/s  w = 3.77      v = 1.00 m/s  w = 0.54
    v = 0.25 m/s  w = 2.60      v = 2.00 m/s  w = 0.14
    v = 0.50 m/s  w = 1.66      v = 3.00 m/s  w = 0.06   (62x between v=0 and v=3)

So the transform makes a falsifiable prediction: the YJ model should
over-predict less (and under-predict more) than the z-score model *exactly in
proportion to w(v)*.  This script tests that against the station-disjoint test
set.

Two deliberate choices guard against reading noise as signal:

* over/under-prediction **rates** are the primary indicator, not mean bias --
  a mean bias can sit near zero while large compensating errors cancel across
  velocity bins, which would look like "calibration" but isn't;
* the per-bin weight is averaged over the lines actually in that bin, so a bin
  holding mostly slow lines is not compared against a weight sampled elsewhere.

    python tools/transform_fingerprint.py --data data/vel --device cuda \
        --checkpoint runs/v1_mse/best.pt:z-score \
        --checkpoint runs/v1_mse_bc/best.pt:YJ \
        --output runs/v1/analysis_3way/fingerprint.json
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
OVER = 0.1   # m/s, "meaningfully over the target"
UNDER = 0.1  # m/s, "meaningfully under the target"


def weight_curve(norm, v: np.ndarray) -> np.ndarray:
    """Jacobian weight (dy/dx)^2 of the fitted Yeo-Johnson transform."""
    if norm.target_lambda is None:
        return np.ones_like(v)
    x = (np.asarray(v, dtype=np.float64) - norm.v_mu) / norm.v_sd
    lam = norm.target_lambda
    jac = np.where(x < 0,
                   np.power(np.maximum(1.0 - x, 1e-12), 1.0 - lam),
                   np.power(np.maximum(x + 1.0, 1e-12), lam - 1.0))
    return jac ** 2


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
    chunks, offset = [], 0
    for pb in preds:
        for row, s in zip(pb, dataset.samples[offset:offset + len(pb)]):
            k = int(np.asarray(s["line_mask"]).sum())
            chunks.append(row[:k])
        offset += len(pb)
    pred = norm.physical_target(np.concatenate(chunks))

    raw_mean, target = [], []
    for s in dataset.samples:
        k = int(np.asarray(s["line_mask"]).sum())
        raw = np.asarray(s["raw_seq_v"], dtype=np.float64)[:k] * norm.v_sd
        valid = np.asarray(s["raw_seq_valid"], dtype=bool)[:k]
        cnt = valid.sum(axis=1)
        raw_mean.append(
            np.where(cnt > 0, (raw * valid).sum(axis=1) / np.maximum(cnt, 1), np.nan))
        target.append(np.asarray(s["target_physical"])[:k])
    return {
        "pred": pred,
        "target": np.concatenate(target),
        "raw_mean": np.concatenate(raw_mean),
        "epoch": ckpt.get("epoch"),
        "norm": norm,
    }


def per_bin(res) -> dict:
    pred, target = res["pred"], res["target"]
    out = {}
    for i, name in enumerate(BIN_NAMES):
        m = (target >= BINS[i]) & (target < BINS[i + 1])
        if not m.any():
            continue
        d = pred[m] - target[m]
        out[name] = {
            "n": int(m.sum()),
            "v_mid": float(target[m].mean()),
            "bias": float(d.mean()),
            "rmse": float(np.sqrt((d ** 2).mean())),
            "frac_over": float((d > OVER).mean()),
            "frac_under": float((d < -UNDER).mean()),
            "weight": float(weight_curve(res["norm"], target[m]).mean()),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/vel")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--checkpoint", action="append", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--figure", default=None)
    args = ap.parse_args()

    labels, results = [], {}
    for spec in args.checkpoint:
        path, _, tag = spec.partition(":")
        tag = tag or Path(path).parent.name
        labels.append(tag)
        print(f"[fingerprint] collecting {tag}: {path}", flush=True)
        results[tag] = collect(path, args.data, args.device)
        print(f"[fingerprint] {tag}: epoch {results[tag]['epoch']}", flush=True)

    report: dict = {"models": {}}
    for tag in labels:
        res = results[tag]
        pred, target = res["pred"], res["target"]
        d = pred - target
        bins = per_bin(res)
        # a mean bias can be ~0 while large compensating errors cancel between
        # bins; the count-weighted mean |bin bias| cannot be fooled that way
        tot = sum(b["n"] for b in bins.values())
        report["models"][tag] = {
            "epoch": res["epoch"],
            "n_lines": int(len(target)),
            "bias": float(d.mean()),
            "rmse": float(np.sqrt((d ** 2).mean())),
            "weighted_abs_bin_bias": float(
                sum(abs(b["bias"]) * b["n"] for b in bins.values()) / tot),
            "frac_over": float((d > OVER).mean()),
            "frac_under": float((d < -UNDER).mean()),
            "bins": bins,
            "zero_lines": {
                "n": int((target == 0).sum()),
                "mean_pred": float(pred[target == 0].mean()),
                "p50_pred": float(np.median(pred[target == 0])),
                "p90_pred": float(np.quantile(pred[target == 0], 0.90)),
                "max_pred": float(pred[target == 0].max()),
                "frac_pred_gt_0p1": float((pred[target == 0] > 0.1).mean()),
                "frac_pred_gt_0p3": float((pred[target == 0] > 0.3).mean()),
            },
            "high_lines": {
                "n": int((target >= 2.0).sum()),
                "bias": float(d[target >= 2.0].mean()),
                "frac_under_0p5": float((d[target >= 2.0] < -0.5).mean()),
                "frac_over_0p5": float((d[target >= 2.0] > 0.5).mean()),
            },
        }

    # ---- the fingerprint test itself -------------------------------------
    if len(labels) >= 2:
        base, treat = labels[0], labels[-1]
        bb, tb = report["models"][base]["bins"], report["models"][treat]["bins"]
        shared = [k for k in BIN_NAMES if k in bb and k in tb]
        w = np.array([tb[k]["weight"] for k in shared])
        d_over = np.array([tb[k]["frac_over"] - bb[k]["frac_over"] for k in shared])
        d_bias = np.array([tb[k]["bias"] - bb[k]["bias"] for k in shared])
        report["fingerprint"] = {
            "base": base, "treated": treat,
            "bins": shared,
            "weight": w.tolist(),
            "delta_frac_over": d_over.tolist(),
            "delta_bias": d_bias.tolist(),
            # negative = the treated model over-predicts less where w is large
            "corr_weight_delta_frac_over": float(np.corrcoef(w, d_over)[0, 1])
            if len(w) > 2 else float("nan"),
            "corr_weight_delta_bias": float(np.corrcoef(w, d_bias)[0, 1])
            if len(w) > 2 else float("nan"),
        }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    # ---- console -----------------------------------------------------------
    for tag in labels:
        m = report["models"][tag]
        print(f"\n=== {tag} (ep{m['epoch']}) ===")
        print(f"  整体: RMSE {m['rmse']:.4f}  bias {m['bias']:+.4f}  "
              f"分段偏差绝对值加权均值 {m['weighted_abs_bin_bias']:.4f}")
        print(f"  过预测率 {m['frac_over']:.4%}   欠预测率 {m['frac_under']:.4%}")
        z = m["zero_lines"]
        print(f"  零速线 n={z['n']:,}: mean_pred {z['mean_pred']:.3f}  p90 {z['p90_pred']:.3f}  "
              f"max {z['max_pred']:.2f}  pred>0.1 {z['frac_pred_gt_0p1']:.2%}  "
              f"pred>0.3 {z['frac_pred_gt_0p3']:.2%}")
        h = m["high_lines"]
        print(f"  高速线(≥2) n={h['n']:,}: bias {h['bias']:+.4f}  "
              f"严重低估 {h['frac_under_0p5']:.2%}  严重高估 {h['frac_over_0p5']:.2%}")
    print(f"\n{'分段':<12}" + "".join(f"{t:>22}" for t in labels) + f"{'权重 w(v)':>12}")
    for k in BIN_NAMES:
        if not all(k in report["models"][t]["bins"] for t in labels):
            continue
        cells = "".join(
            f"{report['models'][t]['bins'][k]['bias']:>+10.4f}/"
            f"{report['models'][t]['bins'][k]['frac_over']:>8.2%}"
            for t in labels)
        print(f"{k:<12}{cells}{report['models'][labels[-1]]['bins'][k]['weight']:>12.3f}")
    print(f"{'':<12}" + "".join(f"{'bias / 过预测率':>22}" for _ in labels))

    if "fingerprint" in report:
        fp = report["fingerprint"]
        print(f"\n=== 指纹检验: {fp['treated']} 相对 {fp['base']} ===")
        print(f"  corr( w(v), Δ过预测率 ) = {fp['corr_weight_delta_frac_over']:+.3f}")
        print(f"  corr( w(v), Δbias     ) = {fp['corr_weight_delta_bias']:+.3f}")
        print("  预期为负: 权重越大的速度段, 变换模型过预测减少越多")
        print(f"  {'分段':<12}{'Δbias':>10}{'Δ过预测率':>12}{'w(v)':>10}")
        for k, dw, db in zip(fp["bins"], fp["weight"], fp["delta_bias"]):
            do = fp["delta_frac_over"][fp["bins"].index(k)]
            print(f"  {k:<12}{db:>+10.4f}{do:>+12.2%}{dw:>10.3f}")
    print(f"\n[fingerprint] written to {args.output}")

    if args.figure:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.3))
        mids = [report["models"][labels[-1]]["bins"][k]["v_mid"] for k in BIN_NAMES
                if k in report["models"][labels[-1]]["bins"]]
        for tag, style in zip(labels, ("-o", "--s", "-^")):
            b = report["models"][tag]["bins"]
            ks = [k for k in BIN_NAMES if k in b]
            axes[0].plot([b[k]["v_mid"] for k in ks], [b[k]["bias"] for k in ks],
                         style, label=tag)
            axes[1].plot([b[k]["v_mid"] for k in ks], [b[k]["frac_over"] for k in ks],
                         style, label=tag)
        wv = np.linspace(0.001, 4.0, 400)
        axes[2].plot(wv, weight_curve(results[labels[-1]]["norm"], wv), color="k")
        axes[2].axhline(1.0, ls=":", color="0.5")
        axes[2].set_yscale("log")
        axes[0].axhline(0, ls=":", color="0.5")
        axes[0].set_xlabel("目标流速 (m/s)"); axes[0].set_ylabel("bias (m/s)")
        axes[0].set_title("分速度段偏差")
        axes[1].axhline(0.1, ls=":", color="0.5")
        axes[1].set_xlabel("目标流速 (m/s)"); axes[1].set_ylabel("过预测率 P(pred>yt+0.1)")
        axes[1].set_title("分速度段过预测率")
        axes[2].set_xlabel("目标流速 (m/s)")
        axes[2].set_ylabel("L2 权重 w(v) = (dy/dx)²")
        axes[2].set_title("Yeo-Johnson 变换的损失权重曲面")
        for ax in axes[:2]:
            ax.legend(fontsize=9); ax.grid(alpha=0.3)
        axes[2].grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(args.figure, dpi=150)
        print(f"[fingerprint] figure written to {args.figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
