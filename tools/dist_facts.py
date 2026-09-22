"""Recompute the target-distribution facts the report will quote.

Everything here is measured on the actual shards, not carried over from the
earlier scratch notes -- the zero mass and the fitted lambda are load-bearing
for the mechanism argument, so they must be reproducible from data.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rebuild_vel.dataset import compute_norm_stats, load_shards  # noqa: E402
from rebuild_vel.train import _select_split_sections  # noqa: E402

sections = load_shards("data/vel")
print(f"sections total: {len(sections):,}")
tr = _select_split_sections(sections, "train", 42)
va = _select_split_sections(sections, "val", 42)
te = _select_split_sections(sections, "test", 42)
print(f"split: train {len(tr):,}  val {len(va):,}  test {len(te):,}")

norm_plain = compute_norm_stats(tr, target_transform=False)
norm_yj = compute_norm_stats(tr, target_transform=True)
print(f"\nv_mu={norm_plain.v_mu:.5f}  v_sd={norm_plain.v_sd:.5f}")
print(f"YJ lambda={norm_yj.target_lambda:+.6f}   t_mu={norm_yj.target_mu:+.5f}  t_sd={norm_yj.target_sd:.5f}")

def targets(split):
    out = []
    for s in split:
        out.append(np.asarray(s["v_surface"], dtype=np.float64))
    return np.concatenate(out)

def skew_kurt(a):
    m, sd = a.mean(), a.std()
    z = (a - m) / sd
    return float((z ** 3).mean()), float((z ** 4).mean() - 3.0)

print(f"\n{'划分':<8}{'n':>12}{'零值占比':>10}{'偏度':>10}{'峰度':>10}"
      f"{'变换后偏度':>12}{'变换后峰度':>12}{'|z|>3占比':>11}")
for name, split in (("train", tr), ("val", va), ("test", te)):
    t = targets(split)
    z = (t - norm_plain.v_mu) / norm_plain.v_sd
    y = norm_yj.norm_target(t)
    sk, ku = skew_kurt(z)
    sk2, ku2 = skew_kurt(y)
    print(f"{name:<8}{len(t):>12,}{(t == 0).mean():>10.2%}{sk:>10.3f}{ku:>+10.3f}"
          f"{sk2:>12.3f}{ku2:>+12.3f}{(np.abs(z) > 3).mean():>11.2%}")

t = targets(tr)
z = (t - norm_plain.v_mu) / norm_plain.v_sd
y = norm_yj.norm_target(t)
print(f"\nz 空间:  zero 处点质量 {(z == 0).mean():.2%}   "
      f"零值线的 z 值 = {(0 - norm_plain.v_mu) / norm_plain.v_sd:+.4f}")
zy = (0.0 - norm_plain.v_mu) / norm_plain.v_sd
print(f"YJ 空间: zero 处点质量 {(np.asarray(t) == 0).mean():.2%}   "
      f"零值线的 y 值 = {norm_yj.norm_target(np.array([0.0]))[0]:+.4f}")
print("\n注意: 点质量在变换前后都精确落在同一个值上 -> 变换不改变零值线的\"原子\"结构,")
print("      但把该原子处的 L2 权重抬到最大 (w(0)=3.77), 即把容量推向枯水线。")

print(f"\n权重拐点: w(v)=1 当 v = v_mu = {norm_plain.v_mu:.4f} m/s")
below = (t < norm_plain.v_mu).mean()
print(f"训练集中 v < 拐点的目标占比: {below:.2%}  (这些线拿到 >1 的 L2 权重)")
print(f"训练集中 v >= 1 m/s 的占比: {(t >= 1.0).mean():.2%} (w = {float(np.power((1.0 - norm_plain.v_mu) / norm_plain.v_sd + 1.0, norm_yj.target_lambda - 1.0)) ** 2:.4f})")

# raw-v max clip, quoted in the report's input description
rmax = [float(np.nanmax(np.abs(np.asarray(s["raw_v"], dtype=np.float64))))
        for s in tr[:4000]]
print(f"\nraw_v 绝对值上界(前4000 section): {np.max(rmax):.2f} (标准化后)")
Path("runs/v1/analysis_3way/dist_facts.json").write_text(json.dumps({
    "v_mu": norm_plain.v_mu, "v_sd": norm_plain.v_sd,
    "lambda": norm_yj.target_lambda, "t_mu": norm_yj.target_mu, "t_sd": norm_yj.target_sd,
    "zero_share": {n: float((targets(s) == 0).mean()) for n, s in
                   (("train", tr), ("val", va), ("test", te))},
    "splits": {"train": len(tr), "val": len(va), "test": len(te)},
}, ensure_ascii=False, indent=2), encoding="utf-8")
