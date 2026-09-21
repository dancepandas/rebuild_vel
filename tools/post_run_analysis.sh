#!/usr/bin/env bash
# Three-way analysis of the V1 model family on the station-disjoint test set.
#
#   runs/v1/attempt5_ep70gate  morphology-biased attention + physics loss
#   runs/v1_mse                vanilla attention + RoPE + pure L2, z-score target
#   runs/v1_mse_bc             same as above but Yeo-Johnson transformed target
#
# The three share architecture, data and split, so the only variables are the
# loss/attention family and the target transform.  Run after training finishes
# (the GPU is free by then).
set -uo pipefail

PY="C:/Users/DELL/.conda/envs/HydroModel/python.exe"
cd /d/chengs/rebuild_vel || exit 1

PHYS=runs/v1/attempt5_ep70gate
PURE=runs/v1_mse
YJ=runs/v1_mse_bc
OUT=runs/v1/analysis_3way
mkdir -p "$OUT"

CKPTS=(--checkpoint "$PHYS/best.pt:物理版"
       --checkpoint "$PURE/best.pt:纯净z-score"
       --checkpoint "$YJ/best.pt:纯净Yeo-Johnson")

step() {
  local name=$1; shift
  echo "[analysis] $name at $(date '+%F %T')"
  if "$PY" "$@" > "$OUT/${name}.stdout" 2>&1; then
    echo "[analysis] $name OK"
  else
    echo "[analysis] $name FAILED rc=$?" | tee "$OUT/STATUS_${name}_FAILED.txt"
  fi
}

step comparison_3way tools/compare_models.py --data data/vel --device cuda \
  "${CKPTS[@]}" --output "$OUT/comparison_3way.json"

step behaviour_3way tools/behaviour_analysis.py --data data/vel --device cuda \
  "${CKPTS[@]}" --output "$OUT/behaviour_3way.json"

step contradiction_3way tools/contradiction_analysis.py --data data/vel --device cuda \
  "${CKPTS[@]}" --output "$OUT/contradiction_3way.json"

# per-velocity-bin error curve for the report (the dense scatter + profiles for
# the YJ model are produced by the training driver into $YJ/figs)
step figs_yj tools/report_figs.py --checkpoint "$YJ/best.pt" \
  --report "$YJ/generalization_best.json" --history "$YJ/history.json" \
  --data data/vel --outdir "$OUT/figs_yj" --device cuda

# also rank the YJ run's own two checkpoints (composite-selected vs
# physical-RMSE-selected) to see whether the transformed objective diverged
# from physical accuracy
step yj_ckpt_duel tools/compare_models.py --data data/vel --device cuda \
  --checkpoint "$YJ/best.pt:YJ复合选点" \
  --checkpoint "$YJ/best_by_rmse.pt:YJ物理RMSE选点" \
  --output "$OUT/yj_ckpt_duel.json"

echo "[analysis] all done at $(date '+%F %T')" | tee "$OUT/STATUS_DONE.txt"
