// Screenshot a region of the phone page in headless Edge at phone size (390 x 844, 2x), to see a screen the way the
// phone shows it. Serve the project first (python -m http.server 8790), then:
//   node tools/screenshot.js http://127.0.0.1:8790/phone/index.html <profileDir> <doneSelector> <setupExpression> <outPng> [clipSelector] [light|dark]
// setupExpression runs in the page before the shot (an async arrow is fine); clipSelector limits the image to one element.
"use strict";
const { spawn } = require("child_process");
const fs = require("fs");
const EDGE = process.env.EDGE || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const [, , url, profile, doneSel, setupExpr, outPng, clipSel, theme] = process.argv;
const port = 9600 + Math.floor(Math.random() * 200);
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let ready = false;
  for (let i = 0; i < 60 && !ready; i++) { await sleep(500); try { ready = (await fetch(`http://127.0.0.1:${port}/json/version`)).ok; } catch (e) {} }
  if (!ready) { console.log("Edge did not start. Set EDGE to a Chromium browser path."); edge.kill(); process.exit(2); }
  const page = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pending = {};
  const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending[i] = { res, rej }; ws.send(JSON.stringify({ id: i, method, params })); });
  ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pending[m.id]) { pending[m.id].res(m.result || m.error); delete pending[m.id]; } };
  await new Promise(r => { ws.onopen = r; });
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  if (theme) await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: theme }] });
  await send("Page.enable");
  await send("Page.navigate", { url });
  let found = false;
  for (let i = 0; i < 120 && !found; i++) { await sleep(500); const r = await send("Runtime.evaluate", { expression: `!!document.querySelector(${JSON.stringify(doneSel)})`, returnByValue: true }); found = !!(r.result && r.result.value); }
  if (!found) { console.log("Timed out waiting for " + doneSel); edge.kill(); process.exit(1); }
  if (setupExpr) {
    const setup = await send("Runtime.evaluate", { expression: setupExpr, awaitPromise: true, returnByValue: true });
    if (setup.exceptionDetails) console.log("setup error:", JSON.stringify(setup.exceptionDetails).slice(0, 600));
    else if (setup.result && setup.result.value != null) console.log(String(setup.result.value));
  }
  await sleep(400);
  let clip;
  if (clipSel) {
    const r = await send("Runtime.evaluate", { expression: `(() => { const el = document.querySelector(${JSON.stringify(clipSel)}); if (!el) return null; const b = el.getBoundingClientRect(); return { x: Math.max(0, b.left + window.scrollX - 4), y: Math.max(0, b.top + window.scrollY - 4), width: Math.min(390, b.width + 8), height: b.height + 8 }; })()`, returnByValue: true });
    if (r.result && r.result.value) clip = Object.assign(r.result.value, { scale: 2 });
  }
  const shot = await send("Page.captureScreenshot", clip ? { format: "png", clip, captureBeyondViewport: true } : { format: "png", captureBeyondViewport: true });
  fs.writeFileSync(outPng, Buffer.from(shot.data, "base64"));
  console.log("wrote " + outPng + (clip ? ` (${Math.round(clip.width)} x ${Math.round(clip.height)} css px)` : ""));
  edge.kill();
  process.exit(0);
})();
