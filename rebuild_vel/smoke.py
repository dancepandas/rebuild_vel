"""End-to-end smoke test: synthetic batch through model + loss + backward.

Run ``python -m rebuild_vel.smoke --device cpu`` after installing torch.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

import numpy as np


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test model/loss/dataset")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--data", default=None,
                        help="optional fetch directory; runs a real mini-train when set")
    return parser.parse_args(argv)


def synthetic_batch(batch: int = 3, k: int = 12, s: int = 10, seed: int = 0):
    import torch
    from .dataset import N_GLOBAL, N_RAW_STATS

    rng = np.random.default_rng(seed)
    morphology = torch.from_numpy(
        rng.random((batch, k, 4)).astype(np.float32))
    raw_stats = torch.from_numpy(
        rng.random((batch, k, N_RAW_STATS)).astype(np.float32))
    raw_seq_v = torch.from_numpy(
        rng.normal(0, 1, (batch, k, s)).astype(np.float32))
    raw_seq_valid = torch.from_numpy(
        (rng.random((batch, k, s)) > 0.2).astype(np.float32))
    raw_seq_dx = torch.from_numpy(
        rng.normal(0, 0.3, (batch, k, s)).astype(np.float32))
    raw_seq_t = torch.from_numpy(
        rng.random((batch, k, s)).astype(np.float32))
    lengths = rng.integers(k // 2, k + 1, batch)
    line_mask = torch.zeros(batch, k)
    for i, length in enumerate(lengths):
        line_mask[i, :length] = 1.0
    target = torch.from_numpy(rng.normal(0, 1, (batch, k)).astype(np.float32))
    global_features = torch.from_numpy(
        rng.random((batch, N_GLOBAL)).astype(np.float32))
    # mimic collate behaviour: padded columns carry zeros, never garbage
    pad2 = (line_mask == 0).unsqueeze(-1)
    for tensor in (morphology, raw_stats, raw_seq_v, raw_seq_dx, raw_seq_t):
        tensor.masked_fill_(pad2, 0.0)
    target = target * line_mask
    raw_seq_valid = raw_seq_valid * line_mask.unsqueeze(-1)
    return {
        "morphology": morphology,
        "raw_stats": raw_stats,
        "raw_seq_v": raw_seq_v,
        "raw_seq_valid": raw_seq_valid,
        "raw_seq_dx": raw_seq_dx,
        "raw_seq_t": raw_seq_t,
        "line_mask": line_mask,
        "target": target,
        "target_physical": target.clone(),
        "global_features": global_features,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    import torch

    from .dataset import collate_sections
    from .model.losses import LossConfig, RebuildPhysicsLoss
    from .model.rebuild import RebuildVelocityModel

    failures: list[str] = []

    def check(name: str, condition: bool) -> None:
        print(f"[{'PASS' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(name)

    # -- model forward/backward on a synthetic batch ------------------------
    model = RebuildVelocityModel(d_model=64, num_heads=4, num_layers=2,
                                 ffn_dim=128, dropout=0.0, raw_hidden=16)
    batch = synthetic_batch()
    output = model.forward_batch(batch)
    check("forward produces velocity_pred [B,K]",
          output["velocity_pred"].shape == batch["target"].shape)
    check("forward produces section_embedding [B,d]",
          output["section_embedding"].shape == (batch["target"].shape[0], 64))

    criterion = RebuildPhysicsLoss(LossConfig(), v_zero_norm=-0.5)
    stats = criterion(output["velocity_pred"], batch["target"],
                      batch["line_mask"], batch["morphology"])
    stats["loss"].backward()
    grads_ok = all(p.grad is not None for p in model.parameters())
    check("backward populates every parameter gradient", grads_ok)

    # -- padding invariance: extra tail padding must not change real outputs
    model.eval()
    with torch.no_grad():
        full_pred = model.forward_batch(batch)["velocity_pred"]
        k = batch["morphology"].shape[1]
        k_extra = k + 4  # extend every section with pure padding
        b = batch["morphology"].shape[0]
        padded = {}
        for key, value in batch.items():
            if value.dim() == 3:
                pad_shape = (b, k_extra - k, value.shape[2])
            elif value.dim() == 2 and key != "global_features":
                pad_shape = (b, k_extra - k)
            else:
                padded[key] = value.clone()
                continue
            pad_tensor = torch.zeros(pad_shape, dtype=value.dtype)
            padded[key] = torch.cat([value.clone(), pad_tensor], dim=1)
        padded_pred = model.forward_batch(padded)["velocity_pred"]
    aligned = torch.allclose(full_pred, padded_pred[:, :k], atol=1e-5)
    check("extra tail padding does not change real-line predictions", aligned)

    # -- collate round-trip ---------------------------------------------------
    sample_a = {k: v[0].numpy() if hasattr(v, "numpy") else v for k, v in batch.items()}
    sample_b = {k: v[1].numpy() if hasattr(v, "numpy") else v for k, v in batch.items()}
    collated = collate_sections([sample_a, sample_b])
    expected_k = max(int(sample_a["line_mask"].sum()), int(sample_b["line_mask"].sum()))
    check("collate keeps batch size", collated["morphology"].shape[0] == 2)
    check("collate pads to the longest section", collated["morphology"].shape[1] == expected_k)

    # -- optional real-data mini train ---------------------------------------
    if args.data:
        import tempfile
        from pathlib import Path

        from .train import main as train_main

        with tempfile.TemporaryDirectory() as tmp:
            code = train_main([
                "--data", args.data, "--output", str(Path(tmp) / "run"),
                "--device", args.device, "--epochs", "2", "--batch-size", "8",
                "--d-model", "64", "--num-heads", "4", "--num-layers", "2",
                "--ffn-dim", "128", "--raw-hidden", "16",
                "--max-train-samples", "16",
            ])
            check("mini train completes on real data", code == 0)
            run_dir = Path(tmp) / "run"
            check("checkpoint written",
                  (run_dir / "best.pt").is_file() or (run_dir / "last.pt").is_file())

    print("ALL PASSED" if not failures else f"FAILURES: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
