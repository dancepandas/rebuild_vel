# Aether — 从原始分段流速重建测速线表面流速

输入：一次测流的完整原始数据（每条测速线 10 个视频分段的原始流速、断面几何、水位）。
输出：每条测速线的表面流速（监督目标 = 平台处理链产物）。
模型：形态偏置 Transformer Encoder（设计继承自 `vmodel/section_pretrain` V3 预训练项目），
Aether 系列三臂：P（物理约束，主模型）/ M（纯净版）/ Y（Yeo-Johnson 变换）。

**刻意不用的信息**（依据实测与 V3 报告结论）：
- 置信度（平台的置信度判据会失效，如"31.6% 分段超 max 但真值占比判 0.88 全站最高"）
- 流速来源标志（算法/插值是处理链内部产物，无重建信息量）

## 环境

```bash
conda activate vmodel        # torch 2.7.1+cu126, requests/pandas/numpy/openpyxl/matplotlib
export PYTHONPATH=<项目根目录>
```

## 流程

### 1. 抓数（增量、可断点续跑）

```bash
python -m rebuild_vel.fetch \
  --begin-time "2025-09-01 00:00:00.000" --end-time "2026-08-31 23:59:59.999" \
  --output data/year \
  --chunk-size 20
# 可选: --stations 00620,00319  --max-measurements N  --accounts-file accounts.json
```

- 站码/设备目录来自 `F:\测算一体预报智能体\read_data\` 下两份 CSV，可用 `--station-info/--flow-config` 覆盖
- 每 20 个测次调用一次 `/flow/procedureDataMergeExport`，解析后按设备写入
  `data/year/sections/{station}_{device}.pkl`；进度在 `ledger.jsonl`，重跑自动跳过已完成测次
- 无过程数据文件的设备自动熔断（`no_procedure_data` 记入 rejected.jsonl）
- 质控（`quality.py`）：线数≥8、严格递增起点距、目标流速≤5.633 m/s、零值占比、
  必须含算法给出线；不合格留痕 rejected.jsonl

### 2. 训练

```bash
python -m rebuild_vel.train --data data/year --output runs/year --device cuda \
  --epochs 40 --batch-size 32 --d-model 256 --num-heads 8 --num-layers 6
# 服务器大配置: --d-model 768 --num-heads 12 --num-layers 14 --ffn-dim 2304
```

- 站级划分（70/15/15, seed 42），归一化统计只用训练集
- AdamW + warmup/余弦，有效批 32，梯度裁剪 1.0
- 损失 = 全断面 MSE + 物理正则(smooth 0.15/depth_corr 0.10/bank 0.08/bank_zero 0.06/grad_smooth 0.05)
- checkpoint: best.pt（按验证集）/ last.pt；config.json 含归一化统计

### 3. 评估

```bash
python -m rebuild_vel.evaluate --data data/year --checkpoint runs/year/best.pt \
  --split test --device cuda --output runs/year/metrics.json
```

- 指标：RMSE/MAE/bias/NSE（物理单位），全量 + 按线来源分组（仅诊断，不进模型）
- 基线：原始分段中位数、截尾均值（99.5 分位截断）；skill = 1 − RMSE_model/RMSE_baseline

### 4. 冒烟

```bash
python -m rebuild_vel.smoke --data data/year   # 合成batch前后向/填充不变性/迷你训练
```

### 5. 展示面板与对外推理接口

```bash
python web/server.py --port 8760     # LAN 面板 + JSON API
```

- 面板：站点/测次选择（已入库 + 实时双通道）、断面重建图、Aether-P/M/Y 三臂对照、
  残差条带、读数表；接口文档见 `web/static/api_docs.html`
- 对外推理：`POST /api/reconstruct`（JSON 断面 → 各臂重建流速，含枯水线阀门与
  细分拒绝码；阀门将水深 ≤ 0 的测速线重建值强制归零）

## 已知数据事实（探测所得）

- 过程数据 xlsx 含 5 个表：水位流量 / 测速线流速(目标) / STIV 原始分段(主输入) /
  光流轨迹法 / 光流法（后两者仅光流场模式设备非空）
- STIV 原始表：每场每线 10 个视频分段（30s 一段），含原始流速/水深/置信度/流向夹角/
  像素长度/物理长度/识别角度
- 部分老设备（如 00060/00063 的 V4.6.x）全程无过程数据文件，抓不到原始分段
- `speedLineDataExport` 导出接口的"测速线原始流速"列全表为 0.00，不可用；
  原始数据只能走 `procedureDataMergeExport`
