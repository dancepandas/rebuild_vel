#!/usr/bin/env bash
# Clean-baseline training: same architecture / data / stratified split as
# runs/v1, but pure MSE loss (no physics regularizers). Runs unattended with
# OOM retry, then test evals + generalization report + figures.
set -uo pipefail

PY="C:/Users/DELL/.conda/envs/HydroModel/python.exe"
cd /d/chengs/rebuild_vel || exit 1
RUN=runs/v1_mse
mkdir -p "$RUN"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

ATTEMPT=0
while true; do
  ATTEMPT=$((ATTEMPT + 1))
  echo "[mse] training attempt $ATTEMPT at $(date '+%F %T')"
  "$PY" -m rebuild_vel.train --data data/vel --output "$RUN" --device cuda --seed 42 \
    --epochs 100 --batch-size 32 --lr 5e-5 --weight-decay 3e-4 \
    --d-model 768 --num-heads 12 --num-layers 14 --ffn-dim 2304 --dropout 0.0 \
    --raw-hidden 64 --loss-mode mse_only --pure-attention \
    >> "$RUN/train.log" 2>&1
  RC=$?
  if [ "$RC" -eq 0 ]; then
    echo "[mse] training rc=0 at $(date '+%F %T')"
    break
  fi
  if grep -qE "CUDA out of memory|OutOfMemoryError" "$RUN/train.log"; then
    echo "[mse] OOM; retrying in 10 min"
    sleep 600
  else
    echo "[mse] TRAINING FAILED rc=$RC (not OOM)" | tee "$RUN/STATUS_TRAIN_FAILED.txt"
    exit "$RC"
  fi
done

for CKPT in best best_by_rmse; do
  "$PY" -m rebuild_vel.evaluate --data data/vel --checkpoint "$RUN/$CKPT.pt" \
    --split test --device cuda --output "$RUN/metrics_test_$CKPT.json" \
    > "$RUN/evaluate_$CKPT.stdout" 2>&1
  "$PY" tools/eval_generalization.py --data data/vel --checkpoint "$RUN/$CKPT.pt" \
    --split test --device cuda --output "$RUN/generalization_$CKPT.json" \
    > "$RUN/generalization_$CKPT.stdout" 2>&1
done
"$PY" tools/plot_generalization.py --checkpoint "$RUN/best.pt" \
  --report "$RUN/generalization_best.json" --history "$RUN/history.json" \
  --outdir "$RUN/figs" --device cuda > /dev/null 2>&1
"$PY" tools/plot_section_recon.py --checkpoint "$RUN/best.pt" \
  --outdir "$RUN/figs" --device cuda > /dev/null 2>&1
echo "[mse] train + evals all done" | tee "$RUN/STATUS_DONE.txt"
