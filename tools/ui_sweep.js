// Renders the Workout screen's card for every exercise in the library inside headless Edge and checks the controls:
// weight and reps where they belong, a hold timer for planks and carries (one button a side for side planks),
// a cardio log with a timer for the machines, a tick and a timer for warm-up and cool-down routines, plates a side
// for barbell lifts. Also proves an old treadmill "set" is converted into minutes.
//
//   node tools/ui_sweep.js          exit code 0 when every check passes
//
// Needs Microsoft Edge (set EDGE=path to use another Chromium). Serves the project folder on a local port while it runs.
"use strict";
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

const ROOT = path.join(__dirname, "..");
const EDGE = process.env.EDGE || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".css": "text/css", ".png": "image/png", ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml" };
const sleep = ms => new Promise(r => setTimeout(r, ms));

const server = http.createServer((req, res) => {
  const file = path.join(ROOT, decodeURIComponent(req.url.split("?")[0]));
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream", "Cache-Control": "no-store" });
  fs.createReadStream(file).pipe(res);
});

/* Runs inside the page. Returns { checked, fails } as JSON. */
const SWEEP = String(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const fails = [], note = (k, m) => fails.push(k + ": " + m);
  await LocalApi.call("PUT", "/api/settings", { sex: "m", birth_date: "1996-05-10", height_cm: 178, start_weight_kg: 82, target_weight_kg: 74, target_date: "2027-10-01", barbell_entry: "per_side" });
  await load(true);
  // the automatic update banner: a newer version shows it, Later silences that version, an up-to-date build shows nothing
  ls.set("ft-update", { at: Date.now(), latest: "99.0", cur: S.version, url: null, newer: true, dismissed: null });
  updateNotice();
  if (!document.querySelector("#updbar .upd")) note("updates", "no banner for a newer version");
  else {
    document.getElementById("updLater").click();
    if (document.querySelector("#updbar .upd")) note("updates", "Later did not hide the banner");
    if ((ls.get("ft-update") || {}).dismissed !== "99.0") note("updates", "Later did not remember the version");
  }
  ls.del("ft-update");
  const lv = await latestVersion();
  if (lv.newer || lv.latest !== S.version) note("updates", "the running build should read as current: " + JSON.stringify(lv));
  await autoUpdateCheck(true);
  if (document.querySelector("#updbar .upd")) note("updates", "banner shown although up to date");
  if (!(ls.get("ft-update") || {}).at) note("updates", "the automatic check did not record when it ran");
  startFreestyle();
  await sleep(600);
  if (!W) return JSON.stringify({ checked: 0, fails: ["no workout could be started"] });
  let checked = 0;
  for (const ex of S.exercises) {
    checked++;
    const mode = entryMode(ex), em = Engine.entryMode(ex);
    if (JSON.stringify(mode) !== JSON.stringify(em)) note(ex.key, "page and engine disagree on the entry mode");
    const cardio = mode.kind === "cardio", routine = mode.kind === "routine";
    const it = { id: "x" + ex.id, section: routine ? "warmup" : cardio ? "main" : "accessory", exercise_id: ex.id, exercise: ex, sets: 3,
      rep_low: mode.time ? 30 : 8, rep_high: mode.time ? 60 : 12, rest_sec: 60, minutes: cardio || routine ? 10 : null,
      protocol: cardio ? "zone2_steady" : null, protocol_text: cardio ? "Steady." : null,
      target: mode.kind === "weight_reps" ? { weight: 60, source: "increase", text: "", last: null } : null, adhoc: true };
    W.sets[it.id] = [];
    const div = document.createElement("div"); div.innerHTML = renderItem(it);
    const q = sel => div.querySelector(sel), has = sel => !!q(sel);
    const check = (cond, msg) => { if (!cond) note(ex.key, msg); };
    const head = (q("h3") || {}).textContent || "";
    if (cardio) {
      check(has("[data-logcardio]"), "cardio needs a Log it button");
      check(has("[data-countdown],[data-interval]"), "cardio needs a timer");
      check(!has("input.w") && !has("input.r"), "cardio must not ask for weight or reps");
      check(/min/.test(head), "cardio header shows minutes");
    } else if (routine) {
      check(has("[data-tickwu]"), "routine needs a Done tick");
      check(has("[data-countdown]"), "routine needs a timer");
      check(!has("input.r") && !has("input.w"), "routine must not ask for weight or reps");
    } else {
      const steppers = div.querySelectorAll(".set.entry .stepper");
      const w = q(".set.entry input.w:not([disabled])"), r = q(".set.entry input.r");
      check(!!r, "needs a reps or seconds box");
      const unit = steppers[1] ? steppers[1].querySelector(".u").textContent : "";
      check(mode.time ? /seconds/.test(unit) : /reps/.test(unit), `unit label is "${unit}"`);
      check(mode.perSide ? /each side/.test(unit) && /each side/.test(head) : !/each side/.test(unit), `per-side wording, label "${unit}", header "${head}"`);
      check(mode.time ? / s\b/.test(head) : !/\d s\b/.test(head), `header units "${head}"`);
      if (mode.weight === true) {
        check(!!w && w.placeholder === "kg", "needs a weight box");
        const label = w ? w.closest(".stepper").querySelector(".u").textContent : "";
        if (mode.bar != null) check(w && w.dataset.side === String(mode.bar) && /a side/.test(label) && w.step === "1.25", `barbell row should be plates a side, got "${label}" step ${w && w.step}`);
        else if (ex.equipment === "assisted") check(/assist/.test(label), `assisted label "${label}"`);
        else if (mode.perHand) check(/kg each/.test(label), `per-hand label "${label}"`);
        else check(label === "kg", `label "${label}"`);
      } else if (mode.weight === "optional") {
        check(!!w && w.placeholder === "+kg" && /added/.test(w.closest(".stepper").querySelector(".u").textContent), "optional added weight box");
      } else {
        check(!w, "must not ask for weight");
      }
      const holds = div.querySelectorAll("[data-hold]");
      if (mode.timer === "hold") {
        check(holds.length === (mode.perSide ? 2 : 1), `hold buttons: ${holds.length}`);
        if (mode.perSide) check([...holds].map(b => b.dataset.hside).join("") === "LR", "a Left and a Right hold button");
      } else check(holds.length === 0, "no hold timer expected");
      // a logged set reads back in the same units
      W.sets[it.id] = [{ client_id: "t" + ex.id, set_no: 1, reps: mode.time ? 30 : 10, weight: mode.weight === true ? 60 : 0, rpe: null, is_warmup: 0 }];
      const div2 = document.createElement("div"); div2.innerHTML = renderItem(it);
      const sum = (div2.querySelector(".set.logged .sum") || {}).textContent || "";
      check(mode.time ? /30 s/.test(sum) : /10 reps/.test(sum), `logged row "${sum}"`);
      if (mode.perSide) check(/each side/.test(sum), `logged row per side "${sum}"`);
      if (mode.bar != null) check(new RegExp(`\\(${(60 - mode.bar) / 2} a side\\)`).test(sum), `logged barbell row "${sum}"`);
      if (mode.kind === "weight_reps" && mode.bar != null) check(/a side/.test(div.querySelector(".target").textContent), "target line shows plates a side");
      delete W.sets[it.id];
    }
  }
  // an old-style treadmill set converts to minutes through the maintenance route
  const tread = S.exercises.find(e => e.key === "treadmill");
  await LocalApi.call("POST", "/api/sync", { ops: [{ type: "set", client_id: "sweep-tread", payload: { workout_client_id: W.client_id, exercise_id: tread.id, set_no: 1, reps: 30, weight_kg: null, rpe: 7 } }] });
  const m = await LocalApi.call("POST", "/api/maintenance/cardio_sets");
  const det = await LocalApi.call("GET", "/api/workouts/" + W.client_id);
  if (m.made !== 1) note("migration", "expected one converted set, got " + JSON.stringify(m));
  if (!det.cardio.some(c => c.minutes === 30 && c.exercise_id === tread.id)) note("migration", "no 30 minute cardio row");
  if (det.sets.some(s => s.exercise_id === tread.id)) note("migration", "the treadmill set is still there");
  return JSON.stringify({ checked, fails });
});

(async () => {
  await new Promise(r => server.listen(0, "127.0.0.1", r));
  const port = server.address().port, cdpPort = 9400 + Math.floor(Math.random() * 300);
  const profile = fs.mkdtempSync(path.join(require("node:os").tmpdir(), "ft-sweep-"));
  const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions", `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
  const finish = code => { try { edge.kill(); } catch (e) {} server.close(); setTimeout(() => { try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) {} process.exit(code); }, 300); };
  try {
    let ready = false;
    for (let i = 0; i < 60 && !ready; i++) { await sleep(500); try { ready = (await fetch(`http://127.0.0.1:${cdpPort}/json/version`)).ok; } catch (e) {} }
    if (!ready) { console.log("Edge did not start. Set EDGE to a Chromium browser path."); return finish(2); }
    const page = await (await fetch(`http://127.0.0.1:${cdpPort}/json/new?${encodeURIComponent(`http://127.0.0.1:${port}/phone/index.html`)}`, { method: "PUT" })).json();
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    let id = 0; const pending = {}, errors = [];
    const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending[i] = { res, rej }; ws.send(JSON.stringify({ id: i, method, params })); });
    ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.id && pending[m.id]) { pending[m.id].res(m.result || m.error); delete pending[m.id]; return; }
      if (m.method === "Runtime.exceptionThrown") { const d = m.params.exceptionDetails; errors.push((d.exception && d.exception.description) || d.text); }
      if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push(m.params.args.map(a => a.value || a.description).join(" "));
    };
    await new Promise(r => { ws.onopen = r; });
    await send("Runtime.enable");
    let booted = false;
    for (let i = 0; i < 60 && !booted; i++) {
      await sleep(500);
      const r = await send("Runtime.evaluate", { expression: `!!document.querySelector("#p-today .card, #p-today .hero, #p-today .cta")`, returnByValue: true });
      booted = !!(r.result && r.result.value);
    }
    if (!booted) { console.log("The app did not boot."); errors.forEach(e => console.log("  " + e)); return finish(2); }
    const r = await send("Runtime.evaluate", { expression: `(${SWEEP})()`, awaitPromise: true, returnByValue: true });
    const out = r.result && r.result.value ? JSON.parse(r.result.value) : { checked: 0, fails: ["sweep returned nothing: " + JSON.stringify(r)] };
    console.log(`UI sweep: ${out.checked} exercises checked, ${out.fails.length} problem(s)`);
    out.fails.forEach(f => console.log("  FAIL " + f));
    if (errors.length) { console.log("Console errors:"); errors.forEach(e => console.log("  " + e)); }
    return finish(out.fails.length || errors.length ? 1 : 0);
  } catch (e) { console.log("Sweep crashed: " + e.message); return finish(2); }
})();
