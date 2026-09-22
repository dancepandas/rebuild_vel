#!/usr/bin/env bash
# V1 training on the current pool (103,573 sections, snapshot:
# runs/v1/data_snapshot_v1_train.json), then test evals.
# Fetching is paused per user decision and resumes ~2h later (see journal).
set -uo pipefail

PY="C:/Users/DELL/.conda/envs/HydroModel/python.exe"
cd /d/chengs/rebuild_vel || exit 1
RUN=runs/v1

"$PY" -m rebuild_vel.train --data data/vel --output "$RUN" --device cuda --seed 42 \
  --epochs 100 --batch-size 32 --lr 5e-5 --weight-decay 3e-4 \
  --d-model 768 --num-heads 12 --num-layers 14 --ffn-dim 2304 --dropout 0.0 \
  --raw-hidden 64 --loss-mode full \
  > "$RUN/train.log" 2>&1
TRAIN_RC=$?
echo "[v1] training rc=$TRAIN_RC at $(date '+%F %T')"
if [ "$TRAIN_RC" -ne 0 ]; then
  echo "[v1] TRAINING FAILED" | tee "$RUN/STATUS_TRAIN_FAILED.txt"
  exit "$TRAIN_RC"
fi

# both selection criteria get a full test + generalization report so the
# composite-vs-RMSE divergence is quantified, not hidden
for CKPT in best best_by_rmse; do
  "$PY" -m rebuild_vel.evaluate --data data/vel --checkpoint "$RUN/$CKPT.pt" --split test \
    --device cuda --output "$RUN/metrics_test_$CKPT.json" > "$RUN/evaluate_$CKPT.stdout" 2>&1
  "$PY" tools/eval_generalization.py --data data/vel --checkpoint "$RUN/$CKPT.pt" --split test \
    --device cuda --output "$RUN/generalization_$CKPT.json" > "$RUN/generalization_$CKPT.stdout" 2>&1
  echo "[v1] evals for $CKPT done at $(date '+%F %T')"
done
echo "[v1] all done" | tee "$RUN/STATUS_DONE.txt"
