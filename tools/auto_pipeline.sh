#!/usr/bin/env bash
# Autonomous joint pipeline:
#   stage 1: resume dense-grid fetch NOW (GPU is held by other jobs anyway)
#   stage 2: poll GPU; when >=16GB free, pause fetch, snapshot, train+evals
#            (expandable_segments guards against allocator fragmentation)
#   stage 3: resume fetch for the night; final snapshot; STATUS_DONE
set -uo pipefail

PY="C:/Users/DELL/.conda/envs/HydroModel/python.exe"
cd /d/chengs/rebuild_vel || exit 1
RUN=runs/v1
mkdir -p "$RUN"

FETCH_ARGS=(--probe data/probe.json --output data/vel
  --begin-time "2022-09-01 00:00:00.000" --end-time "2026-08-31 23:59:59.999"
  --target 100000 --step 15 --chunk-size 20 --max-rounds 25 --per-stratum-cap 300
  --reliability 1 --request-delay 0.2 --timeout 120)

echo "[auto] stage 1: resume fetch at $(date '+%F %T')"
"$PY" -m rebuild_vel.sample_fetch "${FETCH_ARGS[@]}" > "$RUN/fetch_auto.log" 2>&1 &
FPID=$!

TRAINED=0
for i in $(seq 1 216); do   # up to 36h of waiting for the GPU
  sleep 600
  FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
  echo "[auto] poll $i: gpu free ${FREE:-?} MB at $(date '+%T')"
  if [ -n "$FREE" ] && [ "$FREE" -ge 16000 ]; then
    echo "[auto] GPU free; pausing fetch (pid $FPID) and starting training"
    kill "$FPID" 2>/dev/null
    sleep 5
    "$PY" tools/data_snapshot.py --data data/vel \
      --output "$RUN/data_snapshot_train2.json" > /dev/null 2>&1
    export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
    "$PY" -m rebuild_vel.train --data data/vel --output "$RUN" --device cuda --seed 42 \
      --epochs 100 --batch-size 32 --lr 5e-5 --weight-decay 3e-4 \
      --d-model 768 --num-heads 12 --num-layers 14 --ffn-dim 2304 --dropout 0.0 \
      --raw-hidden 64 --loss-mode full \
      > "$RUN/train.log" 2>&1
    TRAIN_RC=$?
    echo "[auto] training rc=$TRAIN_RC at $(date '+%F %T')"
    if [ "$TRAIN_RC" -eq 0 ]; then
      for CKPT in best best_by_rmse; do
        "$PY" -m rebuild_vel.evaluate --data data/vel --checkpoint "$RUN/$CKPT.pt" \
          --split test --device cuda --output "$RUN/metrics_test_$CKPT.json" \
          > "$RUN/evaluate_$CKPT.stdout" 2>&1
        "$PY" tools/eval_generalization.py --data data/vel --checkpoint "$RUN/$CKPT.pt" \
          --split test --device cuda --output "$RUN/generalization_$CKPT.json" \
          > "$RUN/generalization_$CKPT.stdout" 2>&1
      done
      TRAINED=1
      echo "[auto] train+evals done at $(date '+%F %T')"
    else
      echo "[auto] TRAINING FAILED" | tee "$RUN/STATUS_TRAIN_FAILED.txt"
    fi
    break
  fi
done

if [ "$TRAINED" -eq 0 ]; then
  echo "[auto] GPU never freed within wait window - skipping training" \
    | tee "$RUN/STATUS_GPU_NEVER_FREED.txt"
fi

echo "[auto] stage 3: resume fetch for the night at $(date '+%F %T')"
"$PY" -m rebuild_vel.sample_fetch "${FETCH_ARGS[@]}" > "$RUN/fetch_night.log" 2>&1
echo "[auto] night fetch exited at $(date '+%F %T')"
"$PY" tools/data_snapshot.py --data data/vel --output "$RUN/data_snapshot.json" \
  > "$RUN/data_snapshot.stdout" 2>&1
echo "[auto] final snapshot: $( "$PY" -c "import json;print(json.load(open('$RUN/data_snapshot.json',encoding='utf-8'))['n_sections'])" ) sections"
echo "[auto] all done" | tee "$RUN/STATUS_DONE.txt"
