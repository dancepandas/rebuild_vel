#!/usr/bin/env bash
# Converged / best-checkpoint comparison for the transform study.
#
# The chain's first pass compared phys vs z(ep19) vs YJ(ep100).  Two fixes:
#   * the fingerprint's base/treated pairing was phys->YJ; the question is
#     z->YJ, so it is re-run here;
#   * YJ has two legitimate representatives (ep61 selected on physical val
#     RMSE, ep100 selected on the composite objective).  Both are carried.
set -uo pipefail

PY="C:/Users/DELL/.conda/envs/HydroModel/python.exe"
cd /d/chengs/rebuild_vel || exit 1
OUT=runs/v1/analysis_3way

echo "[deep] fingerprint z->YJ(ep61) at $(date '+%F %T')"
"$PY" tools/transform_fingerprint.py --data data/vel --device cuda \
  --checkpoint runs/v1_mse/best.pt:z \
  --checkpoint runs/v1_mse_bc/best.pt:YJep100 \
  --checkpoint runs/v1_mse_bc/best_by_rmse.pt:YJep61 \
  --output "$OUT/fingerprint_z_yj61.json" \
  --figure "$OUT/figs_yj/fingerprint_z_yj61.png" > "$OUT/fingerprint_z_yj61.stdout" 2>&1 \
  && echo "[deep] fingerprint OK" || echo "[deep] fingerprint FAILED"

echo "[deep] comparison all-best at $(date '+%F %T')"
"$PY" tools/compare_models.py --data data/vel --device cuda \
  --checkpoint runs/v1/attempt5_ep70gate/best.pt:phys \
  --checkpoint runs/v1_mse/best.pt:z \
  --checkpoint runs/v1_mse_bc/best_by_rmse.pt:YJep61 \
  --checkpoint runs/v1_mse_bc/best.pt:YJep100 \
  --output "$OUT/comparison_allbest.json" > "$OUT/comparison_allbest.stdout" 2>&1 \
  && echo "[deep] comparison OK" || echo "[deep] comparison FAILED"

echo "[deep] all done at $(date '+%F %T')" | tee "$OUT/STATUS_DEEP_DONE.txt"
