/* Screenshot the real panel over the DevTools protocol.
 *
 * The plain `--screenshot` flag only captures the viewport it was given, and
 * this machine refuses to lay out a headless window taller than ~900px - so
 * everything below the figure (the readout table, the observation list, the
 * scroll wells) could not be looked at at all.  Driving the browser directly
 * gets past that: setDeviceMetricsOverride picks the viewport, and
 * captureBeyondViewport renders the whole scrollable page in one image.
 *
 * It also means the page can be told to do things - click a row, hover a line -
 * which is the difference between checking the layout and checking the panel.
 *
 *   node cdp.js <url> <out.png> [--shot-height N] [--eval "js"] [--after-shots N]
 */
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9333;

const url = process.argv[2];
const out = process.argv[3];
const argOf = (name, dflt) => {
  const i = process.argv.indexOf(name);
  return i < 0 ? dflt : process.argv[i + 1];
};
const shotHeight = Number(argOf("--shot-height", 0)) || 0;
const evals = [];
for (let i = 0; i < process.argv.length; i += 1) {
  if (process.argv[i] === "--eval") evals.push(process.argv[i + 1]);
}
const afterShots = Number(argOf("--after-shots", 0)) || 0;
const viewport = Number(argOf("--height", 0)) || 900;
const wide = Number(argOf("--width", 0)) || 1400;
// Edge's own `--hide-scrollbars` paints over the page's scrollbars, so a
// screenshot taken with it cannot tell a well whose bar the stylesheet removed
// from one whose bar is simply not being drawn today.  Pass this to see the
// bars the page would really wear.
const showBars = process.argv.includes("--show-scrollbars");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const profile = path.join(os.tmpdir(), "cdp-prof-" + process.pid);
  const edge = spawn(EDGE, [
    "--headless",
    "--disable-gpu",
    "--no-sandbox",
    ...(showBars ? [] : ["--hide-scrollbars"]),
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    "about:blank",
  ], { stdio: "ignore" });

  let target = null;
  for (let i = 0; i < 60 && !target; i += 1) {
    await sleep(250);
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      target = list.find((t) => t.type === "page");
    } catch { /* not up yet */ }
  }
  if (!target) throw new Error("Edge never opened a debugging target");

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let seq = 0;
  const pending = new Map();
  const events = [];
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
    } else if (msg.method) events.push(msg);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    seq += 1;
    pending.set(seq, { resolve, reject });
    ws.send(JSON.stringify({ id: seq, method, params }));
  });

  await send("Page.enable");
  await send("Runtime.enable");
  // The board is its own scroll container (body is height:100%, overflow:hidden),
  // so capturing "beyond the viewport" captures nothing extra - the document is
  // exactly one screen tall.  What works is handing the page a tall viewport and
  // letting the grid give the board a tall box: then the whole section fits in
  // one image with no scrolling and no stitching.
  await send("Emulation.setDeviceMetricsOverride", {
    width: wide, height: viewport, deviceScaleFactor: 1, mobile: false,
  });
  await send("Page.navigate", { url });
  for (let i = 0; i < 80; i += 1) {
    await sleep(250);
    if (events.some((e) => e.method === "Page.loadEventFired")) break;
  }
  // the panel fetches a station list, then a measurement; give it time to draw
  await sleep(3500);

  const shoot = async (file) => {
    const { data } = await send("Page.captureScreenshot", {
      format: "png", captureBeyondViewport: true, fromSurface: true,
    });
    fs.writeFileSync(file, Buffer.from(data, "base64"));
    console.log("wrote", file);
  };

  for (const js of evals) {
    const r = await send("Runtime.evaluate", { expression: js, awaitPromise: true, returnByValue: true });
    // an eval that resolves to an object comes back by value only with the flag
    // above; without it there is nothing to print and the whole run dies on the
    // reporting rather than on the page
    const value = r.result ? r.result.value : r.error;
    console.log("eval:", typeof value === "string" ? value : JSON.stringify(value).slice(0, 400));
    await sleep(afterShots || 1200);
  }

  await shoot(out);

  ws.close();
  edge.kill();
  await sleep(300);
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch { /* best effort */ }
}

main().then(() => process.exit(0)).catch((err) => {
  console.error("FAILED:", err.message);
  process.exit(1);
});
