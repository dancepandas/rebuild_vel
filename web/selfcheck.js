/* Geometry self-check for the section plot.
 *
 * The drawing code cannot be eyeballed without a browser, so this runs the
 * real renderChart() against real API payloads under a minimal DOM stub and
 * asserts that the emitted coordinates describe the drawing we intend: every
 * number finite, everything inside the frame, the water body below the water
 * line, one measuring line per wet line and as deep as the survey says, one
 * point per reconstruction, one dot per raw segment, and the depth and velocity
 * scales readable back off the drawing.
 *
 *   node web/selfcheck.js [http://127.0.0.1:8760] [--sweep N] [--live YYYY-MM-DD [--live-stations N]]
 *
 * Without --sweep it inspects one station in full detail.  With it, N random
 * measurements are inspected quietly as well - the corpus runs from a 100-line
 * flood section to a handful of dry lines, and the panel has to hold up on all
 * of them, not on the tidy example.  --live checks the other data source: a
 * handful of real device-days pulled straight off the platform for that date.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const argv = process.argv.slice(2);
const sweepFlag = argv.indexOf("--sweep");
const SWEEP = sweepFlag >= 0 ? Number(argv[sweepFlag + 1] || 12) : 0;
const liveFlag = argv.indexOf("--live");
const LIVE = liveFlag >= 0 ? argv[liveFlag + 1] : null;
const liveStationsFlag = argv.indexOf("--live-stations");
const LIVE_STATIONS = liveStationsFlag >= 0 ? Number(argv[liveStationsFlag + 1] || 6) : 6;
const BASE = argv.find((a) => a.startsWith("http")) || "http://127.0.0.1:8760";

// -- minimal DOM ---------------------------------------------------------
function makeNode(name) {
  const node = {
    nodeName: name,
    children: [],
    attrs: {},
    style: {},
    dataset: {},
    _text: "",
    hidden: false,
    className: "",
    value: "",
    checked: true,
    disabled: false,
    clientWidth: 1180,
    clientHeight: 474,
    // `classList` is real rather than a stub: the scroll wells are the one
    // thing on the page whose state lives *only* in a class, and a stub that
    // silently swallowed `toggle` would let a broken edge shadow pass.  The
    // set is kept beside `className` rather than inside it, so the checks that
    // read `className` for structural classes still see exactly what app.js
    // assigned.
    classList: {
      _set: new Set(),
      add(...names) { for (const name of names) this._set.add(name); },
      remove(...names) { for (const name of names) this._set.delete(name); },
      contains(name) { return this._set.has(name); },
      toggle(name, force) {
        const on = force === undefined ? !this._set.has(name) : Boolean(force);
        if (on) this._set.add(name); else this._set.delete(name);
        return on;
      },
    },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k]; },
    append(...kids) { this.children.push(...kids); },
    appendChild(kid) { this.children.push(kid); return kid; },
    // listeners are kept so a check can fire the control it is asserting about -
    // otherwise it can only read the label and never know the wiring is dead
    listeners: {},
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    querySelector(selector) {
      const want = selector.replace(/^\./, "");
      let found = null;
      const search = (n) => {
        for (const kid of n.children) {
          if (found) return;
          if ((kid.attrs.class || kid.className || "").split(/\s+/).includes(want)) { found = kid; return; }
          search(kid);
        }
      };
      search(this);
      return found;
    },
    querySelectorAll: () => [],
    scrollIntoView() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1180, height: 474 }),
    getTotalLength: () => 0,
    focus() {},
    remove() {},
  };
  // renderChart clears the svg with `svg.textContent = ""`, so the setter has to
  // drop the children the way a real node does - otherwise every redraw stacks
  // on the last one and the walk below counts the whole history
  Object.defineProperty(node, "textContent", {
    get() {
      if (this._text) return this._text;
      return this.children.map((k) => k.textContent || "").join("");
    },
    set(value) {
      this._text = String(value == null ? "" : value);
      this.children.length = 0;
    },
  });
  return node;
}

const byId = new Map();

/* Every element the page has asked for, walked as a forest.  The nodes
   `getElementById` hands out are roots with no parent, so a selector search has
   to start from each of them and include the root itself - `#board` carries the
   scroll class on the element the markup names, not on a child. */
function findAll(selector) {
  const want = selector.replace(/^\./, "");
  const out = [];
  const visit = (node) => {
    if ((node.attrs.class || node.className || "").split(/\s+/).includes(want)) out.push(node);
    for (const kid of node.children) visit(kid);
  };
  for (const root of byId.values()) visit(root);
  return out;
}

const document = {
  getElementById(id) {
    if (!byId.has(id)) byId.set(id, makeNode("div#" + id));
    return byId.get(id);
  },
  createElement: (n) => makeNode(n),
  createElementNS: (_ns, n) => makeNode(n),
  createTextNode: (text) => ({ nodeName: "#text", textContent: text, children: [], attrs: {}, style: {} }),
  querySelector: () => null,
  querySelectorAll: findAll,
  addEventListener() {},
};
const window = {
  location: { origin: BASE },
  matchMedia: () => ({ matches: true }), // reduced motion: skip the draw-in
  addEventListener() {},
  setTimeout, clearTimeout,
};
const URL_ = URL;

// -- load app.js with boot() suppressed ----------------------------------
let source = fs.readFileSync(path.join(__dirname, "static", "app.js"), "utf8");
source = source.replace(/\nboot\(\);\s*$/, "\n/* boot suppressed by selfcheck */\n");
source += "\nglobalThis.__app = { state, C, renderChart, renderStrip, renderReadout, renderObservations, renderTitleblock, renderArms, renderMeasurements, loadMeasurements, setSource, liveReason, openLatestLive, paintScrollEdges };\n";

const sandbox = {
  document, window, console, setTimeout, clearTimeout, URL: URL_, Number, Math, JSON, Object, Array, Map, Set, isFinite, NaN, Infinity,
  fetch: (...a) => fetch(...a),
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: "app.js" });
const app = sandbox.__app;
// the figure's palette, read from the source rather than copied out by hand:
// a colour the checks spell for themselves is a colour that can change without
// them noticing.
const C = app.C;

// -- walk the tree -------------------------------------------------------
function walk(node, visit) {
  visit(node);
  for (const kid of node.children) walk(kid, visit);
}

function collect(node, name, out = []) {
  walk(node, (n) => { if (n.nodeName === name) out.push(n); });
  return out;
}

const num = (v) => (v === undefined || v === null || v === "" ? NaN : Number(v));
const POLYLINE = /^M [\d.\-e]+ [\d.\-e]+(?: L [\d.\-e]+ [\d.\-e]+)+(?: Z)?$/;

/* Inspect one drawn payload.  Returns a list of complaints; empty means the
 * drawing says what we meant it to say.  ``axisLimit`` is the 流速轴上限 setting
 * the drawing is made under - the two settings are two different drawings of the
 * same payload, and each is inspected.
 *
 * The velocity ceiling recovered from the drawing is left in ``lastAxis`` for
 * the cross-mode comparison, since neither setting can check itself. */
let lastAxis = { vMax: NaN, heldBack: 0 };

function inspect(payload, axisLimit) {
  const bad = [];
  const note = (message) => bad.push(message);
  app.state.axisLimit = axisLimit;

  // the same geometry constants app.js draws with, restated here as a cross-check
  const padL = 64, padR = 96, padT = 28, padB = 44;
  app.renderChart(payload);
  const svg = byId.get("section-svg");
  const W = num(svg.attrs.width);
  const H = num(svg.attrs.height);
  const hVel = (H - padT - padB) * 0.46;      // GEOM.velFrac
  const hSec = (H - padT - padB) - hVel;
  const yWL = padT + hVel;

  // the band group and everything under it: a limited axis lets the values past
  // its top run out of the frame, which is the overflow leaving the plot, so the
  // in-frame rule below cannot apply to them - the clip ends the drawing there
  const clipped = new Set();
  walk(svg, (n) => {
    if (!n.attrs["clip-path"]) return;
    const mark = (node) => { clipped.add(node); for (const kid of node.children) mark(kid); };
    mark(n);
  });

  // 1. viewport
  if (!(W > 500 && H > 300)) note(`svg viewport is ${W}x${H}`);

  // 2. every coordinate finite and sane
  walk(svg, (n) => {
    for (const key of ["x", "y", "x1", "y1", "x2", "y2", "cx", "cy"]) {
      if (n.attrs[key] === undefined) continue;
      const value = num(n.attrs[key]);
      if (!isFinite(value) || Math.abs(value) > 50 * Math.max(W, H)) {
        note(`coordinate ${key}=${n.attrs[key]} on <${n.nodeName}> is not a number`);
      }
    }
  });

  // 3. paths parse and stay in frame.  Two shapes are legitimate: closed area
  //    paths (bed, water, reconstruction area - they end in Z) and open
  //    polylines (the reconstruction stroke and the platform value, which have
  //    no Z because they are lines, not regions).
  const paths = collect(svg, "path");
  for (const p of paths) {
    const d = p.attrs.d || "";
    if (!POLYLINE.test(d)) {
      note(`malformed path: len=${d.length} head=${JSON.stringify(d.slice(0, 42))}`);
      continue;
    }
    for (const pair of d.replace(/ Z$/, "").match(/[\d.\-e]+ [\d.\-e]+/g) || []) {
      const [x, y] = pair.split(" ").map(Number);
      // above the frame is only wrong outside the clipped band; below it never is
      const top = clipped.has(p) ? -Infinity : -20;
      if (!isFinite(x) || !isFinite(y) || y < top || y > H + 20) {
        note(`path point out of frame: (${x}, ${y})`);
      }
    }
  }

  // 4. the water polygon never rises above the water line.  It cannot: every
  //    vertex is either a surveyed depth (which is >= 0 by construction) or the
  //    water line itself.  That is the point of the depth scale - the old
  //    elevation scale could put the bed above the surface on a dry line.
  const waterPath = paths.find((p) => (p.attrs.d || "").includes("Z")
    && p.attrs.fill === C.water && p.attrs["fill-opacity"] === "0.22");
  if (!waterPath) note("no water polygon drawn");
  else {
    const ys = (waterPath.attrs.d.match(/[\d.\-e]+ ([\d.\-e]+)/g) || [])
      .map((s) => Number(s.split(" ")[1]));
    const above = ys.filter((y) => y < yWL - 0.6).length;
    if (above) note(`water polygon has ${above} vertices above the water line`);
  }

  // 5. one point on the reconstruction per line that has a prediction
  const armId = app.state.activeArm;
  const recon = paths.find((p) => p.attrs.fill === "none" && p.attrs.stroke === C.water
    && (p.attrs.d || "").startsWith("M"));
  const predicted = payload.lines.filter((l) => l[`pred_${armId}`] !== null && l.x !== null).length;
  if (predicted >= 2) {
    if (!recon) note("no reconstruction stroke drawn");
    else {
      const n = (recon.attrs.d.match(/ L /g) || []).length + 1;
      if (n !== predicted) note(`reconstruction has ${n} points, expected ${predicted}`);
    }
  }

  // 6. every raw segment is a dot at its own value.  Nothing is dropped, nothing
  //    is marked with a symbol of its own, and nothing is pinned to the top edge.
  const dots = collect(svg, "circle").filter((c) => num(c.attrs.r) === 2.7);
  const withV = payload.observations.filter((o) => o.x !== null && o.v !== null && isFinite(o.v));
  if (dots.length !== withV.length) {
    note(`${dots.length} dots for ${withV.length} plottable observations`);
  }
  const strayFlag = [...collect(svg, "path"), ...collect(svg, "circle"), ...collect(svg, "line")]
    .filter((n) => n.attrs.fill === C.flag || n.attrs.stroke === C.flag);
  if (strayFlag.length) note(`${strayFlag.length} off-scale triangle marks are still drawn`);

  // 7. the two scales are recovered from the drawing itself - the tick labels are
  //    the only place either axis is observable - and then used to check the
  //    geometry they describe.
  const velTicks = collect(svg, "text").filter((t) =>
    num(t.attrs.x) === padL - 8 && num(t.attrs["font-size"]) === 11.5 && t.attrs.fill === C.tick);
  let vMax = NaN;
  // the highest tick is the one held on to: its label is what the recovery below
  // is scaled from, and it is also the label whose rounding is amplified most
  let topTick = { text: "", value: NaN, vMax: NaN };
  for (const t of velTicks) {
    const v = Number(t.textContent);
    const rise = yWL - (num(t.attrs.y) - 3.5);
    if (!isFinite(v) || v <= 0 || rise <= 1) continue;
    if (!(v <= topTick.value)) {
      topTick = { text: String(t.textContent), value: v, vMax: v * hVel / rise };
    }
    vMax = topTick.vMax;
  }
  if (!isFinite(vMax) || vMax <= 0) {
    if (velTicks.length) note(`could not recover the velocity axis from ${velTicks.length} tick labels`);
    lastAxis = { vMax: NaN, heldBack: 0 };
  } else {
    const yFor = (v) => yWL - (v / vMax) * hVel;
    const under = payload.lines.flatMap((l) => [l.target, l[`pred_${armId}`]])
      .filter((v) => v !== null && isFinite(v)).sort((a, b) => a - b);
    let drawnMax = 0;
    for (const v of under) if (v > drawnMax) drawnMax = v;
    for (const o of withV) if (o.v > drawnMax) drawnMax = o.v;

    // The ceiling has two legitimate settings and it must be at the one the
    // switch says.  Unlimited, the axis is the data's own range - max over the
    // reconstruction, the platform's value and every raw segment, plus a hair of
    // headroom - so a value drawn past it means something is off-scale that
    // should not be.  Limited, the ceiling is only what the figure discusses and
    // the raw tail is meant to leave the plot through the clip, so the assertion
    // is not that nothing exceeds it but that the excess is accounted for: the
    // the switch that holds them back has to show how many.  A ceiling quietly
    // lowered over readings the reader cannot tell are missing is the silent edit
    // this check exists to prevent.
    const heldBack = withV.filter((o) => o.v > vMax).length;
    // Everything the switch is holding out of the picture - raw segments *and* the
    // reconstruction / platform values past the ceiling - because the badge counts
    // both and a check that counted half would pass a badge wrong by exactly the
    // half it did not count.  Spelled the way app.js spells it, including the
    // comparison against null, which is false in JS and so contributes nothing.
    const heldTotal = payload.observations
      .filter((o) => o.v !== null && isFinite(o.v) && o.v > vMax).length
      + payload.lines.reduce((n, l) => n
          + (isFinite(l.target) && l.target > vMax ? 1 : 0)
          + (isFinite(l[`pred_${armId}`]) && l[`pred_${armId}`] > vMax ? 1 : 0), 0);
    const badge = byId.get("axis-badge");
    const badgeText = (badge.textContent || "").trim();
    const badgeShown = !badge.hidden;
    if (!axisLimit) {
      if (drawnMax > 0 && vMax < drawnMax) {
        note(`axis tops out at ${vMax.toFixed(2)} m/s but values up to ${drawnMax.toFixed(2)} ` +
             `are drawn - the largest is off-scale`);
      }
      if (drawnMax * 1.02 > 0.3 && vMax > drawnMax * 1.10 + 0.05) {
        note(`axis is ${vMax.toFixed(2)} m/s for data reaching only ${drawnMax.toFixed(2)}`);
      }
      if (heldBack) note(`unlimited axis still leaves ${heldBack} raw segments above it`);
      if (badgeShown) {
        note("the axis is not limited but the switch still shows a held-back count");
      }
    } else {
      // The ceiling is the range under discussion - the reconstruction and the
      // platform's value, at the 99.5th percentile, with headroom.  Recovering it
      // from tick labels cannot be exact: the labels are rounded, and the
      // rounding is amplified by the ratio of the ceiling to the label, so the
      // allowance is the label's own quantum scaled by that ratio.  This is the
      // assertion a switch wired to nothing fails: the ceiling stays at the
      // unlimited one and the raw tail is not held back at all.
      const peak = under.length
        ? under[Math.min(under.length - 1, Math.floor(under.length * 0.995))] : 0;
      const want = Math.max(0.3, peak * 1.10);
      const quantum = (text) => {
        const dot = text.indexOf(".");
        return dot < 0 ? 0.5 : 0.5 * Math.pow(10, -(text.length - dot - 1));
      };
      const slack = quantum(topTick.text) * (vMax / topTick.value) + 0.01;
      const tail = withV.filter((o) => o.v > want).length;
      if (tail && !(vMax <= want + slack)) {
        note(`limited axis is ${vMax.toFixed(2)} m/s against a discussion range of ` +
             `${want.toFixed(2)} - the ${tail} raw segments past it are not being held back`);
      }
      // The count that used to be a clause in the caption is now the badge on the
      // switch, and it is read off the page rather than off the payload: a badge
      // wired to the wrong number is exactly the failure that matters here.  Both
      // directions are asserted - a ceiling that holds readings back in silence,
      // and a badge that cries wolf on a section that lost nothing - because a
      // count that is always drawn is as useless as one that never is.
      if (heldTotal && !badgeShown) {
        note(`${heldTotal} readings are past the ${vMax.toFixed(2)} m/s ceiling and the ` +
             `switch holding them back shows no count`);
      } else if (heldTotal && badgeText !== String(heldTotal)) {
        note(`the switch shows "${badgeText}" past the ceiling but ${heldTotal} are past it`);
      }
      if (!heldTotal && badgeShown) {
        note("the switch shows a held-back count but nothing is past the ceiling");
      }
      // A section whose raw readings are all above the range under discussion is
      // not a defect - a low-flow section whose STIV segments are uniformly
      // noisy draws the reconstruction and the platform curve, holds the rest
      // back, and puts the number on the switch, which is the honest picture.
      // All that is required is that the number is there, which the check above
      // enforces.
    }

    // Two captions describe this section and neither may describe the same thing
    // as the other.  The title block states the section's physical facts - the
    // water level, the width, the mean depth, which instrument took the reading -
    // and the counts of measuring lines and raw segments are not among them.  They
    // were listed here as well as in the note under the figure: the same three
    // numbers, twice on one screen, and the first reader to see the finished panel
    // called it cluttered.  A fact repeated is not a fact emphasised; it is a page
    // with nothing left to look at.  The note itself is gone now and the counts
    // with it - they are in the figure, where a reader who wants them can count
    // them - so what this guards is that they do not come back as title-block rows.
    // The data source is the same story: the picker carries a switch for it, so the
    // caption under the figure must not name it a third time.
    const tbText = byId.get("tb-facts").textContent || "";
    for (const word of ["测速线", "算法线", "原始分段"]) {
      if (tbText.includes(word)) {
        note(`the title block counts ${word} - those counts are in the figure, not ` +
             `in a block that describes the section`);
      }
    }
    const scaleText = byId.get("plot-scale").textContent || "";
    if (/入库|实时/.test(scaleText)) {
      note("the caption under the figure names the data source a third time");
    }

    // Every segment sits at its own value.  This is the assertion the pinning
    // clamp used to defeat: `Math.max(pinnedAt, ...)` put every segment above
    // the ceiling on one row, so a section with a long tail drew a straight line
    // of dots along the top edge - and a limited axis is exactly where that
    // temptation returns, since the overflow now has somewhere to go.  Positions
    // must be the values, to the pixel, under either setting.
    const slack = 0.5;
    let misplaced = 0;
    for (let i = 0; i < Math.min(dots.length, withV.length); i += 1) {
      const want = yFor(withV[i].v);
      const got = num(dots[i].attrs.cy);
      // Negative readings are floored at the water line.  Nothing on the page says
      // so any more - the sentence that did was one of the ones cut - so the
      // disclosure is the hover tooltip, which prints the true signed value for
      // every line.  That is the trade the panel made: a reader asking about one
      // line gets the exact number, and a reader who was never going to read a
      // footnote under the figure is no longer told about a handful of sub-zero
      // STIV segments at the cost of a line of the page.
      if (want > yWL + slack) {
        if (Math.abs(got - yWL) > slack) misplaced += 1;
        continue;
      }
      if (Math.abs(got - want) > slack) misplaced += 1;
    }
    if (misplaced) {
      note(`${misplaced} raw segments are not drawn at their own value`);
    }
    // A row is one pixel; two segments may only share one if a pixel is all the
    // axis can resolve between them.  Sharing a row across more than that is the
    // collapse itself, stated as its own finding.
    const perPixel = vMax / hVel;
    const byRow = new Map();
    let collapsed = 0;
    for (const o of withV) {
      if (o.v < 0) continue;
      const row = Math.round(yFor(o.v));
      const seen = byRow.get(row);
      if (seen === undefined) byRow.set(row, o.v);
      else if (Math.abs(seen - o.v) > perPixel * 1.5) collapsed += 1;
    }
    if (collapsed) {
      note(`${collapsed} raw segments of visibly different value share a row`);
    }
    // below the water line is never right - the floor at zero is the one place a
    // segment may be drawn away from its value.  Above the top of the band is the
    // overflow, and only a limited axis has any
    const belowBand = dots.filter((c) => num(c.attrs.cy) > yWL + 0.5).length;
    if (belowBand) note(`${belowBand} raw dots fall below the velocity band`);
    const aboveBand = dots.filter((c) => num(c.attrs.cy) < padT - 1).length;
    if (aboveBand && !axisLimit) {
      note(`${aboveBand} raw dots leave the plot on an axis that was meant to hold them`);
    }
    lastAxis = { vMax, heldBack };
  }

  // 8. the section carries depth.  Recover the depth scale the same way, then
  //    check that there is exactly one measuring line per wet line, that it
  //    starts at the water surface, and that it ends as deep as the survey says.
  const depthTicks = collect(svg, "text").filter((t) =>
    num(t.attrs.x) === W - padR + 8 && num(t.attrs["font-size"]) === 11.5 && t.attrs.fill === C.cap);
  let depthSpan = NaN;
  {
    const perMetre = depthTicks.map((t) => {
      const d = Number(t.textContent);
      const rise = num(t.attrs.y) - 3.5 - yWL;
      return isFinite(d) && d > 0 && rise > 1 ? rise / d : NaN;
    }).filter((v) => isFinite(v)).sort((a, b) => a - b);
    if (perMetre.length) depthSpan = hSec / perMetre[perMetre.length >> 1];
  }
  if (!isFinite(depthSpan) || depthSpan <= 0) {
    note(depthTicks.length
      ? `could not recover the depth scale from ${depthTicks.length} tick labels`
      : "the section has no depth scale");
  } else {
    // the scale has to be the section's own depth range, not some other span
    const fallbackDepth = [payload.meta.max_depth, payload.meta.aver_depth, 1]
      .find((v) => typeof v === "number" && isFinite(v) && v > 0) ?? 1;
    const allDepths = payload.lines.map((l) => l.depth)
      .filter((v) => v !== null && isFinite(v) && v >= 0);
    const expectedSpan = Math.max(allDepths.length ? Math.max(...allDepths) : fallbackDepth, 0.05);
    if (Math.abs(depthSpan - expectedSpan) / expectedSpan > 0.02) {
      note(`depth scale is ${depthSpan.toFixed(3)} m but the section spans ${expectedSpan.toFixed(3)} m`);
    }

    // same x mapping as app.js, so a stem can be traced back to its line
    const xsAll = payload.lines.map((l) => l.x).filter((v) => v !== null);
    const obsXs = payload.observations.map((o) => o.x).filter((v) => v !== null);
    let x0 = Math.min(...xsAll, ...obsXs);
    let x1 = Math.max(...xsAll, ...obsXs);
    if (!isFinite(x0) || !isFinite(x1) || x1 - x0 < 1e-6) { x0 = 0; x1 = 1; }
    const xPad = (x1 - x0) * 0.015;
    x0 -= xPad; x1 += xPad;
    const sx = (x) => padL + ((x - x0) / (x1 - x0)) * (W - padL - padR);

    const vertical = collect(svg, "line").filter((n) => num(n.attrs.x1) === num(n.attrs.x2));
    const stems = vertical.filter((n) => num(n.attrs.y1) === yWL && num(n.attrs["stroke-width"]) === 1);
    const dryTicks = vertical.filter((n) => num(n.attrs.y1) === yWL - 1);
    const wet = payload.lines.filter((l) => l.x !== null && l.depth !== null && l.depth >= 0.01);
    const dry = payload.lines.filter((l) => l.x !== null && l.depth !== null && l.depth < 0.01);
    if (stems.length !== wet.length) {
      note(`${stems.length} measuring lines drawn for ${wet.length} wet lines`);
    }
    if (app.state.layers.dry && dryTicks.length !== dry.length) {
      note(`${dryTicks.length} dry ticks for ${dry.length} dry lines`);
    }

    // a stem has to end where its own surveyed depth puts it
    const byX = new Map();
    for (const l of payload.lines) {
      if (l.x === null) continue;
      const key = sx(l.x);
      if (!byX.has(key)) byX.set(key, []);
      byX.get(key).push(l);
    }
    let misplaced = 0, worst = 0;
    for (const stem of stems) {
      const lines = byX.get(num(stem.attrs.x1));
      const drawn = (num(stem.attrs.y2) - yWL) / hSec * depthSpan;
      const off = lines
        ? Math.min(...lines.map((l) => Math.abs(drawn - Math.max(0, Math.min(l.depth, depthSpan)))))
        : Infinity;
      worst = Math.max(worst, off);
      if (!(off <= 0.02)) misplaced += 1;
    }
    if (misplaced) {
      note(`${misplaced} measuring lines end at the wrong depth (worst ${worst.toFixed(3)} m off)`);
    }
  }

  // 9. anything the plot marks must be named in the legend - a mark the reader
  //    cannot identify is a mark that should not be drawn
  const marks = byId.get("plot-legend").children.map((span) => ({
    cls: (span.children[0] && span.children[0].className) || "",
    label: span.textContent || "",
  }));
  if (!marks.some((m) => m.cls === "hair")) {
    note("measuring lines are drawn into the section with no legend entry naming them");
  }
  const dryDrawn = collect(svg, "line").filter((n) => num(n.attrs.y1) === yWL - 1).length;
  if (dryDrawn && !marks.some((m) => m.cls === "hatch")) {
    note(`${dryDrawn} dry marks drawn with no legend entry naming them`);
  }
  if (marks.some((m) => /高出流速上限/.test(m.label))) {
    note("legend still explains the removed off-scale triangle");
  }

  // 10. the dry-line valve holds.  This is a contract on the numbers, not on the
  //     drawing, so it is checked on the payload the service actually sent: no
  //     line without a water column may carry a nonzero reconstruction from any
  //     arm.  A valve that is claimed but not applied is worse than no valve -
  //     the panel would be reporting a velocity that cannot exist.
  const armIds = Object.keys(payload.metrics);
  for (const line of payload.lines) {
    if (!(line.depth > payload.meta.valve_max_depth)) {
      for (const armId of armIds) {
        const p = line[`pred_${armId}`];
        if (p !== null && p !== undefined && p !== 0) {
          note(`line ${line.i + 1} has depth ${line.depth} m but ${armId} reconstructs ${p} m/s`);
        }
      }
    }
  }
  const valvedSeen = payload.lines.filter((l) => l.valved).length;
  if (valvedSeen !== (payload.meta.n_valved || 0)) {
    note(`meta says ${payload.meta.n_valved} lines were valved but ${valvedSeen} are flagged`);
  }

  // 11. the other renders do not throw, and the two panels below the figure obey
  //     the live channel's rule.  A live timestamp is the platform's own export
  //     taken minutes ago: scoring the arms against its un-reviewed value, and
  //     listing every segment of it, are both claims the panel has no business
  //     making there.  So neither panel is drawn, and - just as important - the
  //     panels must come back on a stored measurement rather than stay hidden.
  const liveOrigin = payload.source === "live";
  app.renderStrip(payload, { W, padL, padR, sx: (x) => padL + ((x - payload.lines[0].x) / 200) * (W - 150) });
  app.renderReadout(payload);
  app.renderObservations(payload);
  app.renderTitleblock(payload);
  if (liveOrigin) {
    if (byId.get("readout-table").children.length) note("the live view still scored the arms against the platform value");
    if (byId.get("obs-table").children.length) note("the live view still lists the raw segments");
    if (!byId.get("readout").hidden) note("the per-model panel is not hidden on the live channel");
    if (!byId.get("obs").hidden) note("the raw-observation panel is not hidden on the live channel");
    if ((byId.get("readout-head").title || "").trim()) {
      note("the live view left a tooltip on the hidden panel's heading");
    }
    if ((byId.get("obs-count").textContent || "").trim()) note("the live view left a count over the hidden panel");
  } else {
    if (!byId.get("readout-table").children.length) note("readout table came out empty");
    if (byId.get("readout").hidden) note("the per-model panel is hidden on a stored measurement");
    if (byId.get("obs").hidden) note("the raw-observation panel is hidden on a stored measurement");
    // The metrics were taken after the valve, so they are not the bare model's
    // numbers; the table's heading must say so rather than let them be read as
    // such.  It is the heading's tooltip that carries this now - the paragraph
    // that used to carry it was cut for being a paragraph - so the check reads the
    // tooltip.  A caveat moved into a tooltip is only disclosed if the tooltip is
    // actually there, and nothing else on the page would notice if it went.
    const caveat = byId.get("readout-head").title || "";
    if (valvedSeen && !/阀门/.test(caveat)) {
      note(`${valvedSeen} valved lines feed the metrics and the table's heading says nothing about it`);
    }
    if (!valvedSeen && /阀门/.test(caveat)) {
      note("the table's heading claims valved lines were counted but none were");
    }
    // The observation table's caption was two sentences and then, after that cut,
    // six characters floating under the scroll well - how the rows are grouped,
    // which the first column says on every row.  `caption-side: bottom` never
    // applied, because the caption was a sibling of the table and not a child, so
    // it always rendered as debris under the card.  It is the table's accessible
    // name now, which labels the table without being read at anyone; this fails if
    // it comes back as visible text.  Read off `#obs-table`, which is where
    // renderObservations appends - it is handed that element as `host`, not `#obs`.
    if ((byId.get("obs-table").textContent || "").includes("按测速线分组")) {
      note("the observation table's grouping is stated again under the table");
    }
    // Each model name appears twice on this page - as the rail's switch, and as the
    // readout table's first column - and each used to carry a second line expanding
    // it (物理约束, 纯净版, Yeo-Johnson).  That expansion is a tooltip now, because
    // the reader who asked for the page's prose to go asked for these too.  What
    // this guards is that it stays a tooltip: a pill or a cell whose text runs past
    // the model's own name is the annotation coming back, and it would come back as
    // a second line that makes every row of the table two lines tall.
    for (const pill of byId.get("arms").children) {
      const text = (pill.textContent || "").trim();
      const arm = app.state.arms.find((a) => text.startsWith(a.label));
      if (!arm) note(`a model pill reads "${text}", which is not one of the model names`);
      else if (text !== arm.label) {
        note(`the model pill reads "${text}" - the description belongs in its tooltip`);
      }
      // The text is the readable half of the claim and the child count is the
      // structural half.  The stub's textContent returns `_text` when it is set, so
      // a cell built with `textContent = label` and then appended to would read back
      // as the label alone - the regression would look exactly like the fix.  The
      // child count is what actually notices.
      if (pill.children.length !== 1) {
        note(`a model pill is ${pill.children.length} elements, not the name alone`);
      }
      // The class on the button is the readable half of the state claim, and it
      // is checked in two places - the stylesheet's `.arm.is-active` rule
      // guards what the marker looks like, and here what it marks.  Neither
      // half substitutes for the other: an unstyled class is a switch nobody
      // can see, and a styled one on the wrong pill is the wrong switch.
      const cls = (pill.attrs.class || pill.className || "");
      const isActive = app.state.arms.some((a) => a.id === arm.id) &&
        app.state.activeArm === arm.id;
      if (isActive !== cls.split(/\s+/).includes("is-active")) {
        note(`the active-model marker on the rail disagrees with state for ${arm.id}`);
      }
    }
    const actives = byId.get("arms").children
      .filter((p) => (p.attrs.class || p.className || "").split(/\s+/).includes("is-active"));
    if (actives.length !== 1) {
      note(`the rail shows ${actives.length} active model strokes, not exactly one`);
    }
    for (const tr of (byId.get("readout-table").children[1] || { children: [] }).children) {
      const cell = tr.children[0];
      const text = (cell.textContent || "").trim();
      if (!app.state.arms.some((a) => a.label === text)) {
        note(`a readout row is labelled "${text}" rather than a model name alone`);
      }
      if (cell.children.length) {
        note(`a readout row's model cell carries ${cell.children.length} extra element(s) - ` +
             `the description belongs in its tooltip`);
      }
    }
  }

  return bad;
}

function describe(payload) {
  return `${payload.station} ${payload.time} (${payload.meta.n_lines} lines, ` +
         `${payload.observations_summary.n} segments)`;
}

/* Draw the payload under both settings of the 流速轴上限 switch and compare the two
 * ceilings.  Neither drawing can judge the switch by itself: each is internally
 * consistent whichever way the axis was set, so the only thing that shows the
 * switch works is the pair.  The limit must lower the ceiling when there is a raw
 * tail to hold back, and must not raise it when there is not. */
function inspectBoth(payload) {
  const was = app.state.axisLimit;
  // The title block is drawn by the app's own draw path, which not every
  // inspection site has walked yet - and the check on it reads what is on the
  // page, so an undrawn title block would read as an empty one and pass without
  // looking at anything.  Rendering it here is idempotent and is what every
  // real draw does, so the inspector always has the page it means to inspect.
  app.renderTitleblock(payload);
  // The rail's model switch is drawn by the app's boot path, which the sandbox does
  // not run - there is no /api/meta to boot against.  Its three pills are read by a
  // check below, so they have to exist; rendering them here is idempotent and is
  // what boot() does anyway.
  app.renderArms();
  const bad = [];
  const ceilings = { limited: NaN, unlimited: NaN };
  let heldBack = 0;
  for (const limit of [true, false]) {
    const found = inspect(payload, limit);
    for (const message of found) bad.push(`[流速轴上限${limit ? "开" : "关"}] ${message}`);
    if (limit) { ceilings.limited = lastAxis.vMax; heldBack = lastAxis.heldBack; }
    else ceilings.unlimited = lastAxis.vMax;
  }
  app.state.axisLimit = was;
  const { limited, unlimited } = ceilings;
  if (isFinite(limited) && isFinite(unlimited)) {
    if (limited > unlimited * 1.001 + 0.01) {
      bad.push(`流速轴上限 raised the axis: ${limited.toFixed(2)} m/s limited against ` +
               `${unlimited.toFixed(2)} unlimited`);
    } else if (heldBack && !(limited < unlimited * 0.999)) {
      bad.push(`流速轴上限 left the axis at ${limited.toFixed(2)} m/s with ${heldBack} ` +
               `raw segments past it - the switch changed nothing`);
    }
  }
  return bad;
}

async function fetchPayload(station, device, time, source) {
  const url = `${BASE}/api/section?station=${encodeURIComponent(station)}` +
    `&device=${encodeURIComponent(device)}&time=${encodeURIComponent(time)}` +
    (source ? `&source=${encodeURIComponent(source)}` : "");
  const payload = await (await fetch(url)).json();
  if (payload.error) throw new Error(`${station} ${time}: ${payload.error}`);
  return payload;
}

(async () => {
  let failures = 0;

  // the page and the script have to agree on what exists.  Every control app.js
  // reaches for with `el(id)` is looked up once at load, and a null there throws
  // before boot() - so an id renamed on one side and not the other takes the
  // whole panel down.  Worse, a control that is only ever read while drawing
  // fails the other way: it exists in the script, was never put in the page, and
  // the reader simply never finds the switch.  The DOM stub below invents any
  // element on demand, so neither shows up in the geometry checks; this is the
  // only place the two files are compared.
  {
    const html = fs.readFileSync(path.join(__dirname, "static", "index.html"), "utf8");
    const inPage = new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]));
    const wired = [...new Set([...source.matchAll(/\bel\("([^"]+)"\)/g)].map((m) => m[1]))];
    for (const id of wired) {
      if (!inPage.has(id)) { console.error(`FAIL  app.js wires #${id} but index.html has no such id`); failures += 1; }
    }
    // and the axis switch has to be findable.  It started inside the 图层 menu,
    // where a reader had to open a dropdown to learn it existed, and the first
    // reader to look for it did not find it.  It belongs in the figure's own tool
    // row, beside the legend that names what the figure draws.
    const at = (id) => html.indexOf(`id="${id}"`);
    if (!(at("plot-legend") < at("limit-axis") && at("limit-axis") < at("plot-stage"))) {
      console.error("FAIL  the 流速轴上限 switch is not in the figure's tool row with the legend");
      failures += 1;
    }
    // Two blocks of prose were cut from this page and must not come back: the note
    // under the figure and the note under the readout table.  Between them they said
    // how many measuring lines the section has, how many of those are algorithm
    // lines against interpolated ones, how many the valve had zeroed, how many
    // readings the ceiling was holding back, what the metrics were computed on, and
    // what the platform's value is worth as a reference.  Three of those were the
    // figure describing itself - the marks are in the drawing - and the rest are
    // caveats, which now live in a `title` on the thing they are about.  The reader
    // who saw the finished panel called the result cluttered in as many words, and
    // the deletions are what answered that; this fails if either element is put
    // back, whatever it is made to say.
    for (const gone of ["plot-note", "readout-note"]) {
      if (inPage.has(gone)) {
        console.error(`FAIL  #${gone} is back - that prose belongs in a tooltip, not on the page`);
        failures += 1;
      }
    }
    // The wells that scroll have their scrollbars hidden, and the class that
    // does it is the one thing about them the sandbox cannot see: it builds its
    // nodes from app.js, and these three carry the class in the markup.  So the
    // markup is read here, and the stylesheet check below proves the class
    // actually hides anything.
    for (const id of ["board", "station-list", "measurement-list"]) {
      const tag = (html.match(new RegExp(`<[^>]*id="${id}"[^>]*>`)) || [""])[0];
      if (!/\bscroll-well\b/.test(tag)) {
        console.error(`FAIL  #${id} scrolls and the markup does not give it the class that hides its scrollbar`);
        failures += 1;
      }
    }
    // 实时 is the default and stands first: it is the only source that can show
    // today, and the panel opens on it.  Both halves matter - a switch that
    // still presses 已入库 on arrival would draw the three-week-old corpus under
    // a heading that says the panel is live.
    if (!(at("src-live") < at("src-cache"))) {
      console.error("FAIL  已入库 stands before 实时 in the source switch");
      failures += 1;
    }
    const liveTag = (html.match(/<button[^>]*id="src-live"[^>]*>/) || [""])[0];
    const cacheTag = (html.match(/<button[^>]*id="src-cache"[^>]*>/) || [""])[0];
    if (!/aria-pressed="true"/.test(liveTag) || /aria-pressed="true"/.test(cacheTag)) {
      console.error("FAIL  the source switch does not arrive pressed on 实时");
      failures += 1;
    }
    const dateTag = (html.match(/<input[^>]*id="live-date"[^>]*>/) || [""])[0];
    if (/\bhidden\b/.test(dateTag)) {
      console.error("FAIL  the live date picker arrives hidden while 实时 is the default");
      failures += 1;
    }
    console.log(`controls: ${wired.length} wired in app.js, ${inPage.size} ids in index.html`);
  }

  // -- one palette, two files ----------------------------------------------
  // The accent has to be a single colour, but it is written down twice: once as
  // a :root token for the interface, once in the chart's palette object,
  // because the SVG is built attribute by attribute and cannot read a custom
  // property.  Two copies of one fact drift.  A reader who retunes the blue in
  // the stylesheet would get an interface in the new colour and a chart still in
  // the old one, with nothing to say so - the figure would simply be wrong in a
  // way that looks deliberate.  So the two are compared here, by name.
  {
    const css = fs.readFileSync(path.join(__dirname, "static", "app.css"), "utf8");
    const root = (css.match(/:root\s*\{[\s\S]*?\n\}/) || [""])[0];
    const token = (name) => {
      const m = root.match(new RegExp(`--${name}:\\s*(#[0-9A-Fa-f]{6})`));
      return m ? m[1].toUpperCase() : null;
    };
    // chart key -> the interface token it must equal
    const PAIRS = [
      ["water", "water"], ["waterInk", "water-ink"], ["field", "field"],
      ["ink", "ink"], ["silt", "silt"], ["dry", "dry"], ["flag", "flag"],
      ["grid", "rule"], ["gridSoft", "rule-2"], ["tick", "ink-2"], ["cap", "ink-3"],
      ["hair", "dry"],
    ];
    let compared = 0;
    for (const [key, name] of PAIRS) {
      const want = token(name);
      if (!want) { console.error(`FAIL  app.css has no --${name} token`); failures += 1; continue; }
      const got = String(C[key] || "").toUpperCase();
      compared += 1;
      if (got !== want) {
        console.error(`FAIL  palette C.${key} is ${got} but --${name} is ${want}`
          + ` - the chart and the interface would disagree about one colour`);
        failures += 1;
      }
    }
    console.log(`palette: ${compared} chart colours matched against the interface tokens`);
  }

  // -- the scrollbars are gone, and the wells still scroll ------------------
  // Two spellings are needed and neither is optional: `scrollbar-width` covers
  // Firefox, `::-webkit-scrollbar` covers Chromium and the Edge this panel is
  // served to, and one without the other leaves a grey system bar in the one
  // browser it does not cover.  The `overflow` assertions matter just as much
  // and in the opposite direction - hiding a bar by making a well unscrollable
  // would pass a check that only looked for the hiding, and would cost the
  // reader everything past the fold.
  {
    const css = fs.readFileSync(path.join(__dirname, "static", "app.css"), "utf8");
    const block = (name) => {
      const m = css.match(new RegExp(`(?:^|\\n)${name}\\s*\\{([^}]*)\\}`));
      return m ? m[1] : "";
    };
    if (!/scrollbar-width:\s*none/.test(block("\\.scroll-well"))) {
      console.error("FAIL  .scroll-well does not set scrollbar-width: none - Firefox keeps its bar");
      failures += 1;
    }
    if (!/\.scroll-well::-webkit-scrollbar\s*\{[^}]*width:\s*0/.test(css)) {
      console.error("FAIL  .scroll-well has no ::-webkit-scrollbar rule - Chromium keeps its bar");
      failures += 1;
    }
    for (const [what, sel] of [["the picker lists", "\\.list"], ["the board", "\\.board"],
                               ["the observation well", "\\.obs-scroll"]]) {
      if (!/overflow-y:\s*auto/.test(block(sel))) {
        console.error(`FAIL  ${what} no longer scroll - hiding a scrollbar must not hide the content`);
        failures += 1;
      }
    }
    for (const edge of ["is-top", "is-end"]) {
      const rule = new RegExp(`\\.scroll-well\\.${edge}::(?:before|after)[^{]*\\{[^}]*opacity:\\s*1`);
      if (!rule.test(css)) {
        console.error(`FAIL  nothing lights the ${edge} edge shadow of a scrolled well`);
        failures += 1;
      }
    }
    console.log("scroll wells: the bars are hidden in both spellings and no well lost its scrolling");
  }

  // -- the model switch reads as names, not as a second chip -----------------
  {
    const css = fs.readFileSync(path.join(__dirname, "static", "app.css"), "utf8");
    const block = (name) => {
      const m = css.match(new RegExp(`(?:^|\\n)${name}\\s*\\{([^}]*)\\}`));
      return m ? m[1] : "";
    };
    // The names stand on their own: a sunk track with a raised thumb painted
    // every model as one blob wedged between the brand and the layers button.
    // What marks the active model is a stroke in the water colour, nothing more.
    if (/background|box-shadow/.test(block("\\.arms-set"))) {
      console.error("FAIL  .arms-set carries a fill or shadow - the model names must stand on the rail");
      failures += 1;
    }
    const armBlock = block("\\.arm\\.is-active");
    if (!/outline:\s*1\.5px solid var\(--water\)/.test(armBlock)) {
      console.error("FAIL  the active model is not marked by a water-colour stroke");
      failures += 1;
    }
    if (/background|box-shadow/.test(armBlock)) {
      console.error("FAIL  the active pill fills itself in - a switch is chrome, not a chip");
      failures += 1;
    }
    // The pill look must not come back in either direction: a border-radius of
    // 999px on the arm button is the old pill, and so is a full-width bottom
    // border - a hairline ring around the text box is what this control is.
    if (/--r-pill/.test(block("\\.arm")) || /--r-pill/.test(armBlock)) {
      console.error("FAIL  a model arm is a pill again - pills read as free-standing buttons");
      failures += 1;
    }
    if (/border-bottom/.test(block("\\.arm")) || /border-bottom/.test(armBlock)) {
      console.error("FAIL  the active model is underlined - a bare underline ties into the letterforms");
      failures += 1;
    }
    console.log("model switch: three names, the active one wearing a water stroke");
  }

  const meta = await (await fetch(`${BASE}/api/meta`)).json();
  app.state.arms = meta.arms.filter((a) => a.available);
  if (!app.state.arms.length) throw new Error("no model arm is available");
  app.state.activeArm = (app.state.arms.find((a) => a.id === "aether-p") || app.state.arms[0]).id;
  app.state.layers = { recon: true, target: true, raw: true, dry: true };
  console.log(`service: ${meta.n_stations} stations / ${meta.n_sections} measurements, ` +
              `arms ${app.state.arms.map((a) => a.id).join(", ")}`);

  // -- one station in full -------------------------------------------------
  const stations = (await (await fetch(`${BASE}/api/stations?limit=1`)).json()).stations;
  const station = stations[0];
  const device = station.devices[0].device;
  const measurements = (await (await fetch(
    `${BASE}/api/measurements?station=${station.code}&device=${device}&limit=200`)).json()).measurements;
  const flowing = measurements.filter((m) => (m.mean_velocity ?? 0) > 0.05 && m.n_lines >= 8);
  const pick = flowing[Math.floor(flowing.length / 2)] || measurements[0];
  const payload = await fetchPayload(station.code, device, pick.time);
  app.state.payload = payload;
  console.log(`payload: ${station.code} ${station.name} ${describe(payload)}`);

  const complaints = inspectBoth(payload);
  const svg = byId.get("section-svg");
  const W = num(svg.attrs.width), H = num(svg.attrs.height);
  console.log(`  viewport ${W}x${H}, ${collect(svg, "path").length} paths, ` +
              `${collect(svg, "circle").length} circles, ${collect(svg, "text").length} labels`);
  if (complaints.length) {
    complaints.forEach((c) => console.error("FAIL  " + c));
    failures += complaints.length;
  } else {
    console.log("  all geometry checks pass");
  }

  // -- arms ----------------------------------------------------------------
  for (const arm of app.state.arms) {
    app.state.activeArm = arm.id;
    const armBad = inspectBoth(payload);
    if (armBad.length) { armBad.forEach((c) => console.error(`FAIL  arm ${arm.id}: ` + c)); failures += armBad.length; }
    else console.log(`  arm ${arm.id.padEnd(5)} ${arm.label} - ${armBad.length ? "bad" : "ok"}`);
  }
  app.state.activeArm = (app.state.arms.find((a) => a.id === "aether-p") || app.state.arms[0]).id;

  // -- the scroll wells ----------------------------------------------------
  // The panel has no scrollbars, and the half of the scrollbar that is kept is
  // the edge shadow.  It has to be right at four points, not one: bare at the
  // top of a list, shadowed at the bottom while there is more, shadowed at the
  // top once you are past it, and bare at both ends once there is nothing
  // beyond - a shadow on an edge with nothing behind it is a lie the reader
  // pays for by scrolling to find nothing.  The stub's `classList` is a real
  // set precisely so this can be asserted at all: a stub that swallowed
  // `toggle` would pass a well with no shadow anywhere.
  {
    const obs = document.querySelectorAll(".scroll-well")
      .find((w) => (w.className || "").includes("obs-scroll"));
    if (!obs) {
      console.error("FAIL  the observation well is not a .scroll-well - its scrollbar would show");
      failures += 1;
    } else {
      const edges = (top, height, client) => {
        obs.scrollTop = top;
        obs.scrollHeight = height;
        obs.clientHeight = client;
        app.paintScrollEdges();
        return `${obs.classList.contains("is-top") ? "T" : "-"}`
          + `${obs.classList.contains("is-end") ? "E" : "-"}`;
      };
      const cases = [
        ["at the top of a long table", edges(0, 900, 420), "-E"],
        ["scrolled into a long table", edges(200, 900, 420), "TE"],
        ["at the end of a long table", edges(480, 900, 420), "T-"],
        ["a table short enough to fit", edges(0, 300, 420), "--"],
      ];
      const wrong = cases.filter(([, got, want]) => got !== want);
      for (const [what, got] of wrong) {
        console.error(`FAIL  the observation well's edge shadow reads ${got} ${what}`);
      }
      if (wrong.length) failures += wrong.length;
      else console.log("scroll wells: no bars, and the edge shadow tracks only the ends with content");
    }
  }

  // -- sweep ---------------------------------------------------------------
  if (SWEEP) {
    const all = (await (await fetch(`${BASE}/api/stations?limit=500`)).json()).stations;
    let done = 0, skipped = 0;
    const okShapes = new Set();
    for (let i = 0; i < SWEEP; i += 1) {
      const st = all[Math.floor(Math.random() * all.length)];
      const dev = st.devices[Math.floor(Math.random() * st.devices.length)].device;
      const rows = (await (await fetch(
        `${BASE}/api/measurements?station=${st.code}&device=${dev}&limit=400`)).json()).measurements;
      if (!rows.length) { skipped += 1; continue; }
      const row = rows[Math.floor(Math.random() * rows.length)];
      let swept;
      try {
        swept = await fetchPayload(st.code, dev, row.time);
      } catch (exc) {
        console.error(`FAIL  sweep ${st.code} ${row.time}: ${exc.message}`);
        failures += 1;
        continue;
      }
      app.state.payload = swept;
      let sweptBad;
      try {
        sweptBad = inspectBoth(swept);
      } catch (exc) {
        console.error(`FAIL  sweep ${st.code} ${row.time} threw: ${exc.message}`);
        failures += 1;
        continue;
      }
      done += 1;
      const shape = `${swept.meta.n_lines}L/${swept.meta.n_algo}A/${swept.meta.n_dry}D/${swept.observations_summary.n}O`;
      okShapes.add(shape);
      if (sweptBad.length) {
        console.error(`FAIL  sweep ${st.code} ${describe(swept)}`);
        sweptBad.forEach((c) => console.error("        " + c));
        failures += sweptBad.length;
      }
    }
    console.log(`sweep: ${done} measurements inspected${skipped ? `, ${skipped} skipped (no rows)` : ""}, ` +
                `${okShapes.size} distinct shapes`);
    console.log(`  shapes: ${[...okShapes].slice(0, 10).join("  ")}`);
  }

  // -- live channel --------------------------------------------------------
  // A live measurement reaches the page through a different pipeline than a
  // stored one (platform export -> parse -> quality control -> inference), so
  // it can carry shapes the cache never produces.  It is also the only path
  // that fails routinely: on a real day most timestamps are rejected outright.
  // So this walks the list the way a reader would - newest first, click, read
  // the error, click the next - and checks both halves of what the panel does:
  // the rejection is reported, and the one that does reconstruct draws cleanly.
  if (LIVE) {
    let checked = 0, rejected = 0, done = 0;
    const reasons = new Map();
    const all = (await (await fetch(`${BASE}/api/stations?limit=500`)).json()).stations;

    // The arrival endpoint: the panel opens on whatever this says is newest, so
    // it has to be newest-first, on the day that was asked for, and about
    // stations the picker actually has.  A candidate naming a station that is
    // not in the index would leave the board on its empty state every morning,
    // and one dated to another day would draw yesterday under today's heading.
    {
      const latest = await (await fetch(`${BASE}/api/live/latest?date=${LIVE}`)).json();
      const codes = new Set(all.map((s) => s.code));
      const problems = [];
      if (latest.date !== LIVE) problems.push(`asked for ${LIVE}, answered for ${latest.date}`);
      if (typeof latest.probed !== "number") problems.push("no count of the devices it asked");
      let previous = "9999";
      for (const c of latest.candidates || []) {
        if (!codes.has(c.station)) problems.push(`candidate ${c.station} is not in the index`);
        if (!String(c.time).startsWith(LIVE)) problems.push(`candidate ${c.time} is not on ${LIVE}`);
        if (String(c.time) > previous) problems.push(`${c.time} comes after ${previous} in a newest-first list`);
        previous = String(c.time);
        if (!c.device) problems.push(`candidate ${c.station} ${c.time} names no device`);
      }
      for (const p of problems) console.error(`FAIL  live/latest: ${p}`);
      failures += problems.length;
      if (!problems.length) {
        console.log(`live/latest ${LIVE}: ${latest.probed} device(s) asked, ` +
                    `${(latest.candidates || []).length} candidate(s), newest ` +
                    `${(latest.candidates || [{ time: "—" }])[0].time}`);
      }
    }
    for (const st of all) {
      if (checked >= LIVE_STATIONS) break;
      const dev = st.devices[Math.floor(Math.random() * st.devices.length)].device;
      checked += 1;
      const rows = (await (await fetch(`${BASE}/api/live/measurements?station=${encodeURIComponent(st.code)}` +
        `&device=${encodeURIComponent(dev)}&begin=${LIVE}&end=${LIVE}`)).json()).measurements || [];
      if (!rows.length) { reasons.set("当天无测次", (reasons.get("当天无测次") || 0) + 1); continue; }
      for (const row of rows) {
        // read the body rather than going through fetchPayload: a live rejection
        // arrives as {error}, and fetchPayload glues the station and time onto
        // the front of it, burying the message this tally wants to count
        const url = `${BASE}/api/section?station=${encodeURIComponent(st.code)}` +
          `&device=${encodeURIComponent(dev)}&time=${encodeURIComponent(row.time)}&source=live`;
        const live = await (await fetch(url)).json();
        if (live.error) {
          rejected += 1;
          // bucket by defect: the service states each refusal as an outcome, so
          // the part after the colon is the defect.  Different outcomes must not
          // merge into one bucket just because they share a prefix.
          const text = String(live.error);
          const cut = Math.max(text.indexOf("："), text.indexOf(":"));
          const why = (cut >= 0 ? text.slice(cut + 1) : text).trim().slice(0, 24) || "其他";
          reasons.set(why, (reasons.get(why) || 0) + 1);
          // the service's sentences are the reviewer's whole vocabulary for
          // this; none of the pipeline's own words may reach them
          if (/\b(no_raw_input|mostly_zero|too_few_lines|velocity_out_of_range|no_algorithm_lines|dominant_value|raw tables?|tolerance)\b/i.test(text)) {
            console.error(`FAIL  live refusal leaks internal vocabulary: ${text}`);
            failures += 1;
          }
          // the list shows this reader a short verdict, not the whole sentence:
          // every real rejection must classify to something specific
          const label = app.liveReason(live.error);
          if (label === "拉取失败") { console.error(`FAIL  live reason fell through to generic: ${live.error}`); failures += 1; }
          continue;
        }
        if (live.source !== "live") { console.error(`FAIL  live ${st.code} ${row.time}: service returned source=${live.source}`); failures += 1; continue; }
        app.state.payload = live;
        const bad = inspectBoth(live);
        done += 1;
        console.log(`live: ${st.code} ${describe(live)}`);
        if (bad.length) { bad.forEach((c) => console.error("FAIL  live " + c)); failures += bad.length; }
        else console.log("  live geometry checks pass");
        break;
      }
    }
    console.log(`live channel ${LIVE}: ${checked} device-day(s) probed, ${done} reconstructed, ${rejected} rejected before drawing`);
    for (const [why, n] of [...reasons].sort((a, b) => b[1] - a[1])) console.log(`  ${String(n).padStart(4)}  ${why}`);
    if (!done && checked) console.error("FAIL  live channel: nothing on this day could be reconstructed");
    if (!done && checked) failures += 1;

    // The timestamp-only live list is where a reader spends their time: on a
    // real day most rows cannot be opened.  So the panel has to write the
    // verdict onto the row it came from - a reader who is told "no velocity
    // lines" stops clicking that one, and a reader told nothing clicks it again.
    app.state.source = "live";
    app.state.station = { code: "00000", name: "probe" };
    app.state.device = "DEVICE";
    app.state.time = null;
    app.state.loading = false;
    app.state.measurements = [
      { device: "DEVICE", time: `${LIVE} 08:00:00` },
      { device: "DEVICE", time: `${LIVE} 09:00:00` },
      { device: "DEVICE", time: `${LIVE} 10:00:00` },
    ];
    app.state.liveTried.clear();
    app.state.liveTried.set(`${LIVE} 09:00:00`, { ok: false, why: app.liveReason("这个测次无法成图：该测次的标定流速几乎全为零") });
    app.state.liveTried.set(`${LIVE} 10:00:00`, { ok: true, why: "" });
    app.renderMeasurements();
    const listRows = () => byId.get("measurement-list").children
      .filter((li) => li.children[0] && li.children[0].className.includes("row--time")).length;
    if (listRows() !== 3) { console.error(`FAIL  live list drew ${listRows()} rows for 3 measurements`); failures += 1; }
    const listText = byId.get("measurement-list").textContent || "";
    const want = ["点击拉取", "标定流速异常", "可重建"];
    for (const phrase of want) {
      if (!listText.includes(phrase)) { console.error(`FAIL  live list is missing "${phrase}" - got: ${JSON.stringify(listText.slice(0, 160))}`); failures += 1; }
    }
    // and the verdict must be gone once the list is rebuilt for a new day
    app.state.liveTried.clear();
    app.renderMeasurements();
    if ((byId.get("measurement-list").textContent || "").includes("标定流速异常")) {
      console.error("FAIL  live verdicts survived a list reload onto another day");
      failures += 1;
    }

    // -- the list cap -------------------------------------------------------
    // Opening at 20 rows is a display choice; the offer to see the rest is not.
    // A cap whose remainder cannot be reached would hide most of a device-day.
    const many = [];
    for (let i = 0; i < 47; i += 1) many.push({ device: "DEVICE", time: `${LIVE} 0${Math.floor(i / 60)}:${String(i % 60).padStart(2, "0")}:00` });
    app.state.measurements = many;
    app.state.measurementShown = 20;
    app.renderMeasurements();
    const drawn = listRows();
    const footer = byId.get("measurement-list").children.slice(-1)[0];
    const footerText = (footer && footer.children[0] && footer.children[0].textContent) || "";
    if (drawn !== 20) { console.error(`FAIL  measurement list drew ${drawn} rows, not 20`); failures += 1; }
    if (!/还有 27 条/.test(footerText)) {
      console.error(`FAIL  list cap hides the remainder with no way back: footer says ${JSON.stringify(footerText)}`);
      failures += 1;
    }
    if (footer.children[0] && footer.children[0].disabled) {
      console.error("FAIL  the show-more control is disabled, so the capped rows are unreachable");
      failures += 1;
    }
    // fire the control rather than trusting its label: the cap has to actually
    // lift, or the other 27 measurements are decoration
    const more = footer.children[0];
    if (more && more.listeners && more.listeners.click) {
      for (const fn of more.listeners.click) fn({});
    } else {
      console.error("FAIL  the show-more control has no click handler, so it cannot lift the cap");
      failures += 1;
    }
    if (listRows() !== 40) { console.error(`FAIL  lifting the cap drew ${listRows()} rows, not 40`); failures += 1; }
    app.state.measurements = [];
    app.state.measurementShown = 20;
  }

  // -- the picker stays clickable after a list load -------------------------
  // Every row carries `disabled = state.loading`, so the order of "settle the
  // busy flag" and "draw the rows" is a user-facing contract, and getting it
  // backwards fails silently: the list draws, looks right, and swallows every
  // click for the rest of its life.  A loaded list must come back live.
  {
    const realFetch = sandbox.fetch;
    sandbox.fetch = async () => ({
      ok: true, status: 200, statusText: "OK",
      json: async () => ({
        station: "TESTSITE", total: 2,
        measurements: [
          { device: "TESTSITE01", time: "2026-01-02 08:00:00", mean_velocity: 0.42, n_lines: 12 },
          { device: "TESTSITE01", time: "2026-01-02 09:00:00", mean_velocity: null, n_lines: 9 },
        ],
      }),
    });
    app.state.source = "cache";
    app.state.station = { code: "TESTSITE", name: "测试站", n: 2, devices: [{ device: "TESTSITE01", n: 2 }] };
    app.state.device = "TESTSITE01";
    await app.loadMeasurements();
    const rowButtons = () => byId.get("measurement-list").children
      .map((li) => li.children[0])
      .filter((b) => b && b.className.includes("row--time"));
    const assertLive = (label) => {
      const buttons = rowButtons();
      if (buttons.length !== 2) {
        console.error(`FAIL  ${label}: drew ${buttons.length} measurement rows for 2 measurements`);
        failures += 1;
      }
      if (app.state.loading) {
        console.error(`FAIL  ${label}: the board is still busy after the list settled`);
        failures += 1;
      }
      const dead = buttons.filter((b) => b.disabled);
      if (dead.length) {
        console.error(`FAIL  ${label}: ${dead.length} of ${buttons.length} rows drew disabled, so the picker cannot be clicked`);
        failures += 1;
      }
      // disabled is the mechanism; a handler is the effect.  Assert the effect.
      for (const button of buttons) {
        if (!(button.listeners && button.listeners.click && button.listeners.click.length)) {
          console.error(`FAIL  ${label}: row ${JSON.stringify(button.textContent)} has no click handler`);
          failures += 1;
        }
      }
    };
    assertLive("list load");
    // The reported defect was a source switch: over to the platform's list, then
    // back to the local store, with the rows dead at both ends.  Both tabs run
    // through the same list load, so drive them the way the tabs do.
    await app.setSource("live");
    assertLive("live tab");
    await app.setSource("cache");
    assertLive("back on the cache tab");
    app.state.measurements = [];
    sandbox.fetch = realFetch;
  }

  console.log(failures ? `\nSELF-CHECK FAILED (${failures} complaints)` : "\nSELF-CHECK PASSED");
  if (failures) process.exitCode = 1;
})();
