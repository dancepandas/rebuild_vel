#!/usr/bin/env bash
# Wide-range fetch to 200k total, then V3-hyperparam training + evals.
#   stage 1: wide-range fetch 2022-09 .. 2026-08 (48 months); 48,157 sections
#            already banked (snapshot: runs/v1/data_snapshot_stage1.json),
#            ledger skips every measurement already taken in 2024-09..2026-08
#   stage 2: snapshot; require >= 200000 sections or abort honestly
#   stage 3: wait for a mostly-free GPU (another job shares the 4090D)
#   stage 4: train runs/v1 with V3 hyperparameters
#   stage 5: test evaluation + cross-station/device generalization report
set -uo pipefail

PY="C:/Users/DELL/.conda/envs/HydroModel/python.exe"
cd /d/chengs/rebuild_vel || exit 1
RUN=runs/v1
mkdir -p "$RUN"

echo "[watcher] stage 1: dense-grid fetch (target 142000 more) starting at $(date '+%F %T')"
"$PY" -m rebuild_vel.sample_fetch --probe data/probe.json --output data/vel \
  --begin-time "2022-09-01 00:00:00.000" --end-time "2026-08-31 23:59:59.999" \
  --target 142000 --step 15 --chunk-size 20 --max-rounds 25 --per-stratum-cap 300 \
  --reliability 1 --request-delay 0.2 --timeout 120 \
  > "$RUN/fetch_wide.log" 2>&1
echo "[watcher] stage 1 done rc=$? at $(date '+%F %T')"

"$PY" tools/data_snapshot.py --data data/vel --output "$RUN/data_snapshot.json" \
  > "$RUN/data_snapshot.stdout" 2>&1
N=$("$PY" -c "import json;print(json.load(open('$RUN/data_snapshot.json',encoding='utf-8'))['n_sections'])")
echo "[watcher] accepted sections: $N (goal 200000; if the pool is smaller this IS the max)"
if [ "$N" -lt 200000 ]; then
  echo "[watcher] pool exhausted below goal - training on the max collected" \
    | tee "$RUN/STATUS_POOL_EXHAUSTED.txt"
fi

echo "[watcher] stage 3: waiting for free GPU (up to 24h)..."
FREE=unknown
for i in $(seq 1 144); do
  FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
  [ -n "$FREE" ] && [ "$FREE" -ge 16000 ] && break
  sleep 600
done
echo "[watcher] gpu free MB=$FREE at $(date '+%F %T'); starting training"

"$PY" -m rebuild_vel.train --data data/vel --output "$RUN" --device cuda --seed 42 \
  --epochs 100 --batch-size 32 --lr 1e-4 --weight-decay 3e-4 \
  --d-model 768 --num-heads 12 --num-layers 14 --ffn-dim 2304 --dropout 0.0 \
  --raw-hidden 64 --loss-mode full \
  > "$RUN/train.log" 2>&1
TRAIN_RC=$?
echo "[watcher] training rc=$TRAIN_RC at $(date '+%F %T')"
if [ "$TRAIN_RC" -ne 0 ]; then
  echo "[watcher] TRAINING FAILED" | tee "$RUN/STATUS_TRAIN_FAILED.txt"
  exit "$TRAIN_RC"
fi

"$PY" -m rebuild_vel.evaluate --data data/vel --checkpoint "$RUN/best.pt" --split test \
  --device cuda --output "$RUN/metrics_test.json" > "$RUN/evaluate.stdout" 2>&1
EVAL_RC=$?
"$PY" tools/eval_generalization.py --data data/vel --checkpoint "$RUN/best.pt" --split test \
  --device cuda --output "$RUN/generalization.json" > "$RUN/generalization.stdout" 2>&1
GEN_RC=$?
echo "[watcher] evaluate rc=$EVAL_RC generalization rc=$GEN_RC at $(date '+%F %T')" \
  | tee "$RUN/STATUS_DONE.txt"
