"""How far does a transform-space fit sit below a physical-space fit?

Two conditioning units give wildly different answers, and the difference is the
point:

* conditioning on a velocity BIN makes the gap look negligible (ratio 0.97-0.99).
  A bin is a narrow slice, so within it the target barely varies and the
  concavity of the transform has almost nothing to bite on.
* conditioning on a SECTION -- which is what the model actually sees, since it
  reads a whole cross-section at once -- gives a median relative shortfall of
  ~9%, with a p95 above 30%.

The dataset is 31% exact-zero lines, so a section's target vector is strongly
right-skewed.  Minimising squared error after a concave (log-like) transform is
minimising relative error, whose minimiser sits well below the arithmetic mean.
So a model trained this way is *structurally* biased low, by construction, not
by any failure of fitting -- and the deficit should grow with the section's
velocity spread, which is why it shows up hardest at high flow.

    python tools/jensen_gap.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rebuild_vel.dataset import compute_norm_stats, load_shards  # noqa: E402
from rebuild_vel.train import _select_split_sections  # noqa: E402


def main() -> int:
    sections = load_shards("data/vel")
    tr = _select_split_sections(sections, "train", 42)
    te = _select_split_sections(sections, "test", 42)
    norm = compute_norm_stats(tr, target_transform=True)

    def inv_mean(v: np.ndarray) -> float:
        return float(np.asarray(
            norm.physical_target(np.array([norm.norm_target(v).mean()]))).reshape(-1)[0])

    gaps, means, spreads, zeros = [], [], [], []
    for s in te:
        v = np.asarray(s["v_surface"], dtype=np.float64)
        if v.size < 5:
            continue
        a = float(v.mean())
        if a <= 1e-6:
            continue
        gaps.append((a - inv_mean(v)) / a)
        means.append(a)
        spreads.append(float(v.std()))
        zeros.append(float((v == 0).mean()))
    gaps, means = np.array(gaps), np.array(means)
    spreads, zeros = np.array(spreads), np.array(zeros)

    print(f"测试集断面级条件集: n={len(gaps):,} (每断面 >=5 条线)")
    print("\n相对下移 (算术均值 - 变换空间均值) / 算术均值:")
    for q in (5, 25, 50, 75, 95, 99):
        print(f"  p{q:>2} = {np.percentile(gaps, q):+7.2%}")
    print(f"  均值 = {gaps.mean():+.2%}   最大 = {gaps.max():+.2%}")

    print(f"\n{'断面均速段':<14}{'n':>8}{'中位下移':>11}{'该段零值占比中位':>18}")
    for lo, hi in ((0, 0.2), (0.2, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 99)):
        m = (means >= lo) & (means < hi)
        if m.sum() > 3:
            print(f"[{lo}, {hi})".ljust(14) + f"{int(m.sum()):>8,}"
                  f"{np.median(gaps[m]):>11.2%}{np.median(zeros[m]):>18.2%}")

    print(f"\n相关系数:")
    print(f"  corr(零值占比, 下移幅度) = {np.corrcoef(zeros, gaps)[0,1]:+.3f}")
    print(f"  corr(断面均速, 下移幅度) = {np.corrcoef(means, gaps)[0,1]:+.3f}")
    print("\n解读: 零值占比越高的断面, 分布越偏态, 变换空间拟合相对于算术均值的")
    print("      下移越大。这是一条构造性的偏差, 不是拟合不足 —— 且随流速放大。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
