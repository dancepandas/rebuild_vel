"""Verify the Yeo-Johnson target transform roundtrips and is worth having.

Runs on the real fetched shards: fits the transform on the training split the
same way ``train.py`` does, then checks

1. ``physical_target(norm_target(v)) == v`` for every training target,
2. exact zeros stay exact zeros (the zero-velocity mass is why Yeo-Johnson was
   chosen over Box-Cox in the first place),
3. the analytic inverse agrees with a bisection inverse of
   ``scipy.stats.yeojohnson`` (guards against a branch/typo bug),
4. the transform actually normalizes the target (skew / kurtosis before-after).

    python tools/check_target_transform.py --data data/vel
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rebuild_vel.dataset import compute_norm_stats, load_shards
from rebuild_vel.train import _select_split_sections


def bisect_inverse(values: np.ndarray, lam: float) -> np.ndarray:
    """Numeric inverse of scipy's yeojohnson (y -> x) by bisection."""
    from scipy.stats import yeojohnson

    lo = np.full(values.shape, -1e6, dtype=np.float64)
    hi = np.full(values.shape, 1e6, dtype=np.float64)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        over = yeojohnson(mid, lmbda=lam) > values
        hi = np.where(over, mid, hi)
        lo = np.where(over, lo, mid)
    return 0.5 * (lo + hi)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/vel")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from scipy.stats import kurtosis, skew, yeojohnson

    sections = load_shards(args.data)
    train_sections = _select_split_sections(sections, "train", args.seed)
    print(f"train sections: {len(train_sections)}")

    norm = compute_norm_stats(train_sections, target_transform=True)
    targets = np.concatenate(
        [np.asarray(s["v_surface"], dtype=np.float64) for s in train_sections])
    print(f"fitted: lambda={norm.target_lambda:.6f} "
          f"mu={norm.target_mu:.6f} sd={norm.target_sd:.6f}")
    print(f"        v_mu={norm.v_mu:.6f} v_sd={norm.v_sd:.6f}")

    ok = True

    # 1. roundtrip over every training target
    back = norm.physical_target(norm.norm_target(targets))
    err = float(np.abs(back - targets).max())
    rel = float((np.abs(back - targets) / np.maximum(np.abs(targets), 1e-3)).max())
    print(f"\n[1] roundtrip max abs err = {err:.3e}  max rel err = {rel:.3e}")
    ok &= err < 1e-4

    # 2. zeros
    z_in = np.zeros(1000, dtype=np.float64)
    z_out = norm.physical_target(norm.norm_target(z_in))
    zero_err = float(np.abs(z_out).max())
    zero_share = float((targets == 0).mean())
    print(f"[2] zeros stay zeros: {zero_err:.3e} (zero mass = {zero_share:.1%})")
    ok &= zero_err < 1e-6

    # 3. analytic inverse vs numeric bisection of scipy's forward transform
    rng = np.random.default_rng(0)
    z_std = rng.uniform(-3.0, 6.0, 4000)  # a plausible standardized-velocity range
    yt_test = np.asarray(yeojohnson(z_std, lmbda=norm.target_lambda), dtype=np.float64)
    model_in = (yt_test - norm.target_mu) / norm.target_sd
    v_back = np.asarray(norm.physical_target(model_in), dtype=np.float64)
    our_x = (v_back - norm.v_mu) / norm.v_sd          # -> standardized axis
    ref_x = bisect_inverse(yt_test, norm.target_lambda)  # -> standardized axis
    inv_err = float(np.abs(our_x - ref_x).max())
    print(f"[3] analytic inverse vs bisection: max err = {inv_err:.3e}")
    ok &= inv_err < 1e-6

    # 4. does the transform help?
    print("\n[4] distribution of the target")
    print(f"    physical : skew={skew(targets):+.3f} kurt={kurtosis(targets):+.3f}")
    for name, t in (("z-score", (targets - norm.v_mu) / norm.v_sd),
                    ("yeo-john", norm.norm_target(targets).astype(np.float64))):
        print(f"    {name:>9} : skew={skew(t):+.3f} kurt={kurtosis(t):+.3f} "
              f"|z|>3 {(np.abs(t) > 3).mean():.4%}")
    # monotonicity: the map must not reorder lines
    idx = np.argsort(targets)
    mono = np.all(np.diff(norm.norm_target(targets)[idx].astype(np.float64)) >= -1e-6)
    print(f"    monotone: {mono}")
    ok &= bool(mono)

    # 5. the Jacobian weight the transform puts on the L2 loss.  dL/dv^2 scales
    #    with (dy/dx)^2, so this is the multiplier relative to the plain z-score
    #    target at each velocity - the trade-off this run is testing.
    print("\n[5] L2 weight multiplier vs the z-score target  (dy/dx)^2")
    lam = norm.target_lambda
    for v in (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        x = (v - norm.v_mu) / norm.v_sd
        jac = (1.0 - x) ** (1.0 - lam) if x < 0 else (x + 1.0) ** (lam - 1.0)
        print(f"    v = {v:4.2f} m/s  (x={x:+6.2f})  weight x{jac ** 2:8.3f}")
    zero_w = ((1.0 - (0.0 - norm.v_mu) / norm.v_sd) ** (1.0 - lam)) ** 2
    tail_w = (((3.0 - norm.v_mu) / norm.v_sd + 1.0) ** (lam - 1.0)) ** 2
    print(f"    -> zero line weighted {zero_w / tail_w:.0f}x a 3 m/s line")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
