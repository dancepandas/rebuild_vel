"""Per-section reconstruction profiles for a rebuild-vel checkpoint.

Runs inference on the station-disjoint test split, picks representative
sections (best / median / worst / driest / optical-flow-only) and plots the
velocity profile along each cross-section: true vs predicted per line.

    python tools/plot_section_recon.py --checkpoint runs/v1/best.pt \
        --data data/vel --outdir runs/v1/figs
"""

from __future__ import annotations

import argparse
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
    ap.add_argument("--data", default="data/vel")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--n-panels", type=int, default=6)
    args = ap.parse_args()

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
    preds: list[np.ndarray] = []
    with torch.no_grad():
        for batch in loader:
            batch = {k: v.to(args.device) for k, v in batch.items()}
            preds.append(model.forward_batch(batch)["velocity_pred"].cpu().numpy())

    records = []
    off = 0
    for pred in preds:
        for row, sample in zip(pred, dataset.samples[off:off + len(pred)]):
            mask = sample["line_mask"].astype(bool)
            k = int(mask.sum())
            p = row[:len(mask)][:k] * norm.v_sd + norm.v_mu
            t = np.asarray(sample["target_physical"])[:k]
            depth = np.abs(sample["morphology"][:k, 1])  # d_norm channel
            # raw per-segment observations, back to physical units
            raw = np.asarray(sample["raw_seq_v"], dtype=np.float64)[:k] * norm.v_sd
            valid = np.asarray(sample["raw_seq_valid"], dtype=bool)[:k]
            raw_x, raw_y = np.nonzero(valid)
            records.append(dict(
                station=sample.get("station", "?"), time=sample.get("time", "?"),
                pred=p, true=t, depth=depth,
                rmse=float(np.sqrt(np.mean((p - t) ** 2))),
                zero_share=float((t == 0).mean()),
                of_only=int(sample.get("raw_source_id", 0)) != 0,
                raw_x=raw_x, raw_y=raw[raw_x, raw_y],
            ))
        off += len(pred)

    outdir = Path(args.outdir) if args.outdir else Path(args.checkpoint).parent / "figs"
    outdir.mkdir(parents=True, exist_ok=True)

    valid = [r for r in records if r["true"].size >= 8]
    rmse_sorted = sorted(valid, key=lambda r: r["rmse"])
    picks: list[tuple[str, dict]] = [
        ("最好断面", rmse_sorted[0]),
        ("中位断面", rmse_sorted[len(rmse_sorted) // 2]),
        ("最差断面", rmse_sorted[-1]),
    ]
    dry = sorted(valid, key=lambda r: -r["zero_share"])
    if dry and dry[0] is not rmse_sorted[0]:
        picks.append(("枯水断面(零速最多)", dry[0]))
    of = [r for r in valid if r["of_only"]]
    if of:
        picks.append(("光流-only 断面", sorted(of, key=lambda r: r["rmse"])[len(of) // 2]))
    picks = picks[: args.n_panels]

    n = len(picks)
    cols = 2
    rows = (n + 1) // 2
    fig, axes = plt.subplots(rows, cols, figsize=(13, 4.2 * rows), squeeze=False)
    for ax, (label, r) in zip(axes.flat, picks):
        k = r["true"].size
        x = np.arange(k)
        ax.plot(x, r["true"], "-", color="tab:blue", lw=1.8, label="真值")
        ax.plot(x, r["pred"], "--", color="tab:red", lw=1.6, label="预测")
        if r["raw_x"].size:
            ax.scatter(r["raw_x"], r["raw_y"], s=7, color="tab:green",
                       alpha=0.5, label="原始观测(30s段)", zorder=3)
        dry = r["depth"] < 0.01
        if dry.any():
            ax.fill_between(x, 0, 1, where=dry, transform=ax.get_xaxis_transform(),
                            color="lightgray", alpha=0.5, label="枯水线(水深<1cm)")
        ax.set_title(f"{label}  站{r['station']} {r['time'][:16]}  RMSE={r['rmse']:.3f}",
                     fontsize=10)
        ax.set_xlabel("测速线序号"); ax.set_ylabel("表面流速 (m/s)")
        ax.legend(fontsize=8, loc="upper right")
    for ax in axes.flat[n:]:
        ax.axis("off")
    fig.tight_layout()
    out = outdir / "section_recon_profiles.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(out)
    summary = ", ".join(
        "{} 站{} rmse={:.3f}".format(label, r["station"], r["rmse"])
        for label, r in picks)
    print("panels:", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
