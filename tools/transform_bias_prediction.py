"""The distributional prediction: what SHOULD a transform-space fit predict?

Independent of any model.  For each target bin this computes

  * the arithmetic mean of the target  -- the minimiser of physical L2
  * the inverse-transformed mean of the transformed target -- the minimiser of
    transform-space L2, mapped back to m/s

and their ratio.  If the transform is doing what Jensen's inequality says, that
ratio should fall below 1 and decline with velocity, because the training
population is right-skewed and the transform is concave there.

This is the theoretical curve the models are checked against by
tools/jensen_test.py -- stated here so the check is against a number derived
before looking at predictions, not after.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rebuild_vel.dataset import compute_norm_stats, load_shards  # noqa: E402
from rebuild_vel.train import _select_split_sections  # noqa: E402

BINS = [0.0, 0.2, 0.5, 1.0, 2.0, 3.0, 100.0]
NAMES = ["[0,0.2)", "[0.2,0.5)", "[0.5,1)", "[1,2)", "[2,3)", "[3+)"]

sections = _select_split_sections(load_shards("data/vel"), "test", 42)
norm = compute_norm_stats(_select_split_sections(load_shards("data/vel"), "train", 42),
                          target_transform=True)
t = np.concatenate([np.asarray(s["v_surface"], dtype=np.float64) for s in sections])
print(f"lambda = {norm.target_lambda:+.6f}  (lambda->0 时正支即 log(1+z))")

print(f"\n{'分段':<12}{'n':>10}{'算术均值':>10}{'变换空间均值':>14}{'比值':>9}{'该段偏度':>10}")
rows = []
for i, name in enumerate(NAMES):
    m = (t >= BINS[i]) & (t < BINS[i + 1])
    if not m.any():
        continue
    v = t[m]
    amean = float(v.mean())
    tmean = float(np.asarray(
        norm.physical_target(np.array([norm.norm_target(v).mean()]))).reshape(-1)[0])
    z = (v - v.mean()) / (v.std() or 1.0)
    sk = float((z ** 3).mean())
    rows.append((name, int(m.sum()), amean, tmean, tmean / amean, sk))
    print(f"{name:<12}{int(m.sum()):>10,}{amean:>10.4f}{tmean:>14.4f}"
          f"{tmean / amean:>9.4f}{sk:>+10.3f}")

print("\n解读: 比值 <1 表示「在变换空间拟合」会系统性低估该段的算术均值;")
print("      比值随流速下降表示低估幅度随流速放大 —— 这正是实测 bias 曲线的形状。")
r = [x[4] for x in rows]
print(f"\n比值区间: {min(r):.4f} .. {max(r):.4f}   单调下降: {all(a >= b for a, b in zip(r, r[1:]))}")
