const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  ImageRun, Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType,
} = require("docx");

const SIZES = JSON.parse(fs.readFileSync("runs/v1/report_figs/sizes.json", "utf-8"));

const T = (t, o) => new TextRun({ text: t, size: 21, ...(o || {}) });
const B = (t, o) => new TextRun({ text: t, size: 21, bold: true, ...(o || {}) });
const P = (runs, o) => new Paragraph({
  spacing: { after: 100, line: 300 }, ...(o || {}),
  children: (Array.isArray(runs) ? runs : [runs]).map(r => typeof r === "string" ? T(r) : r),
});
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 260, after: 120 }, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 180, after: 100 }, children: [new TextRun(t)] });

const FIG = (file, widthPx, caption) => {
  const norm = file.replace(/\\/g, "/");
  const [w, h] = SIZES[norm] || SIZES[norm.split("/").pop()] || [1400, 900];
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER, spacing: { before: 140, after: 40 },
      children: [new ImageRun({
        type: "png", data: fs.readFileSync(file),
        transformation: { width: widthPx, height: Math.round(widthPx * h / w) },
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
    children: [new TextRun({ text, size: 19, bold: !!o.head || !!o.bold })],
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

const children = [
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 160, after: 60 },
    children: [new TextRun({ text: "测速线表面流速重建模型 V1 最终报告", bold: true, size: 40, color: "1F3864" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 80 },
    children: [new TextRun({ text: "物理正则版 vs 纯净基线（RoPE + 纯 L2）对照评测", bold: true, size: 24, color: "2E5496" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 260 },
    children: [new TextRun({ text: "2026-09-21  ·  数据 218,306 断面（221 站）· 站级分层划分  ·  测试集 40 站 / 182.4 万条测速线  ·  日志 runs/v1/journal.md", size: 19, color: "595959" })],
  }),

  // 摘要
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
        P([T("① "), B("单一变量对照"), T("：两版模型同架构（82.76M）、同数据（218,306 断面）、同站级分层划分，仅两处不同——物理版的形态偏置注意力 + MSE+五项物理正则，对照版的 RoPE 位置编码 + 纯 L2。")]),
        P([T("② "), B("总体"), T("：纯净版全面占优——RMSE 0.342 对 0.364（好 6.0%），NSE 0.835 对 0.814，bias 0.023 对 0.056；对原始观测中位数基线的 skill 0.553 对 0.524。")]),
        P([T("③ "), B("误差结构"), T("：物理版的回归趋中被证实并部分归因于物理正则——纯净版在低速段 [0.2,0.5) 的 bias 从 +0.164 降至 +0.073，高速段(≥2 m/s)严重低估占比从 18.4% 降至 15.3%，剧烈分歧（|误差|>0.5 m/s）占比从 8.7% 降至 6.6%。")]),
        P([T("④ "), B("物理先验的守护价值"), T("：在观测薄弱的场景物理版反而更稳——零速枯水线 RMSE 0.199 对 0.252、光流-only 测次 RMSE 0.281 对 0.471。物理项充当了「观测不可信时的兜底先验」。")]),
        P([T("⑤ "), B("共同短板"), T("：两版的最优验证 epoch 都停在早期（ep26 / ep19）后进入长平台，且高速段（≥3 m/s）RMSE 均在 0.85+——高速与观测-目标矛盾样本是下一阶段的重点。")]),
      ],
    })] })],
  }),
  P(" ", { spacing: { after: 60 } }),

  H1("一、任务与数据"),
  P([T("模型从原始分段流速观测（STIV 30 秒视频段 / 光流区域估计）重建断面各测速线表面流速。数据池 "), B("218,306 条质检通过断面"),
     T("（221 站 / 254 设备，2024-09 – 2026-08 为主，reliability=1）。每断面测速线中位 35 条，每线原始观测中位 10 个。")]),
  P([T("划分采用"), B("站级分层"), T("（按站点均速分位切 10 层、层内 70/15/15），站间不相交。修正动因：随机站划分曾把偏快河段集中分入测试集（流速中位 0.737 对训练 0.429），分层后测试集中位回到 0.441。全库 25% 分位流速恰为 0，诊断为「枯水线」（98–100% 水深<1cm）的真实物理规律，训练全部保留。")]),

  H1("二、两版设定（单一变量对照）"),
  TB([1800, 3780, 3780], [
    tbRow([tbCell("项", { head: true, fill: "D9E2F3", w: 1800 }), tbCell("物理版（runs/v1）", { head: true, fill: "D9E2F3", w: 3780 }), tbCell("纯净版（runs/v1_mse）", { head: true, fill: "D9E2F3", w: 3780 })]),
    tbRow([tbCell("注意力", { left: true }), tbCell("形态偏置（线距/水深/岸别/坡度四个可学习 β）", { left: true }), tbCell("vanilla attention + RoPE 位置编码（q/k 按绝对位置旋转）", { left: true })]),
    tbRow([tbCell("损失", { left: true }), tbCell("全断面 MSE + 五项物理正则（λ=0.05/0.02/0.01/0.02/0.01）", { left: true }), tbCell("纯 L2（mse_only）", { left: true })]),
    tbRow([tbCell("其余", { left: true }), tbCell("同架构 82.76M（768/12/14/2304）、同分层划分、AdamW lr 5e-5、batch 32、100 epoch 预算、dropout 0、seed 42", { left: true }), tbCell("同左", { left: true })]),
    tbRow([tbCell("实际停止", { left: true }), tbCell("ep70 闸门触发（best 停在 ep26，44 epoch 无新最优），存档 attempt5_ep70gate", { left: true }), tbCell("ep87 用户叫停（best 停在 ep19），检查点已留存", { left: true })]),
    tbRow([tbCell("训练时长", { left: true }), tbCell("约 9.5 h（490 s/epoch）", { left: true }), tbCell("约 8 h（351 s/epoch）", { left: true })]),
  ]),

  H1("三、总体结果"),
  P([T("检查点取验证 RMSE 最优的 ep26（物理版）/ ep19（纯净版）。站级测试集（40 站、182.4 万条测速线，训练全程未见）总体："),
     B("物理版 RMSE 0.364 / NSE 0.814 / bias +0.056；纯净版 RMSE 0.342 / NSE 0.835 / bias +0.023"), T("。")]),
  ...FIG("runs/v1_mse/report_figs/fig_density.png", 430,
    "图 1  纯净版重建流速 vs 目标流速密度图（测试集全量 182 万线，对数色标）。主对角带紧密；虚线 y=x，灰带 ±0.3 m/s。"),
  TB([2600, 2250, 2250, 2260], [
    tbRow([tbCell("指标", { head: true, fill: "D9E2F3", w: 2600 }), tbCell("物理版", { head: true, fill: "D9E2F3", w: 2250 }), tbCell("纯净版", { head: true, fill: "D9E2F3", w: 2250 }), tbCell("原始中位数基线", { head: true, fill: "D9E2F3", w: 2260 })]),
    tbRow([tbCell("RMSE (m/s)", { left: true, bold: true }), tbCell("0.364"), tbCell("0.342"), tbCell("0.764")]),
    tbRow([tbCell("MAE (m/s)", { left: true }), tbCell("0.176"), tbCell("0.159"), tbCell("0.266")]),
    tbRow([tbCell("NSE", { left: true, bold: true }), tbCell("0.814"), tbCell("0.835"), tbCell("0.178")]),
    tbRow([tbCell("bias (m/s)", { left: true }), tbCell("+0.056"), tbCell("+0.023"), tbCell("+0.020")]),
    tbRow([tbCell("skill vs 中位数基线", { left: true }), tbCell("0.524"), tbCell("0.553"), tbCell("—")]),
  ]),
  P([T("两版都把「直接取原始观测中位数」的误差砍掉一半以上。纯净版总体 RMSE 再比物理版低 "),
     B("6.0%"), T("，且 bias 减半——去掉了物理正则对零速/低速的抬升效应后，整体预测更贴近目标。")]),

  H1("四、误差结构：分速度段拆解"),
  TB([2000, 1900, 1900, 1900, 1660], [
    tbRow([tbCell("目标速度段", { head: true, fill: "D9E2F3", w: 2000 }), tbCell("RMSE 物理 / 纯净", { head: true, fill: "D9E2F3", w: 1900 }), tbCell("bias 物理 / 纯净", { head: true, fill: "D9E2F3", w: 1900 }), tbCell("线数", { head: true, fill: "D9E2F3", w: 1900 }), tbCell("占优方", { head: true, fill: "D9E2F3", w: 1660 })]),
    tbRow([tbCell("[0, 0.2)", { left: true }), tbCell("0.397 / 0.351"), tbCell("+0.132 / +0.112"), tbCell("318k"), tbCell("纯净")]),
    tbRow([tbCell("[0.2, 0.5)", { left: true }), tbCell("0.304 / 0.223"), tbCell("+0.164 / +0.073"), tbCell("330k"), tbCell("纯净（大幅）")]),
    tbRow([tbCell("[0.5, 1)", { left: true }), tbCell("0.204 / 0.205"), tbCell("+0.067 / +0.011"), tbCell("334k"), tbCell("纯净（bias）")]),
    tbRow([tbCell("[1, 2)", { left: true }), tbCell("0.308 / 0.331"), tbCell("−0.060 / −0.089"), tbCell("313k"), tbCell("物理")]),
    tbRow([tbCell("[2, 3)", { left: true }), tbCell("0.510 / 0.505"), tbCell("−0.208 / −0.164"), tbCell("107k"), tbCell("纯净（bias）")]),
    tbRow([tbCell("[3+)", { left: true }), tbCell("0.849 / 0.885"), tbCell("−0.360 / −0.228"), tbCell("22k"), tbCell("物理")]),
  ]),
  P([T("用户此前的诊断「实测 0 处预测偏大、实测大处预测偏小」在物理版上完全成立，且"), B("主要元凶是物理正则"),
     T("：纯净版把 [0.2,0.5) 段的正偏置砍掉一半以上，高速段严重低估占比从 18.4% 降至 15.3%。但物理项并非一无是处——它把纯零速线的 RMSE 压到 0.199（纯净版 0.252，零速线平均预测 0.027 对 0.048），并显著改善光流-only 测次（0.281 对 0.471）。")]),

  H1("五、跨站 / 跨设备 / 分源泛化"),
  ...FIG("runs/v1/report_figs/fig_by_station.png", 620,
    "图 2  物理版各测试站 RMSE（左，红=RMSE>0.8）与 NSE（右，灰=近常数站指标退化，†标记）。两版跨站分布形态相似；纯净版中位 RMSE 0.263 更好，但 p90 0.677 更差。"),
  P([T("站级中位：物理版 RMSE 0.289 / NSE 0.744；纯净版 RMSE 0.263 / NSE 0.637。纯净版中位 RMSE 更好但 "), B("NSE 中位反而更低"),
     T("，且 p90（0.677 对 0.464）更差——它的误差分布更两极：多数站更好，少数站（观测薄弱型）更差。最差站两版一致：站 00423（RMSE 1.14 / 1.17）与站 00156（0.98 / 1.03），后者即「原始观测 8+ m/s、目标 0.1」的观测-目标矛盾站（原始 STIV 超出河流物理上限，详见 journal）。")]),
  P([B("分源是两版最大的分野："), T("光流-only 测次物理版 RMSE 0.281 / NSE 0.846，纯净版 0.471 / 0.567。解释：物理版的形态偏置注意力把「水深、岸别、坡度」的结构先验直接注入注意力，在原始观测稀疏（光流-only 每线常只有 1 个估计）时兜底；纯净版只能依赖 RoPE 与嵌入里的形态通道，观测一弱就漂。STIV 测次（占 98.9%）纯净版反而更好（0.341 对 0.364）。")]),

  H1("六、断面重建案例"),
  ...FIG("runs/v1/report_figs/fig_sections.png", 600,
    "图 1  物理版：最好 / 中位 / 最差（观测-目标矛盾）/ 枯水 / 光流-only 五类断面。枯水区预测≈0，「没水→流速 0」规律已学会。"),
  ...FIG("runs/v1_mse/report_figs/fig_sections.png", 600,
    "图 2  纯净版：同五类断面。低速段跟随更紧，但枯水区偶有 0.1–0.2 m/s 的虚增速（物理版没有）。"),

  H1("七、结论"),
  P([B("结论 1（损失函数）："), T("物理正则是回归趋中的直接成因之一。纯净版总体 RMSE 好 6%、bias 减半、剧烈分歧率从 8.7% 降到 6.6%——纯 L2 让模型对「该 0 就 0、该大就大」的响应更忠实。")]),
  P([B("结论 2（物理先验的两面性）："), T("物理正则在观测充足时是拖累（把预测拉向均值），在观测薄弱时是兜底（枯水线、光流-only 显著更稳）。它不是该不该要的问题，而是该在哪起作用的问题——作为无条件附加损失是错的，作为「观测置信度低时加大的自适应先验」可能是对的。")]),
  P([B("结论 3（共同瓶颈）："), T("两版最优验证 epoch 都停在早期（ep26/ep19）后进入长平台，且 [3+) 高速段 RMSE 均在 0.85+。瓶颈不在训练时长，而在高速样本稀少（占比 1.2%）与观测-目标矛盾样本。建议下一阶段：高速段过采样 / 分段损失加权 + 剧烈分歧集合人工复核。")]),
  P([B("结论 4（交付建议）："), T("以纯净版为主模型（总体与分歧率全面占优、结构干净无手工先验）；对光流-only 与疑似枯水断面叠加物理版或物理先验做二段校验；两版分歧集合（合计约 6–9% 线）进入人工复核队列。")]),

  H1("附录 A  评测口径"),
  P([T("测试集为 40 个训练全程未见的站、45,118 断面、1,824,298 条测速线。基线为逐线原始观测中位数（raw_median）与截断均值（raw_clip_mean），均不含置信度信息，与模型输入口径一致。零速线指目标恰为 0 的线（枯水物理）；高速线指目标 ≥2 m/s；剧烈分歧指 |预测−目标| > 0.5 m/s。目标 std < 0.1 m/s 的近常数站 NSE 退化，只报 RMSE。")]),
  P([T("报告与全部中间产物见 runs/v1/ 与 runs/v1_mse/：journal.md（完整决策与事故日志）、history.json（逐 epoch 指标）、comparison.json（对比明细）、metrics_test_*.json（含基线）、gen_*_final.json（泛化明细）、report_figs/（图件）。",
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
  fs.writeFileSync("runs/v1/V1_最终报告.docx", buf);
  console.log("written", buf.length, "bytes");
});
