"""Test whether the transform swapped the regression target's statistic.

The fingerprint test (tools/transform_fingerprint.py) falsified the naive
mechanism -- "the loss is reweighted by the Jacobian w(v), so errors move in
proportion to w(v)".  What it measured instead was a downward shift of bias in
*every* velocity bin, growing with velocity.

That is the signature of a different mechanism.  With lambda = -0.0519 ~ 0, the
positive branch of the transform is y = log(z + 1), and minimising squared error
in log space minimises *relative* error, whose minimiser is the conditional
geometric mean rather than the conditional arithmetic mean.  For a right-skewed
target the geometric mean sits below the arithmetic mean, and the gap widens as
the conditional distribution spreads -- so the deficit should grow with velocity.
That is Jensen's inequality, and it predicts the exact shape observed.

This script distinguishes the two accounts directly.  For each target bin it
compares each model's mean prediction against

    arithmetic mean of target  -- what an L2-in-velocity-space fit converges to
    geometric  mean of target  -- what an L2-in-log-space fit converges to

A model that minimises physical L2 should track the arithmetic mean; a model
that minimises log-space L2 should track the geometric mean.  The zero mass
makes the plain geometric mean degenerate (any exact zero sends it to 0), so it
is computed over positive targets only and the bin's zero share is reported
alongside it.

    python tools/jensen_test.py --data data/vel --device cuda \
        --checkpoint runs/v1_mse/best.pt:z \
        --checkpoint runs/v1_mse_bc/best_by_rmse.pt:YJep61 \
        --output runs/v1/analysis_3way/jensen.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.transform_fingerprint import BINS, BIN_NAMES, collect  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/vel")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--checkpoint", action="append", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--cache", default=None,
                    help="directory for cached per-model predictions (npz)")
    args = ap.parse_args()

    labels, preds, target = [], {}, None
    norms = {}
    cache = Path(args.cache) if args.cache else None
    for spec in args.checkpoint:
        path, _, tag = spec.partition(":")
        tag = tag or Path(path).parent.name
        labels.append(tag)
        # inference is ~4 min/model; cache it so the analysis itself can be
        # iterated on without paying for the forward pass again
        cached = cache / f"{tag}.npz" if cache else None
        if cached is not None and cached.exists():
            npz = np.load(cached, allow_pickle=False)
            preds[tag], target = npz["pred"], npz["target"]
            print(f"[jensen] {tag}: loaded from cache", flush=True)
            from rebuild_vel.dataset import NormStats
            import json as _json
            norms[tag] = NormStats.from_dict(_json.loads(str(npz["norm"])))
            continue
        res = collect(path, args.data, args.device)
        preds[tag] = res["pred"]
        norms[tag] = res["norm"]
        target = res["target"]
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(cached, pred=res["pred"], target=target,
                                norm=json.dumps(res["norm"].to_dict(), ensure_ascii=False))
        print(f"[jensen] {tag}: epoch {res['epoch']}", flush=True)

    # The exact quantity a model with a perfect fit in a given transform space
    # would predict for a bin is the *inverse-transformed mean of the
    # transformed target*, not the mean of the raw target.  Affine rescaling
    # after the transform does not move that point, so only lambda matters.
    def transform_mean_physical(norm, values: np.ndarray) -> float:
        if norm.target_lambda is None:
            return float(np.mean(values))
        inv = norm.physical_target(np.array([norm.norm_target(values).mean()]))
        return float(np.asarray(inv).reshape(-1)[0])

    report = {"bins": {}}
    print(f"\n{'分段':<12}{'n':>10}{'零值占比':>9}{'算术均值':>10}{'YJ反变换均值':>13}"
          + "".join(f"{t:>12}" for t in labels))
    for i, name in enumerate(BIN_NAMES):
        m = (target >= BINS[i]) & (target < BINS[i + 1])
        if not m.any():
            continue
        t = target[m]
        pos = t[t > 0]
        amean = float(t.mean())
        gmean = float(np.exp(np.log(pos).mean())) if pos.size else 0.0
        row = {"n": int(m.sum()), "zero_share": float((t == 0).mean()),
               "arith_mean": amean, "geo_mean_positive": gmean,
               "geom_of_raw_minus1": float(np.exp(np.log1p(pos).mean()) - 1.0) if pos.size else 0.0,
               "yj_transform_mean": transform_mean_physical(norms[labels[-1]], t)}
        cells = ""
        for tag in labels:
            p = float(preds[tag][m].mean())
            row[f"mean_pred_{tag}"] = p
            row[f"ratio_to_arith_{tag}"] = p / amean if amean else float("nan")
            row[f"ratio_to_geo_{tag}"] = p / gmean if gmean else float("nan")
            cells += f"{p:>12.4f}"
        report["bins"][name] = row
        print(f"{name:<12}{row['n']:>10,}{row['zero_share']:>9.2%}{amean:>10.4f}"
              f"{row['yj_transform_mean']:>13.4f}" + cells)

    # aggregate: how far each model sits from what a physical-L2 fit would
    # predict (the arithmetic mean) versus what a transform-space fit would
    # predict (the inverse-transformed mean of the transformed target)
    print(f"\n{'模型':<12}{'log距离: 算术均值':>20}{'log距离: 变换空间均值':>22}{'更接近':>14}")
    for tag in labels:
        da, dt, n = 0.0, 0.0, 0
        for name in BIN_NAMES:
            if name not in report["bins"]:
                continue
            r = report["bins"][name]
            p, a, y = r[f"mean_pred_{tag}"], r["arith_mean"], r["yj_transform_mean"]
            if not (p > 0 and a > 0 and y > 0):
                continue
            da += abs(np.log(p) - np.log(a)) * r["n"]
            dt += abs(np.log(p) - np.log(y)) * r["n"]
            n += r["n"]
        report[f"logdist_{tag}"] = {"to_arith": da / n, "to_transform": dt / n}
        who = "变换空间均值" if dt < da else "算术均值"
        print(f"{tag:<12}{da / n:>20.4f}{dt / n:>22.4f}{who:>14}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(f"\n[jensen] written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
