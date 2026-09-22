"""Figures for the target-transform report.

Data sources, deliberately few and explicit:
  runs/v1/analysis_3way/comparison_allbest.json   per-bin/overall stats for the
                                                  four checkpoints (phys, z,
                                                  YJep61, YJep100)
  runs/v1/analysis_3way/fingerprint_z_yj61.json   the z -> YJ per-bin deltas
  runs/v1_mse_bc/best_by_rmse.pt                  only for lambda / v_mu / v_sd

Three figures, each answering one question:
  fig_weights          what the transform was *supposed* to do, versus what the
                       per-bin over-prediction change actually did
  fig_three_arm_bins   where each of the three models is strongest by velocity
  fig_jensen           the section-level shortfall a transform-space fit implies
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "axes.unicode_minus": False,
    "savefig.dpi": 200, "savefig.bbox": "tight", "savefig.facecolor": "white",
    "axes.grid": True, "grid.alpha": 0.3, "figure.facecolor": "white",
})

NAMES = ["[0,0.2)", "[0.2,0.5)", "[0.5,1)", "[1,2)", "[2,3)", "[3+)"]
ARMS = [("phys", "物理版", "#C00000"),
        ("z", "纯净 z-score", "#1F4E79"),
        ("YJep61", "纯净 Yeo-Johnson", "#2E8B57")]


def weight_curve(norm, v: np.ndarray) -> np.ndarray:
    if norm.target_lambda is None:
        return np.ones_like(v)
    x = (np.asarray(v, float) - norm.v_mu) / norm.v_sd
    lam = norm.target_lambda
    jac = np.where(x < 0, np.power(np.maximum(1 - x, 1e-12), 1 - lam),
                   np.power(np.maximum(x + 1, 1e-12), lam - 1))
    return jac ** 2


def fig_weights(cmp_, fp, norm, out: Path) -> None:
    fig, ax = plt.subplots(1, 3, figsize=(15.5, 4.5))

    v = np.linspace(0.001, 4.5, 600)
    w = weight_curve(norm, v)
    ax[0].plot(v, w, color="#2E8B57", lw=2.4)
    ax[0].axhline(1.0, ls=":", color="0.45")
    ax[0].axvline(norm.v_mu, ls="--", color="#C00000", lw=1.2)
    ax[0].annotate(f"w=1 拐点  v={norm.v_mu:.3f} m/s", (norm.v_mu, 1.0),
                   xytext=(norm.v_mu + 0.45, 1.55), fontsize=9, color="#C00000",
                   arrowprops=dict(arrowstyle="->", color="#C00000", lw=1))
    ax[0].plot([1e-3], [w[0]], marker="*", ms=15, color="#7030A0", zorder=5)
    ax[0].annotate(f"枯水线 v=0（占训练目标 31.0%）\nw={w[0]:.2f} ← 权重最大",
                   (1e-3, w[0]), xytext=(0.60, 3.05), fontsize=9, color="#7030A0",
                   arrowprops=dict(arrowstyle="->", color="#7030A0", lw=1))
    ax[0].set_yscale("log")
    ax[0].set_xlabel("目标流速 (m/s)")
    ax[0].set_ylabel("L2 权重   w(v) = (dy/dx)²")
    ax[0].set_title("(a) 变换给出的损失权重曲面", fontsize=11.5)

    f = fp["fingerprint"]
    bins = f["bins"]
    wb = f["weight"]
    do = np.array(f["delta_frac_over"]) * 100
    ax[1].scatter(wb, do, s=110, color="#1F4E79", zorder=3)
    for k, wi, di in zip(bins, wb, do):
        ax[1].annotate(k, (wi, di), fontsize=8.5, xytext=(5, 5),
                       textcoords="offset points")
    ax[1].axhline(0, ls=":", color="0.45")
    ax[1].set_xscale("log")
    ax[1].set_xlabel("该速度段的平均权重 w(v)   （对数轴）")
    ax[1].set_ylabel("过预测率变化 Δ (百分点)")
    ax[1].set_title(f"(b) 假设检验：权重越大应降得越多\n实测 r = {f['corr_weight_delta_frac_over']:+.3f}（预期为负 → 证伪）",
                    fontsize=11, color="#C00000")

    x = np.arange(len(bins))
    for i, (tag, lab, col) in enumerate(ARMS):
        vals = [cmp_[tag]["bins"][k]["bias"] for k in bins]
        ax[2].bar(x + (i - 1) * 0.27, vals, 0.27, label=lab, color=col, alpha=0.9)
    ax[2].axhline(0, color="0.25", lw=1)
    ax[2].set_xticks(x)
    ax[2].set_xticklabels(bins, fontsize=9)
    ax[2].set_xlabel("目标流速段 (m/s)")
    ax[2].set_ylabel("bias (m/s)")
    ax[2].set_title("(c) 三臂分速度段偏差", fontsize=11.5)
    ax[2].legend(fontsize=9.5)
    fig.tight_layout()
    fig.savefig(out / "fig_weights.png")
    plt.close(fig)


def fig_three_arm_bins(cmp_, out: Path) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(14, 4.6))
    x = np.arange(len(NAMES))
    for i, (tag, lab, col) in enumerate(ARMS):
        ax[0].bar(x + (i - 1) * 0.27, [cmp_[tag]["bins"][k]["rmse"] for k in NAMES],
                  0.27, label=lab, color=col, alpha=0.9)
    ax[0].set_xticks(x)
    ax[0].set_xticklabels(NAMES, fontsize=9.5)
    ax[0].set_xlabel("目标流速段 (m/s)")
    ax[0].set_ylabel("RMSE (m/s)")
    ax[0].set_title("(a) 分速度段 RMSE：三方各有优势区间", fontsize=11.5)
    ax[0].legend(fontsize=9.5)

    n = [cmp_["z"]["bins"][k]["n"] for k in NAMES]
    share = np.array(n) / sum(n) * 100
    ax[1].bar(x, share, 0.55, color="#8FAADC")
    for xi, s in zip(x, share):
        ax[1].text(xi, s + 1.5, f"{s:.1f}%", ha="center", fontsize=9.5)
    ax[1].set_xticks(x)
    ax[1].set_xticklabels(NAMES, fontsize=9.5)
    ax[1].set_xlabel("目标流速段 (m/s)")
    ax[1].set_ylabel("占测试集测速线比例 (%)")
    ax[1].set_ylim(0, max(share) * 1.25)
    ax[1].set_title("(b) 各速度段的样本占比", fontsize=11.5)
    fig.tight_layout()
    fig.savefig(out / "fig_three_arm_bins.png")
    plt.close(fig)


def fig_jensen(out: Path, cache: Path) -> None:
    from rebuild_vel.dataset import compute_norm_stats, load_shards
    from rebuild_vel.train import _select_split_sections

    sections = load_shards("data/vel")
    norm = compute_norm_stats(_select_split_sections(sections, "train", 42),
                              target_transform=True)
    te = _select_split_sections(sections, "test", 42)

    def inv_mean(v):
        return float(np.asarray(
            norm.physical_target(np.array([norm.norm_target(v).mean()]))).reshape(-1)[0])

    gaps, means, zeros = [], [], []
    for s in te:
        v = np.asarray(s["v_surface"], dtype=np.float64)
        if v.size < 5:
            continue
        a = float(v.mean())
        if a <= 1e-6:
            continue
        gaps.append((a - inv_mean(v)) / a)
        means.append(a)
        zeros.append(float((v == 0).mean()))
    gaps, means, zeros = np.array(gaps), np.array(means), np.array(zeros)
    cache.write_text(json.dumps({
        "n": int(len(gaps)), "median": float(np.median(gaps)),
        "mean": float(gaps.mean()), "p95": float(np.percentile(gaps, 95)),
        "corr_zero_share": float(np.corrcoef(zeros, gaps)[0, 1]),
        "by_velocity": {lab: float(np.median(gaps[(means >= lo) & (means < hi)]))
                        for lab, lo, hi in zip(
                            ["[0,0.2)", "[0.2,0.5)", "[0.5,1)", "[1,2)", "[2+)"],
                            [0, 0.2, 0.5, 1.0, 2.0], [0.2, 0.5, 1.0, 2.0, 99])},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    fig, ax = plt.subplots(1, 3, figsize=(15.5, 4.5))
    ax[0].hist(gaps * 100, bins=60, color="#2E8B57", alpha=0.85)
    ax[0].axvline(np.median(gaps) * 100, color="#C00000", ls="--", lw=1.8,
                  label=f"中位 {np.median(gaps):+.2%}")
    ax[0].axvline(0, color="0.3", lw=1)
    ax[0].set_xlabel("相对下移 (%)        (算术均值 − 变换空间均值) / 算术均值")
    ax[0].set_ylabel("断面数")
    ax[0].set_title(f"(a) 断面级下移分布（{len(gaps):,} 个测试断面）", fontsize=11.5)
    ax[0].legend(fontsize=9.5)

    labs = ["[0,0.2)", "[0.2,0.5)", "[0.5,1)", "[1,2)", "[2+)"]
    edges = [0, 0.2, 0.5, 1.0, 2.0, 99]
    med, cnt = [], []
    for lo, hi in zip(edges, edges[1:]):
        m = (means >= lo) & (means < hi)
        med.append(np.median(gaps[m]) * 100 if m.sum() else 0.0)
        cnt.append(int(m.sum()))
    ax[1].bar(np.arange(len(labs)), med, 0.55, color="#1F4E79", alpha=0.9)
    for xi, (mm, cc) in enumerate(zip(med, cnt)):
        ax[1].text(xi, mm + 0.35, f"{mm:.1f}%\nn={cc:,}", ha="center", fontsize=8.5)
    ax[1].set_xticks(np.arange(len(labs)))
    ax[1].set_xticklabels(labs, fontsize=9.5)
    ax[1].set_xlabel("断面均速段 (m/s)")
    ax[1].set_ylabel("相对下移中位数 (%)")
    ax[1].set_ylim(0, max(med) * 1.45)
    ax[1].set_title("(b) 中高流速断面的下移最大", fontsize=11.5)

    ax[2].scatter(zeros * 100, gaps * 100, s=6, alpha=0.15, color="#7030A0")
    ax[2].set_xlabel("断面内枯水线占比 (%)")
    ax[2].set_ylabel("相对下移 (%)")
    ax[2].set_title(f"(c) 分布越偏态，下移越大   (r = {np.corrcoef(zeros, gaps)[0, 1]:+.3f})",
                    fontsize=11.5)
    fig.tight_layout()
    fig.savefig(out / "fig_jensen.png")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--comparison", required=True)
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--checkpoint", default="runs/v1_mse_bc/best_by_rmse.pt")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    cmp_ = json.loads(Path(args.comparison).read_text(encoding="utf-8"))
    fp = json.loads(Path(args.fingerprint).read_text(encoding="utf-8"))

    import torch
    from rebuild_vel.dataset import NormStats
    ck = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    norm = NormStats.from_dict(ck["config"]["norm"])
    print(f"lambda={norm.target_lambda:+.6f} v_mu={norm.v_mu:.5f} v_sd={norm.v_sd:.5f}")

    fig_weights(cmp_, fp, norm, out)
    fig_three_arm_bins(cmp_, out)
    fig_jensen(out, out / "jensen_gap.json")

    from PIL import Image
    sizes = {}
    for p in sorted(out.glob("*.png")):
        with Image.open(p) as im:
            sizes[str(p).replace("\\", "/")] = list(im.size)
    (out / "sizes.json").write_text(json.dumps(sizes), encoding="utf-8")
    print(json.dumps(sizes, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
