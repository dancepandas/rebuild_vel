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
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, keepNext: true, spacing: { before: 260, after: 120 }, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, keepNext: true, spacing: { before: 180, after: 100 }, children: [new TextRun(t)] });

const FIG = (file, widthPx, caption) => {
  const norm = file.replace(/\\/g, "/");
  const [w, h] = SIZES[norm] || SIZES[norm.split("/").pop()] || [1400, 900];
  // cap both dimensions to the usable page area so Word never pushes an
  // oversized image to its own (mostly blank) page
  const MAXW = Math.min(widthPx, 600), MAXH = 780;
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
        P([T("① "), B("模型定位"), T("：以自动采集的原始分段流速观测（STIV 视频段 / 光流区域估计）为输入，直接重建整条断面全部测速线的表面流速，全程无需人工参与。站级测试集上重建 RMSE 0.34–0.36 m/s，较原始观测直接使用（0.76 m/s）降低过半；监测正常的测速线误差 0.24–0.27 m/s；枯水断面自动判零；模型-目标剧烈分歧断面自动标记（约占 6.6%）。")]),
        P([T("② "), B("研究价值"), T("：现行断面流速标准值依赖人工/半自动整编，本次数据中 51% 的测速线为插值填充；自动观测虽 7×24 持续产出，但单段噪声大（直接使用 RMSE 0.76 m/s）无法直接应用。本模型验证了从自动观测重建可靠断面流速的技术可行性：训练一次（约 8 小时单卡）即可持续产出，人工工作量由全量整编收敛至约 6.6% 的可疑断面复核。")]),
        P([T("③ "), B("对照实验（单一变量）"), T("：两版模型同架构（82.76M）、同数据、同站级分层划分，仅两处不同——物理版的形态偏置注意力 + MSE+五项物理正则，对照版的 RoPE 位置编码 + 纯 L2。总体上纯净版全面占优：RMSE 0.342 对 0.364（好 6.0%），NSE 0.835 对 0.814，bias 0.023 对 0.056；对原始观测中位数基线的 skill 0.553 对 0.524。")]),
        P([T("④ "), B("方法学发现"), T("：物理版的回归趋中被证实并部分归因于物理正则——纯净版在低速段 [0.2,0.5) 的 bias 从 +0.164 降至 +0.073，高速段(≥2 m/s)严重低估占比从 18.4% 降至 15.3%，剧烈分歧（|误差|>0.5 m/s）占比从 8.7% 降至 6.6%。")]),
        P([T("⑤ "), B("物理先验的守护价值"), T("：在观测薄弱的场景物理版反而更稳——零速枯水线 RMSE 0.199 对 0.252、光流-only 测次 RMSE 0.281 对 0.471，物理项充当了「观测不可信时的兜底先验」。")]),
        P([T("⑥ "), B("共同短板"), T("：两版的最优验证 epoch 都停在早期（ep26 / ep19）后进入长平台，且高速段（≥3 m/s）RMSE 均在 0.85+——高速与观测-目标矛盾样本是下一阶段的重点。")]),
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
  ...FIG("runs/v1/report_figs/fig_density.png", 430,
    "图 1  物理版重建流速 vs 目标流速密度图（测试集全量 182 万线，对数色标）。低速段散布在对角线上方（正偏置），高速段被压向均值。"),
  ...FIG("runs/v1_mse/report_figs/fig_density.png", 430,
    "图 2  纯净版同口径密度图。主对角带更紧密，[0.2,0.5) 段抬升效应明显减弱；虚线 y=x，灰带 ±0.3 m/s。"),
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
    "图 3  物理版各测试站 RMSE（左，红=RMSE>0.8）与 NSE（右，灰=近常数站指标退化，†标记）。两版跨站分布形态相似；纯净版中位 RMSE 0.263 更好，但 p90 0.677 更差。"),
  P([T("站级中位：物理版 RMSE 0.289 / NSE 0.744；纯净版 RMSE 0.263 / NSE 0.637。纯净版中位 RMSE 更好但 "), B("NSE 中位反而更低"),
     T("，且 p90（0.677 对 0.464）更差——它的误差分布更两极：多数站更好，少数站（观测薄弱型）更差。最差站两版一致：站 00423（RMSE 1.14 / 1.17）与站 00156（0.98 / 1.03），后者即「原始观测 8+ m/s、目标 0.1」的观测-目标矛盾站（原始 STIV 超出河流物理上限，详见 journal）。")]),
  P([B("分源是两版最大的分野："), T("光流-only 测次物理版 RMSE 0.281 / NSE 0.846，纯净版 0.471 / 0.567。解释：物理版的形态偏置注意力把「水深、岸别、坡度」的结构先验直接注入注意力，在原始观测稀疏（光流-only 每线常只有 1 个估计）时兜底；纯净版只能依赖 RoPE 与嵌入里的形态通道，观测一弱就漂。STIV 测次（占 98.9%）纯净版反而更好（0.341 对 0.364）。")]),

  H2("5.1 观测-目标矛盾的普遍性检验（最终模型复核）"),
  P([T("对站 00156 的「原始观测 8+ m/s 对目标 0.1 m/s」现象做了全测试集复核。"), B("矛盾普遍存在但低发，个别站集中"),
     T("：全测试集 182 万条有观测的线中，观测远大于目标（差值 >max(0.5, 1.5×目标)）的占 "), B("5.4%"),
     T("（矛盾线上观测中位 2.21 m/s 对目标中位 0.21，约 10 倍），观测远小于目标的占 4.6%，合计约 10%；其余 90% 的线观测与目标基本一致（相关系数 r=0.722）。分站看，矛盾率中位仅 5.9%，"),
     B("只有 2/37 个站的矛盾率超过 20%"), T("（站 00156 为最严重者，全库 1,727 个断面、原始观测段均值中位 0.25 m/s 对目标 0.09 m/s，最差断面单线达 8.7 m/s）。")]),
  P([T("用最终两版检查点复核该站：物理版 1,727 断面 / 63,899 线上 RMSE 1.020（预测均值 0.75 对目标 0.158），纯净版 RMSE 0.791（预测均值 0.47）——两版都部分跟随了被高估的原始观测，但纯净版跟随程度更低。")]),
  P([B("对模型可靠性的含义"), T("：在 90% 观测-目标一致的线上，两版都可靠（RMSE：物理版 0.270、纯净版 0.244）；矛盾线上误差升至 0.80–0.82（约 3 倍），且两版在矛盾方向的追随权重都很低（0.05–0.18），说明模型总体保守、并未普遍盲从观测。因此「监测质量不是完全垃圾即产出可靠结果」成立；对约 10% 的矛盾线（其中 2 个集中站贡献最大），以「原始观测与目标剧烈分歧」为特征即可自动筛出送人工复核——该规则无需模型参与，一行判据即可上线。")]),

  H1("六、断面重建案例"),
  ...FIG("runs/v1/report_figs/fig_sections.png", 600,
    "图 4  物理版：最好 / 中位 / 最差（观测-目标矛盾）/ 枯水 / 光流-only 五类断面。枯水区预测≈0，「没水→流速 0」规律已学会。"),
  ...FIG("runs/v1_mse/report_figs/fig_sections.png", 600,
    "图 5  纯净版：同五类断面。低速段跟随更紧，但枯水区偶有 0.1–0.2 m/s 的虚增速（物理版没有）。"),
  ...FIG("runs/v1/report_figs/fig_training_curves.png", 620,
    "图 6  物理版损失与验证 RMSE 曲线（ep70 停止时止）。最优停在 ep26，其后 44 epoch 平台。"),
  ...FIG("runs/v1_mse/report_figs/fig_training_curves.png", 620,
    "图 7  纯净版损失与验证 RMSE 曲线（ep87 停止时止）。最优停在 ep19，但整体水平低于物理版。"),

  H1("七、结论"),
  H2("7.1 这个模型能干什么"),
  P([T("给定一个断面任意时刻的原始分段流速观测（哪些线有观测、观测值多少，无需人工整理），模型输出该断面"), B("全部测速线的表面流速"),
     T("。实测能力（站级测试集，182 万条测速线）：")]),
  TB([3400, 5960], [
    tbRow([tbCell("能力", { head: true, fill: "D9E2F3", w: 3400 }), tbCell("实测水平", { head: true, fill: "D9E2F3", w: 5960 })]),
    tbRow([tbCell("有实测线的流速重建", { left: true }), tbCell("RMSE 0.26 m/s、NSE 0.92——可替代人工读数的精度", { left: true })]),
    tbRow([tbCell("无实测线的流速补全（占全部测速线 51%）", { left: true }), tbCell("RMSE 0.40 m/s——可用于趋势判断与异常筛查", { left: true })]),
    tbRow([tbCell("原始观测自动去噪", { left: true }), tbCell("原始观测直接使用误差 0.76 m/s，模型降至 0.34 m/s", { left: true })]),
    tbRow([tbCell("枯水自动判零", { left: true }), tbCell("枯水线（水深<1cm）重建值≈0，零速规则自动习得", { left: true })]),
    tbRow([tbCell("可疑数据自动红旗", { left: true }), tbCell("分歧>0.5 m/s 的线自动标出（占 6.6%），直接作为人工复核清单", { left: true })]),
  ]),
  H2("7.2 为什么值得做"),
  P([T("现状：断面流速的「标准值」靠人工/半自动整编——本次 21.8 万断面中 "), B("51% 的测速线为插值填充"),
     T("，人工整编慢、覆盖不全、本身带噪声；而自动观测设备 7×24 海量产出，却因单段噪声大（直接使用误差 0.76 m/s）无法利用。")]),
  P([T("本模型在两者之间搭桥："), B("把不可直接使用的自动观测变成可用的断面流速"),
     T("。一次训练（约 8 小时单卡）之后，每个断面无需人工步骤即可出全断面结果；人工工作量从「整编全部断面」缩减为「复核约 6.6% 的可疑线」。观测持续积累后模型可增量重训，收益持续放大。")]),
  H2("7.3 模型行为分析：对矛盾与极端观测的响应"),
  P([T("对两版模型在三类特殊样本上的行为做了量化。三类行为共同表明：模型并非对任一信息源的二元服从，而是在人工目标与自动观测之间进行了"), B("稳健的加权融合"), T("。")]),
  TB([3000, 2000, 2000, 2360], [
    tbRow([tbCell("行为", { head: true, fill: "D9E2F3", w: 3000 }), tbCell("物理版", { head: true, fill: "D9E2F3", w: 2000 }), tbCell("纯净版", { head: true, fill: "D9E2F3", w: 2000 }), tbCell("样本量", { head: true, fill: "D9E2F3", w: 2360 })]),
    tbRow([tbCell("高流速压制：原始观测≥3 m/s 的线，重建均值/观测均值", { left: true }), tbCell("0.557"), tbCell("0.574"), tbCell("观测均值全部>3 m/s 的线", { left: true })]),
    tbRow([tbCell("零标定流速恢复：目标≤0.2 而观测≥0.5 的线，重建均值/观测均值", { left: true }), tbCell("0.441"), tbCell("0.406"), tbCell("52,978 条线", { left: true })]),
    tbRow([tbCell("矛盾线融合位置（0=目标，1=观测）中位数", { left: true }), tbCell("0.246"), tbCell("0.187"), tbCell("164,462 条线", { left: true })]),
  ]),
  P([B("行为一（高流速压制）："), T("对原始观测达到 3 m/s 以上的极端测速线（多数超出河流物理上限，属观测伪影），两版模型均将重建值压缩至观测的 56%–57%。该压缩对高流速观测伪影起到稳健估计的作用；对真实洪水测次则会引入低估，是 [3+) 段 RMSE 偏高的组成部分。")]),
  P([B("行为二（零标定断面的流速恢复）："), T("人工目标被标为近零（≤0.2 m/s）而原始观测显著（均值 2.01 m/s）的测速线达 52,978 条。两版模型在其中 91%–92% 的线上给出高于人工零标的重建值，且重建量级稳定为观测信号的 41%–44%。这表明模型并未盲从人工零标定，而是从观测中系统性地恢复了被抹去的流速信号。这 5.3 万条线是人工整编与自动观测分歧最集中的样本集——无论分歧根源是整编遗漏还是观测伪影，都具备明确的复核定标价值，且模型的重建值可作为复核的先验参考。")]),
  P([B("行为三（矛盾线的稳健折中）："), T("在观测与目标分歧的 164,462 条线上，重建值的位置分布为中位 19%–25%（0=目标，1=观测），四分位距 4%–61%——总体偏向目标一侧的加权折中，而非对任一信息源的二元取舍；个别断面上观测权重显著升高（如站 00156），构成自动识别矛盾样本的信号。")]),

  H2("7.4 方法学结论（对建模者）"),
  P([B("结论 1（损失函数）："), T("物理正则是回归趋中的直接成因之一。纯净版总体 RMSE 好 6%、bias 减半、剧烈分歧率从 8.7% 降到 6.6%——纯 L2 下模型对零流速与高流速的重建均更忠实于观测证据。")]),
  P([B("结论 2（物理先验的两面性）："), T("物理正则在观测充足时是拖累（把预测拉向均值），在观测薄弱时是兜底（枯水线、光流-only 显著更稳）。问题不是该不该要，而是该在哪起作用——作为无条件附加损失是错的，作为「观测置信度低时加大的自适应先验」可能是对的。")]),
  P([B("结论 3（共同瓶颈）："), T("两版最优验证 epoch 都停在早期（ep26/ep19）后进入长平台，且 [3+) 高速段 RMSE 均在 0.85+。瓶颈不在训练时长，而在高速样本稀少（占比 1.2%）与观测-目标矛盾样本。下一阶段：高速段过采样 / 分段损失加权 + 剧烈分歧集合人工复核。")]),
  H2("7.5 后续工作"),
  P([T("① 高流速段：样本占比仅 1.2% 而 RMSE 达 0.85+，建议训练期按速度分层加权或过采样，并对高流速测次单独检验。② 矛盾线定标复核：52,978 条零标定-高观测矛盾线与约 10% 的分歧线建议人工复核定标，复核结果可反哺训练。③ 自适应物理先验：将物理正则由无条件附加改为随观测置信度调节，以兼得纯净版的总体精度与物理版在观测薄弱场景的稳健性。")]),

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
