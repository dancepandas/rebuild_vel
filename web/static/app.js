/* 断面流速重建 — panel logic.
 *
 * One fetch per measurement: the API returns every arm's prediction together
 * with the platform's own value and the raw segment observations, so switching
 * models redraws from data already in hand rather than going back to the
 * server.  Plot geometry is redrawn at the container's true pixel width so the
 * 仿宋 axis text stays crisp instead of being scaled by a viewBox.
 */

// Aether-P is the project's main model, so it is what the panel opens on;
// the registry from /api/meta replaces this list as soon as it answers
const ARMS_FALLBACK = ["aether-p"];

//: measurements the picker lists at once; one device-day can hold hundreds
const MEASUREMENTS_PAGE = 20;

const state = {
  arms: [],            // [{id,label,note,available}]
  activeArm: "aether-p",
  station: null,       // {code,name,n,devices}
  devices: [],
  device: null,
  time: null,
  payload: null,
  measurements: [],
  // how many of them the picker is currently listing
  measurementShown: MEASUREMENTS_PAGE,
  stationQuery: "",
  stations: [],
  // which channel the measurement records come from: the local store (already
  // through the pipeline) or the platform itself (raw, pulled on demand).
  //
  // 实时 is the default and stands first in the switch, because it is the only
  // one of the two that can show today.  The stored corpus in this index ends
  // on 2026-08-31 - three weeks before this panel went up - so 已入库 is a
  // history view, and a history view is not what a panel on a wall is for.
  source: "live",
  liveDate: todayISO(),
  meta: null,
  layers: { recon: true, target: true, raw: true, dry: true },
  // cap the velocity axis at the range the figure is discussing.  On by
  // default: raw STIV segments on reflective water run to twenty times the
  // channel's real speed, and letting them set the scale flattens the profile
  // into the bottom sliver of the panel.
  axisLimit: true,
  pinned: null,
  loading: false,
  // navigation generation.  Every reader gesture that starts a new navigation
  // (station click, measurement click, channel switch, day change) bumps this;
  // anything already in flight - above all the boot walk in openLatestLive,
  // whose per-candidate exports run tens of seconds - stamps it at entry and
  // bails the moment it no longer matches, instead of resolving late and
  // drawing over whatever the reader has moved on to
  navSeq: 0,
  // time -> {ok, why} for live timestamps already opened: the platform list is
  // timestamp-only, so this is the only place a live day's pullability is known
  liveTried: new Map(),
};

function todayISO() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

// The figure's palette, in one place.  These values have to live here rather
// than in a stylesheet because the SVG is built attribute by attribute - and
// every one of them is a data channel, so a reader of the code should see at
// the call site which channel a colour belongs to rather than chase a class
// name into app.css.  Named to match the :root tokens one for one.
const C = {
  water:     "#3370FF",  // model reconstruction, and the water body itself
  waterInk:  "#245BDB",  // the same blue where it carries text - see app.css
  field:     "#B07407",  // raw STIV / optical-flow observations
  ink:       "#1D1D1F",  // the platform's own manual value - the reference
  silt:      "#8E7F6C",  // the river bed
  dry:       "#C9C9CF",  // lines with no water over them
  flag:      "#D70015",  // disagreement, flagged for review
  grid:      "#E3E4E9",  // the velocity gridlines
  gridSoft:  "#EFEFF4",  // the depth gridlines, one step quieter
  tick:      "#6E6E73",  // axis numerals
  cap:       "#9A9AA1",  // axis captions, and the quiet strokes
  hair:      "#C9C9CF",  // a measuring line, under its water column
};

const GEOM = { padL: 64, padR: 96, padT: 28, padB: 44, height: 474, velFrac: 0.46 };

const el = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  return node;
}

/* -- formatting ---------------------------------------------------------- */

const num = (value, digits = 2) =>
  value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : Number(value).toFixed(digits);

/* `isFinite(null)` is true in JavaScript, because null coerces to 0.  So a null
   coming back from the service - a statistic that is undefined for this section,
   or a reading the export did not carry - would sail through a bare isFinite()
   and get drawn or ranked as a real zero.  Anything testing a payload number
   has to ask this instead. */
const finite = (value) => typeof value === "number" && Number.isFinite(value);

const int = (value) => (value === null || value === undefined ? "—" : Number(value).toLocaleString("zh-CN"));

const shortTime = (value) => (value ? value.slice(5, 16) : "—");
const dayTime = (value) => (value ? value.slice(5) : "—");

/* -- api ----------------------------------------------------------------- */

async function api(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, value);
  }
  const response = await fetch(url);
  let body = null;
  try { body = await response.json(); } catch { /* non-JSON error page */ }
  if (!response.ok) {
    throw new Error((body && body.error) || `${response.status} ${response.statusText}`);
  }
  return body;
}

/* -- top rail ------------------------------------------------------------ */

function renderArms() {
  const host = el("arms");
  host.textContent = "";
  for (const arm of state.arms) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "arm";
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(arm.id === state.activeArm));
    // `is-active` travels in className rather than via classList so it is
    // visible to the self-check's stub, whose classList is a separate set that
    // does not write back into the string the check reads.
    if (arm.id === state.activeArm) button.className = "arm is-active";
    button.disabled = !arm.available;
    const name = document.createElement("span");
    name.className = "arm-name";
    name.textContent = arm.label;
    // What the three letters mean - 物理约束, 纯净版, Yeo-Johnson - used to be a
    // second line inside each pill, and the same sentence sat under the same name
    // again in the readout table's first column.  Twice on one screen, and the
    // reader who asked for the rest of the prose to go asked for these too.  It is
    // a real thing to know, so it is not deleted - it is the pill's tooltip, which
    // is one hover away and costs the rail nothing.
    button.title = [arm.available ? "" : `不可用：${arm.reason || "checkpoint 缺失"}`, arm.note]
      .filter(Boolean).join(" · ");
    button.append(name);
    button.addEventListener("click", () => {
      if (arm.id === state.activeArm) return;
      state.activeArm = arm.id;
      renderArms();
      if (state.payload) {
        renderChart(state.payload);
        renderReadout(state.payload);
      }
    });
    host.append(button);
  }
}

/* -- pickers ------------------------------------------------------------- */

function renderStations() {
  const host = el("station-list");
  host.textContent = "";
  el("station-count").textContent = state.stations.length ? `${state.stations.length} 站` : "";
  if (!state.stations.length) {
    host.append(emptyNote("没有匹配的站点。"));
    return;
  }
  for (const station of state.stations) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "row";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(state.station && station.code === state.station.code));

    const main = document.createElement("span");
    main.className = "row-main";
    const code = document.createElement("span");
    code.className = "row-code";
    code.textContent = station.code;
    const name = document.createElement("span");
    name.className = "row-name";
    name.textContent = station.name && station.name !== station.code ? station.name : "";
    main.append(code, name);

    const meta = document.createElement("span");
    meta.className = "row-meta";
    meta.append(spanText(`${int(station.n)} 测次`));
    if (station.devices.length > 1) meta.append(spanText(`${station.devices.length} 设备`));

    button.append(main, meta);
    button.addEventListener("click", () => { state.navSeq += 1; selectStation(station); });
    li.append(button);
    host.append(li);
  }
  const selected = host.querySelector('[aria-selected="true"]');
  if (selected) selected.scrollIntoView({ block: "nearest" });
  paintScrollEdges();
}

function renderMeasurements() {
  const host = el("measurement-list");
  host.textContent = "";
  const rows = state.measurements;
  const live = state.source === "live";
  el("measurement-count").textContent = rows.length ? `${int(rows.length)} 条` : "";
  el("measurement-list").setAttribute("aria-label", live ? "平台测次" : "已入库测次");
  if (!state.station) {
    host.append(emptyNote("先选站点。"));
    return;
  }
  if (!rows.length) {
    host.append(emptyNote(live
      ? `平台上这个设备在 ${state.liveDate} 没有测次。换一天试试。`
      : "这个站点没有已入库的测次。"));
    return;
  }
  const shown = rows.slice(0, state.measurementShown);
  for (const row of shown) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "row row--time";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(row.time === state.time));
    button.disabled = state.loading;

    const main = document.createElement("span");
    main.className = "row-main";
    const code = document.createElement("span");
    code.className = "row-code";
    code.textContent = dayTime(row.time);
    main.append(code);

    const meta = document.createElement("span");
    meta.className = "row-meta";
    if (live) {
      // The platform's list endpoint returns timestamps only - flow and line
      // count are not known until a measurement is pulled. So the row states
      // what a click will do, and once clicked, what it did.
      const tried = state.liveTried.get(row.time);
      if (!tried) {
        meta.append(spanText("点击拉取"), spanText(row.device.slice(-6)));
      } else if (tried.ok) {
        meta.append(spanText("可重建", "m-flow"), spanText(row.device.slice(-6)));
      } else {
        meta.append(spanText(tried.why, "m-none"), spanText(row.device.slice(-6)));
      }
    } else {
      const mean = row.mean_velocity;
      meta.append(
        spanText(mean === null ? "均速 —" : `均速 ${num(mean, 2)} m/s`,
          mean !== null && mean > 0.15 ? "m-flow" : "m-still"),
        spanText(`${row.n_lines ?? "—"} 线`),
        spanText(row.device.slice(-6)),
      );
    }

    button.append(main, meta);
    // the bump marks every in-flight navigation (the boot walk above all)
    // as superseded, so its late resolutions cannot draw over this click
    button.addEventListener("click", () => { state.navSeq += 1; selectMeasurement(row); });
    li.append(button);
    host.append(li);
  }
  if (rows.length > shown.length) {
    const li = document.createElement("li");
    const more = document.createElement("button");
    more.type = "button";
    more.className = "more";
    // The list opens at MEASUREMENTS_PAGE because a device can run to hundreds
    // of measurements and the picker is not a browser - but a cap that cannot be
    // lifted would strand the rest, so this offers the next page rather than
    // just counting what it hid.
    const step = Math.min(MEASUREMENTS_PAGE, rows.length - shown.length);
    more.textContent = `还有 ${int(rows.length - shown.length)} 条 · 再显示 ${step} 条`;
    more.addEventListener("click", () => {
      state.measurementShown += MEASUREMENTS_PAGE;
      renderMeasurements();
    });
    li.append(more);
    host.append(li);
  }
  const selected = host.querySelector('[aria-selected="true"]');
  if (selected) selected.scrollIntoView({ block: "nearest" });
  paintScrollEdges();
}

function spanText(text, className) {
  const span = document.createElement("span");
  span.textContent = text;
  if (className) span.className = className;
  return span;
}

function emptyNote(text) {
  const li = document.createElement("li");
  li.className = "list-empty";
  li.textContent = text;
  return li;
}

/* -- scroll wells -------------------------------------------------------- */

/* Every scrolling well on the page has its scrollbar hidden - see
   `.scroll-well` in the stylesheet for why - and this is the half of it that
   is kept.  A well with content beyond an edge grows a soft shadow on that
   edge: it is the only thing left saying "there is more", and without it a
   picker pane holding 221 stations looks exactly like a pane holding eight.

   The shadow lives on whichever edges are actually live, so a well scrolled to
   the top is bare on top and a well short enough not to scroll is bare
   entirely.  It costs one class per edge, which is why this repaints on a
   scroll *and* after every render - content that grew underneath a reader who
   has not moved changes which edges should be lit, and no scroll event fires
   for that. */
const edgedWells = new WeakSet();

function edgeOf(box) {
  // two pixels of slack at each end: a fractional layout height can leave
  // scrollTop at 0.5 when the well is visually at the top, and rounding puts
  // the far end a hair short of scrollHeight on some zoom levels
  box.classList.toggle("is-top", box.scrollTop > 2);
  box.classList.toggle("is-end", box.scrollTop + box.clientHeight < box.scrollHeight - 2);
}

function paintScrollEdges() {
  for (const box of document.querySelectorAll(".scroll-well")) {
    if (!edgedWells.has(box)) {
      edgedWells.add(box);
      // the repaint asks the document rather than walking a registry: the
      // observation well is rebuilt from scratch on every section, and a
      // registry would hold every one of them for the life of the page
      box.addEventListener("scroll", () => paintScrollEdges(), { passive: true });
    }
    edgeOf(box);
  }
}

/* -- selection ----------------------------------------------------------- */

async function selectStation(station, preferredDevice = null) {
  state.station = station;
  state.devices = station.devices || [];
  state.device = preferredDevice
    || (state.devices.find((d) => d.device === state.device) || state.devices[0] || {}).device
    || null;
  // a new station is a new subject: whatever is on the board belongs to the
  // station the picker has just left
  state.time = null;
  state.payload = null;
  renderStations();
  await loadMeasurements({ autoPick: true });
}

async function loadMeasurements({ autoPick = false } = {}) {
  if (!state.station || !state.device) return;
  const seq = state.navSeq;   // a newer navigation supersedes this load
  const live = state.source === "live";
  // a new station, device, day or source is a new list: the old verdicts are
  // about timestamps that are no longer on screen, and the list folds back to
  // its first page
  state.liveTried.clear();
  state.measurementShown = MEASUREMENTS_PAGE;
  setBusy(true, live ? "正在向平台查询测次…" : "正在读取测次…");
  try {
    const data = live
      ? await api("/api/live/measurements", {
          station: state.station.code,
          device: state.device,
          begin: state.liveDate,
          end: state.liveDate,
        })
      : await api("/api/measurements", {
          station: state.station.code,
          device: state.device,
          limit: 500,
        });
    // superseded while we were asking (a reader click during the boot walk):
    // the newer navigation owns the panel, and touching anything here would
    // overwrite its list - leave without a trace
    if (seq !== state.navSeq) return;
    state.measurements = data.measurements || [];
    // settle the busy flag before drawing the rows, never after: a row drawn
    // while the board is busy is drawn `disabled`, and nothing rebuilds it when
    // the board goes idle - so the whole list would sit there looking normal and
    // swallowing every click.  That is exactly what happened on the live tab and
    // then on the cache tab, which have no auto-pick to rebuild the list behind
    // them the way a station's arrival does.
    setBusy(false);
    renderMeasurements();
    // A live measurement costs a platform export plus a quality check before it
    // can be drawn, and a good share of them are rejected outright, so a list
    // of them is not auto-opened here the way a station's arrival opens a
    // typical stored section - the live channel has its own entry point, which
    // asks the service what today's newest timestamps are and walks them.
    if (autoPick && !live && state.measurements.length) {
      await selectMeasurement(pickTypical(state.measurements));
    } else if (state.payload) {
      // a section is still the board's subject and the loader took its panel
      // down on the way in - put it back rather than leave a blank board
      showContent();
    } else if (el("board-error").hidden) {
      // nothing is coming: the list is empty, or the reader is being left to
      // choose a timestamp, which on the live tab is the usual case
      showEmpty();
    }
  } catch (error) {
    if (seq !== state.navSeq) return;
    setBusy(false);
    showError(live ? "平台上的测次读不到" : "读不到测次列表", error.message);
  }
}

/* A station's record spans floods, ordinary days and dry spells, and roughly a
 * third of all lines in this corpus carry no water at all.  Opening the most
 * recent measurement can therefore land on an empty channel; open the one
 * closest to the station's median flow instead, so the panel shows something
 * characteristic on arrival. */
function pickTypical(rows) {
  const scored = rows.filter((r) => r.mean_velocity !== null && r.mean_velocity > 0.05 && r.n_lines >= 8);
  const pool = scored.length ? scored : rows;
  const values = pool.map((r) => r.mean_velocity ?? 0).slice().sort((a, b) => a - b);
  const median = values[Math.floor(values.length / 2)] ?? 0;
  return pool.reduce((best, row) =>
    Math.abs((row.mean_velocity ?? 0) - median) < Math.abs((best.mean_velocity ?? 0) - median) ? row : best);
}

async function selectMeasurement(row) {
  if (!state.station || !state.device) return false;
  const seq = state.navSeq;   // superseded mid-pull: draw nothing, touch nothing
  const live = state.source === "live";
  state.time = row.time;
  setBusy(true, live ? "正在从平台拉取这个测次…" : "正在重建流速分布…");
  // raised first, drawn second: the rows are meant to be dead for the length of
  // the pull - a live one runs tens of seconds, and drawing them before the flag
  // goes up left them clickable, so a reader could queue five pulls before the
  // first came back.  Both exits below re-render on a settled flag.
  renderMeasurements();
  try {
    const payload = await api("/api/section", {
      station: state.station.code,
      device: state.device,
      time: row.time,
      arms: state.arms.filter((a) => a.available).map((a) => a.id).join(","),
      source: live ? "live" : "cache",
    });
    // the reader navigated elsewhere while this pull was in flight (the boot
    // walk lands here): their newer view owns the board, and settling this
    // one would paint a section about a station they have already left
    if (seq !== state.navSeq) return false;
    if (live) state.liveTried.set(row.time, { ok: true, why: "" });
    state.payload = payload;
    state.pinned = null;
    setBusy(false);
    showContent();
    renderTitleblock(payload);
    renderChart(payload);
    renderReadout(payload);
    renderObservations(payload);
    renderMeasurements();
    return true;
  } catch (error) {
    if (seq !== state.navSeq) return false;
    // A live timestamp can fail for reasons the list cannot predict, and most of
    // a given day usually does - so remember what this one turned out to be.
    // Otherwise the reader clicks down the list blind, and re-clicks the ones
    // that already said no.
    if (live) state.liveTried.set(row.time, { ok: false, why: liveReason(error.message) });
    setBusy(false);
    showError(live ? "平台上这个测次没能重建出来" : "这个测次没能重建出来", error.message);
    renderMeasurements();
    return false;
  }
}

/* The service states the refusal as an outcome, and the list has room for a
   verdict rather than a sentence - so this shortens what it was told, and
   reports only what was actually observed. */
function liveReason(message) {
  const text = String(message || "");
  // the service's own words, first: these are outcomes, already fit to show
  if (/无法获得原始观测/.test(text)) return "无原始观测";
  if (/几乎全为零|几乎全为同一个值|超出可用范围|标定流速缺失/.test(text)) return "标定流速异常";
  if (/测速线太少|没有算法测得的测速线/.test(text)) return "无测速线";
  if (/没有水位记录|没有水深|起点距不唯一|缺少站点|非数值/.test(text)) return "数据不完整";
  // anything the export itself said, which the service passes through
  if (/没有导出文件|过程数据/.test(text)) return "平台无过程文件";
  // the export 500s intermittently - the same timestamp succeeds on a retry, so
  // this one is worth saying "try again" about rather than writing off
  if (/下载失败|导出失败|returned code=5\d\d/.test(text)) return "导出失败，可重试";
  if (/未通过质检/.test(text)) return "未通过质检";
  return "拉取失败";
}

/* -- export ---------------------------------------------------------------
 * One CSV per measurement, built from the very payload the board is showing,
 * so the file can never disagree with the figure.  UTF-8 BOM keeps the Chinese
 * headers intact when the file lands in Excel.  Every available arm is
 * written, not only the one on screen: the export is the measurement's
 * record, not a screenshot of a toggle. */

function csvCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return String(Number(value.toFixed(4)));
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function buildExportCsv(payload) {
  const armIds = Object.keys(payload.lines[0] || {})
    .filter((key) => key.startsWith("pred_"))
    .map((key) => key.slice(5));
  const armLabel = (id) => (state.arms.find((a) => a.id === id) || {}).label || id;
  // the panel caps the dots per line; the median is over the same sample the
  // figure shows, which is the honest thing to write down next to the count
  const byLine = new Map();
  for (const obs of payload.observations || []) {
    if (obs.v === null || obs.v === undefined) continue;
    if (!byLine.has(obs.line)) byLine.set(obs.line, []);
    byLine.get(obs.line).push(obs.v);
  }
  const median = (values) => {
    if (!values || !values.length) return null;
    const sorted = values.slice().sort((a, b) => a - b);
    const mid = sorted.length >> 1;
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  };

  const meta = payload.meta || {};
  const head = [
    ["Aether 断面流速重建"],
    ["站点", `${payload.station} ${payload.station_name || ""}`.trim()],
    ["设备", payload.device],
    ["测次", payload.time],
    ["通道", payload.source === "live" ? "实时" : "已入库"],
    ["水位 m", meta.water_level],
    ["河宽 m", meta.water_width],
    ["断面面积 m²", meta.section_area],
    ["原始观测来源", meta.raw_source],
    ["原始段数（面板采样）", (payload.observations || []).length],
    ["枯水线阀门", `水深 ≤ ${meta.valve_max_depth} m 的测速线重建值归零，本场 ${meta.n_valved} 条`],
    ["导出于", new Date().toLocaleString("zh-CN", { hour12: false })],
    [],
    ["模型", "RMSE m/s", "MAE m/s", "bias m/s", "NSE", "超差线数"],
    ...armIds.map((id) => {
      const m = (payload.metrics || {})[id] || {};
      return [armLabel(id), m.rmse, m.mae, m.bias, m.nse, m.disagreement];
    }),
    [],
    ["测速线", "起点距 m", "水深 m", "河底高程 m", "平台标定流速 m/s",
     "原始观测中位 m/s", "原始段数", "算法线", "阀门归零",
     ...armIds.map((id) => `${armLabel(id)} 重建 m/s`)],
    ...payload.lines.map((line) => [
      line.i, line.x, line.depth, line.bed, line.target,
      median(byLine.get(line.i)), line.n_raw, line.algo ? "是" : "否",
      line.valved ? "是" : "否",
      ...armIds.map((id) => line[`pred_${id}`]),
    ]),
  ];
  return "﻿" + head.map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

function exportCurrent() {
  const payload = state.payload;
  if (!payload || !payload.lines || !payload.lines.length) return;
  const stamp = (payload.time || "").slice(0, 16).replace(/[-:]/g, "").replace(" ", "_");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([buildExportCsv(payload)], { type: "text/csv;charset=utf-8" }));
  link.download = `Aether_${payload.station}_${stamp}_${payload.source}.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 4000);
}

/* -- data source --------------------------------------------------------- */

function renderSource() {
  const live = state.source === "live";
  el("src-cache").setAttribute("aria-pressed", String(!live));
  el("src-live").setAttribute("aria-pressed", String(live));
  el("live-date").hidden = !live;
  el("live-date").value = state.liveDate;
}

async function setSource(source) {
  if (state.source === source) return;
  state.navSeq += 1;   // the in-flight load, if any, belongs to the old channel
  state.source = source;
  state.time = null;
  state.payload = null;
  state.measurements = [];
  // the arrival message belongs to the arrival: a reader who switches away from
  // it is asking a different question, and the empty panel goes back to saying
  // what it says for everyone else
  el("board-empty-line").textContent = "左边选一个站点和测次。";
  el("board-empty-sub").textContent =
    "面板会画出这个测次的断面，以及模型从原始测速线重建出的流速分布。";
  renderSource();
  renderMeasurements();
  showEmpty();
  if (state.station) await loadMeasurements();
}

/* -- board states -------------------------------------------------------- */

function setBusy(busy, text) {
  state.loading = busy;
  el("loading-text").textContent = text || "读取中…";
  if (busy) {
    el("board-loading").hidden = false;
    el("board-empty").hidden = true;
    el("board-error").hidden = true;
    el("board-content").hidden = true;
  } else {
    el("board-loading").hidden = true;
  }
}

function showError(title, detail) {
  el("error-title").textContent = title;
  el("error-detail").textContent = detail;
  el("board-error").hidden = false;
  el("board-empty").hidden = true;
  el("board-content").hidden = true;
}

function showContent() {
  el("board-error").hidden = true;
  el("board-loading").hidden = true;
  el("board-empty").hidden = true;
  el("board-content").hidden = false;
}

function showEmpty() {
  el("board-error").hidden = true;
  el("board-loading").hidden = true;
  el("board-content").hidden = true;
  el("board-empty").hidden = false;
}

/* -- title block --------------------------------------------------------- */

function renderTitleblock(payload) {
  el("tb-station").textContent =
    payload.station_name && payload.station_name !== payload.station
      ? `${payload.station} ${payload.station_name}`
      : payload.station;
  el("tb-time").textContent = payload.time;

  const meta = payload.meta;
  const facts = [
    ["水位", meta.water_level === null ? "—" : `${num(meta.water_level, 2)} m`],
    ["河宽", meta.water_width === null ? "—" : `${num(meta.water_width, 1)} m`],
    ["平均水深", meta.aver_depth === null ? "—" : `${num(meta.aver_depth, 2)} m`],
    ["输入来源", sourceLabel(meta.raw_source)],
    ["设备", payload.device],
  ];
  // What is left is what the figure cannot say for itself: the section's own
  // physical facts, and which instrument took the reading.  The observation
  // counts - how many measuring lines, how many algorithm lines against
  // interpolated ones, how many raw segments - were listed here as well, and the
  // note under the figure states all three of them.  The same three numbers
  // twice on one screen is not twice the information, it is a title block that
  // has stopped being about the section.
  const host = el("tb-facts");
  host.textContent = "";
  for (const [label, value] of facts) {
    const wrap = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    wrap.append(dt, dd);
    host.append(wrap);
  }
}

function sourceLabel(source) {
  return { stiv: "STIV 视频分段", of: "光流法", of_traj: "光流轨迹法" }[source] || source || "—";
}

/* -- the section plot ---------------------------------------------------- */

function renderChart(payload) {
  const stage = el("plot-stage");
  const width = Math.max(560, Math.round(stage.clientWidth || 960));
  const W = width;
  const H = GEOM.height;
  const { padL, padR, padT, padB } = GEOM;

  const svg = el("section-svg");
  svg.textContent = "";
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W);
  svg.setAttribute("height", H);

  const lines = payload.lines;
  const obs = payload.observations;
  const meta = payload.meta;
  const armId = state.activeArm;

  // -- domains -----------------------------------------------------------
  const xs = lines.map((l) => l.x).filter((v) => v !== null);
  const obsXs = obs.map((o) => o.x).filter((v) => v !== null);
  let x0 = Math.min(...xs, ...obsXs);
  let x1 = Math.max(...xs, ...obsXs);
  if (!isFinite(x0) || !isFinite(x1) || x1 - x0 < 1e-6) { x0 = 0; x1 = 1; }
  const xPad = (x1 - x0) * 0.015;
  x0 -= xPad; x1 += xPad;

  // The section is drawn against depth, not against absolute stage.  Depth is
  // what the measuring lines actually carry, it is non-negative by construction,
  // and it cannot invert.  Stage can: on a line with no water over it the
  // platform logs the ground elevation, which sits above the water surface -
  // plotted as bed that throws the profile up into the velocity axis, and on a
  // section that is dry end to end it inverts the scale outright.
  const depths = lines.map((l) => l.depth).filter((v) => finite(v) && v >= 0);
  const fallbackDepth = [meta.max_depth, meta.aver_depth, 1]
    .find((v) => finite(v) && v > 0) ?? 1;
  const depthSpan = Math.max(depths.length ? Math.max(...depths) : fallbackDepth, 0.05);

  // The axis.  By default it stops at the range the figure is actually
  // discussing - the reconstruction and the platform's value - because raw STIV
  // segments on reflective water and floating debris run to twenty times the
  // channel's real speed, and a scale that spans them flattens the profile into
  // the bottom sliver.  The 图层 menu lifts the limit, and then the axis spans
  // every value the figure draws.  Either way nothing is moved: a segment past a
  // limited axis keeps its own value and leaves the plot through the top.
  const discussion = [];
  for (const line of lines) {
    if (finite(line.target)) discussion.push(line.target);
    const pred = line[`pred_${armId}`];
    if (finite(pred)) discussion.push(pred);
  }
  let axisTop = 0;
  for (const line of lines) {
    if (finite(line.target) && line.target > axisTop) axisTop = line.target;
    const pred = line[`pred_${armId}`];
    if (finite(pred) && pred > axisTop) axisTop = pred;
  }
  for (const o of obs) if (finite(o.v) && o.v > axisTop) axisTop = o.v;

  const sorted = discussion.slice().sort((a, b) => a - b);
  const axisPeak = sorted.length
    ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.995))]
    : 1;
  // the floor keeps a still or dry section from collapsing to a zero-height
  // axis; the 2% / 10% is headroom, so the topmost value lands inside the frame
  // rather than being cut in half by its edge
  const full = Math.max(0.3, axisTop * 1.02);
  // limited never means higher: on a section whose largest reading is the
  // reconstruction itself there is no tail to hold back, and taking the
  // discussion range's wider headroom there would raise the axis above what the
  // data needs - a limit that loosens.  So the limit only ever takes the lower of
  // the two, which is the full range exactly when it has nothing to hold back.
  const vMax = state.axisLimit
    ? Math.min(Math.max(0.3, axisPeak * 1.10), full)
    : full;

  // what the limit is holding back.  This is the one thing on the page that
  // changes what the figure shows, so it is the one thing that still has to be
  // said - and it is said as a count on the switch that did it, not as a sentence
  // under the figure.  A hidden reading that says nothing is a silent edit.
  const hiddenRaw = state.axisLimit
    ? obs.filter((o) => finite(o.v) && o.v > vMax).length : 0;
  const hiddenLines = state.axisLimit
    ? lines.reduce((n, l) => n
        + (finite(l.target) && l.target > vMax ? 1 : 0)
        + (finite(l[`pred_${armId}`]) && l[`pred_${armId}`] > vMax ? 1 : 0), 0)
    : 0;

  const hVel = (H - padT - padB) * GEOM.velFrac;
  const hSec = (H - padT - padB) - hVel;
  const yWL = padT + hVel;

  const sx = (x) => padL + ((x - x0) / (x1 - x0)) * (W - padL - padR);
  const yDepth = (d) => yWL + (Math.max(0, Math.min(d, depthSpan)) / depthSpan) * hSec;
  // the velocity axis is open above and floored at the water line: a small
  // negative reading is not physically meaningful, so it is floored at zero rather
  // than drawn dipping into the water body.  Nothing announces that on the page -
  // the reading's true signed value is in the hover tooltip, which is where a
  // reader asking about one line is already looking, and a sentence under the
  // figure about a handful of sub-zero STIV segments was read by nobody and cost
  // a line of the page.  No ceiling clamp: with the limit off the axis was taken
  // from these values, so every one of them already has room; with it on the clamp
  // would be the very pinning the limit is meant to avoid, and the clip takes the
  // overflow instead.
  const yVel = (v) => Math.min(yWL, yWL - (v / vMax) * hVel);

  // -- frame and grid ----------------------------------------------------
  const g = svgEl("g", { class: "draw-in" });
  svg.append(g);

  const gridTop = svgEl("g");
  const velTicks = niceTicks(0, vMax, 5);
  for (const v of velTicks) {
    const y = yVel(v);
    if (y < padT - 1) continue;
    gridTop.append(svgEl("line", { x1: padL, x2: W - padR, y1: y, y2: y, stroke: C.grid, "stroke-width": 1 }));
    const label = svgEl("text", {
      x: padL - 8, y: y + 3.5, "text-anchor": "end", "font-size": 11.5, fill: C.tick,
    });
    label.textContent = tickLabel(v);
    gridTop.append(label);
  }
  const depthTicks = niceTicks(0, depthSpan, 4);
  for (const d of depthTicks) {
    const y = yDepth(d);
    if (y > H - padB + 1 || y < yWL - 1) continue;
    gridTop.append(svgEl("line", { x1: padL, x2: W - padR, y1: y, y2: y, stroke: C.gridSoft, "stroke-width": 1 }));
    const label = svgEl("text", {
      x: W - padR + 8, y: y + 3.5, "font-size": 11.5, fill: C.cap,
    });
    label.textContent = tickLabel(d);
    gridTop.append(label);
  }
  g.append(gridTop);

  const axisCaption = (text, x, y, fill, anchor) => {
    const node = svgEl("text", { x, y, "font-size": 11, fill, "letter-spacing": "0.06em" });
    if (anchor) node.setAttribute("text-anchor", anchor);
    node.textContent = text;
    return node;
  };
  g.append(
    axisCaption("流速 m/s", padL - 8, padT - 12, C.waterInk, "end"),
    axisCaption("水深 m", W - padR + 8, padT - 12, C.cap),
  );

  // -- river bed and water -----------------------------------------------
  // The bed is the depth profile itself: at each measuring line the bed sits
  // exactly `depth` below the water surface, which is what the survey measured.
  const bedPts = lines
    .filter((l) => l.x !== null && l.depth !== null && l.depth >= 0)
    .map((l) => [sx(l.x), yDepth(l.depth)]);
  const sectionLeft = bedPts.length ? bedPts[0][0] : padL;
  const sectionRight = bedPts.length ? bedPts[bedPts.length - 1][0] : W - padR;
  if (bedPts.length >= 2) {
    const bedPath = [`M ${sectionLeft} ${H - padB}`]
      .concat(bedPts.map((p) => `L ${p[0]} ${p[1]}`))
      .concat([`L ${sectionRight} ${H - padB}`, "Z"])
      .join(" ");
    g.append(svgEl("path", { d: bedPath, fill: C.silt, "fill-opacity": 0.85, stroke: "none" }));

    // water body: the block between the water surface and the bed
    const waterPath = [`M ${sectionLeft} ${yWL}`]
      .concat(bedPts.map((p) => `L ${p[0]} ${p[1]}`))
      .concat([`L ${sectionRight} ${yWL}`, "Z"])
      .join(" ");
    g.append(svgEl("path", { d: waterPath, fill: C.water, "fill-opacity": 0.22, stroke: "none" }));
  }

  g.append(svgEl("line", {
    x1: sectionLeft, x2: sectionRight, y1: yWL, y2: yWL,
    stroke: C.water, "stroke-width": 1.4, "stroke-opacity": 0.75,
    "stroke-linecap": "round",
  }));

  // -- measuring lines ---------------------------------------------------
  // Each measuring line is drawn into the section, from the water surface down
  // to the bed, so the section shows where the lines are and how deep the water
  // is over each one.  Its measured velocity is in the velocity panel above.
  const lineGroup = svgEl("g");
  for (const line of lines) {
    if (line.x === null || line.depth === null || line.depth < 0.01) continue;
    const x = sx(line.x);
    lineGroup.append(svgEl("line", {
      x1: x, x2: x, y1: yWL, y2: yDepth(line.depth),
      stroke: C.water, "stroke-width": 1, "stroke-opacity": 0.42,
    }));
  }
  g.append(lineGroup);

  // -- dry lines ---------------------------------------------------------
  // No water over the line, so there is no column to draw: a tick at the surface
  // says the line exists and is dry, which is itself the physical finding.
  if (state.layers.dry) {
    const group = svgEl("g");
    for (const line of lines) {
      if (line.x === null || line.depth === null || line.depth >= 0.01) continue;
      const x = sx(line.x);
      group.append(svgEl("line", {
        x1: x, x2: x, y1: yWL - 1, y2: yWL + 4,
        stroke: C.hair, "stroke-width": 2.4, "stroke-opacity": 0.85,
        "stroke-linecap": "round",
      }));
    }
    if (group.children.length) g.append(group);
  }

  // -- velocity band, and the clip that ends it ---------------------------
  // Nothing is ever moved onto the edge: a value past a limited axis keeps its
  // own value and leaves the plot through the top, which the clip cuts cleanly.
  // Pinning those segments to the ceiling instead would stack readings of very
  // different value at one height, and a row of dots along the top edge reads as
  // though the channel had one anomalous speed rather than a few unusable ones.
  // The band reaches a few pixels past the water line so a reading floored at
  // zero is not sliced in half by its lower edge.
  const defs = svgEl("defs");
  const clip = svgEl("clipPath", { id: "vel-clip" });
  clip.append(svgEl("rect", {
    x: padL, y: padT, width: W - padL - padR, height: hVel + 4,
  }));
  defs.append(clip);
  svg.append(defs);
  const band = svgEl("g", { "clip-path": "url(#vel-clip)" });
  g.append(band);

  // -- reconstruction area -----------------------------------------------
  const profile = lines
    .filter((l) => l.x !== null && l[`pred_${armId}`] !== null && l[`pred_${armId}`] !== undefined)
    .map((l) => ({ x: sx(l.x), y: yVel(l[`pred_${armId}`]), v: l[`pred_${armId}`] }));
  if (state.layers.recon && profile.length >= 2) {
    const area = [`M ${profile[0].x} ${yWL}`]
      .concat(profile.map((p) => `L ${p.x} ${p.y}`))
      .concat([`L ${profile[profile.length - 1].x} ${yWL}`, "Z"])
      .join(" ");
    band.append(svgEl("path", { d: area, fill: C.water, "fill-opacity": 0.18, stroke: "none" }));
    const line = [`M ${profile[0].x} ${profile[0].y}`]
      .concat(profile.slice(1).map((p) => `L ${p.x} ${p.y}`))
      .join(" ");
    const path = svgEl("path", {
      d: line, fill: "none", stroke: C.water, "stroke-width": 2.1,
      "stroke-linecap": "round", "stroke-linejoin": "round",
      "stroke-linejoin": "round", "stroke-linecap": "round",
    });
    band.append(path);
    // one orchestrated reveal: the profile draws itself on load
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const length = path.getTotalLength ? path.getTotalLength() : 0;
      if (length) {
        path.style.strokeDasharray = length;
        path.style.strokeDashoffset = length;
        path.getBoundingClientRect();
        path.style.transition = "stroke-dashoffset .7s cubic-bezier(.22,.61,.36,1)";
        path.style.strokeDashoffset = 0;
      }
    }
  }

  // -- platform value ----------------------------------------------------
  if (state.layers.target) {
    const target = lines
      .filter((l) => l.x !== null && l.target !== null)
      .map((l) => ({ x: sx(l.x), y: yVel(l.target) }));
    if (target.length >= 2) {
      const d = [`M ${target[0].x} ${target[0].y}`]
        .concat(target.slice(1).map((p) => `L ${p.x} ${p.y}`))
        .join(" ");
      band.append(svgEl("path", {
        d, fill: "none", stroke: C.ink, "stroke-width": 1.25,
      "stroke-linecap": "round", "stroke-linejoin": "round",
        "stroke-dasharray": "5 3", "stroke-opacity": 0.85,
      }));
    }
  }

  // -- raw observations --------------------------------------------------
  // Every segment is drawn, at its measured value.  When the axis is limited the
  // ones past its top leave through the clip above rather than being pinned
  // onto the edge, and the caption says how many went and how to bring them
  // back - a reading held back without a word is a silent edit to the record.
  if (state.layers.raw) {
    const group = svgEl("g", { fill: C.field });
    for (const o of obs) {
      if (o.x === null || o.v === null) continue;
      group.append(svgEl("circle", {
        cx: sx(o.x), cy: yVel(o.v), r: 2.7, "fill-opacity": 0.78,
      }));
    }
    band.append(group);
  }

  // -- axes --------------------------------------------------------------
  const xTicks = niceTicks(x0, x1, Math.max(4, Math.round(W / 150)));
  for (const value of xTicks) {
    const x = sx(value);
    if (x < padL - 1 || x > W - padR + 1) continue;
    g.append(svgEl("line", { x1: x, x2: x, y1: H - padB, y2: H - padB + 4, stroke: C.cap, "stroke-width": 1 }));
    const label = svgEl("text", {
      x, y: H - padB + 17, "text-anchor": "middle", "font-size": 11.5, fill: C.tick,
    });
    label.textContent = Math.abs(value) >= 1000 ? value.toFixed(0) : value.toFixed(value % 1 ? 1 : 0);
    g.append(label);
  }
  const xCaption = svgEl("text", {
    x: W - padR, y: H - padB + 33, "text-anchor": "end", "font-size": 11, fill: C.tick,
  });
  xCaption.textContent = "起点距 m";
  g.append(xCaption);

  // line-level markers for the hover target
  const hoverLayer = svgEl("g", { class: "hover-layer" });
  g.append(hoverLayer);

  svg.append(svgEl("rect", {
    x: padL, y: padT, width: 0, height: 0, fill: "none", stroke: "none",
  }));

  // Under the title there used to be a paragraph: how many measuring lines, how
  // many of them algorithm lines against interpolated ones, how many the valve had
  // zeroed, how many readings the ceiling was holding back.  None of it was data.
  // The drawing already shows every line it has, and a reader who wants the count
  // can count the marks in the strip below.  The one part that was a genuine
  // disclosure - readings held out of the picture - belonged on the switch that
  // holds them, not in a sentence three inches away from it.  So the count is a
  // badge on that switch and the sentence is its tooltip, and nothing is written
  // here at all.  The rule the panel now follows: the figure states numbers, and
  // a sentence has to earn a place on the page or live in a `title`.
  renderAxisBadge(hiddenRaw + hiddenLines, vMax);

  renderLegend(payload);
  renderScale(payload);
  renderStrip(payload, { W, padL, padR, sx });
  attachHover(svg, payload, { sx, yVel, yWL, W, H, padL, padR, padT, padB, armId });
  // the drawing is most of the board's height, so this is the repaint that
  // matters for the page's own scroll edge
  paintScrollEdges();
}

// One count, on the control that causes it.  This is the only place on the page
// where a reading is kept out of the picture, so it is the only place that has to
// say so - and it says it as a number attached to the switch that did it, which is
// where a reader who wonders "is this all of it?" will already be looking.  The
// sentence that used to say it is now the switch's tooltip: a reader who wants the
// threshold and the way back can ask for them, and a reader who does not is not
// made to read past them.
function renderAxisBadge(held, vMax) {
  const badge = el("axis-badge");
  badge.textContent = held ? String(held) : "";
  badge.hidden = !held;
  badge.textContent = held ? String(held) : "";
  el("axis-switch").title = held
    ? `流速轴只到模型重建与平台标定值的范围，超过 ${num(vMax, 1)} m/s 的 ${held} 个读数`
      + `（原始分段与重建值合计）已移出画面。取消勾选可让流速轴跨全部原始观测值。`
    : "流速轴只到模型重建与平台标定值的范围；本测次没有读数被移出画面。"
      + "取消勾选可让流速轴跨全部原始观测值。";
}

function niceTicks(lo, hi, count) {
  if (!finite(lo) || !finite(hi) || hi <= lo) return [lo];
  const raw = (hi - lo) / Math.max(1, count);
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) || magnitude * 10;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 0.001; v += step) {
    ticks.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  }
  return ticks;
}

// A tick label has to state the tick's actual value: niceTicks can return steps
// of 0.025 or 2.5, and rounding those to one decimal mislabels the axis (and the
// self-check, which reads the scale back off the labels, would be reading a
// scale nobody drew).  So print the fewest decimals that round-trip.
function tickLabel(value) {
  for (let digits = 0; digits <= 4; digits += 1) {
    if (Number(value.toFixed(digits)) === value) return value.toFixed(digits);
  }
  return String(value);
}

function renderLegend(payload) {
  const host = el("plot-legend");
  host.textContent = "";
  const arm = state.arms.find((a) => a.id === state.activeArm) || { label: state.activeArm };
  const items = [
    state.layers.recon ? { cls: "", color: C.water, label: `模型重建 · ${arm.label}` } : null,
    state.layers.target ? { cls: "dash", color: C.ink, label: "平台标定值" } : null,
    state.layers.raw ? { cls: "swatch", color: C.field, label: "原始测速线观测" } : null,
    { cls: "hair", color: C.water, label: "断面测速线（长度 = 水深）" },
    state.layers.dry ? { cls: "hatch", color: C.dry, label: "枯水线（水深 < 1 cm）" } : null,
  ].filter(Boolean);
  for (const item of items) {
    const span = document.createElement("span");
    const mark = document.createElement("i");
    mark.className = item.cls;
    if (item.cls === "swatch") mark.style.background = item.color;
    else mark.style.borderTopColor = item.color;
    span.append(mark, document.createTextNode(item.label));
    host.append(span);
  }
}

function renderScale(payload) {
  const summary = payload.observations_summary;
  el("plot-scale").textContent = "";
  const left = document.createElement("span");
  left.textContent = `原始观测 p5 ${num(summary.p05)} · 中位 ${num(summary.median)} · p95 ${num(summary.p95)} m/s`;
  // The source used to be named here a third time, after the picker's own
  // 已入库/实时 switch and the rail.  Three statements of one fact is not
  // emphasis, it is clutter, and the reader is already standing on the switch
  // that decides it.
  el("plot-scale").append(left);
}

/* -- residual + grounding strip ------------------------------------------ */

function renderStrip(payload, geo) {
  const host = el("strip");
  const W = geo.W;
  const H = 84;
  const top = 22;
  const bottom = 62;
  const svg = el("strip-svg");
  svg.textContent = "";
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W);
  svg.setAttribute("height", H);

  const armId = state.activeArm;
  const rows = payload.lines
    .filter((l) => l.x !== null && l.target !== null && l[`pred_${armId}`] !== null)
    .map((l) => ({ x: geo.sx(l.x), target: l.target, pred: l[`pred_${armId}`], diff: l[`pred_${armId}`] - l.target }));
  if (!rows.length) return;

  const span = Math.max(1.2, ...rows.map((r) => Math.abs(r.diff)));
  const band = bottom - top;
  const yFor = (d) => top + band / 2 - (d / span) * (band / 2);

  const threshold = payload.disagreement_threshold;
  for (const value of [threshold, -threshold]) {
    const y = yFor(value);
    if (y < top - 1 || y > bottom + 1) continue;
    svg.append(svgEl("line", {
      x1: geo.padL, x2: W - geo.padR, y1: y, y2: y, stroke: C.flag,
      "stroke-width": 1, "stroke-dasharray": "3 3", "stroke-opacity": 0.55,
    }));
  }
  const zero = yFor(0);
  svg.append(svgEl("line", { x1: geo.padL, x2: W - geo.padR, y1: zero, y2: zero, stroke: C.cap, "stroke-width": 1 }));

  for (const row of rows) {
    const y = yFor(row.diff);
    const flagged = Math.abs(row.diff) > threshold;
    svg.append(svgEl("line", {
      x1: row.x, x2: row.x, y1: zero, y2: y,
      stroke: flagged ? C.flag : C.water,
      "stroke-width": 1.7, "stroke-opacity": flagged ? 0.9 : 0.5,
    }));
  }

  const cap = svgEl("text", { x: geo.padL - 8, y: top + 4, "text-anchor": "end", "font-size": 11, fill: C.tick });
  cap.textContent = "残差 m/s";
  svg.append(cap);
  const hi = svgEl("text", { x: W - geo.padR + 6, y: yFor(threshold) + 3.5, "font-size": 11, fill: C.flag });
  hi.textContent = `±${threshold.toFixed(1)}`;
  svg.append(hi);

  svg.append(svgEl("line", {
    x1: geo.padL, x2: W - geo.padR, y1: 72, y2: 72, stroke: C.grid, "stroke-width": 1,
  }));
  for (const line of payload.lines) {
    if (line.x === null) continue;
    const x = geo.sx(line.x);
    if (line.algo) {
      svg.append(svgEl("rect", { x: x - 1.4, y: 74, width: 2.8, height: 7, rx: 1.4, fill: C.water, "fill-opacity": 0.85 }));
    } else {
      svg.append(svgEl("rect", {
        x: x - 1.4, y: 74, width: 2.8, height: 7, fill: "none",
        stroke: C.cap, "stroke-width": 0.9,
        "stroke-linejoin": "round",
      }));
    }
  }
  const groundCap = svgEl("text", { x: geo.padL - 8, y: 80, "text-anchor": "end", "font-size": 11, fill: C.tick });
  groundCap.textContent = "输入";
  svg.append(groundCap);

  // Four sentences became three words and a count.  The strip carries its own axis
  // caption ("残差 m/s") and prints the threshold on the rule itself, so a legend
  // that repeats either of them is reading the figure back to the reader - which is
  // what the first two entries were doing.  All that is left for the legend to say
  // is what the marks mean, and what a mark's definition adds over its name goes in
  // the tooltip.  The list is one line of the page and now reads like one.
  const flagged = rows.filter((r) => Math.abs(r.diff) > threshold).length;
  const key = el("strip-key");
  key.textContent = "";
  const legendItems = [
    {
      swatch: C.flag,
      label: `送复核 ${flagged} 条`,
      hint: `残差超过 ±${threshold.toFixed(1)} m/s 的测速线送人工复核，本测次 ${flagged} 条；`
        + "其余测速线的残差以下方的蓝色柱表示。",
    },
    { swatch: C.water, label: "算法线", hint: "该线有原始观测输入，模型据此重建。" },
    { hollow: true, label: "插值线", hint: "该线无原始观测输入，模型由断面上下文推断。" },
  ];
  for (const item of legendItems) {
    const span = document.createElement("span");
    const mark = document.createElement("i");
    // `solid` used to be its own flag and it set no colour, so the one entry that
    // needed a filled swatch drew an invisible square.  The filled marks are the
    // same blue as the bars they stand for.
    if (item.hollow) mark.className = "hollow";
    else mark.style.background = item.swatch;
    span.title = item.hint;
    span.append(mark, document.createTextNode(item.label));
    key.append(span);
  }
}

/* -- hover --------------------------------------------------------------- */

function attachHover(svg, payload, geo) {
  const tip = el("tip");
  const guide = svgEl("line", {
    y1: GEOM.padT - 6, y2: GEOM.height - GEOM.padB,
    stroke: C.ink, "stroke-width": 1, "stroke-opacity": 0.32, "stroke-dasharray": "3 3",
  });
  const marker = svgEl("circle", { r: 4.2, fill: "none", stroke: C.ink, "stroke-width": 1.6 });
  const layer = svg.querySelector(".hover-layer");
  layer.append(guide, marker);
  guide.style.display = marker.style.display = "none";

  const lines = payload.lines.filter((l) => l.x !== null);
  const positions = lines.map((l) => geo.sx(l.x));

  const pick = (clientX) => {
    const rect = svg.getBoundingClientRect();
    const local = ((clientX - rect.left) / rect.width) * svg.viewBox.baseVal.width;
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < positions.length; i += 1) {
      const dist = Math.abs(positions[i] - local);
      if (dist < bestDist) { bestDist = dist; best = i; }
    }
    return { line: lines[best], x: positions[best], rect };
  };

  const show = (event) => {
    const { line, x, rect } = pick(event.clientX);
    if (!line) return;
    const scale = rect.width / svg.viewBox.baseVal.width;
    guide.setAttribute("x1", x); guide.setAttribute("x2", x);
    const pred = line[`pred_${geo.armId}`];
    marker.setAttribute("cx", x);
    // the marker is a pointer, not a reading, so it is held at the top of the
    // band when its line is off-scale - the readout beside it still gives the
    // true value, whereas an unclamped marker would float in the axis caption
    marker.setAttribute("cy", Math.max(geo.padT, geo.yVel(pred ?? line.target ?? 0)));
    guide.style.display = marker.style.display = "";

    const diff = pred !== null && line.target !== null ? pred - line.target : null;
    const flagged = diff !== null && Math.abs(diff) > payload.disagreement_threshold;
    const rows = [
      ["起点距", `${num(line.x, 1)} m`],
      ["水深", line.depth === null ? "—" : `${num(line.depth, 2)} m`],
      ["模型重建", pred === null ? "—" : `${num(pred, 3)} m/s${line.valved ? "（阀门归零）" : ""}`],
      ["平台标定值", line.target === null ? "—" : `${num(line.target, 3)} m/s`],
      ["差值", diff === null ? "—" : `${diff >= 0 ? "+" : ""}${num(diff, 3)}`],
      ["原始分段", `${line.n_raw} 个`],
    ];
    tip.textContent = "";
    const head = document.createElement("b");
    head.textContent = `测速线 #${line.i + 1} · ${line.algo ? "算法线" : "插值线"}`;
    tip.append(head);
    for (const [key, value] of rows) {
      const span = document.createElement("span");
      const em = document.createElement("em");
      em.textContent = key;
      const val = document.createElement("span");
      val.textContent = value;
      if (key === "差值" && flagged) val.className = "is-flag";
      span.append(em, val);
      tip.append(span);
    }
    tip.hidden = false;
    const tipX = x * scale + 14;
    const tipY = (geo.yVel(pred ?? line.target ?? 0)) * scale + 8;
    tip.style.left = `${Math.min(tipX, rect.width - 176)}px`;
    tip.style.top = `${Math.max(0, Math.min(tipY, rect.height - 150))}px`;
  };

  svg.addEventListener("mousemove", show);
  svg.addEventListener("mouseleave", () => {
    tip.hidden = true;
    guide.style.display = marker.style.display = "none";
  });
}

/* -- readout ------------------------------------------------------------- */

const READOUT_COLUMNS = [
  { key: "rmse", label: "RMSE", digits: 3, better: "low" },
  { key: "mae", label: "MAE", digits: 3, better: "low" },
  { key: "bias", label: "偏差", digits: 3, better: "abs" },
  { key: "nse", label: "NSE", digits: 3, better: "high" },
  { key: "max_abs", label: "最大偏差", digits: 3, better: "low" },
  { key: "disagreement", label: `分歧线 >${(state.payload?.disagreement_threshold ?? 1).toFixed(1)}`, digits: 0, better: "low" },
];

function renderReadout(payload) {
  const host = el("readout-table");
  host.textContent = "";
  // The live channel shows the section as the platform hands it over.  This panel
  // scores every arm against the platform's own value as though that value were a
  // reference, and a timestamp pulled straight off the platform has not been
  // through the corpus's review - so a score against it is not a score, and the
  // panel is not part of the live view.  The gate is the payload's own source
  // field rather than the tab the reader is on: it is what the section actually
  // came from, so no call site has to remember the rule.
  const live = payload.source === "live";
  el("readout").hidden = live;
  if (live) { el("readout-head").title = ""; return; }
  const armIds = Object.keys(payload.metrics);
  if (!armIds.length) return;

  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.append(thText("模型"));
  for (const column of READOUT_COLUMNS) headRow.append(thText(column.label));
  head.append(headRow);
  host.append(head);

  const body = document.createElement("tbody");
  const best = {};
  for (const column of READOUT_COLUMNS) {
    const values = armIds.map((id) => payload.metrics[id][column.key]).filter(finite);
    if (!values.length) continue;
    best[column.key] = column.better === "high" ? Math.max(...values)
      : column.better === "abs" ? values.reduce((a, b) => (Math.abs(a) <= Math.abs(b) ? a : b))
        : Math.min(...values);
  }

  for (const armId of armIds) {
    const arm = state.arms.find((a) => a.id === armId) || { label: armId, note: "" };
    const metrics = payload.metrics[armId];
    const tr = document.createElement("tr");
    if (armId === state.activeArm) tr.className = "is-active";
    const nameCell = document.createElement("td");
    nameCell.textContent = arm.label;
    // the same one-word expansion as the pill above, and for the same reason: a
    // tooltip is not an annotation on the page
    nameCell.title = arm.note || "";
    tr.append(nameCell);
    for (const column of READOUT_COLUMNS) {
      const value = metrics[column.key];
      const cell = document.createElement("td");
      cell.textContent = finite(value) ? Number(value).toFixed(column.digits) : "—";
      if (finite(value) && Math.abs(value - best[column.key]) < 1e-9) cell.className = "best";
      if (column.key === "disagreement" && value > 0) cell.className += " bad";
      tr.append(cell);
    }
    body.append(tr);
  }
  host.append(body);

  const valved = payload.meta.n_valved || 0;
  // Three sentences stood under this table - what the metrics were computed on,
  // what the platform's value is worth as a reference, and what the valve did to
  // the absolute numbers.  The first two are what a reader works out from the
  // table itself or from the column names; the third is the one that changes how
  // the numbers may be used, and the three were read as one grey block and
  // skipped.  So the table keeps a heading and nothing else, and the caveats hang
  // off that heading's tooltip, one hover away, at no cost to the page.
  el("readout-head").title =
    `指标在本次测次的 ${payload.lines.length} 条测速线上计算；RMSE / MAE / 偏差 / 最大偏差单位 m/s，`
    + "NSE 无量纲。平台标定值是人工产物、本身带噪，所以「分歧线」是提示人工复核的标记，不等于模型错。"
    + (valved
      // these lines were zeros before the metrics were taken, so they flatter
      // every arm equally and the comparison between arms is unaffected - but
      // the absolute numbers no longer match the training report's
      ? `其中 ${valved} 条无水深测速线已由阀门强制归零后才计入，因此这里的绝对值`
        + "与训练报告的同期数字不可直接比较（三个模型受同样影响，横向比较不受影响）。"
      : "");
}

function thText(text) {
  const th = document.createElement("th");
  th.textContent = text;
  return th;
}

/* -- observations -------------------------------------------------------- */

function renderObservations(payload) {
  const host = el("obs-table");
  host.textContent = "";
  // the segment-by-segment list is the reviewer's material for a stored
  // measurement; on a live timestamp it is a wall of numbers taken seconds ago
  // off a device nobody has checked, and the panel's job there is to show what the
  // model made of the section.  Gated on the payload's own source, as above.
  const live = payload.source === "live";
  el("obs").hidden = live;
  if (live) { el("obs-count").textContent = ""; return; }
  const armId = state.activeArm;
  const byLine = new Map();
  for (const o of payload.observations) {
    if (!byLine.has(o.line)) byLine.set(o.line, []);
    byLine.get(o.line).push(o);
  }
  el("obs-count").textContent = `${int(payload.observations_summary.n)} 个分段 / ${byLine.size} 条测速线`;

  const wrap = document.createElement("div");
  wrap.className = "obs-scroll scroll-well";
  const table = document.createElement("table");

  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.append(thText("测速线"), thText("起点距 m"), thText("原始流速 m/s"), thText("置信度"),
    thText("时段 s"), thText("重建 m/s"), thText("平台值 m/s"), thText("差值"));
  head.append(headRow);
  table.append(head);

  const body = document.createElement("tbody");
  const lines = payload.lines.filter((l) => byLine.has(l.i));
  for (const line of lines) {
    const pred = line[`pred_${armId}`];
    const diff = pred !== null && line.target !== null ? pred - line.target : null;
    const flagged = diff !== null && Math.abs(diff) > payload.disagreement_threshold;
    const entries = byLine.get(line.i);
    entries.forEach((o, index) => {
      const tr = document.createElement("tr");
      if (flagged) tr.className = "is-flagged";
      const first = index === 0;
      tr.append(tdText(first ? `#${line.i + 1}` : "", !first));
      tr.append(tdText(num(o.x, 1), !first));
      tr.append(tdText(num(o.v, 3), false));
      tr.append(tdText(num(o.confidence, 2), false));
      tr.append(tdText(num(o.t, 0), false));
      tr.append(tdText(first && pred !== null ? num(pred, 3) : "", !first, first && flagged));
      tr.append(tdText(first && line.target !== null ? num(line.target, 3) : "", !first));
      tr.append(tdText(first && diff !== null ? `${diff >= 0 ? "+" : ""}${num(diff, 3)}` : "", !first, first && flagged));
      body.append(tr);
    });
  }
  table.append(body);
  wrap.append(table);
  host.append(wrap);
  // There is no caption under this table.  It was two sentences - how many rows,
  // and what a red row means - and both were already on the page: the count is in
  // the heading above and the red rows are the strip's 送复核 marks, named in its
  // key.  What was left after that cut was six characters floating under the card
  // ("按测速线分组"), which is the shape of every annotation the reader has asked to
  // be rid of: a fragment saying something the table says by itself, in the first
  // column, on every row.  So the grouping is the table's accessible name instead,
  // where it labels the table without being read at anyone.
  table.setAttribute("aria-label", "按测速线分组的原始观测");
  // this runs last of the four board renderers, so it is also where the page's
  // own scroll edge is repainted - the table it just added is the last thing
  // to change how far down the board goes
  paintScrollEdges();
}

function tdText(text, dim, flagged = false) {
  const td = document.createElement("td");
  td.textContent = text;
  if (dim) td.className = "dim";
  if (flagged) td.className += " bad";
  return td;
}

/* -- boot ---------------------------------------------------------------- */

/* The panel opens on a live reconstruction, not on an empty sheet.
 *
 * The service is asked which live device-days on today's date are newest, and
 * the newest of those that can actually be drawn is what the board opens with.
 * Asking rather than guessing is the whole point: the panel has no way to know
 * on its own which gauges are reporting this afternoon, and the picker's first
 * station is overwhelmingly likely to be one that is not.
 *
 * "The newest one that draws" rather than "the newest one", because a live
 * timestamp is refused routinely - the export 500s, the calibration is flat,
 * the quality check rejects it - so opening the newest and stopping would leave
 * the panel showing a platform error on arrival most days, which is worse than
 * showing the newest one that worked.  The walk is bounded by the service,
 * which hands back five candidates at most, and each refusal costs about a
 * second: a reader who sees the panel settle on the fourth has still waited
 * less time than one page of the stored corpus takes to draw.
 *
 * Every failure is left on the board rather than swallowed.  If nothing on the
 * day can be drawn, the empty state says so in the platform's own terms and
 * leaves the picker on a station the reader can browse from. */
async function openLatestLive() {
  setBusy(true, "正在找今天最新的实时测次…");
  const seq = state.navSeq;   // a reader click during the walk takes over: bail
  let found = null;
  try {
    found = await api("/api/live/latest", { date: state.liveDate });
  } catch (error) {
    found = null;
  }
  if (seq !== state.navSeq) return false;

  const candidates = (found && found.candidates) || [];
  for (const candidate of candidates) {
    if (seq !== state.navSeq) return false;
    const station = state.stations.find((s) => s.code === candidate.station);
    if (!station) continue;
    await selectStation(station, candidate.device);
    // the reader may have clicked while that list was being pulled - the walk
    // is over the moment the panel answers to somebody else
    if (seq !== state.navSeq) return false;
    // the live list is newest-first, so the row this candidate named is in it
    const row = state.measurements.find((r) => r.time === candidate.time);
    if (!row) continue;
    if (await selectMeasurement(row)) return true;
  }

  // nothing today: say what the live channel found, and let the reader move on
  // rather than sit in front of a board that looks broken.  A takeover during
  // the last candidate's export lands here too - say nothing over their view.
  if (seq !== state.navSeq) return false;
  el("board-empty-line").textContent = candidates.length
    ? `${state.liveDate} 的实时测次都没有重建出来。`
    : (found && found.reason) || `${state.liveDate} 还没有实时测次。`;
  el("board-empty-sub").textContent =
    "换一天，或者切到 已入库 看历史测次；左边选站点和测次也可以。";
  // put the picker on a station first so neither list is left empty - then put
  // the empty panel back, because `loadMeasurements` hides it on the way out
  // and has nothing of its own to replace it with
  if (state.stations.length && !state.station) await selectStation(state.stations[0]);
  if (seq !== state.navSeq) return false;
  setBusy(false);
  showEmpty();
  return false;
}

async function boot() {
  // the wells are in the markup before any data is: this gives them their
  // scroll listeners and their first, bare edge state
  paintScrollEdges();
  try {
    const meta = await api("/api/meta");
    state.meta = meta;
    state.arms = (meta.arms || []).filter((a) => true);
    const available = state.arms.filter((a) => a.available);
    state.activeArm = available.length ? available[0].id : (state.arms[0] || { id: ARMS_FALLBACK[0] }).id;
    renderArms();
    renderSource();
  } catch (error) {
    showError("服务没有响应", error.message);
    return;
  }

  try {
    const data = await api("/api/stations", { limit: 500 });
    state.stations = data.stations || [];
    renderStations();
    if (!state.stations.length) {
      showError("没有可用站点", "索引里没有任何站点。先在 tools/ 里跑一次拉取，然后用 --rebuild-index 重启服务。");
      return;
    }
    await openLatestLive();
  } catch (error) {
    showError("读不到站点列表", error.message);
  }
}

/* -- wiring -------------------------------------------------------------- */

let searchTimer = null;
el("station-search").addEventListener("input", (event) => {
  const value = event.target.value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    try {
      const data = await api("/api/stations", { q: value, limit: 500 });
      state.stations = data.stations || [];
      renderStations();
    } catch (error) {
      showError("站点搜索失败", error.message);
    }
  }, 160);
});

el("error-retry").addEventListener("click", () => {
  state.navSeq += 1;
  if (state.station) selectStation(state.station);
  else boot();
});

el("src-cache").addEventListener("click", () => setSource("cache"));
el("src-live").addEventListener("click", () => setSource("live"));
el("export-btn").addEventListener("click", exportCurrent);
el("live-date").addEventListener("change", (event) => {
  state.liveDate = event.target.value || todayISO();
  event.target.value = state.liveDate;
  // the day changed, so the section on the board is about a day the picker is
  // no longer showing
  state.navSeq += 1;
  state.payload = null;
  if (state.source === "live" && state.station) loadMeasurements();
});

function bindLayer(id, key) {
  el(id).addEventListener("change", (event) => {
    state.layers[key] = event.target.checked;
    if (state.payload) renderChart(state.payload);
  });
}
bindLayer("show-recon", "recon");
bindLayer("show-target", "target");
bindLayer("show-raw", "raw");
bindLayer("show-dry", "dry");

el("limit-axis").addEventListener("change", (event) => {
  state.axisLimit = event.target.checked;
  if (state.payload) renderChart(state.payload);
});

el("layers-toggle").addEventListener("click", () => {
  const menu = el("layers-menu");
  const open = menu.hidden;
  menu.hidden = !open;
  el("layers-toggle").setAttribute("aria-expanded", String(open));
  el("scrim").hidden = !open;
});
el("scrim").addEventListener("click", () => {
  el("layers-menu").hidden = true;
  el("layers-toggle").setAttribute("aria-expanded", "false");
  el("scrim").hidden = true;
});

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (state.payload) renderChart(state.payload); }, 180);
});

boot();
