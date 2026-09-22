"""Train the raw-to-surface velocity reconstruction model.

Local runs are CPU smoke tests; full training runs on the server with the same
command and ``--device cuda``.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import time
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from .dataset import SectionDataset, collate_sections, compute_norm_stats, load_shards
from .model.losses import LossConfig, RebuildPhysicsLoss
from .model.rebuild import RebuildVelocityModel

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the reconstruction model")
    parser.add_argument("--data", required=True, help="fetch output directory")
    parser.add_argument("--output", required=True, help="run directory")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--weight-decay", type=float, default=3e-4)
    parser.add_argument("--warmup-fraction", type=float, default=0.05)
    parser.add_argument("--min-lr-fraction", type=float, default=0.01)
    parser.add_argument("--d-model", type=int, default=768)
    parser.add_argument("--num-heads", type=int, default=12)
    parser.add_argument("--num-layers", type=int, default=14)
    parser.add_argument("--ffn-dim", type=int, default=2304)
    parser.add_argument("--dropout", type=float, default=0.0)
    parser.add_argument("--raw-hidden", type=int, default=64)
    parser.add_argument("--target-transform", action="store_true",
                        help="Yeo-Johnson transform the target (Box-Cox family, "
                             "handles the zero mass) before the L2 loss")
    parser.add_argument("--pure-attention", action="store_true",
                        help="disable the morphology attention bias (vanilla attention)")
    parser.add_argument("--loss-mode", default="full", choices=["full", "mse_only"])
    parser.add_argument("--max-train-samples", type=int, default=None,
                        help="cap training samples (smoke tests)")
    parser.add_argument("--eval-every", type=int, default=1, help="epochs between val evals")
    parser.add_argument("--num-workers", type=int, default=0)
    return parser.parse_args(argv)


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    import torch

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


class LengthBucketingSampler:
    """Group similar-length sections to minimize padding waste."""

    def __init__(self, lengths: list[int], batch_size: int, seed: int = 42) -> None:
        self.lengths = lengths
        self.batch_size = batch_size
        self.seed = seed
        self.epoch = 0

    def batches(self) -> list[list[int]]:
        rng = random.Random(self.seed + self.epoch)
        order = list(range(len(self.lengths)))
        rng.shuffle(order)
        order.sort(key=lambda index: self.lengths[index] + rng.random() * 4)
        return [order[i:i + self.batch_size] for i in range(0, len(order), self.batch_size)]


def evaluate(model: Any, loader: Any, criterion: Any, device: str,
             norm: Any = None) -> dict[str, float]:
    import torch

    model.eval()
    sse = 0.0
    sae = 0.0
    count = 0
    sum_pred = 0.0
    sum_target = 0.0
    # composite loss and per-term values, accumulated with the same weighting
    # as mse so checkpoint selection can follow the full training objective
    loss_sum = 0.0
    term_sums = {"smooth": 0.0, "depth_corr": 0.0, "bank": 0.0,
                 "bank_zero": 0.0, "grad_smooth": 0.0}
    phys_res2 = 0.0
    phys_abs = 0.0
    phys_bias = 0.0
    phys_n = 0
    with torch.no_grad():
        for batch in loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            output = model.forward_batch(batch)
            stats = criterion(output["velocity_pred"], batch["target"],
                              batch["line_mask"], batch["morphology"])
            mask = batch["line_mask"].bool()
            n = int(mask.sum().item())
            count += n
            sse += float(stats["mse"].item()) * n
            loss_sum += float(stats["loss"].item()) * n
            for name in term_sums:
                term_sums[name] += float(stats[name].item()) * n
            diff = (output["velocity_pred"] - batch["target"]).abs().masked_select(mask)
            sae += float(diff.sum().item())
            sum_pred += float(output["velocity_pred"].masked_select(mask).sum().item())
            sum_target += float(batch["target"].masked_select(mask).sum().item())
            if norm is not None:
                pp = norm.physical_target(output["velocity_pred"].cpu().numpy())
                tt = norm.physical_target(batch["target"].cpu().numpy())
                d = (pp - tt)[mask.cpu().numpy()]
                phys_res2 += float((d ** 2).sum())
                phys_abs += float(np.abs(d).sum())
                phys_bias += float(d.sum())
                phys_n += d.size
    rmse = math.sqrt(sse / max(count, 1))
    out = {
        "rmse_norm": rmse,
        "mae_norm": sae / max(count, 1),
        "bias_norm": (sum_pred - sum_target) / max(count, 1),
        # composite objective (same function the optimizer minimizes); the
        # primary checkpoint-selection criterion
        "composite_norm": loss_sum / max(count, 1),
        **{f"{name}_norm": value / max(count, 1) for name, value in term_sums.items()},
        "count": float(count),
    }
    if norm is not None and phys_n:
        out["rmse_physical"] = math.sqrt(phys_res2 / phys_n)
        out["mae_physical"] = phys_abs / phys_n
        out["bias_physical"] = phys_bias / phys_n
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import torch
    from torch.utils.data import DataLoader

    _seed_everything(args.seed)
    device = args.device
    run_dir = Path(args.output)
    run_dir.mkdir(parents=True, exist_ok=True)

    sections = load_shards(args.data)
    logger.info("loaded %d sections from %s", len(sections), args.data)
    if not sections:
        raise SystemExit("no sections found; run rebuild_vel.fetch first")

    # norm stats must come from the training split only
    train_sections = _select_split_sections(sections, "train", args.seed)
    norm = compute_norm_stats(train_sections, target_transform=args.target_transform)
    logger.info("norm: v_mu=%.4f v_sd=%.4f raw_v_max=%.2f stations=%d",
                norm.v_mu, norm.v_sd, norm.raw_v_max, len({s['station'] for s in train_sections}))

    train_set = SectionDataset(sections, norm, split="train", seed=args.seed)
    val_set = SectionDataset(sections, norm, split="val", seed=args.seed)
    test_set = SectionDataset(sections, norm, split="test", seed=args.seed)
    logger.info("split: train=%d val=%d test=%d (stations %d/%d/%d)",
                len(train_set), len(val_set), len(test_set),
                len(train_set.stations), len(val_set.stations), len(test_set.stations))

    if args.max_train_samples and len(train_set) > args.max_train_samples:
        train_set.samples = train_set.samples[: args.max_train_samples]
        logger.info("capped train set to %d samples", len(train_set))

    generator = torch.Generator().manual_seed(args.seed)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False,
                            collate_fn=collate_sections, num_workers=args.num_workers)
    test_loader = DataLoader(test_set, batch_size=args.batch_size, shuffle=False,
                             collate_fn=collate_sections, num_workers=args.num_workers)

    model = RebuildVelocityModel(
        d_model=args.d_model,
        num_heads=args.num_heads,
        num_layers=args.num_layers,
        ffn_dim=args.ffn_dim,
        dropout=args.dropout,
        raw_hidden=args.raw_hidden,
        pure_attention=args.pure_attention,
    ).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    logger.info("model parameters: %d", n_params)

    v_zero_norm = (0.0 - norm.v_mu) / norm.v_sd
    criterion = RebuildPhysicsLoss(LossConfig(mode=args.loss_mode), v_zero_norm=v_zero_norm)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                  weight_decay=args.weight_decay)

    sampler = LengthBucketingSampler(
        [int(item["line_mask"].sum()) for item in train_set.samples],
        args.batch_size, seed=args.seed,
    )
    steps_per_epoch = len(sampler.batches())
    total_steps = steps_per_epoch * args.epochs
    warmup_steps = max(1, int(total_steps * args.warmup_fraction))
    min_lr = args.lr * args.min_lr_fraction

    def lr_at(step: int) -> float:
        if step < warmup_steps:
            return args.lr * (step + 1) / warmup_steps
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        return min_lr + 0.5 * (args.lr - min_lr) * (1 + math.cos(math.pi * progress))

    run_config = vars(args).copy()
    run_config["norm"] = norm.to_dict()
    run_config["n_params"] = n_params
    (run_dir / "config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    best_val = float("inf")
    best_val_rmse = float("inf")
    step = 0
    history: list[dict[str, Any]] = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        sampler.epoch = epoch
        batches = sampler.batches()
        running = 0.0
        started = time.time()
        for batch_indices in batches:
            lr = lr_at(step)
            for group in optimizer.param_groups:
                group["lr"] = lr
            batch = collate_sections([train_set.samples[i] for i in batch_indices])
            batch = {key: value.to(device) for key, value in batch.items()}
            output = model.forward_batch(batch)
            stats = criterion(output["velocity_pred"], batch["target"],
                              batch["line_mask"], batch["morphology"])
            optimizer.zero_grad(set_to_none=True)
            stats["loss"].backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            running += float(stats["loss"].item())
            step += 1
        train_loss = running / max(1, len(batches))

        record: dict[str, Any] = {"epoch": epoch, "lr": lr_at(step - 1),
                                  "train_loss": train_loss,
                                  "seconds": time.time() - started}
        if epoch % args.eval_every == 0 and len(val_set):
            val_stats = evaluate(model, val_loader, criterion, device, norm=norm)
            record.update({f"val_{k}": v for k, v in val_stats.items()})
            # with a target transform the normalized RMSE lives in transform
            # space; the RMSE-selected checkpoint must stay comparable across
            # runs, so it is chosen on physical m/s
            val_rmse_phys = val_stats.get("rmse_physical", val_stats["rmse_norm"] * norm.v_sd)
            record["val_rmse_physical"] = val_rmse_phys
            # primary selection: composite loss = the objective itself; the
            # RMSE-selected checkpoint is kept alongside for divergence comparison
            if val_stats["composite_norm"] < best_val:
                best_val = val_stats["composite_norm"]
                torch.save({"model": model.state_dict(),
                            "config": run_config,
                            "epoch": epoch,
                            "selected_by": "composite"}, run_dir / "best.pt")
                record["best"] = True
            if val_rmse_phys < best_val_rmse:
                best_val_rmse = val_rmse_phys
                torch.save({"model": model.state_dict(),
                            "config": run_config,
                            "epoch": epoch,
                            "selected_by": "rmse_physical"}, run_dir / "best_by_rmse.pt")
                record["best_by_rmse"] = True
        history.append(record)
        logger.info(
            "epoch %d/%d train_loss=%.4f%s (%.1fs)",
            epoch, args.epochs, train_loss,
            "".join(f" val_rmse={record['val_rmse_physical']:.4f} m/s"
                    f" val_composite={record['val_composite_norm']:.4f}"
                    if "val_rmse_physical" in record else ""),
            record["seconds"],
        )
        (run_dir / "history.json").write_text(
            json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # final test evaluation with the best checkpoint (last if no val set)
    torch.save({"model": model.state_dict(),
                "config": run_config,
                "epoch": args.epochs}, run_dir / "last.pt")
    best_path = run_dir / "best.pt"
    restore_path = best_path if best_path.is_file() else run_dir / "last.pt"
    checkpoint = torch.load(restore_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model"])
    if len(test_set):
        test_stats = evaluate(model, test_loader, criterion, device, norm=norm)
        if norm.target_lambda is None:
            # legacy z-score target: the normalized metrics are a pure rescale
            # of physical units, so reporting them in m/s under the old names
            # is exact
            test_stats = {k: (v * norm.v_sd if k in ("rmse_norm", "mae_norm", "bias_norm") else v)
                          for k, v in test_stats.items()}
        else:
            # transformed target: rmse_norm/mae_norm/bias_norm live in transform
            # space and must not be dressed up as physical (a previous version
            # multiplied them by v_sd, which reads as m/s but is not).  Rename
            # them; the physical metrics are reported separately below.
            test_stats = {
                (k[:-5] + "_transform" if k in ("rmse_norm", "mae_norm", "bias_norm") else k): v
                for k, v in test_stats.items()}
        logger.info("test: %s", {k: round(v, 4) for k, v in test_stats.items()})
        (run_dir / "test_metrics.json").write_text(
            json.dumps(test_stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("run directory: %s", run_dir)
    return 0


def _select_split_sections(sections, split: str, seed: int):
    """Sections belonging to one station-level split (no norm leakage)."""
    from .dataset import split_stations

    station_splits = split_stations(sections, seed=seed)
    chosen = station_splits[split]
    by_station: dict[str, list] = {}
    for section in sections:
        by_station.setdefault(str(section["station"]), []).append(section)
    return [s for station in chosen for s in by_station[station]]


if __name__ == "__main__":
    raise SystemExit(main())
