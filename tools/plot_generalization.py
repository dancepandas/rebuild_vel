"""Plots for the rebuild-vel generalization report.

Standalone: reads the generalization json + training history and the
checkpoint (one inference pass for the pred/target scatter). Writes PNGs to
the run's figs/ directory. Re-runnable for any checkpoint/report pair:

    python tools/plot_generalization.py --checkpoint runs/v1/best.pt \
        --report runs/v1/gen_midtraining_ep2.json --data data/vel
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--history", default="runs/v1/history.json")
    ap.add_argument("--data", default="data/vel")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-scatter", type=int, default=120000,
                    help="subsample cap for the scatter plot")
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    outdir = Path(args.outdir) if args.outdir else Path(args.checkpoint).parent / "figs"
    outdir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    # -- 1. training curves --------------------------------------------------
    hist_path = Path(args.history)
    if hist_path.is_file():
        h = json.loads(hist_path.read_text(encoding="utf-8"))
        ep = [r["epoch"] for r in h]
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        axes[0].plot(ep, [r["train_loss"] for r in h], label="train_loss")
        axes[0].plot(ep, [r["val_composite_norm"] for r in h], label="val_composite")
        axes[0].set_xlabel("epoch"); axes[0].set_yscale("log"); axes[0].legend()
        axes[0].set_title("损失曲线")
        if any("val_rmse_physical" in r for r in h):
            vr = [(r["epoch"], r["val_rmse_physical"]) for r in h if "val_rmse_physical" in r]
            axes[1].plot(*zip(*vr), color="tab:red", label="val RMSE (m/s)")
            axes[1].set_xlabel("epoch"); axes[1].legend(); axes[1].set_title("验证集 RMSE")
        fig.tight_layout()
        p = outdir / "training_curves.png"; fig.savefig(p, dpi=150); plt.close(fig)
        paths.append(p)

    # -- 2/3. per-station RMSE & NSE, sorted ---------------------------------
    st = report["by_station"]
    names = sorted(st, key=lambda k: st[k]["rmse"])
    rmse = [st[k]["rmse"] for k in names]
    nse = [st[k]["nse"] for k in names]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    axes[0].bar(range(len(names)), rmse, color="tab:blue")
    axes[0].axhline(float(np.median(rmse)), color="k", ls="--", lw=1,
                    label=f"中位 {np.median(rmse):.3f}")
    axes[0].set_xticks(range(len(names))); axes[0].set_xticklabels(names, rotation=90, fontsize=7)
    axes[0].set_ylabel("RMSE (m/s)"); axes[0].legend(); axes[0].set_title("跨站 RMSE（站级划分测试集）")
    order = sorted(range(len(names)), key=lambda i: -nse[i])
    axes[1].bar(range(len(names)), [nse[i] for i in order], color="tab:green")
    axes[1].axhline(float(np.median(nse)), color="k", ls="--", lw=1,
                    label=f"中位 {np.median(nse):.3f}")
    axes[1].set_xticks(range(len(names)))
    axes[1].set_xticklabels([names[i] for i in order], rotation=90, fontsize=7)
    axes[1].set_ylabel("NSE"); axes[1].legend(); axes[1].set_title("跨站 NSE")
    fig.tight_layout()
    p = outdir / "by_station.png"; fig.savefig(p, dpi=150); plt.close(fig)
    paths.append(p)

    # -- 4. source comparison -------------------------------------------------
    src = report["by_source"]
    labels = list(src)
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    axes[0].bar(labels, [src[k]["rmse"] for k in labels], color=["tab:blue", "tab:orange"][:len(labels)])
    axes[0].set_title("分源 RMSE (m/s)")
    axes[1].bar(labels, [src[k]["nse"] for k in labels], color=["tab:blue", "tab:orange"][:len(labels)])
    axes[1].set_title("分源 NSE")
    for ax in axes:
        for i, k in enumerate(labels):
            ax.text(i, ax.patches[i].get_height(), f"n={int(src[k]['count']):,}",
                    ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    p = outdir / "by_source.png"; fig.savefig(p, dpi=150); plt.close(fig)
    paths.append(p)

    # -- 5. pred vs target scatter (one inference pass) -----------------------
    try:
        import torch
        from rebuild_vel.dataset import NormStats, SectionDataset, collate_sections, load_shards
        from rebuild_vel.model.rebuild import RebuildVelocityModel
        from torch.utils.data import DataLoader

        ckpt = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
        cfg = ckpt["config"]
        norm = NormStats.from_dict(cfg["norm"])
        dataset = SectionDataset(load_shards(args.data), norm, split="test", seed=42)
        model = RebuildVelocityModel(
            d_model=cfg.get("d_model", 768), num_heads=cfg.get("num_heads", 12),
            num_layers=cfg.get("num_layers", 14), ffn_dim=cfg.get("ffn_dim", 2304),
            dropout=0.0, raw_hidden=cfg.get("raw_hidden", 64),
            pure_attention=cfg.get("pure_attention", False)).to(args.device)
        model.load_state_dict(ckpt["model"]); model.eval()
        loader = DataLoader(dataset, batch_size=64, shuffle=False, collate_fn=collate_sections)
        preds: list[np.ndarray] = []
        with torch.no_grad():
            for batch in loader:
                batch = {k: v.to(args.device) for k, v in batch.items()}
                preds.append(model.forward_batch(batch)["velocity_pred"].cpu().numpy())
        xs, ys, srcs = [], [], []
        off = 0
        for pred in preds:
            for row, sample in zip(pred, dataset.samples[off:off + len(pred)]):
                mask = sample["line_mask"].astype(bool)
                xs.append(row[:len(mask)][mask])
                ys.append(np.asarray(sample["target_physical"])[mask])
                srcs.extend(["stiv" if int(sample.get("raw_source_id", 0)) == 0 else "of"] * int(mask.sum()))
            off += len(pred)
        x = norm.physical_target(np.concatenate(xs))
        y = np.concatenate(ys)
        src_arr = np.array(srcs)
        if len(x) > args.max_scatter:
            idx = np.random.default_rng(0).choice(len(x), args.max_scatter, replace=False)
            x, y, src_arr = x[idx], y[idx], src_arr[idx]
        fig, ax = plt.subplots(figsize=(6.5, 6.5))
        for key, color, label in (("stiv", "tab:blue", "STIV"), ("of", "tab:orange", "光流-only")):
            m = src_arr == key
            if m.any():
                ax.scatter(y[m], x[m], s=2, alpha=0.15, color=color, label=label)
        lim = [0, max(float(y.max()), float(x.max())) * 1.02]
        ax.plot(lim, lim, "k--", lw=1, label="y = x")
        ax.set_xlim(lim); ax.set_ylim(lim)
        ax.set_xlabel("真值表面流速 (m/s)"); ax.set_ylabel("预测表面流速 (m/s)")
        ax.set_title(f"预测 vs 真值（站级测试集, n={len(x):,}）")
        ax.legend(markerscale=8)
        fig.tight_layout()
        p = outdir / "pred_vs_target.png"; fig.savefig(p, dpi=150); plt.close(fig)
        paths.append(p)
    except Exception as exc:  # noqa: BLE001 - plotting must not break training
        print(f"[plot] scatter skipped: {type(exc).__name__}: {exc}")

    for p in paths:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
