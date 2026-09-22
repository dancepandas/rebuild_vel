const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  ImageRun, Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType,
} = require("docx");

const SIZES = JSON.parse(
  fs.readFileSync("runs/v1/analysis_3way/report_figs/sizes_all.json", "utf-8"));

const T = (t, o) => new TextRun({ text: t, size: 21, ...(o || {}) });
const B = (t, o) => new TextRun({ text: t, size: 21, bold: true, ...(o || {}) });
const P = (runs, o) => new Paragraph({
  spacing: { after: 100, line: 300 }, ...(o || {}),
  children: (Array.isArray(runs) ? runs : [runs]).map(r => typeof r === "string" ? T(r) : r),
});
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, keepNext: true, spacing: { before: 260, after: 120 }, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, keepNext: true, spacing: { before: 180, after: 100 }, children: [new TextRun(t)] });

const FIG = (file, widthPx, caption) => {
  const norm = file.replace(/\\/g, "/");
  const [w, h] = SIZES[norm] || [1400, 900];
  const MAXW = Math.min(widthPx, 620), MAXH = 700;
  const scale = Math.min(MAXW / w, MAXH / h, 1);
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 140, after: 40 },
      children: [new ImageRun({
        type: "png", data: fs.readFileSync(file),
        transformation: { width: Math.round(w * scale), height: Math.round(h * scale) },
      })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER, spacing: { after: 200 },
      children: [new TextRun({ text: caption, size: 18, color: "595959", italics: true })],
    }),
  ];
};

const tbCell = (text, o = {}) => new TableCell({
  width: { size: o.w || 1500, type: WidthType.DXA },
  shading: o.fill ? { type: ShadingType.CLEAR, fill: o.fill } : undefined,
  margins: { top: 70, bottom: 70, left: 110, right: 110 },
  children: [new Paragraph({
    alignment: o.left ? AlignmentType.LEFT : AlignmentType.CENTER,
    children: [new TextRun({ text, size: o.sz || 18, bold: !!o.head || !!o.bold })],
  })],
});
const tbRow = (cells) => new TableRow({ children: cells });
const TB = (widths, rows) => new Table({
  columnWidths: widths,
  width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
  borders: {
    top: { style: BorderStyle.SINGLE, size: 6, color: "2E5496" },
    bottom: { style: BorderStyle.SINGLE, size: 6, color: "2E5496" },
    left: { style: BorderStyle.SINGLE, size: 2, color: "BBBBBB" },
    right: { style: BorderStyle.SINGLE, size: 2, color: "BBBBBB" },
    insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC" },
    insideVertical: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC" },
  },
  rows,
});

const HEAD = "D9E2F3";

const children = [
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 160, after: 60 },
    children: [new TextRun({ text: "目标变换实验报告", bold: true, size: 40, color: "1F3864" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 80 },
    children: [new TextRun({ text: "Yeo-Johnson 变换对断面流速重建的影响：三臂对照与机制检验", bold: true, size: 23, color: "2E5496" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 260 },
    children: [new TextRun({ text: "2026-09-22  ·  测试集 45,118 断面 / 182.4 万条测速线（站级不相交）  ·  产物 runs/v1/analysis_3way/", size: 19, color: "595959" })],
  }),

  // ---------- 摘要 ----------
  new Table({
    columnWidths: [9360],
    width: { size: 9360, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 12, color: "2E5496" },
      bottom: { style: BorderStyle.SINGLE, size: 12, color: "2E5496" },
      left: { style: BorderStyle.SINGLE, size: 12, color: "2E5496" },
      right: { style: BorderStyle.SINGLE, size: 12, color: "2E5496" },
      insideHorizontal: { style: BorderStyle.NONE }, insideVertical: { style: BorderStyle.NONE },
    },
    rows: [new TableRow({ children: [new TableCell({
      width: { size: 9360, type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill: "EEF3FA" },
      margins: { top: 140, bottom: 140, left: 200, right: 200 },
      children: [
        P([B("摘  要", { size: 24 })], { spacing: { after: 120 } }),
        P([T("① "), B("问题"), T("：重建目标的分布强偏态——偏度 1.281、峰度 +1.325，且 31.0% 是精确零值（枯水线）。对长尾目标做正态化是标准做法，故本轮把目标由 z-score 换成 Box-Cox 族的 "), B("Yeo-Johnson 变换"), T("（该族中唯一能原样容纳精确零值、不需加偏移的成员；实测 λ = −0.0519）。变换后偏度降到 0.265、峰度 −1.313。")]),
        P([T("② "), B("总体结论：变换没有提升总体精度。"), T("在三臂（物理正则 / 纯 L2+z-score / 纯 L2+Yeo-Johnson）同架构、同数据、同划分的对照下，YJ 版最好检查点 RMSE 0.3659，比 z-score 版 0.3419 差 "), B("0.024 m/s"), T("；其 MAE 0.1572 反而是三臂最优。这个组合本身就是结论：变换做的是一次"), B("误差重分配"), T("，不是一次改进。")]),
        P([T("③ "), B("机制被证伪"), T("：开跑前登记的假设是「变换按 Jacobian 权重 w(v)=(dy/dx)² 重新加权 L2」，实测 w(0)=3.77 是 3 m/s 处的 62 倍。实测结果与该假设"), B("方向相反"), T("——Δ过预测率与 w(v) 的相关系数为 "), B("+0.396"), T("（预期为负），权重最大的枯水段几乎没动（−5.3%），权重最小的 [3+) 段反而降得最多（−28.1%）。")]),
        P([T("④ "), B("真实机制是系统性低偏，且幅度随流速放大"), T("：过预测率从 23.3% 降到 14.8%、欠预测率从 14.8% 升到 19.6%，全速度段 bias 一律下移。这不是「按权重选择性地加权」，而是「把回归目标的条件统计量整体向下换了一档」。")]),
        P([T("⑤ "), B("方法学要点：条件集的选择决定结论"), T("。若按速度分段（模型看不到的边际分布）计算「变换空间完美拟合」应给出的值，它只比算术均值低 "), B("0.7%–3%"), T("——量级差十倍，会让人错误地否掉机制；换用"), B("断面"), T("（模型实际的条件集，一次读入整条断面）计算，中位下移 "), B("+8.70%"), T("、p95 "), B("+31.82%"), T("，与实测同量级。同一份数据、同一套公式，仅因条件单元不同，结论就从「无解释力」翻转为「数量级正确」。")]),
        P([T("⑥ "), B("代价发生在高流速段，收益发生在低流速段"), T("：[0.2,0.5) 段 RMSE 由 0.2226 降至 0.1887（改善 15%），[3+) 段由 0.8848 升至 1.0569（恶化 19%）。低流速（<1 m/s）测速线占测试集 "), B("73.5%"), T("，但总体 RMSE 由占 2.6% 的 [3+) 段主导。")]),
        P([T("⑦ "), B("对模型涌现行为的影响是负面的"), T("：本项目最看重的行为——「人工标定近零、但原始观测显著时，模型不盲从人工标定」——在 YJ 版上"), B("减弱"), T("（给出高于人工零标定的比例由 0.909 降到 0.820）。这与③④一致：目标被系统性下压后，模型更倾向停留在近零的标定值上。")]),
        P([T("⑧ "), B("建议"), T("：YJ 版"), B("不作为主模型"), T("（主模型仍为 z-score 纯净版）。变换在低流速段的能力（[0,0.5) 两段 RMSE 均为三臂最优）使其适合作为「低流速优先」场景的可选头，或与 z-score 版做按流速分段的集成。完整复现脚本见附录。")]),
      ],
    })] })],
  }),
  P(" ", { spacing: { after: 60 } }),

  H1("一、问题：为什么要做目标变换"),
  P([T("重建目标（测速线表面流速）的分布是典型的右偏长尾："), B("偏度 1.281、峰度 +1.325，且 31.0% 的样本是精确的 0"), T("（枯水线，98–100% 水深 < 1 cm，是真实物理状态而非缺失值）。对这类目标做正态化再回归，是统计建模的常规做法，通常能改善优化条件与尾部行为。")]),
  P([T("在 Box-Cox 族中选择 Yeo-Johnson，理由是"), B("精确零值"), T("：Box-Cox 要求目标严格为正，遇到 31% 的零值必须加一个 ε 偏移，而那会把一个真实的点质量抹成一段人为的连续区间；Yeo-Johnson 对 x ≥ 0 用分段定义，x = 0 是一个合法且可逆的输入点。实测拟合 "), B("λ = −0.0519"), T("，因 λ 接近 0，正支近似 y ≈ log(1+z)——这一点在下文的机制分析中是关键。")]),
  TB([2400, 2200, 2400, 2360], [
    tbRow([tbCell("划分", { head: true, fill: HEAD, w: 2400 }), tbCell("断面数", { head: true, fill: HEAD, w: 2200 }), tbCell("零值（枯水线）占比", { head: true, fill: HEAD, w: 2400 }), tbCell("目标偏度", { head: true, fill: HEAD, w: 2360 })]),
    tbRow([tbCell("训练", { left: true }), tbCell("148,465"), tbCell("30.96%"), tbCell("1.281 → 0.265")]),
    tbRow([tbCell("验证", { left: true }), tbCell("24,723"), tbCell("27.23%"), tbCell("1.739 → −0.047")]),
    tbRow([tbCell("测试", { left: true }), tbCell("45,118"), tbCell("20.11%"), tbCell("1.664 → 0.390")]),
  ]),
  P([T("表末列「→」后为变换后的偏度。三行的零值占比并不相同——"), B("站级划分使各划分的枯水断面比例本身就有差异（训练 31.0% 对测试 20.1%）"), T("。这是站间的真实差异而非抽样误差（划分按站点均速分层以保证流速分布对齐，但未对齐枯水比例），构成一个跨划分分布偏移，在解读验证—测试差值时必须计入。")]),

  H1("二、实验设定：三臂单一变量"),
  P([T("三臂共用同一架构（82.76M、768/12/14/2304）、同一份数据、同一站级分层划分、同一优化器与超参、seed 42、dropout 0。唯一差异是注意力类型与目标/损失：")]),
  TB([1600, 2600, 2580, 2580], [
    tbRow([tbCell("项", { head: true, fill: HEAD, w: 1600 }), tbCell("物理版 runs/v1", { head: true, fill: HEAD, w: 2600 }), tbCell("纯净 z-score runs/v1_mse", { head: true, fill: HEAD, w: 2580 }), tbCell("纯净 Yeo-Johnson runs/v1_mse_bc", { head: true, fill: HEAD, w: 2580 })]),
    tbRow([tbCell("注意力", { left: true }), tbCell("形态偏置（线距/水深/岸别/坡度四个可学习 β）", { left: true }), tbCell("vanilla attention + RoPE", { left: true }), tbCell("同 z-score", { left: true })]),
    tbRow([tbCell("损失", { left: true }), tbCell("MSE + 五项物理正则（λ=0.05/0.02/0.01/0.02/0.01）", { left: true }), tbCell("纯 L2（mse_only）", { left: true }), tbCell("纯 L2（mse_only）", { left: true })]),
    tbRow([tbCell("目标", { left: true }), tbCell("z-score", { left: true }), tbCell("z-score", { left: true }), tbCell("Yeo-Johnson（λ=−0.0519）后再标准化", { left: true })]),
    tbRow([tbCell("训练轮数", { left: true }), tbCell("ep70 闸门停止", { left: true }), tbCell("ep87 叫停", { left: true }), tbCell("100 / 100 跑满", { left: true })]),
    tbRow([tbCell("最优检查点", { left: true }), tbCell("ep26", { left: true }), tbCell("ep19", { left: true }), tbCell("ep61（物理 RMSE）/ ep100（复合）", { left: true })]),
  ]),

  H1("三、总体结果"),
  P([T("四个检查点（YJ 版两个，因变换使「按训练目标选点」与「按物理 RMSE 选点」分岔）在站级测试集上的结果：")]),
  TB([2200, 1800, 1790, 1790, 1780], [
    tbRow([tbCell("指标", { head: true, fill: HEAD, w: 2200 }), tbCell("物理版 ep26", { head: true, fill: HEAD, w: 1800 }), tbCell("z-score ep19", { head: true, fill: HEAD, w: 1790 }), tbCell("YJ ep61", { head: true, fill: HEAD, w: 1790 }), tbCell("YJ ep100", { head: true, fill: HEAD, w: 1780 })]),
    tbRow([tbCell("RMSE (m/s)", { left: true, bold: true }), tbCell("0.3639"), tbCell("0.3419 ★"), tbCell("0.3659"), tbCell("0.3685")]),
    tbRow([tbCell("MAE (m/s)", { left: true }), tbCell("0.1762"), tbCell("0.1589"), tbCell("0.1602"), tbCell("0.1572 ★")]),
    tbRow([tbCell("NSE", { left: true, bold: true }), tbCell("0.8136"), tbCell("0.8354 ★"), tbCell("0.8115"), tbCell("0.8088")]),
    tbRow([tbCell("bias (m/s)", { left: true }), tbCell("+0.0559"), tbCell("+0.0229"), tbCell("−0.0194 ★"), tbCell("−0.0326")]),
    tbRow([tbCell("剧烈分歧占比 |误差|>0.5", { left: true }), tbCell("8.73%"), tbCell("6.56% ★"), tbCell("7.48%"), tbCell("7.42%")]),
    tbRow([tbCell("大分歧占比 |误差|>1.0", { left: true }), tbCell("2.59%"), tbCell("2.08% ★"), tbCell("2.66%"), tbCell("2.76%")]),
  ]),
  P([T("★ 为该行最优。"), B("YJ 版在 RMSE 上最差、在 MAE 上最好，且大误差占比高于 z-score 版"), T("——这是「把高流速精度换成低流速精度」的典型签名：MAE 对全部测速线等权，RMSE 与大分歧率则由少量高流速线的绝对误差主导。")]),
  P([T("另一处值得注意：YJ 版的两个检查点差异极小（RMSE 0.3659 对 0.3685），说明变换并未显著加剧选点分歧；真正放大分歧的是物理正则臂（z 与 YJ 各自的两个选点标准给出了同一或近乎同一的 epoch）。")]),

  H1("四、机制检验：变换到底做了什么"),
  P([T("本节是本次实验的核心。变换不是一个中性的重参数化——它把目标 y 映射为 φ(y)，于是在 y 空间最小化平方误差，等价于在原空间最小化一个被 Jacobian 加权过的损失：")]),
  P([B("    dL/dv²  ∝  w(v) = (dy/dx)²"), ], { alignment: AlignmentType.CENTER, spacing: { after: 140 } }),
  P([T("对 λ = −0.0519 的拟合，这条权重曲线在实测速度范围内是单调下降的：w(0) = 3.77、w(1) = 0.54、w(3) = 0.06，两端相差 "), B("62 倍"), T("。曲线的拐点 w = 1 恰好落在 v = 0.723 m/s，几乎正是目标的均值 v_mu = 0.7226；训练目标中有 "), B("60.93%"), T(" 落在拐点以下（拿到 >1 的权重），29.27% 在 1 m/s 以上（权重 0.54 或更低）。")]),

  H2("4.1 开跑前登记的假设"),
  P([T("据此登记了一个可证伪的预测："), B("如果变换确实在按 w(v) 重新分配误差，那么 YJ 版应当恰好在 w(v) 大的速度段减少过预测、在 w(v) 小的速度段增加欠预测"), T("。这条预测在训练开始前写入日志，不是事后拟合。")]),

  H2("4.2 检验结果：假设被证伪"),
  ...FIG("runs/v1/analysis_3way/report_figs/fig_weights.png", 620,
    "图 1  (a) 变换给出的损失权重曲面，星号为枯水线 v=0（权重最大 3.77）；(b) 假设检验散点——横轴为该速度段的平均权重，纵轴为过预测率的变化。预期应呈下降趋势，实测 r = +0.396 方向相反；(c) 三臂分速度段偏差。"),
  P([T("检验结论是"), B("证伪"), T("。实测 Δ过预测率与 w(v) 的相关系数为 "), B("+0.396"), T("（预期为负）。逐段看更清楚：")]),
  TB([1600, 1400, 1700, 1900, 1900], [
    tbRow([tbCell("速度段", { head: true, fill: HEAD, w: 1600 }), tbCell("w(v)", { head: true, fill: HEAD, w: 1400 }), tbCell("Δbias (m/s)", { head: true, fill: HEAD, w: 1700 }), tbCell("Δ过预测率", { head: true, fill: HEAD, w: 1900 }), tbCell("该段线数占比", { head: true, fill: HEAD, w: 1900 })]),
    tbRow([tbCell("[0, 0.2)", { left: true }), tbCell("3.538"), tbCell("−0.0216"), tbCell("−5.28%"), tbCell("35.6%")]),
    tbRow([tbCell("[0.2, 0.5)", { left: true }), tbCell("2.245"), tbCell("−0.0449"), tbCell("−9.39%"), tbCell("16.9%")]),
    tbRow([tbCell("[0.5, 1)", { left: true }), tbCell("1.063"), tbCell("−0.0245"), tbCell("−2.97%"), tbCell("21.0%")]),
    tbRow([tbCell("[1, 2)", { left: true }), tbCell("0.312"), tbCell("−0.0167"), tbCell("−2.22%"), tbCell("17.3%")]),
    tbRow([tbCell("[2, 3)", { left: true }), tbCell("0.098"), tbCell("−0.1406"), tbCell("−11.93%"), tbCell("6.6%")]),
    tbRow([tbCell("[3+)", { left: true }), tbCell("0.045"), tbCell("−0.3793"), tbCell("−28.07%"), tbCell("2.6%")]),
  ]),
  P([T("权重最大的 [0, 0.2) 段只降了 5.28%，权重最小的 [3+) 段却降了 28.07%。"), B("变换的效果与它宣称的权重曲面无关，甚至方向相反。")]),

  H2("4.3 实测签名：全段下移，幅度随流速放大"),
  P([T("把六个段的 Δbias 放在一起看，符号全部为负——"), B("每一个速度段的偏差都在往下走"), T("，且下移幅度随流速单调放大（−0.022 → −0.379）。这不是「按权重选择性加权」，而是一次"), B("整体性的向下重标定"), T("。与之吻合的三个全局量：过预测率 23.27% → 14.78%、欠预测率 14.78% → 19.65%、高速线均值预测 2.576 → 2.367（真值 2.758）。模型从系统性偏正，翻转为系统性偏负。")]),

  H2("4.4 正确的条件集：为什么按速度分段会得出错误结论"),
  P([T("要判断「一次系统性下移是否由变换本身导致」，需要先算出「一个在变换空间完美拟合的模型应该预测什么」，即"), B("变换后目标的均值再反变换回 m/s"), T("，并与「物理空间完美拟合应该给出的算术均值」比较。问题出在这个均值按什么条件集来算。")]),
  ...FIG("runs/v1/analysis_3way/report_figs/fig_jensen.png", 620,
    "图 2  (a) 断面级相对下移分布（44,839 个测试断面），中位 +8.70%；(b) 按断面均速分层，[1,2) 段下移最大（14.4%）；(c) 断面内枯水线占比与下移幅度正相关（r = +0.357）。"),
  TB([2600, 2100, 2100, 2560], [
    tbRow([tbCell("条件集", { head: true, fill: HEAD, w: 2600 }), tbCell("相对下移中位", { head: true, fill: HEAD, w: 2100 }), tbCell("p95", { head: true, fill: HEAD, w: 2100 }), tbCell("与实测是否同量级", { head: true, fill: HEAD, w: 2560 })]),
    tbRow([tbCell("按速度分段（边际分布）", { left: true }), tbCell("0.7% – 3.0%"), tbCell("—"), tbCell("否，差约 10 倍", { left: true })]),
    tbRow([tbCell("按断面（模型实际的条件集）", { left: true }), tbCell("+8.70%"), tbCell("+31.82%"), tbCell("是", { left: true })]),
  ]),
  P([T("同一个公式，两种条件集，结论从「完全解释不了」变成「数量级正确」。原因是："), B("一个速度段内部的目标分布本来就很窄，变换的凹性几乎没有可作用的空间"), T("（所以分段边际只给出 1–3%）；而模型一次读入的是整条断面，断面内 31% 是枯水线、其余分布右偏，条件分布很宽，凹性得以充分放大。")]),
  P([T("补充：断面级下移与断面内枯水线占比正相关（r = +0.357），与断面均速亦正相关（r = +0.241），峰值出现在 [1,2) 段（14.4%）。这解释了为什么实测偏差在高流速段恶化最重——那一带的条件分布最偏、可作用空间最大。")]),
  P([T("需要说明的是，这只确立了"), B("方向与数量级"), T("，不是逐段精确预测：断面级下移是一个「完美拟合应给出的差额」的上界型量，而实测 Δbias 是两个真实模型之间的差，其中 z-score 版本身也带有偏置。把变换效应与「另一次训练收敛到另一个局部最优」完全分离，单次训练做不到。")]),

  H1("五、误差结构的重分配"),
  ...FIG("runs/v1/analysis_3way/report_figs/fig_three_arm_bins.png", 620,
    "图 3  (a) 三臂分速度段 RMSE——物理版占据中高流速段，两种纯净版占据低速段，z-score 在 [2,3) 最优；(b) 各速度段在测试集中的占比，低流速（<1 m/s）合计 73.5%。"),
  TB([1700, 1750, 1750, 1750, 2410], [
    tbRow([tbCell("速度段", { head: true, fill: HEAD, w: 1700 }), tbCell("物理版", { head: true, fill: HEAD, w: 1750 }), tbCell("z-score", { head: true, fill: HEAD, w: 1750 }), tbCell("YJ ep61", { head: true, fill: HEAD, w: 1750 }), tbCell("占优方", { head: true, fill: HEAD, w: 2410 })]),
    tbRow([tbCell("[0, 0.2)", { left: true }), tbCell("0.3965"), tbCell("0.3508"), tbCell("0.3427"), tbCell("YJ（0.3416 @ep100）", { left: true })]),
    tbRow([tbCell("[0.2, 0.5)", { left: true }), tbCell("0.3036"), tbCell("0.2226"), tbCell("0.1992"), tbCell("YJ，改善 15%（对 z）", { left: true })]),
    tbRow([tbCell("[0.5, 1)", { left: true }), tbCell("0.2040"), tbCell("0.2051"), tbCell("0.2170"), tbCell("物理版", { left: true })]),
    tbRow([tbCell("[1, 2)", { left: true }), tbCell("0.3082"), tbCell("0.3308"), tbCell("0.3664"), tbCell("物理版", { left: true })]),
    tbRow([tbCell("[2, 3)", { left: true }), tbCell("0.5098"), tbCell("0.5050"), tbCell("0.5945"), tbCell("z-score", { left: true })]),
    tbRow([tbCell("[3+)", { left: true }), tbCell("0.8485"), tbCell("0.8848"), tbCell("1.0569"), tbCell("物理版，YJ 恶化 19%", { left: true })]),
  ]),
  P([T("三臂呈现清晰的分工："), B("物理版在中高流速段最强（[0.5,1)、[1,2)、[3+) 三段最优），两种纯净版在低速段最强，z-score 版总体最优"), T("。这本身是一个有用的结论——形态先验（水深、岸别、坡度）在高流速段提供的信息量，是 RoPE 位置编码替代不了的；而物理正则带来的回归趋中，在低速段是纯粹的负担。")]),
  P([T("零速线专项（目标恰为 0 的 366,903 条线）需要单独澄清，它并不支持「变换把容量推向了枯水线」这一直觉：")]),
  TB([2600, 2200, 2200, 2360], [
    tbRow([tbCell("零速线指标", { head: true, fill: HEAD, w: 2600 }), tbCell("物理版", { head: true, fill: HEAD, w: 2200 }), tbCell("z-score", { head: true, fill: HEAD, w: 2200 }), tbCell("YJ ep100", { head: true, fill: HEAD, w: 2360 })]),
    tbRow([tbCell("RMSE (m/s)", { left: true }), tbCell("0.1989 ★"), tbCell("0.2520"), tbCell("0.2385")]),
    tbRow([tbCell("平均预测 (m/s)", { left: true }), tbCell("0.0268 ★"), tbCell("0.0484"), tbCell("0.0319")]),
    tbRow([tbCell("预测 >0.1 的占比", { left: true }), tbCell("3.67%"), tbCell("5.48%"), tbCell("2.93% ★")]),
  ]),
  P([T("YJ 把「枯水线被虚增到 0.1 m/s 以上」的发生率压到最低（2.93% 对 z 的 5.48%），但枯水线的"), B("误差量级"), T("仍是物理版最优（0.1989 对 0.2385）。也就是说：变换降低的是枯水线过预测的"), B("频次"), T("，而物理先验降低的是过预测的"), B("幅度"), T("。两者不可互相替代。")]),

  H1("六、对模型涌现行为的影响"),
  P([T("本项目此前量化的三项涌现行为（B1 高流速压制、B2 零标定流速恢复、B3 矛盾线融合位置）在 YJ 版上的变化如下。这三项是模型价值叙事的主体，它们的变化比总体指标更能说明变换的实际后果。")]),
  TB([3200, 1700, 1700, 2540], [
    tbRow([tbCell("行为", { head: true, fill: HEAD, w: 3200 }), tbCell("z-score", { head: true, fill: HEAD, w: 1700 }), tbCell("YJ", { head: true, fill: HEAD, w: 1700 }), tbCell("样本量 / 方向", { head: true, fill: HEAD, w: 2540 })]),
    tbRow([tbCell("B1 高流速压制：观测≥3 m/s 的线，重建均值/观测均值", { left: true }), tbCell("0.574"), tbCell("0.508"), tbCell("97,842 条线 / 压制更强", { left: true })]),
    tbRow([tbCell("B2 零标定流速恢复：目标≤0.2 而观测≥0.5，重建均值/观测均值", { left: true }), tbCell("0.406"), tbCell("0.395"), tbCell("52,978 条线 / 恢复更弱", { left: true })]),
    tbRow([tbCell("B2 给出高于人工零标定的比例", { left: true }), tbCell("0.909"), tbCell("0.820"), tbCell("越低越「盲从标定」", { left: true })]),
    tbRow([tbCell("B3 矛盾线融合位置中位数（0=目标，1=观测）", { left: true }), tbCell("0.187"), tbCell("0.251"), tbCell("164,462 条线 / 更靠观测", { left: true })]),
  ]),
  P([B("行为二的变化最需要关注，且方向不利。"), T("B2 描述的是本模型最受重视的一种表现：人工标定把整条断面标成近零、而原始观测显示显著流速时，模型"), B("不盲从人工标定"), T("。z-score 版在 90.9% 的这类线上给出了高于人工零标的预测；YJ 版降到 82.0%。")]),
  P([T("这与第四节的机制完全自洽：变换把目标整体向下换了一档，模型在「跟人工标定」和「跟原始观测」之间的平衡点也随之向标定一侧偏移。换言之，"), B("在总量指标上看似只是「高流速换低流速」的取舍，在行为层面表现为削弱了模型最有价值的那个特性。")]),
  P([T("B1 与 B3 的变化方向与之相反：YJ 版的压制更强（0.508 对 0.574，重建更远离被高估的原始观测）、矛盾线的融合位置更靠观测（0.251 对 0.187）。B1 与 B2 是一对张力——更强的压制意味着对真实高流速测次也压得更多，这既解释了 [3+) 段的恶化，也说明这三个行为量必须联合解读，不能单独取其一作为「变好」的证据。")]),

  H1("七、结论与建议"),
  H2("7.1 结论"),
  P([B("结论 1（总体）：目标变换未提升总体精度。"), T("YJ 版最好检查点 RMSE 0.3659，较 z-score 版 0.3419 差 0.024 m/s（约 7%），大误差占比亦更高（|误差|>1.0 为 2.76% 对 2.08%）。其 MAE 0.1572 为三臂最优，证实这是一次误差重分配而非改进。")]),
  P([B("结论 2（机制）：变换的作用不是 Jacobian 加权，而是系统性低偏。"), T("开跑前登记的可证伪假设被实测证伪（Δ过预测率与 w(v) 相关系数 +0.396，预期为负）。实测签名是全部速度段一律下移、幅度随流速放大，等价于把回归目标的条件统计量整体下移一档。")]),
  P([B("结论 3（方法）：条件集的选择决定机制检验的成败。"), T("同一套「变换空间完美拟合应给出什么」的计算，按速度分段（边际）得到 0.7–3%，会得出「变换无解释力」的错误结论；按断面（模型实际条件集）得到中位 +8.70%、p95 +31.82%，与实测同量级。做此类机制归因时，条件单元必须与模型的实际上下文一致。")]),
  P([B("结论 4（收益区间）：变换的能力集中在低流速段。"), T("[0,0.2) 与 [0.2,0.5) 两段 RMSE 均为三臂最优，[0.2,0.5) 段较 z-score 改善 15%；枯水线被虚增到 0.1 m/s 以上的发生率降至 2.93%（三臂最低）。")]),
  P([B("结论 5（行为）：变换削弱了模型最受重视的涌现行为。"), T("「不盲从人工近零标定」的比例由 0.909 降至 0.820。若该行为是交付叙事的一部分，变换的代价不止于 RMSE。")]),
  H2("7.2 建议"),
  P([T("① "), B("主模型维持 z-score 纯净版"), T("（总体 RMSE、NSE、大误差占比、涌现行为四项均为最优或接近最优）。")]),
  P([T("② "), B("变换版定位为「低流速优先」的可选头"), T("：在枯水期与低流速监测场景（<0.5 m/s 测速线占测试集 52.5%），YJ 版的误差明显更低，可作为该场景的替代模型或与主模型做按流速分段的集成。")]),
  P([T("③ "), B("若目标是提升高流速精度，方向不在目标变换"), T("：变换在 [3+) 段带来 19% 的恶化。物理版在该段最优（0.8485），提示形态先验是更有效的抓手；此前提出的高流速段过采样/分层加权仍是正确的方向。")]),
  P([T("④ "), B("站级划分应同时对齐枯水比例"), T("：训练/验证/测试的零值占比为 31.0% / 27.2% / 20.1%，构成一个未被控制的分布偏移。建议在 station 分层时把「枯水线占比」加入分层变量，否则验证选点与测试表现之间会存在系统性落差（本轮 YJ 版验证 RMSE 0.2941 与 z-score 版 0.2940 几乎相同，测试 RMSE 却相差 0.024，与该偏移吻合）。")]),

  H1("附录 A  评测口径与复现"),
  P([T("测试集为 40 个训练全程未见的站、45,118 断面、1,824,298 条测速线。所有跨模型比较一律使用物理单位（m/s）：YJ 版的归一化 RMSE 位于变换空间，与 z-score 版的归一化量不可直接比较，本报告未使用该项。零速线指目标恰为 0 的线；高速线指目标 ≥2 m/s；剧烈分歧指 |预测−目标| > 0.5 m/s。")]),
  P([T("复现脚本（依执行顺序）：tools/transform_fingerprint.py（预登记假设检验）、tools/jensen_gap.py（断面级条件集计算）、tools/transform_bias_prediction.py（分段边际对照）、tools/jensen_test.py（模型预测 vs 两种参考均值）、tools/transform_report_figs.py（本报告图件）、tools/deep_compare.sh（四检查点全量对比）。原始输出见 runs/v1/analysis_3way/。")]),
  P([T("诚实记录：全部训练过程、被证伪的中间假设（含一处我此前基于前 34 个 epoch 得出的「z-score 偏差全程稳定在 +0.03」的错误结论，在拉取全 87 轮后被更正为「z 的偏差也在缓慢收敛，只是比 YJ 慢」）、以及分析口径的修订，均记于 runs/v1/journal.md。",
    { italics: true, color: "595959", size: 19 })], { spacing: { before: 200 } }),
];

const doc = new Document({
  styles: {
    default: {
      heading1: { run: { size: 28, bold: true, color: "1F3864", font: "Microsoft YaHei" } },
      heading2: { run: { size: 24, bold: true, color: "2E5496", font: "Microsoft YaHei" } },
    },
  },
  sections: [{ properties: {}, children }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync("runs/v1/YJ目标变换实验报告.docx", buf);
  console.log("written runs/v1/YJ目标变换实验报告.docx");
});
