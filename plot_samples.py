"""Visualize fetched sections: geometry, target velocity, raw segments, confidence."""
import pickle
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False


def plot_section(ax_geo, ax_vel, section, index):
    x = section["x"]
    depth = section["depth"]
    target = section["v_surface"]
    is_algo = section["is_algo"]
    conf = section["confidence"]
    raw_v = section["raw_v"]
    raw_conf = section["raw_conf"]
    valid = section["raw_valid"]

    title = (f"{index + 1}. {section['station_name']} {section['time']}  "
             f"水位={section['water_level']:.2f}m  "
             f"河宽={section['water_width']:.1f}m  原始真值占比={section['original_value_prop']:.2f}")

    # geometry
    ax_geo.fill_between(x, -depth, 0, color="#9ecae1", alpha=0.6)
    ax_geo.plot(x, -depth, color="#08519c", lw=1.5)
    ax_geo.axhline(0, color="#08519c", lw=0.5)
    ax_geo.set_ylabel("河床 (m, 相对水面)")
    ax_geo.set_title(title, fontsize=10)
    ax_geo.grid(alpha=0.2)

    # velocity: target line, algo vs interp, raw segments
    ax_vel.plot(x, target, "-", color="#bbbbbb", lw=1)
    ax_vel.scatter(x[is_algo], target[is_algo], c="#2E86AB", s=22, zorder=3, label="目标-算法给出")
    ax_vel.scatter(x[~is_algo], target[~is_algo], c="#F28E2B", s=22, zorder=3, label="目标-插值")
    # raw segments: jitter x per segment, color by confidence
    S = raw_v.shape[1]
    sc = None
    for i in range(len(x)):
        xs = x[i] + (np.arange(S) - (S - 1) / 2) * (x[1] - x[0]) * 0.06
        vs = raw_v[i]
        cs = raw_conf[i]
        m = valid[i] & np.isfinite(vs)
        if not m.any():
            continue
        sc = ax_vel.scatter(xs[m], vs[m], c=cs[m], cmap="RdYlGn", vmin=0, vmax=1,
                            s=14, zorder=2)
    if sc is not None:
        sc.set_label("原始分段流速（颜色=置信度）")
    ax_vel.set_ylabel("流速 (m/s)")
    ax_vel.set_xlabel("起点距 (m)")
    ax_vel.grid(alpha=0.2)
    ax_vel.legend(fontsize=8, loc="upper right")
    if index == 0:
        cbar = plt.colorbar(sc, ax=ax_vel, pad=0.01)
        cbar.set_label("原始分段置信度", fontsize=8)


def main():
    shards = sorted(Path("data/raw/sections").glob("*.pkl"))
    sections = []
    for shard in shards:
        with shard.open("rb") as f:
            sections.extend(pickle.load(f))
    # pick 4 spread-out sections (evenly spaced indices)
    pick_idx = np.linspace(0, len(sections) - 1, 4).astype(int)
    picked = [sections[i] for i in pick_idx]

    fig, axes = plt.subplots(len(picked), 2, figsize=(15, 3.4 * len(picked)), squeeze=False)
    for i, section in enumerate(picked):
        plot_section(axes[i, 0], axes[i, 1], section, i)
    fig.suptitle("抓取数据抽检：断面几何（左）与 目标表面流速 + 原始分段流速（右）", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = "data_sample_check.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print("saved", out)
    # quick numeric sanity per picked section
    for i, s in enumerate(picked):
        rv = s["raw_v"][s["raw_valid"]]
        print(f"[{i+1}] {s['station_name']} {s['time']} K={len(s['x'])} "
              f"algo={int(s['is_algo'].sum())}/{len(s['x'])} "
              f"target[min/mean/max]=[{s['v_surface'].min():.2f}/{s['v_surface'].mean():.2f}/{s['v_surface'].max():.2f}] "
              f"raw[min/mean/max]=[{rv.min():.2f}/{rv.mean():.2f}/{rv.max():.2f}]")


if __name__ == "__main__":
    main()
