"""Publication-quality figures for the V1 report.

One inference pass over the station-disjoint test set feeds every figure:
density scatter, per-station metrics, source comparison, section profiles,
and training curves. Writes to --outdir (default runs/v1/report_figs).

    python tools/report_figs.py --checkpoint runs/v1/best.pt --data data/vel
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
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

# -- shared style ------------------------------------------------------------
C_TRUE = "#2878B5"
C_PRED = "#C82423"
C_RAW = "#59A14F"
C_DRY = "#E8E8E8"
C_ACCENT = "#F2A900"

mpl.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "axes.unicode_minus": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.6,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.labelsize": 11.5,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "legend.frameon": False,
    "figure.dpi": 110,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
    "savefig.facecolor": "white",
})


def load_predictions(args):
    import torch
    from torch.utils.data import DataLoader

    from rebuild_vel.dataset import NormStats, SectionDataset, collate_sections, load_shards
    from rebuild_vel.model.rebuild import RebuildVelocityModel

    ckpt = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
    cfg = ckpt["config"]
    norm = NormStats.from_dict(cfg["norm"])
    dataset = SectionDataset(load_shards(args.data), norm, split="test", seed=42)
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
    recs = []
    off = 0
    for pred in preds:
        for row, sample in zip(pred, dataset.samples[off:off + len(pred)]):
            mask = sample["line_mask"].astype(bool)
            k = int(mask.sum())
            if k < 1:
                continue
            p = row[:len(mask)][:k] * norm.v_sd + norm.v_mu
            t = np.asarray(sample["target_physical"])[:k]
            raw = np.asarray(sample["raw_seq_v"], dtype=np.float64)[:k] * norm.v_sd
            valid = np.asarray(sample["raw_seq_valid"], dtype=bool)[:k]
            rx, ry = np.nonzero(valid)
            recs.append(dict(
                station=sample.get("station", "?"), time=sample.get("time", "?"),
                pred=p, true=t, depth=np.abs(sample["morphology"][:k, 1]),
                rmse=float(np.sqrt(np.mean((p - t) ** 2))),
                zero=float((t == 0).mean()),
                of_only=int(sample.get("raw_source_id", 0)) != 0,
                raw_x=rx, raw_y=raw[rx, ry],
            ))
        off += len(pred)
    return recs, norm, cfg, ckpt


def fig_density(recs, out):
    y = np.concatenate([r["true"] for r in recs])
    x = np.concatenate([r["pred"] for r in recs])
    lim = 4.5
    m = (x <= lim) & (y <= lim)
    fig, ax = plt.subplots(figsize=(6.4, 6.0))
    hb = ax.hexbin(y[m], x[m], gridsize=70, mincnt=1, cmap="YlGnBu",
                   norm=LogNorm(), linewidths=0.1)
    cb = fig.colorbar(hb, ax=ax, pad=0.02)
    cb.set_label("样本数（对数色标）", fontsize=10)
    ax.plot([0, lim], [0, lim], color="0.15", lw=1.4, ls="--", label="y = x")
    band = np.linspace(0, lim, 50)
    ax.fill_between(band, band - 0.3, band + 0.3, color="0.7", alpha=0.25,
                    label="±0.3 m/s")
    rmse = float(np.sqrt(np.mean((x - y) ** 2)))
    nse = 1 - np.sum((x - y) ** 2) / max(np.sum((y - y.mean()) ** 2), 1e-9)
    ax.text(0.03, 0.97, f"RMSE = {rmse:.3f} m/s\nNSE = {nse:.3f}\nn = {len(y):,}",
            transform=ax.transAxes, va="top", fontsize=11,
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="0.6", alpha=0.9))
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_xlabel("目标表面流速 (m/s)")
    ax.set_ylabel("模型重建表面流速 (m/s)")
    ax.set_title("重建流速 vs 目标流速 — 站级测试集全量")
    ax.legend(loc="lower right")
    ax.set_aspect("equal")
    fig.savefig(out)
    plt.close(fig)


def fig_by_station(gen, out):
    st = gen["by_station"]
    # NSE is degenerate on near-constant series; rank by RMSE, show both
    names = sorted(st, key=lambda k: st[k]["rmse"])
    rmse = np.array([st[k]["rmse"] for k in names])
    nse = np.array([st[k]["nse"] for k in names])
    counts = np.array([st[k]["count"] for k in names])
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 7.2))
    y = np.arange(len(names))
    colors = [C_PRED if n > 0.8 else ("#9EC5E8" if n < 0.2 else C_TRUE) for n in rmse]
    axes[0].barh(y, rmse, color=colors, height=0.72)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels(
        [f"{k} ({c/1000:.0f}k)" if c >= 1000 else f"{k} ({int(c)})" for k, c in zip(names, counts)],
        fontsize=8)
    med = float(np.median(rmse))
    axes[0].axvline(med, color="0.15", ls="--", lw=1.2)
    axes[0].text(med, len(names) + 0.6, f"中位 {med:.3f}", fontsize=10, ha="center")
    for i, (n_, v_) in enumerate(zip(names, rmse)):
        if v_ > 0.5:
            axes[0].text(v_ + 0.01, i, f"{v_:.2f}", va="center", fontsize=8, color=C_PRED)
    axes[0].set_xlabel("RMSE (m/s)")
    axes[0].set_title("各测试站 RMSE（站级划分，训练全程未见）")
    axes[0].set_ylim(-0.8, len(names) + 1.2)
    order = np.argsort(nse)
    nse_sorted = nse[order]
    bars = axes[1].barh(np.arange(len(names)), np.clip(nse_sorted, -1, 1),
                        color=["#B0B0B0" if n < -1 else C_TRUE for n in nse_sorted],
                        height=0.72)
    axes[1].set_yticks(np.arange(len(names)))
    axes[1].set_yticklabels([names[i] for i in order], fontsize=8)
    med = float(np.median(nse))
    axes[1].axvline(med, color="0.15", ls="--", lw=1.2)
    axes[1].text(med, len(names) + 0.6, f"中位 {med:.3f}", fontsize=10, ha="center")
    for i, n_ in enumerate(nse_sorted):
        if n_ < -1:
            axes[1].text(-0.95, i, f"NSE={n_:.0f}†", va="center", fontsize=7.5,
                         color=C_PRED)
        elif n_ < 0:
            axes[1].text(0.02, i, f"{n_:.2f}", va="center", fontsize=7.5, color=C_PRED)
    axes[1].set_xlabel("NSE（近常数站截断于 −1，†=指标退化，见正文）")
    axes[1].set_title("各测试站 NSE")
    axes[1].set_xlim(-1.15, 1.05)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def fig_by_source(gen, out):
    src = gen["by_source"]
    labels = {"stiv": "STIV 测次", "optical_flow": "光流-only 测次"}
    keys = list(src)
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.8))
    metrics = [("rmse", "RMSE (m/s)"), ("mae", "MAE (m/s)"), ("nse", "NSE")]
    palette = ["#2878B5", "#F2A900"]
    for ax, (key, title) in zip(axes, metrics):
        vals = [src[k][key] for k in keys]
        bars = ax.bar([labels[k] for k in keys], vals, color=palette, width=0.55)
        for b, k in zip(bars, keys):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(),
                    f"{src[k][key]:.3f}", ha="center", va="bottom", fontsize=10.5,
                    fontweight="bold")
            ax.text(b.get_x() + b.get_width() / 2, -0.09,
                    f"n={int(src[k]['count']):,}", ha="center", va="top",
                    fontsize=8, color="0.35", transform=ax.transData)
        ax.set_title(title)
        ax.set_ylim(0, max(vals) * 1.22 if key != "nse" else 1.0)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def fig_sections(recs, out, n_panels=5):
    valid = [r for r in recs if r["true"].size >= 8]
    by_rmse = sorted(valid, key=lambda r: r["rmse"])
    picks = [("最好断面", by_rmse[0]), ("中位断面", by_rmse[len(by_rmse) // 2]),
             ("最差断面（观测-目标矛盾）", by_rmse[-1])]
    dry = sorted(valid, key=lambda r: -r["zero"])
    if all(dry[0] is not p[1] for p in picks):
        picks.append(("枯水断面（零速占比最高）", dry[0]))
    of = [r for r in valid if r["of_only"]]
    if of:
        picks.append(("光流-only 断面", sorted(of, key=lambda r: r["rmse"])[len(of) // 2]))
    picks = picks[:n_panels]

    fig, axes = plt.subplots(n_panels, 1, figsize=(9.6, 3.0 * n_panels),
                             squeeze=False)
    for ax, (label, r) in zip(axes.flat, picks):
        k = r["true"].size
        x = np.arange(k)
        dry = r["depth"] < 0.01
        if dry.any():
            ax.fill_between(x, 0, 1, where=dry, transform=ax.get_xaxis_transform(),
                            color=C_DRY, label="枯水线（水深<1cm）", zorder=0)
        ax.plot(x, r["true"], "-o", color=C_TRUE, lw=2.0, ms=3.5,
                label="目标流速", zorder=3)
        ax.plot(x, r["pred"], "--", color=C_PRED, lw=2.0, label="模型重建", zorder=4)
        if r["raw_x"].size:
            ax.scatter(r["raw_x"], r["raw_y"], s=9, color=C_RAW, alpha=0.55,
                       label="原始 30s 段观测", zorder=2)
        ax.set_xlim(-0.5, k - 0.5)
        ax.set_xlabel("测速线序号", fontsize=10)
        ax.set_ylabel("表面流速 (m/s)", fontsize=10)
        ax.set_title(f"{label} — 站 {r['station']}  {r['time'][:16]}    RMSE = {r['rmse']:.3f} m/s",
                     fontsize=11.5, loc="left")
        ax.legend(fontsize=9, ncol=4, loc="upper right")
    fig.tight_layout(h_pad=1.6)
    fig.savefig(out)
    plt.close(fig)


def fig_history(hist_path, out):
    if not Path(hist_path).is_file():
        return False
    h = json.loads(Path(hist_path).read_text(encoding="utf-8"))
    ep = [r["epoch"] for r in h]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.9))
    axes[0].plot(ep, [r["train_loss"] for r in h], "-o", ms=3, color=C_TRUE,
                 label="训练损失（MSE+物理）")
    axes[0].plot(ep, [r["val_composite_norm"] for r in h], "-o", ms=3,
                 color=C_PRED, label="验证复合损失")
    axes[0].set_xlabel("epoch"); axes[0].set_ylabel("损失（归一化）")
    axes[0].set_title("损失曲线"); axes[0].legend()
    vr = [(r["epoch"], r["val_rmse_physical"]) for r in h if "val_rmse_physical" in r]
    if vr:
        e, v = zip(*vr)
        axes[1].plot(e, v, "-o", ms=3, color=C_TRUE)
        b = min(v)
        be = e[v.index(b)]
        axes[1].scatter([be], [b], s=60, color=C_ACCENT, zorder=5)
        axes[1].annotate(f"best {b:.3f} (ep{be})", (be, b), textcoords="offset points",
                         xytext=(8, 8), fontsize=10, fontweight="bold")
        axes[1].set_xlabel("epoch"); axes[1].set_ylabel("验证 RMSE (m/s)")
        axes[1].set_title("验证集 RMSE")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--report", required=True, help="eval_generalization output json")
    ap.add_argument("--history", default="runs/v1/history.json")
    ap.add_argument("--data", default="data/vel")
    ap.add_argument("--outdir", default="runs/v1/report_figs")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--skip-inference", action="store_true")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    gen = json.loads(Path(args.report).read_text(encoding="utf-8"))

    fig_by_station(gen, outdir / "fig_by_station.png")
    fig_by_source(gen, outdir / "fig_by_source.png")
    fig_history(args.history, outdir / "fig_training_curves.png")
    if not args.skip_inference:
        recs, _norm, _cfg, _ckpt = load_predictions(args)
        fig_density(recs, outdir / "fig_density.png")
        fig_sections(recs, outdir / "fig_sections.png")
    for p in sorted(outdir.glob("*.png")):
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
