"use strict";
"use strict";
/* ---------------------------------------------------------- helpers */
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const n0 = x => (x == null || isNaN(x)) ? "-" : Math.round(x).toLocaleString("en-NZ");
const n1 = x => (x == null || isNaN(x)) ? "-" : (Math.round(x * 10) / 10).toLocaleString("en-NZ", { maximumFractionDigits: 1 });
const kg = x => x == null ? "" : n1(x) + " kg";
const pad2 = n => String(n).padStart(2, "0");
const isoOf = d => d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
const D = iso => new Date(String(iso).slice(0, 10) + "T00:00:00");
const todayIso = () => isoOf(new Date());
const addDays = (iso, n) => { const d = D(iso); d.setDate(d.getDate() + n); return isoOf(d); };
const nowIso = () => { const d = new Date(); return isoOf(d) + "T" + pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds()); };
const fmtDay   = iso => D(iso).toLocaleDateString("en-NZ", { weekday: "short", day: "numeric", month: "short" });
const fmtLong  = iso => D(iso).toLocaleDateString("en-NZ", { weekday: "long", day: "numeric", month: "long" });
const fmtShort = iso => D(iso).toLocaleDateString("en-NZ", { day: "numeric", month: "short" });
const fmtDate  = iso => D(iso).toLocaleDateString("en-NZ", { day: "numeric", month: "short", year: "numeric" });
const wdShort  = iso => D(iso).toLocaleDateString("en-NZ", { weekday: "short" });
const plural = (n, w) => n + " " + (n === 1 ? w : w + "s");
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : "x" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
const mmss = s => { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ":" + pad2(s % 60); };
const daysBetween = (a, b) => Math.round((D(b) - D(a)) / 86400000);
const ls = {
  get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  del(k) { try { localStorage.removeItem(k); } catch (e) {} },
};
const SLOT_NAMES = { breakfast: "Breakfast", lunch: "Lunch", dinner: "Dinner", snack: "Snacks" };
const SLOTS = ["breakfast", "lunch", "dinner", "snack"];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const KIND_SHORT = { upper_a: "Upper A", lower_a: "Lower A", upper_b: "Upper B", lower_b: "Lower B", conditioning: "Conditioning", zone2: "Zone 2", rest: "Rest" };

/* ---------------------------------------------------------- state */
let S = null;        // /api/state
let T = null;        // /api/today, cached for the gym
let FOODS = null;    // /api/foods/list rows
let ONLINE = true;
const IS_ANDROID_APP = !!(window.Android && window.Android.saveFile);
const UI = { tab: ls.get("ft-tab", "today"), foodDate: todayIso(), planDate: todayIso(), progressDays: 90, histRange: 90, histQ: "", exQ: "", foodQ: "" };
let W = ls.get("ft-live");       // the workout in progress, mirrored on every tap
const REST = { end: 0, total: 0, timer: null, finished: false };

/* ---------------------------------------------------------- local api */
async function api(method, path, body) {
  try { return await LocalApi.call(method, path, body); }
  catch (e) { const err = new Error(e.message || "Something went wrong"); err.code = e.code; throw err; }
}
/* Every write goes through here: it is applied on the device at once, then the screens refresh. */
async function mutate(type, client_id, payload, local) {
  if (local) { try { local(); } catch (e) { console.error(e); } }
  try {
    const res = await LocalApi.call("POST", "/api/sync", { ops: [{ type, client_id, payload, at: nowIso() }] });
    if (res.rejected.length) toast(res.rejected[0].error);
  } catch (e) { toast(e.message); }
  await load(true);
  return client_id;
}
async function flush() {}
async function updateNotice() { $("#notice").innerHTML = ""; }

/* ---------------------------------------------------------- load */
async function load(quiet) {
  try {
    const [s, t] = await Promise.all([api("GET", "/api/state"), api("GET", "/api/today")]);
    S = s; T = t;
    if (W && !S.in_progress) { W = null; saveW(); stopRest(); }
  } catch (e) {
    console.error(e);
    $("main").innerHTML = `<div class="card"><h2>Something went wrong</h2><p class="hint">${esc(e.message)}. Reload the app. If it keeps happening, export a backup from Settings and start fresh.</p></div>`;
    return;
  }
  renderAll();
  updateNotice();
}
function saveW() { if (W) ls.set("ft-live", W); else ls.del("ft-live"); $("#navLive").hidden = !W; }

function renderAll() {
  renderToday();
  renderWorkout();
  if (UI.tab === "plan") renderPlan();
  if (UI.tab === "food") renderFood();
  if (UI.tab === "progress") renderProgress();
  if (UI.tab === "history") renderHistory();
  if (UI.tab === "settings") renderSettings();
  $("#footBuild").textContent = S ? `Version ${S.version}, build ${S.build}${ONLINE ? "" : ", offline"}` : "";
}

/* ---------------------------------------------------------- tabs, theme, sheets, toast, tooltip */
function switchTab(name) {
  if (name === "more") { openSheet(`<div class="handle"></div><h2>More</h2><div class="grid" style="margin-top:10px">
    ${["plan", "progress", "history", "settings"].map(t => `<button class="big wide" data-go="${t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div>`); return; }
  UI.tab = name;
  $$(".tile").forEach(t => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  $$("[data-panel]").forEach(p => { p.hidden = p.dataset.panel !== name; });
  $$("#bottombar button").forEach(b => b.classList.toggle("on", b.dataset.go === name || (b.dataset.go === "more" && ["plan", "progress", "history", "settings"].includes(name))));
  ls.set("ft-tab", name);
  hideTip();
  closeSheet();
  if (S || T) {
    if (name === "plan") renderPlan();
    if (name === "food") renderFood();
    if (name === "progress") renderProgress();
    if (name === "history") renderHistory();
    if (name === "settings") renderSettings();
    if (name === "workout") renderWorkout();
  }
  window.scrollTo({ top: 0 });
}
$$(".tile").forEach(t => t.addEventListener("click", () => switchTab(t.dataset.tab)));
document.addEventListener("click", e => {
  const go = e.target.closest("[data-go]");
  if (go) switchTab(go.dataset.go);
});
$("#brand").addEventListener("click", e => { e.preventDefault(); switchTab("today"); });

const themeToggle = $("#themeToggle");
function applyTheme(t) { document.documentElement.setAttribute("data-theme", t); themeToggle.checked = t === "dark"; ls.set("ft-theme", t); }
themeToggle.addEventListener("change", () => { applyTheme(themeToggle.checked ? "dark" : "light"); if (S) renderAll(); });
{ const saved = ls.get("ft-theme"); if (saved) applyTheme(saved); else themeToggle.checked = matchMedia("(prefers-color-scheme: dark)").matches; }

let toastTimer = null;
function toast(msg, undo, ms) {
  const el = $("#toast");
  el.innerHTML = esc(msg) + (undo ? ` <button type="button">Undo</button>` : "");
  if (undo) $("button", el).addEventListener("click", async () => { el.classList.remove("show"); try { await undo(); } catch (e) { toast(e.message); } });
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), ms || (undo ? 6000 : 2600));
}
function showTip(html, ev) {
  const t = $("#tip"); t.innerHTML = html; t.classList.add("show");
  const pad = 14; let x = ev.clientX + pad, y = ev.clientY + pad;
  const r = t.getBoundingClientRect();
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - pad;
  t.style.left = x + "px"; t.style.top = y + "px";
}
function hideTip() { $("#tip").classList.remove("show"); }
document.addEventListener("touchstart", e => { if (!e.target.closest("svg")) hideTip(); }, { passive: true });

function openSheet(html, onOpen) {
  const back = $("#sheetBack"), sh = $("#sheet");
  sh.innerHTML = html; back.hidden = false; document.body.style.overflow = "hidden";
  if (onOpen) onOpen(sh);
  const first = $("input, select, button.primary", sh);
  if (first && !matchMedia("(max-width: 640px)").matches) first.focus();
}
function closeSheet() { $("#sheetBack").hidden = true; document.body.style.overflow = ""; }
$("#sheetBack").addEventListener("click", e => { if (e.target.id === "sheetBack") closeSheet(); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#sheetBack").hidden) closeSheet(); });

/* Service worker: the whole app is cached, so it opens with no connection. Not used inside the Android package. */
if ("serviceWorker" in navigator && !IS_ANDROID_APP && location.protocol.startsWith("http")) {
  navigator.serviceWorker.register("./sw.js").then(reg => {
    let hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (hadController) toast("Updated. Tap to reload", () => location.reload(), 12000);
      hadController = true;
    });
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") reg.update().catch(() => {}); });
  }).catch(() => {});
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
}

/* ---------------------------------------------------------- shared bits */
function targetLine(it) {
  const t = it.target; if (!t) return "";
  const scheme = it.sets ? `${it.sets} x ${it.rep_low}-${it.rep_high}${it.exercise && it.exercise.timed ? " s" : ""}` : "";
  const last = t.last && t.last.sets && t.last.sets.length ? `Last (${fmtShort(t.last.date)}): ${summariseSets(t.last.sets, it.exercise)}` : "First time";
  const tgt = t.weight != null ? `Target: ${scheme} at <b>${kg(t.weight)}</b>${it.exercise && it.exercise.per_hand ? " each" : ""}` : `Target: ${scheme}`;
  return `${last}. ${tgt}<span class="why">${esc(t.text || "")}</span>`;
}
function summariseSets(sets, ex) {
  const timed = ex && ex.timed;
  const groups = [];
  sets.forEach(s => {
    const g = groups[groups.length - 1];
    if (g && g.w === s.weight && g.r === s.reps) g.n++; else groups.push({ w: s.weight, r: s.reps, n: 1 });
  });
  const rpes = sets.map(s => s.rpe).filter(x => x != null);
  const rpe = rpes.length ? ", RPE " + n1(rpes.reduce((a, b) => a + b, 0) / rpes.length) : "";
  return groups.map(g => `${g.n} x ${g.r}${timed ? " s" : ""}${g.w ? " at " + kg(g.w) : ""}`).join(", ") + rpe;
}
function weekStrip(strip) {
  const today = todayIso();
  return `<div class="strip">${strip.map(s => {
    const dot = s.status === "done" ? "done" : s.kind === "rest" ? "rest" : s.status;
    return `<button class="day${s.date === today ? " today" : ""}" data-sess="${s.id}" title="${esc(s.title)}">
      <span class="d">${wdShort(s.date)}</span><span class="dot ${dot}"></span><span class="k">${esc(KIND_SHORT[s.kind] || s.title)}</span></button>`;
  }).join("")}</div>`;
}

/* ---------------------------------------------------------- Today */
function renderToday() {
  const root = $("#p-today");
  if (!S) { root.innerHTML = `<div class="card"><h2>Loading</h2></div>`; return; }
  const tg = S.targets, wb = S.weight, fd = S.food, st = S.settings;
  const today = todayIso();
  let hero;
  if (!S.profile_complete) {
    hero = `<div class="hero"><div><div class="kicker">Welcome</div><div class="big">Let's set you up</div>
      <p class="sub">Add your height, birth date, target weight and target date, and the app works out your daily calories, protein and pace.</p>
      <div class="quick"><button class="primary big" data-go="settings">Finish your profile</button></div></div>
      <div>${S.strip ? weekStrip(S.strip) : ""}</div></div>`;
  } else {
    const leftCls = tg.left < 0 ? " crit" : "";
    const modeText = tg.mode === "maintaining" ? "Holding steady at your target." :
      `${tg.mode === "losing" ? "Losing" : "Gaining"} about <b>${n1(Math.abs(tg.weekly_pace || 0))} kg a week</b> towards ${kg(st.target_weight_kg)} by ${fmtDate(st.target_date)}`;
    const days = tg.days_left;
    const capNote = tg.capped ? `<div class="callout warn">At ${n0(Math.abs(tg.deficit))} kcal a day you would reach ${kg(st.target_weight_kg)} on <strong>${fmtDate(tg.eta)}</strong>.${tg.target_passed ? " The target date has passed. Set a new one in Settings." : " The target date is too soon to be safe."}</div>` : "";
    const floorNote = tg.floored ? `<div class="callout">Held at the ${n0(tg.floor)} kcal floor. Eating less than this is not a good idea.</div>` : "";
    const macro = (label, have, want, cls) => `<div class="macro"><b>${label}</b><div class="meter ${cls}${have > want * 1.1 ? " over" : ""}"><span style="width:${Math.min(100, want ? have / want * 100 : 0)}%"></span></div><span class="num">${n0(have)} / ${n0(want)} g</span></div>`;
    hero = `<div class="hero">
      <div>
        <div class="kicker">Left to eat today</div>
        <div class="big num${leftCls}">${n0(tg.left)}<small>kcal</small></div>
        <p class="sub"><span class="fuel-ink">${n0(tg.eaten)} eaten</span> of a ${n0(tg.budget)} budget${tg.exercise ? `, including <span class="burn-ink">${n0(tg.exercise)} burned</span> training` : ""}.</p>
        <div class="macros">${macro("Protein", fd.totals.protein, tg.protein, "fuel")}${macro("Carbs", fd.totals.carb, tg.carbs, "fuel")}${macro("Fat", fd.totals.fat, tg.fat, "fuel")}</div>
        <div class="countdown">
          <div><div class="tiny muted">Days to go</div><div class="v num">${days != null ? Math.max(0, days) : "-"}</div></div>
          <div><div class="tiny muted">Weight</div><div class="v num">${wb.trend ? kg(wb.trend) : "log it"}</div></div>
          <div><div class="tiny muted">Pace</div><div class="v"><span class="pill ${wb.verdict.code === "on_pace" || wb.verdict.code === "ahead" ? "good" : wb.verdict.code === "behind" ? "warn" : ""}">${esc(wb.verdict.text)}</span></div></div>
        </div>
        <p class="sub" style="margin-top:10px">${modeText}</p>
        ${capNote}${floorNote}
      </div>
      <div>
        ${S.strip ? weekStrip(S.strip) : ""}
        ${sessionCard(S.session_today)}
        <div class="quick">
          <button data-q="weight">Log weight</button>
          <button data-q="water">Water +250 ml${S.daily.water_ml ? ` <span class="pill">${n0(S.daily.water_ml)} ml</span>` : ""}</button>
          <button data-q="sleep">Sleep${S.daily.sleep_h ? ` <span class="pill">${n1(S.daily.sleep_h)} h</span>` : ""}</button>
          <button data-q="steps">Steps${S.daily.steps ? ` <span class="pill">${n0(S.daily.steps)}</span>` : ""}</button>
        </div>
      </div>
    </div>`;
  }
  const prs = S.recent_prs && S.recent_prs.length ? `<div class="card"><h2>Personal bests from your last session</h2><ul class="prs">${S.recent_prs.map(p => `<li><b>${esc(p.exercise)}</b>: ${esc(p.text)}</li>`).join("")}</ul></div>` : "";
  const adh = S.week ? S.week.adherence : null;
  const stats = `<div class="grid g3">
    <div class="stat"><div class="l">This week</div><div class="v num">${adh ? `${adh.done} / ${adh.planned}` : "-"}</div><div class="f">sessions done${S.week && S.week.week.is_deload ? ", deload week" : ""}</div></div>
    <div class="stat"><div class="l">Weeks on track</div><div class="v num">${S.weeks_streak}</div><div class="f">weeks with 4 of 5 sessions or more</div></div>
    <div class="stat"><div class="l">Block</div><div class="v num">${S.week ? `${S.week.week.block_no}, week ${S.week.week.week_no}` : "-"}</div><div class="f">${S.week && S.week.week.week_no === 3 ? "deload next week" : S.week && S.week.week.is_deload ? "lighter on purpose" : "building"}</div></div>
  </div>`;
  root.innerHTML = hero + stats + prs;
  wireToday(root);
}
function sessionCard(s) {
  if (!s) return "";
  if (W && W.session_id === s.id) return `<div class="session-card"><h3>${esc(s.title)} in progress</h3><p class="muted small">Started ${W.started_at.slice(11, 16)}.</p><div class="quick"><button class="primary big" data-go="workout">Continue</button></div></div>`;
  if (s.kind === "rest") return `<div class="session-card"><h3>Rest day</h3><p class="muted small">Recovery counts. If you feel like moving, take an easy walk.</p><div class="quick"><button data-go="plan">See the week</button></div></div>`;
  const names = s.items.filter(i => ["main", "accessory", "core"].includes(i.section)).slice(0, 4).map(i => i.exercise ? i.exercise.name : "").filter(Boolean);
  const fin = s.items.find(i => i.section === "finisher");
  return `<div class="session-card"><div class="between"><h3>${esc(s.title)}${s.is_deload ? ' <span class="pill">deload</span>' : ""}</h3><span class="muted small">about ${n0(s.est_minutes)} min</span></div>
    <ul>${names.map(n => `<li>${esc(n)}</li>`).join("")}${fin ? `<li class="muted">${esc(fin.exercise ? fin.exercise.name : "Cardio")} finisher, ${n0(fin.minutes)} min</li>` : ""}</ul>
    <div class="quick">${s.status === "done" ? `<span class="pill good">Done</span>` : `<button class="primary big" data-start="${s.id}">Start</button>`}<button data-go="plan">Plan</button></div></div>`;
}
function wireToday(root) {
  $$("[data-start]", root).forEach(b => b.addEventListener("click", () => startSession(+b.dataset.start)));
  $$("[data-sess]", root).forEach(b => b.addEventListener("click", () => { UI.planDate = (S.strip.find(s => s.id === +b.dataset.sess) || {}).date || todayIso(); switchTab("plan"); }));
  $$("[data-q]", root).forEach(b => b.addEventListener("click", () => quickLog(b.dataset.q)));
}
function quickLog(kind) {
  const d = todayIso();
  if (kind === "water") {
    const cur = (S.daily.water_ml || 0) + 250;
    mutate("daily", "daily-" + d, { date: d, water_ml: cur }, () => { S.daily.water_ml = cur; renderToday(); });
    toast(`${n0(cur)} ml today`);
    return;
  }
  const fields = {
    weight: [["weight_kg", "Weight (kg)", "decimal", S.weight.latest ? S.weight.latest.weight_kg : S.settings.start_weight_kg], ["waist_cm", "Waist (cm), optional", "decimal", ""], ["chest_cm", "Chest (cm), optional", "decimal", ""], ["arm_cm", "Upper arm (cm), optional", "decimal", ""], ["hip_cm", "Hips (cm), optional", "decimal", ""], ["thigh_cm", "Thigh (cm), optional", "decimal", ""]],
    sleep: [["sleep_h", "Hours slept", "decimal", S.daily.sleep_h || ""]],
    steps: [["steps", "Steps", "numeric", S.daily.steps || ""]],
  }[kind];
  const titles = { weight: "Log your weight", sleep: "Last night's sleep", steps: "Steps today" };
  openSheet(`<div class="handle"></div><h2>${titles[kind]}</h2><p class="hint">For ${fmtLong(d)}. Measurements are optional and only need doing monthly.</p>
    ${fields.map(([k, label, mode, val]) => `<label class="field mb"><span>${label}</span><input type="number" step="0.1" inputmode="${mode}" id="q-${k}" value="${val ?? ""}"></label>`).join("")}
    <div class="row mt"><button class="primary big" id="qSave">Save</button><button class="ghost" id="qCancel">Cancel</button></div>`, sh => {
    $("#qCancel", sh).addEventListener("click", closeSheet);
    $("#qSave", sh).addEventListener("click", () => {
      const payload = { date: d };
      fields.forEach(([k]) => { const v = $("#q-" + k, sh).value; if (v !== "") payload[k] = +v; });
      if (kind === "weight") {
        if (!payload.weight_kg) { toast("Type your weight"); return; }
        mutate("body", "body-" + d, payload, () => { S.weight.latest = { date: d, weight_kg: payload.weight_kg }; S.weight.trend = payload.weight_kg; });
      } else {
        mutate("daily", "daily-" + d, payload, () => { Object.assign(S.daily, payload); });
      }
      closeSheet(); renderToday(); toast("Saved");
    });
  });
}

/* ---------------------------------------------------------- Workout */
function sessionById(id) {
  return (T && T.sessions.find(s => s.id === id)) || (S && S.week && S.week.sessions.find(s => s.id === id)) || null;
}
function startSession(id) {
  const s = sessionById(id);
  if (!s) { toast("That session is not loaded yet"); return; }
  if (W) { toast("Finish or discard the current workout first"); switchTab("workout"); return; }
  const today = todayIso();
  const items = JSON.parse(JSON.stringify(s.items));
  W = { client_id: uid(), session_id: s.id, date: today, started_at: nowIso(), title: s.title, kind: s.kind, is_deload: s.is_deload, items, sets: {}, cardio: [], skipped: {}, open: {}, local: true };
  saveW();
  mutate("workout", W.client_id, { session_id: s.id, date: today, started_at: W.started_at });
  switchTab("workout");
}
function startFreestyle() {
  const today = todayIso();
  W = { client_id: uid(), session_id: null, date: today, started_at: nowIso(), title: "Freestyle", kind: "adhoc", items: [], sets: {}, cardio: [], skipped: {}, open: {}, local: true };
  saveW();
  mutate("workout", W.client_id, { date: today, started_at: W.started_at });
  switchTab("workout");
}
function renderWorkout() {
  const root = $("#p-workout");
  $("#navLive").hidden = !W;
  if (!W) {
    // resume a workout started on another device
    if (S && S.in_progress && !W) {
      const ip = S.in_progress;
      const sess = sessionById(ip.session_id);
      root.innerHTML = `<div class="card"><h2>A workout is open</h2><p class="hint">Started ${esc((ip.started_at || "").slice(0, 16).replace("T", " "))}${sess ? " for " + esc(sess.title) : ""}, probably on your other device. Finish it there, or take it over here.</p>
        <div class="row"><button class="primary" id="takeover">Take over here</button><button class="danger" id="discardOpen">Discard it</button></div></div>`;
      $("#takeover").addEventListener("click", async () => {
        try {
          const det = await api("GET", "/api/workouts/" + ip.client_id);
          W = { client_id: det.client_id, session_id: det.session_id, date: det.date, started_at: det.started_at, title: sess ? sess.title : "Workout", kind: sess ? sess.kind : "adhoc", is_deload: sess && sess.is_deload, items: sess ? JSON.parse(JSON.stringify(sess.items)) : [], sets: {}, cardio: det.cardio.map(c => ({ client_id: c.client_id, plan_item_id: c.plan_item_id, minutes: c.minutes, intensity: c.intensity })), skipped: {}, open: {}, local: false };
          det.sets.forEach(s => { (W.sets[s.plan_item_id || "x" + s.exercise_id] = W.sets[s.plan_item_id || "x" + s.exercise_id] || []).push({ client_id: s.client_id, set_no: s.set_no, reps: s.reps, weight: s.weight_kg, rpe: s.rpe, is_warmup: s.is_warmup, done_at: s.done_at }); });
          saveW(); renderWorkout();
        } catch (e) { toast(e.message); }
      });
      $("#discardOpen").addEventListener("click", () => { if (confirm("Discard that open workout? Its sets will be removed.")) { mutate("workout", ip.client_id, { deleted: 1 }); S.in_progress = null; renderWorkout(); } });
      return;
    }
    const sessions = (T && T.sessions) || (S && S.week ? S.week.sessions : []);
    const today = todayIso();
    const todays = sessions.find(s => s.date === today);
    root.innerHTML = `<div class="card"><h2>Ready to train?</h2>
      <p class="hint">${todays && todays.kind !== "rest" ? `Today is <b>${esc(todays.title)}</b>, about ${n0(todays.est_minutes)} minutes.` : "Today is a rest day in the plan. You can still pull a session forward."}</p>
      ${sessions.filter(s => s.kind !== "rest").map(s => `<div class="pickcard"><div><b>${esc(s.title)}</b> <span class="muted small">${fmtDay(s.date)}${s.date === today ? ", today" : ""}${s.is_deload ? ", deload" : ""}</span>
          <div class="muted small">${s.items.filter(i => ["main", "accessory"].includes(i.section)).slice(0, 3).map(i => i.exercise ? esc(i.exercise.name) : "").filter(Boolean).join(", ")}</div></div>
          ${s.status === "done" ? `<span class="pill good">Done</span>` : `<button class="${s.date === today ? "primary" : ""}" data-start="${s.id}">${s.date === today ? "Start" : "Do it today"}</button>`}</div>`).join("") || `<div class="empty">No sessions loaded. Open the app on home wifi once.</div>`}
      <div class="row mt2"><button class="ghost" id="freestyle">Freestyle workout</button></div></div>`;
    $$("[data-start]", root).forEach(b => b.addEventListener("click", () => startSession(+b.dataset.start)));
    $("#freestyle").addEventListener("click", startFreestyle);
    return;
  }
  const elapsed = Math.round((Date.now() - new Date(W.started_at.length === 19 ? W.started_at : W.started_at)) / 1000);
  const sections = ["warmup", "main", "accessory", "core", "finisher", "cooldown"];
  const names = { warmup: "Warm-up", main: "Main lifts", accessory: "Accessories", core: "Core", finisher: "Finisher", cooldown: "Cool-down" };
  let html = `<div class="wk-head"><h2>${esc(W.title)}${W.is_deload ? ' <span class="pill">deload</span>' : ""}</h2><span class="elapsed" id="elapsed">${mmss(elapsed)}</span><span class="spacer"></span>
    <button class="primary" id="finishBtn">Finish</button><button class="ghost" id="discardBtn" title="Discard this workout">Discard</button></div>`;
  sections.forEach(sec => {
    const items = W.items.filter(i => i.section === sec);
    if (!items.length) return;
    html += `<div class="section-head">${names[sec]}</div>` + items.map(it => renderItem(it)).join("");
  });
  if (!W.items.length || W.kind === "adhoc") html += `<div class="section-head">Freestyle</div>`;
  html += `<div class="row mt"><button id="addEx">Add an exercise</button><button id="addCardio">Add cardio</button></div>`;
  const stray = Object.keys(W.sets).filter(k => k.startsWith("x"));
  if (stray.length) html += `<div class="section-head">Added</div>` + stray.map(k => renderItem({ id: k, section: "accessory", exercise_id: +k.slice(1), exercise: exById(+k.slice(1)), sets: 3, rep_low: 8, rep_high: 12, rest_sec: 90, target: null, adhoc: true })).join("");
  html += `<div class="row mt2"><button class="primary big wide" id="finishBtn2">Finish workout</button></div>`;
  root.innerHTML = html;
  wireWorkout(root);
  tickElapsed();
}
function exById(id) { return (S && S.exercises && S.exercises.find(e => e.id === id)) || null; }
function loggedSets(it) { return W.sets[it.id] || []; }
function renderItem(it) {
  const ex = it.exercise || exById(it.exercise_id) || { name: "Exercise", cues: [] };
  const done = loggedSets(it);
  const skipped = W.skipped[it.id];
  if (it.section === "warmup" || it.section === "cooldown") {
    const isCardio = it.protocol;
    return `<div class="ex${done.length || skipped ? " done" : ""}" data-item="${it.id}">
      <div class="ex-top"><div class="grow"><h3>${esc(ex.name)} <span class="scheme">${n0(it.minutes)} min</span></h3>
      ${isCardio ? `<div class="target">${esc(it.protocol_text || "Easy pace.")}</div>` : `<ul class="cues">${(ex.cues || []).map(c => `<li>${esc(c)}</li>`).join("")}</ul>`}</div>
      <button class="${skipped ? "" : "good"}" data-tickwu="${it.id}">${skipped ? "Undo" : "Done"}</button></div></div>`;
  }
  if (it.section === "finisher") {
    const c = W.cardio.find(x => x.plan_item_id === it.id);
    return `<div class="ex${c || skipped ? " done" : ""}" data-item="${it.id}">
      <div class="ex-top"><div class="grow"><h3>${esc(ex.name)} finisher <span class="scheme">${n0(it.minutes)} min</span></h3><div class="target">${esc(it.protocol_text || "")}</div></div></div>
      <div class="tools">${c ? `<span class="pill good">Logged ${n0(c.minutes)} min, ${esc(c.intensity)}</span><button class="ghost" data-uncardio="${it.id}">Remove</button>` : skipped ? `<span class="pill">Skipped</span><button class="ghost" data-unskip="${it.id}">Undo</button>` :
        `${it.protocol_detail && it.protocol_detail.work_sec ? `<button data-interval="${it.id}">Interval timer</button>` : `<button data-countdown="${it.id}">Timer</button>`}<button class="good" data-logcardio="${it.id}">Log it</button><button class="ghost" data-skip="${it.id}">Skip</button>`}</div></div>`;
  }
  const planned = it.sets || 3;
  const rows = [];
  const showWarm = it.slot_key === "main1" && it.target && it.target.weight && !done.some(s => s.is_warmup) && !done.length;
  if (showWarm) {
    rows.push(warmRow(it, 1, roundLoad(it.target.weight * 0.5, ex), 8));
    rows.push(warmRow(it, 2, roundLoad(it.target.weight * 0.75, ex), 4));
  }
  const working = done.filter(s => !s.is_warmup);
  working.forEach(s => rows.push(`<div class="set logged${s.is_warmup ? " warm" : ""}" data-edit="${s.client_id}" data-item="${it.id}"><span class="n">${s.set_no}</span>
    <span class="sum">${s.reps}${ex.timed ? " s" : " reps"}${s.weight ? " at " + kg(s.weight) : ""}${ex.per_hand && s.weight ? " each" : ""}<small>${s.rpe ? "RPE " + s.rpe : ""}</small></span><span class="tick">✓</span></div>`));
  if (!skipped && (working.length < planned || W.open[it.id])) {
    const n = working.length + 1;
    const last = working[working.length - 1];
    const defW = last ? last.weight : (it.target && it.target.weight != null ? it.target.weight : "");
    const defR = last ? last.reps : (ex.timed ? it.rep_low : it.rep_low);
    rows.push(setEntryRow(it, ex, n, defW, defR));
  }
  const cuesOpen = W.open["cues" + it.id];
  return `<div class="ex${working.length >= planned || skipped ? " done" : ""}" data-item="${it.id}">
    <div class="ex-top"><div class="grow"><h3>${esc(ex.name)} <span class="scheme">${planned} x ${it.rep_low}-${it.rep_high}${ex.timed ? " s" : ""}${ex.per_hand ? ", each hand" : ""}</span></h3>
      <div class="target">${targetLine(it)}</div>
      ${cuesOpen ? `<ul class="cues">${(ex.cues || []).map(c => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}</div></div>
    <div class="sets">${skipped ? `<div class="muted small">Skipped. <button class="link" data-unskip="${it.id}">Undo</button></div>` : rows.join("")}</div>
    <div class="tools"><button class="ghost" data-cues="${it.id}">${cuesOpen ? "Hide cues" : "Form cues"}</button>
      ${!skipped && working.length >= planned ? `<button class="ghost" data-more="${it.id}">Add a set</button>` : ""}
      ${!it.adhoc && !working.length && !skipped ? `<button class="ghost" data-swap="${it.id}">Swap</button><button class="ghost" data-skip="${it.id}">Skip</button>` : ""}</div></div>`;
}
function roundLoad(x, ex) { const step = ex && ex.equipment === "dumbbell" && x < 10 ? 1 : 2.5; return Math.floor(x / step + 0.5) * step; }
function warmRow(it, n, w, reps) {
  return `<div class="set warm" data-warm="${it.id}"><span class="n">W${n}</span><div class="muted small" style="grid-column:2/4">Warm-up: ${reps} at ${kg(w)}</div><button class="logbtn" data-logwarm="${it.id}" data-w="${w}" data-r="${reps}">✓</button></div>`;
}
function setEntryRow(it, ex, n, defW, defR) {
  const step = ex.equipment === "dumbbell" && (defW || 0) < 10 ? 1 : 2.5;
  const noWeight = ex.timed || (ex.equipment === "bodyweight" && !ex.bodyweight_fraction) || ex.pattern === "mobility";
  const label = ex.equipment === "assisted" ? "assist kg" : ex.per_hand ? "kg each" : "kg";
  return `<div class="set entry" data-entry="${it.id}">
    <span class="n">${n}</span>
    ${noWeight && ex.equipment !== "assisted" ? `<div class="stepper" style="visibility:${ex.equipment === "bodyweight" ? "visible" : "hidden"}"><button data-step="w" data-d="-${step}">−</button><div><input type="number" inputmode="decimal" step="${step}" class="w" value="${defW === "" || defW == null ? "" : defW}" placeholder="+kg"><div class="u">added kg</div></div><button data-step="w" data-d="${step}">+</button></div>` :
      `<div class="stepper"><button data-step="w" data-d="-${step}">−</button><div><input type="number" inputmode="decimal" step="${step}" class="w" value="${defW === "" || defW == null ? "" : defW}" placeholder="kg"><div class="u">${label}</div></div><button data-step="w" data-d="${step}">+</button></div>`}
    <div class="stepper"><button data-step="r" data-d="-1">−</button><div><input type="number" inputmode="numeric" class="r" value="${defR ?? ""}" placeholder="${ex.timed ? "s" : "reps"}"><div class="u">${ex.timed ? "seconds" : "reps"}</div></div><button data-step="r" data-d="${ex.timed ? 5 : 1}">+</button></div>
    <button class="primary logbtn" data-log="${it.id}" aria-label="Log set">✓</button>
    <div class="rpe"><span>RPE</span>${[6, 7, 8, 9, 10].map(v => `<button type="button" data-rpe="${v}">${v}</button>`).join("")}<button type="button" data-rpehalf title="add a half">½</button></div>
  </div>`;
}
function wireWorkout(root) {
  $$("[data-step]", root).forEach(b => b.addEventListener("click", () => {
    const inp = $(b.dataset.step === "w" ? "input.w" : "input.r", b.closest(".stepper"));
    const d = parseFloat(b.dataset.d);
    inp.value = Math.max(0, Math.round(((parseFloat(inp.value) || 0) + d) * 100) / 100);
  }));
  $$("[data-rpe]", root).forEach(b => b.addEventListener("click", () => {
    const wrap = b.closest(".rpe");
    const on = b.classList.contains("on");
    $$("[data-rpe]", wrap).forEach(x => x.classList.remove("on"));
    if (!on) b.classList.add("on");
  }));
  $$("[data-rpehalf]", root).forEach(b => b.addEventListener("click", () => b.classList.toggle("on")));
  $$("[data-log]", root).forEach(b => b.addEventListener("click", () => {
    const row = b.closest(".set"), it = W.items.find(i => String(i.id) === b.dataset.log) || strayItem(b.dataset.log);
    const ex = it.exercise || exById(it.exercise_id) || {};
    const wInp = $("input.w", row), rInp = $("input.r", row);
    const reps = parseInt(rInp.value, 10);
    const weight = wInp && wInp.value !== "" ? parseFloat(wInp.value) : (ex.timed || ex.equipment === "bodyweight" ? 0 : null);
    if (!reps && reps !== 0) { toast(ex.timed ? "How many seconds?" : "How many reps?"); rInp.focus(); return; }
    if (weight === null) { toast("What weight?"); wInp.focus(); return; }
    const on = $(".rpe .on[data-rpe]", row);
    let rpe = on ? parseFloat(on.dataset.rpe) : null;
    if (rpe && $("[data-rpehalf]", row).classList.contains("on") && rpe < 10) rpe += 0.5;
    logSet(it, reps, weight, rpe, 0);
  }));
  $$("[data-logwarm]", root).forEach(b => b.addEventListener("click", () => {
    const it = W.items.find(i => String(i.id) === b.dataset.logwarm);
    logSet(it, +b.dataset.r, +b.dataset.w, null, 1, true);
  }));
  $$("[data-edit]", root).forEach(row => row.addEventListener("click", () => editSet(row.dataset.item, row.dataset.edit)));
  $$("[data-cues]", root).forEach(b => b.addEventListener("click", () => { W.open["cues" + b.dataset.cues] = !W.open["cues" + b.dataset.cues]; saveW(); renderWorkout(); }));
  $$("[data-more]", root).forEach(b => b.addEventListener("click", () => { W.open[b.dataset.more] = true; saveW(); renderWorkout(); }));
  $$("[data-skip]", root).forEach(b => b.addEventListener("click", () => { W.skipped[b.dataset.skip] = true; saveW(); renderWorkout(); }));
  $$("[data-unskip]", root).forEach(b => b.addEventListener("click", () => { delete W.skipped[b.dataset.unskip]; saveW(); renderWorkout(); }));
  $$("[data-tickwu]", root).forEach(b => b.addEventListener("click", () => { const k = b.dataset.tickwu; if (W.skipped[k]) delete W.skipped[k]; else W.skipped[k] = true; saveW(); renderWorkout(); }));
  $$("[data-swap]", root).forEach(b => b.addEventListener("click", () => swapItem(+b.dataset.swap)));
  $$("[data-logcardio]", root).forEach(b => b.addEventListener("click", () => logCardioSheet(W.items.find(i => String(i.id) === b.dataset.logcardio))));
  $$("[data-uncardio]", root).forEach(b => b.addEventListener("click", () => {
    const idx = W.cardio.findIndex(c => String(c.plan_item_id) === b.dataset.uncardio);
    if (idx >= 0) { const c = W.cardio.splice(idx, 1)[0]; saveW(); mutate("cardio", c.client_id, { deleted: 1 }); renderWorkout(); }
  }));
  $$("[data-interval]", root).forEach(b => b.addEventListener("click", () => intervalTimer(W.items.find(i => String(i.id) === b.dataset.interval))));
  $$("[data-countdown]", root).forEach(b => b.addEventListener("click", () => { const it = W.items.find(i => String(i.id) === b.dataset.countdown); startRest(Math.round((it.minutes || 10) * 60), "Finisher"); }));
  $("#finishBtn").addEventListener("click", finishSheet);
  $("#finishBtn2").addEventListener("click", finishSheet);
  $("#discardBtn").addEventListener("click", () => {
    if (!confirm("Discard this workout? Everything logged in it will be removed.")) return;
    const cid = W.client_id; W = null; saveW(); stopRest();
    mutate("workout", cid, { deleted: 1 });
    renderWorkout(); toast("Workout discarded");
  });
  $("#addEx").addEventListener("click", addExerciseSheet);
  $("#addCardio").addEventListener("click", () => logCardioSheet(null));
}
function strayItem(key) {
  const exId = +String(key).slice(1);
  return { id: key, section: "accessory", exercise_id: exId, exercise: exById(exId), sets: 3, rep_low: 8, rep_high: 12, rest_sec: 90, adhoc: true };
}
function logSet(it, reps, weight, rpe, is_warmup, quiet) {
  const key = it.id;
  const list = W.sets[key] = W.sets[key] || [];
  const set_no = list.filter(s => !s.is_warmup).length + (is_warmup ? 0 : 1) || 1;
  const cid = uid();
  const rec = { client_id: cid, set_no: is_warmup ? list.filter(s => s.is_warmup).length + 1 : set_no, reps, weight, rpe, is_warmup, done_at: nowIso() };
  list.push(rec);
  W.local = true;
  saveW();
  mutate("set", cid, { workout_client_id: W.client_id, plan_item_id: it.adhoc ? null : it.id, exercise_id: it.exercise_id, set_no: rec.set_no, reps, weight_kg: weight, rpe, is_warmup, done_at: rec.done_at });
  renderWorkout();
  if (!quiet) startRest(it.rest_sec || (S && S.settings.rest_default_sec) || 90, (it.exercise || exById(it.exercise_id) || {}).name);
}
function editSet(itemKey, cid) {
  const it = W.items.find(i => String(i.id) === String(itemKey)) || strayItem(itemKey);
  const ex = it.exercise || exById(it.exercise_id) || {};
  const list = W.sets[it.id] || [];
  const s = list.find(x => x.client_id === cid);
  if (!s) return;
  openSheet(`<div class="handle"></div><h2>Set ${s.set_no}, ${esc(ex.name)}</h2>
    <div class="f-row"><label class="field grow"><span>${ex.timed ? "Seconds" : "Reps"}</span><input type="number" inputmode="numeric" id="e-reps" value="${s.reps}"></label>
    <label class="field grow"><span>${ex.equipment === "assisted" ? "Assistance (kg)" : "Weight (kg)"}</span><input type="number" inputmode="decimal" step="0.5" id="e-w" value="${s.weight ?? ""}"></label>
    <label class="field grow"><span>RPE</span><input type="number" inputmode="decimal" step="0.5" min="5" max="10" id="e-rpe" value="${s.rpe ?? ""}"></label></div>
    <div class="row"><button class="primary big" id="e-save">Save</button><button class="danger" id="e-del">Delete set</button><button class="ghost" id="e-cancel">Cancel</button></div>`, sh => {
    $("#e-cancel", sh).addEventListener("click", closeSheet);
    $("#e-save", sh).addEventListener("click", () => {
      s.reps = parseInt($("#e-reps", sh).value, 10) || 0; s.weight = $("#e-w", sh).value === "" ? null : parseFloat($("#e-w", sh).value); s.rpe = $("#e-rpe", sh).value === "" ? null : parseFloat($("#e-rpe", sh).value);
      saveW(); mutate("set", cid, { workout_client_id: W.client_id, exercise_id: it.exercise_id, reps: s.reps, weight_kg: s.weight, rpe: s.rpe });
      closeSheet(); renderWorkout();
    });
    $("#e-del", sh).addEventListener("click", () => {
      W.sets[it.id] = list.filter(x => x.client_id !== cid);
      W.sets[it.id].filter(x => !x.is_warmup).forEach((x, i) => { x.set_no = i + 1; });
      saveW(); mutate("set", cid, { deleted: 1 }); closeSheet(); renderWorkout();
    });
  });
}
async function swapItem(itemId) {
  try {
    const r = await api("POST", "/api/plan/swap", { item_id: itemId });
    const it = W.items.find(i => i.id === itemId);
    it.exercise = r.exercise; it.exercise_id = r.exercise.id; it.target = null;
    if (r.exercise.timed) { it.rep_low = 30; it.rep_high = 60; }
    saveW(); renderWorkout(); toast("Swapped to " + r.exercise.name);
    load(true);
  } catch (e) { toast(e.message); }
}
function addExerciseSheet() {
  const exs = (S && S.exercises || []).filter(e => e.active && !e.pattern.startsWith("cardio") && e.pattern !== "mobility").sort((a, b) => a.name.localeCompare(b.name));
  openSheet(`<div class="handle"></div><h2>Add an exercise</h2><input type="search" id="ax-q" placeholder="Search the library" autocomplete="off">
    <div id="ax-list" style="margin-top:10px;max-height:50vh;overflow-y:auto"></div>`, sh => {
    const list = $("#ax-list", sh), q = $("#ax-q", sh);
    const draw = () => {
      const t = q.value.trim().toLowerCase();
      const hits = exs.filter(e => !t || e.name.toLowerCase().includes(t) || e.pattern.includes(t) || e.primary_muscle.includes(t)).slice(0, 40);
      list.innerHTML = hits.map(e => `<div class="lg-row click" data-add="${e.id}"><div class="lg-what"><div class="t">${esc(e.name)}</div><div class="c">${esc(e.primary_muscle)}, ${esc(e.equipment)}</div></div><span class="pill">${esc(e.pattern.replace("_", " "))}</span></div>`).join("") || `<div class="empty">Nothing matches</div>`;
      $$("[data-add]", list).forEach(r => r.addEventListener("click", () => { W.sets["x" + r.dataset.add] = W.sets["x" + r.dataset.add] || []; W.open["x" + r.dataset.add] = true; saveW(); closeSheet(); renderWorkout(); }));
    };
    q.addEventListener("input", draw); draw();
  });
}
function logCardioSheet(it) {
  const machines = (S && S.exercises || []).filter(e => e.pattern.startsWith("cardio"));
  const ex = it ? (it.exercise || exById(it.exercise_id)) : null;
  const proto = it && it.protocol_detail || {};
  openSheet(`<div class="handle"></div><h2>${it ? "Log the finisher" : "Log cardio"}</h2>
    ${it ? `<p class="hint">${esc(ex ? ex.name : "")}: ${esc(it.protocol_text || "")}</p>` : `<label class="field mb"><span>Machine</span><select id="c-ex">${machines.map(m => `<option value="${m.id}">${esc(m.name)}</option>`).join("")}</select></label>`}
    <div class="f-row"><label class="field grow"><span>Minutes</span><input type="number" inputmode="decimal" step="1" id="c-min" value="${it ? it.minutes || 10 : 20}"></label>
    <label class="field grow"><span>Distance (km), optional</span><input type="number" inputmode="decimal" step="0.1" id="c-km"></label></div>
    <label class="field mb"><span>How hard</span><select id="c-int">${["easy", "moderate", "vigorous", "interval"].map(v => `<option value="${v}"${(proto.intensity || "moderate") === v ? " selected" : ""}>${v[0].toUpperCase() + v.slice(1)}</option>`).join("")}</select></label>
    <div class="row"><button class="primary big" id="c-save">Save</button><button class="ghost" id="c-cancel">Cancel</button></div>`, sh => {
    $("#c-cancel", sh).addEventListener("click", closeSheet);
    $("#c-save", sh).addEventListener("click", () => {
      const cid = uid();
      const rec = { client_id: cid, plan_item_id: it ? it.id : null, exercise_id: it ? it.exercise_id : +$("#c-ex", sh).value, minutes: parseFloat($("#c-min", sh).value) || 0, intensity: $("#c-int", sh).value, protocol: it ? it.protocol : null, distance_km: $("#c-km", sh).value ? parseFloat($("#c-km", sh).value) : null };
      if (!rec.minutes) { toast("How many minutes?"); return; }
      W.cardio.push(rec); saveW();
      mutate("cardio", cid, { workout_client_id: W.client_id, plan_item_id: rec.plan_item_id, exercise_id: rec.exercise_id, minutes: rec.minutes, intensity: rec.intensity, protocol: rec.protocol, distance_km: rec.distance_km });
      closeSheet(); renderWorkout(); toast("Cardio logged");
    });
  });
}
/* Rest timer in the sticky bar. */
function startRest(sec, label) {
  REST.total = sec; REST.end = Date.now() + sec * 1000; REST.finished = false; REST.label = label || "Rest";
  const bar = $("#timerbar"); bar.hidden = false;
  clearInterval(REST.timer);
  const draw = () => {
    const left = Math.ceil((REST.end - Date.now()) / 1000);
    if (left <= 0 && !REST.finished) {
      REST.finished = true;
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      beep();
      bar.innerHTML = `<span class="t">Go</span><span class="l">${esc(REST.label)}</span><span class="spacer"></span><button class="primary" id="restClose">Next set</button>`;
      $("#restClose").addEventListener("click", stopRest);
      setTimeout(() => { if (REST.finished) stopRest(); }, 8000);
      clearInterval(REST.timer);
      return;
    }
    bar.innerHTML = `<span class="t num">${mmss(left)}</span><span class="l">rest, ${esc(REST.label)}</span><span class="spacer"></span><button id="restPlus">+30 s</button><button id="restSkip">Skip</button>`;
    $("#restPlus").addEventListener("click", () => { REST.end += 30000; draw(); });
    $("#restSkip").addEventListener("click", stopRest);
  };
  draw();
  REST.timer = setInterval(draw, 500);
}
function stopRest() { clearInterval(REST.timer); REST.finished = false; $("#timerbar").hidden = true; }
function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination); o.frequency.value = 880; g.gain.value = 0.08;
    o.start(); setTimeout(() => { o.stop(); ctx.close(); }, 220);
  } catch (e) {}
}
function tickElapsed() {
  clearInterval(tickElapsed.t);
  tickElapsed.t = setInterval(() => { const el = $("#elapsed"); if (!el || !W) { clearInterval(tickElapsed.t); return; } el.textContent = mmss((Date.now() - new Date(W.started_at)) / 1000); }, 1000);
}
function intervalTimer(it) {
  const p = it.protocol_detail, rounds = it.rounds || 6;
  let round = 1, phase = "work", end = Date.now() + p.work_sec * 1000, timer;
  openSheet(`<div class="handle"></div><h2>${esc((it.exercise || {}).name || "Interval")} intervals</h2><p class="hint">${esc(it.protocol_text || "")}</p>
    <div class="proto"><div><div class="tiny muted" id="iv-phase">Work</div><div class="t work" id="iv-t">${mmss(p.work_sec)}</div></div><div class="display" id="iv-round" style="font-size:22px">Round 1 of ${rounds}</div></div>
    <div class="row mt2"><button class="primary big" id="iv-done">Done, log it</button><button class="ghost" id="iv-stop">Stop</button></div>`, sh => {
    const draw = () => {
      const left = Math.ceil((end - Date.now()) / 1000);
      if (left <= 0) {
        if (navigator.vibrate) navigator.vibrate(phase === "work" ? [300] : [150, 100, 150]);
        beep();
        if (phase === "work") { phase = "rest"; end = Date.now() + p.rest_sec * 1000; }
        else { round++; if (round > rounds) { clearInterval(timer); $("#iv-phase", sh).textContent = "Finished"; $("#iv-t", sh).textContent = "Done"; return; } phase = "work"; end = Date.now() + p.work_sec * 1000; }
      }
      $("#iv-phase", sh).textContent = phase === "work" ? "Work" : "Easy";
      const t = $("#iv-t", sh); t.textContent = mmss(Math.max(0, Math.ceil((end - Date.now()) / 1000))); t.classList.toggle("work", phase === "work");
      $("#iv-round", sh).textContent = `Round ${Math.min(round, rounds)} of ${rounds}`;
    };
    timer = setInterval(draw, 250);
    $("#iv-stop", sh).addEventListener("click", () => { clearInterval(timer); closeSheet(); });
    $("#iv-done", sh).addEventListener("click", () => { clearInterval(timer); closeSheet(); logCardioSheet(it); });
  });
}
function localSummary() {
  let sets = 0, volume = 0, hard = 0, rpes = 0;
  const bw = (T && T.bodyweight) || (S && S.weight && S.weight.trend) || 80;
  Object.entries(W.sets).forEach(([k, list]) => {
    const it = W.items.find(i => String(i.id) === k) || strayItem(k);
    const ex = it.exercise || exById(it.exercise_id) || {};
    list.filter(s => !s.is_warmup).forEach(s => {
      sets++;
      const load = ex.equipment === "assisted" ? Math.max(0, (ex.bodyweight_fraction || 0) * bw - (s.weight || 0)) : (s.weight || 0) + (ex.bodyweight_fraction || 0) * bw;
      if (!ex.timed) volume += load * (s.reps || 0) * (ex.per_hand ? 2 : 1);
      if (s.rpe != null) { rpes++; if (s.rpe >= 8) hard++; }
    });
  });
  return { sets, volume: Math.round(volume), hard, rpes, cardioMin: W.cardio.reduce((a, c) => a + (c.minutes || 0), 0) };
}
function finishSheet() {
  const sum = localSummary();
  openSheet(`<div class="handle"></div><h2>Finish ${esc(W.title)}</h2>
    <div class="summary"><div class="parts"><div><b>${sum.sets}</b><span>working sets</span></div><div><b>${n0(sum.volume)}</b><span>kg lifted</span></div><div><b>${sum.hard}</b><span>hard sets</span></div></div></div>
    <p class="hint mt">Calories and the effort score are worked out on the laptop once this syncs. If your watch gave you numbers, type them in.</p>
    <div class="f-row"><label class="field grow"><span>Calories from your watch, optional</span><input type="number" inputmode="numeric" id="f-kcal"></label>
    <label class="field grow"><span>Average heart rate, optional</span><input type="number" inputmode="numeric" id="f-hr"></label>
    <label class="field grow"><span>How hard overall, 1 to 10</span><input type="number" inputmode="decimal" step="0.5" min="1" max="10" id="f-rpe"></label></div>
    <label class="field mb"><span>Notes</span><textarea id="f-notes" placeholder="Anything worth remembering"></textarea></label>
    <div class="row"><button class="primary big" id="f-save">Finish</button><button class="ghost" id="f-cancel">Not yet</button></div>`, sh => {
    $("#f-cancel", sh).addEventListener("click", closeSheet);
    $("#f-save", sh).addEventListener("click", async () => {
      const payload = { ended_at: nowIso() };
      if ($("#f-kcal", sh).value) payload.kcal_wearable = +$("#f-kcal", sh).value;
      if ($("#f-hr", sh).value) payload.hr_avg = +$("#f-hr", sh).value;
      if ($("#f-rpe", sh).value) payload.session_rpe = +$("#f-rpe", sh).value;
      if ($("#f-notes", sh).value.trim()) payload.notes = $("#f-notes", sh).value.trim();
      const cid = W.client_id;
      W = null; saveW(); stopRest(); closeSheet();
      if (S) S.in_progress = null;
      await mutate("workout", cid, payload);
      renderWorkout();
      toast("Workout saved. Nice work.");
      setTimeout(() => showWorkoutSummary(cid), 1200);
    });
  });
}
async function showWorkoutSummary(cid) {
  if (!ONLINE) return;
  try {
    const d = await api("GET", "/api/workouts/" + cid);
    if (!d.ended_at) return;
    const parts = d.effort_parts || {};
    openSheet(`<div class="handle"></div><h2>${esc(d.session ? d.session.title : "Workout")} done</h2>
      <div class="summary"><div class="row" style="align-items:baseline;gap:14px"><div class="big num">${d.effort ?? "-"}</div><div><div class="tiny muted">effort out of 100</div><div class="muted small">${n0(d.kcal_used)} kcal burned${d.kcal_wearable ? " (from your watch)" : " (estimated)"}</div></div></div>
      <div class="parts"><div><b>${d.work_sets}</b><span>sets</span></div><div><b>${n0(d.volume)}</b><span>kg lifted</span></div><div><b>${d.hard_sets}</b><span>hard sets</span></div></div>
      ${parts.volume != null ? `<p class="hint mt">Effort parts: volume ${n1(parts.volume)}, hard sets ${n1(parts.hard_sets)}, calories ${n1(parts.calories)}${parts.ref_volume ? `. Your usual volume for this session is ${n0(parts.ref_volume)} kg` : ""}.</p>` : ""}
      ${d.prs && d.prs.length ? `<h3 class="mt">Personal bests</h3><ul class="prs">${d.prs.map(p => `<li><b>${esc(p.exercise)}</b>: ${esc(p.text)}</li>`).join("")}</ul>` : ""}</div>
      <div class="row mt2"><button class="primary big" id="sumClose">Close</button></div>`, sh => $("#sumClose", sh).addEventListener("click", closeSheet));
  } catch (e) {}
}

/* ---------------------------------------------------------- Plan */
let PLANWEEK = null;
async function renderPlan() {
  const root = $("#p-plan");
  let wk = null;
  try { wk = await api("GET", "/api/plan/week?date=" + UI.planDate); }
  catch (e) { toast(e.message); }
  if (!wk) { root.innerHTML = `<div class="card"><h2>Plan</h2><p class="hint">That week could not be loaded.</p><div class="row"><button id="planToday">Back to this week</button></div></div>`; $("#planToday").addEventListener("click", () => { UI.planDate = todayIso(); renderPlan(); }); return; }
  PLANWEEK = wk;
  const w = wk.week, today = todayIso();
  root.innerHTML = `<div class="week-nav">
      <button class="ghost" id="wkPrev" aria-label="Previous week">‹</button>
      <div><h2>Block ${w.block_no}, week ${w.week_no} of ${wk.weeks_in_block}${w.is_deload ? ' <span class="pill">deload</span>' : ""}${wk.split_name ? ` <span class="pill accent">${esc(wk.split_name)}</span>` : ""}</h2><div class="muted small">${fmtShort(w.start_date)} to ${fmtShort(addDays(w.start_date, 6))}, ${wk.adherence.done} of ${wk.adherence.planned} done</div></div>
      <button class="ghost" id="wkNext" aria-label="Next week">›</button>
      <span class="spacer"></span>
      ${UI.planDate.slice(0, 10) !== today && !(w.start_date <= today && addDays(w.start_date, 6) >= today) ? `<button id="wkToday">This week</button>` : ""}
      <button id="wkShuffle" title="Different accessories and finishers for the sessions you have not started">Shuffle week</button>
    </div>
    <div class="plan-grid">${wk.sessions.map(s => planDay(s, today)).join("")}</div>
    <p class="hint mt2">Main lifts stay for the block so you can build on them. Accessories and finishers rotate each week. Week 4 is lighter on purpose.${w.week_no === 4 ? " Next block, the main lifts change." : ""}</p>`;
  $("#wkPrev").addEventListener("click", () => { UI.planDate = addDays(w.start_date, -7); renderPlan(); });
  $("#wkNext").addEventListener("click", () => { UI.planDate = addDays(w.start_date, 7); renderPlan(); });
  const wt = $("#wkToday"); if (wt) wt.addEventListener("click", () => { UI.planDate = today; renderPlan(); });
  $("#wkShuffle").addEventListener("click", async () => { try { await api("POST", "/api/plan/shuffle", { week_id: w.id }); toast("Shuffled"); await renderPlan(); load(true); } catch (e) { toast(e.message); } });
  $$("[data-start]", root).forEach(b => b.addEventListener("click", () => startSession(+b.dataset.start)));
  $$("[data-move]", root).forEach(b => b.addEventListener("click", async () => { try { await api("POST", "/api/plan/move", { session_id: +b.dataset.move }); toast("Moved to today"); UI.planDate = today; await load(true); renderPlan(); } catch (e) { toast(e.message); } }));
  $$("[data-rest]", root).forEach(b => b.addEventListener("click", async () => { try { await api("POST", "/api/plan/rest", { session_id: +b.dataset.rest }); toast("Marked as rest"); await renderPlan(); load(true); } catch (e) { toast(e.message); } }));
  $$("[data-pswap]", root).forEach(b => b.addEventListener("click", async () => { try { const r = await api("POST", "/api/plan/swap", { item_id: +b.dataset.pswap }); toast("Swapped to " + r.exercise.name); await renderPlan(); load(true); } catch (e) { toast(e.message); } }));
  $$("[data-view]", root).forEach(b => b.addEventListener("click", () => showWorkoutDetail(b.dataset.view)));
}
function planDay(s, today) {
  const isToday = s.date === today;
  const pill = s.status === "done" ? `<span class="pill good">done</span>` : s.status === "skipped" ? `<span class="pill crit">${s.note === "rest" ? "rested" : "missed"}</span>` : s.status === "void" ? `<span class="pill">before start</span>` : s.kind === "rest" ? "" : isToday ? `<span class="pill accent">today</span>` : "";
  const items = s.items.filter(i => ["main", "accessory", "core"].includes(i.section) && i.sets);
  const fin = s.items.find(i => i.section === "finisher");
  const canEdit = s.status === "planned" && !(s.workout && s.workout.started_at) && s.date >= today;
  const list = s.kind === "rest" ? `<p class="muted small">Recovery day.</p>` : `<ul>${items.map(i => `<li><span>${esc(i.exercise ? i.exercise.name : "")}${i.optional ? ' <span class="tiny muted">(if time)</span>' : ""}</span><span class="s">${i.sets} x ${i.rep_low}-${i.rep_high}${i.target && i.target.weight ? " · " + n1(i.target.weight) : ""}${canEdit ? ` <button class="ghost" data-pswap="${i.id}" title="Swap for another">⇄</button>` : ""}</span></li>`).join("")}
    ${fin ? `<li><span class="muted">${esc(fin.exercise ? fin.exercise.name : "Cardio")} finisher</span><span class="s">${n0(fin.minutes)} min</span></li>` : ""}
    ${s.items.filter(i => i.section === "main" && i.protocol).map(i => `<li><span>${esc(i.exercise ? i.exercise.name : "")}: ${esc(i.protocol_text || "")}</span><span class="s">${n0(i.minutes)} min</span></li>`).join("")}</ul>`;
  const acts = s.kind === "rest" ? "" : s.status === "done" && s.workout ? `<button data-view="${s.workout.client_id}">View</button>` :
    isToday && s.status !== "done" ? `<button class="primary" data-start="${s.id}">${W && W.session_id === s.id ? "Continue" : "Start"}</button>` :
    ["planned", "skipped", "void"].includes(s.status) && s.date !== today ? `<button data-move="${s.id}">Do today</button>${s.status === "planned" && s.date > today ? `<button class="ghost" data-rest="${s.id}">Rest</button>` : ""}` : "";
  return `<div class="pday${isToday ? " today" : ""}${s.kind === "rest" ? " rest" : ""}"><div class="dh"><b>${wdShort(s.date)} ${D(s.date).getDate()}</b>${pill}</div>
    <h3>${esc(s.title)}${s.moved_from ? ` <span class="tiny muted">moved</span>` : ""}</h3>${list}
    ${s.kind !== "rest" ? `<div class="tiny muted">about ${n0(s.est_minutes)} min</div>` : ""}<div class="acts">${acts}</div></div>`;
}
async function showWorkoutDetail(cid) {
  try {
    const d = await api("GET", "/api/workouts/" + cid);
    const byEx = {};
    d.sets.forEach(s => (byEx[s.exercise_name] = byEx[s.exercise_name] || []).push(s));
    openSheet(`<div class="handle"></div><h2>${esc(d.session ? d.session.title : "Workout")}, ${fmtDay(d.date)}</h2>
      <div class="summary"><div class="parts"><div><b>${d.effort ?? "-"}</b><span>effort</span></div><div><b>${n0(d.kcal_used)}</b><span>kcal</span></div><div><b>${n0(d.volume)}</b><span>kg lifted</span></div></div></div>
      ${Object.entries(byEx).map(([name, sets]) => `<div class="mt"><b>${esc(name)}</b><div class="muted small">${sets.map(s => `${s.is_warmup ? "warm-up " : ""}${s.reps}${s.weight_kg ? " at " + kg(s.weight_kg) : ""}${s.rpe ? " @" + s.rpe : ""}`).join(", ")}</div></div>`).join("")}
      ${d.cardio.length ? `<div class="mt"><b>Cardio</b><div class="muted small">${d.cardio.map(c => `${esc(c.exercise_name || "")} ${n0(c.minutes)} min, ${esc(c.intensity)}, ${n0(c.kcal_est)} kcal`).join("; ")}</div></div>` : ""}
      ${d.prs && d.prs.length ? `<h3 class="mt">Personal bests</h3><ul class="prs">${d.prs.map(p => `<li><b>${esc(p.exercise)}</b>: ${esc(p.text)}</li>`).join("")}</ul>` : ""}
      ${d.notes ? `<p class="hint mt">${esc(d.notes)}</p>` : ""}
      <div class="row mt2"><button class="primary" id="wdClose">Close</button><button class="danger" id="wdDelete">Delete workout</button></div>`, sh => {
      $("#wdClose", sh).addEventListener("click", closeSheet);
      $("#wdDelete", sh).addEventListener("click", async () => { if (!confirm("Delete this workout and its sets?")) return; await mutate("workout", cid, { deleted: 1 }); closeSheet(); toast("Deleted"); await load(true); if (UI.tab === "plan") renderPlan(); if (UI.tab === "history") renderHistory(); });
    });
  } catch (e) { toast(e.message); }
}

/* ---------------------------------------------------------- Food */
const FOODDAYS = {};
const tokens = s => String(s || "").toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
const SOURCE_RANK = { custom: 0, nz: 0, in: 0, off: 1, usda: 2 };
async function loadFoods() {
  try {
    const blob = await api("GET", "/api/foods/list");
    FOODS = blob.foods.map(r => { const o = {}; blob.fields.forEach((f, i) => { o[f] = r[i]; }); o._tokens = tokens(o.name + " " + (o.brand || "") + " " + (o.search || "")); return o; });
  } catch (e) { toast(e.message); FOODS = FOODS || []; }
}
function rankFoods(query, limit = 30) {
  const q = tokens(query);
  if (String(query || "").trim().length < 2 || !q.length) {
    return FOODS.filter(f => f.last_used).sort((a, b) => String(b.last_used).localeCompare(String(a.last_used)) || (b.times_used || 0) - (a.times_used || 0)).slice(0, 20);
  }
  const score = f => { let m = 0, ex = 0; for (const t of q) { if (f._tokens.some(x => x.startsWith(t))) m++; if (f._tokens.includes(t)) ex++; } return [m, ex]; };
  let scored = [];
  for (const f of FOODS) { const [m, ex] = score(f); if (m === q.length) scored.push([f, m, ex]); }
  if (!scored.length) for (const f of FOODS) { const [m, ex] = score(f); if (m) scored.push([f, m, ex]); }
  scored.sort((a, b) => (b[1] - a[1]) || (b[2] - a[2]) || ((SOURCE_RANK[a[0].source] ?? 3) - (SOURCE_RANK[b[0].source] ?? 3)) || ((b[0]._tokens[0] || "").startsWith(q[0]) - (a[0]._tokens[0] || "").startsWith(q[0])) || ((b[0].times_used || 0) - (a[0].times_used || 0)) || (a[0].name.length - b[0].name.length));
  return scored.slice(0, limit).map(x => x[0]);
}
function defaultSlot() { const h = new Date().getHours(); return h < 11 ? "breakfast" : h < 15 ? "lunch" : h < 20 ? "dinner" : "snack"; }
async function foodDay(date) {
  if (S && date === S.today) return S.food;
  if (FOODDAYS[date]) return FOODDAYS[date];
  try { FOODDAYS[date] = await api("GET", "/api/food/day?date=" + date); } catch (e) { FOODDAYS[date] = { date, slots: { breakfast: [], lunch: [], dinner: [], snack: [] }, totals: { kcal: 0, protein: 0, carb: 0, fat: 0 }, offline: true }; }
  return FOODDAYS[date];
}
async function renderFood() {
  const root = $("#p-food");
  if (!FOODS) { root.innerHTML = `<div class="empty">Loading the food list</div>`; await loadFoods(); }
  const date = UI.foodDate, isToday = S && date === S.today;
  const day = await foodDay(date);
  const tg = isToday && S.targets && S.targets.complete ? S.targets : null;
  const totals = day.totals;
  const bar = tg ? `<div class="card"><div class="between"><div><span class="kicker muted small">Left today</span><div class="display num${tg.left < 0 ? " crit-ink" : ""}" style="font-size:34px;font-weight:600">${n0(tg.budget - totals.kcal)} <span class="muted" style="font-size:16px">kcal</span></div></div>
      <div class="muted small">${n0(totals.kcal)} of ${n0(tg.budget)} eaten</div></div>
      <div class="macros"><div class="macro"><b>Protein</b><div class="meter fuel${totals.protein > tg.protein * 1.1 ? " over" : ""}"><span style="width:${Math.min(100, totals.protein / tg.protein * 100)}%"></span></div><span class="num">${n0(totals.protein)} / ${n0(tg.protein)} g</span></div>
      <div class="macro"><b>Carbs</b><div class="meter fuel"><span style="width:${Math.min(100, totals.carb / tg.carbs * 100)}%"></span></div><span class="num">${n0(totals.carb)} / ${n0(tg.carbs)} g</span></div>
      <div class="macro"><b>Fat</b><div class="meter fuel"><span style="width:${Math.min(100, totals.fat / tg.fat * 100)}%"></span></div><span class="num">${n0(totals.fat)} / ${n0(tg.fat)} g</span></div></div></div>` :
    `<div class="card"><div class="between"><b>${n0(totals.kcal)} kcal</b><span class="muted small">${n0(totals.protein)} g protein, ${n0(totals.carb)} g carbs, ${n0(totals.fat)} g fat</span></div></div>`;
  const canScan = "BarcodeDetector" in window;
  root.innerHTML = `<div class="daynav mb"><button class="ghost" id="fdPrev" aria-label="Previous day">‹</button><h2>${isToday ? "Today" : fmtDay(date)}</h2><button class="ghost" id="fdNext" aria-label="Next day">›</button>${isToday ? "" : `<button class="ghost" id="fdToday">Today</button>`}</div>
    ${bar}
    <div class="card"><div class="searchbox"><input type="search" id="foodQ" placeholder="Type a food: eggs, Weet-Bix, flat white" autocomplete="off" value="${esc(UI.foodQ)}"><div class="results" id="foodResults" hidden></div></div>
      <div class="row mt"><button id="foodOnline">Search online</button><button id="foodBarcode">Barcode</button>${canScan ? `<button id="foodScan">Scan</button>` : ""}<button id="foodNew">New food</button><button id="foodMeal">Saved meals</button></div></div>
    ${SLOTS.map(slot => slotCard(slot, day, date)).join("")}
    <p class="hint mt2">Search works offline over the bundled list, which includes New Zealand staples and Kerala and Indian dishes. Foods marked <span class="approx">approx</span> use typical values. Online search uses Open Food Facts and needs internet.</p>`;
  $("#fdPrev").addEventListener("click", () => { UI.foodDate = addDays(date, -1); renderFood(); });
  $("#fdNext").addEventListener("click", () => { UI.foodDate = addDays(date, 1); renderFood(); });
  const ft = $("#fdToday"); if (ft) ft.addEventListener("click", () => { UI.foodDate = todayIso(); renderFood(); });
  const q = $("#foodQ"), res = $("#foodResults");
  const draw = () => {
    UI.foodQ = q.value;
    const hits = rankFoods(q.value);
    res.hidden = !hits.length || !q.value.trim();
    res.innerHTML = hits.map(f => `<div class="result" data-fid="${f.id ?? ""}" data-cid="${f.client_id || ""}"><div><div class="n">${esc(f.name)}${f.approx ? '<span class="approx">approx</span>' : ""}</div><div class="b">${esc(f.brand || "")}${f.brand ? " · " : ""}${f.portions && f.portions[0] ? esc(f.portions[0][0]) + ", " + n0(f.kcal_100 * f.portions[0][1] / 100) + " kcal" : n0(f.kcal_100) + " kcal per 100 " + f.unit}</div></div>
      <div class="k">${n0(f.kcal_100)}<small>kcal / 100 ${esc(f.unit)}</small></div></div>`).join("");
    $$(".result", res).forEach(r => r.addEventListener("click", () => { const f = FOODS.find(x => (r.dataset.fid && String(x.id) === r.dataset.fid) || (r.dataset.cid && x.client_id === r.dataset.cid)); res.hidden = true; portionSheet(f, date); }));
  };
  q.addEventListener("input", draw);
  q.addEventListener("focus", draw);
  q.addEventListener("keydown", e => { if (e.key === "Enter") { const first = $(".result", res); if (first) first.click(); } if (e.key === "Escape") res.hidden = true; });
  document.addEventListener("click", e => { if (!e.target.closest(".searchbox")) res.hidden = true; }, { once: true });
  $("#foodOnline").addEventListener("click", () => onlineSearchSheet(q.value.trim(), date));
  $("#foodBarcode").addEventListener("click", () => barcodeSheet(date, false));
  if (canScan) $("#foodScan").addEventListener("click", () => barcodeSheet(date, true));
  $("#foodNew").addEventListener("click", () => newFoodSheet(date, q.value.trim()));
  $("#foodMeal").addEventListener("click", () => mealsSheet(date));
  $$("[data-delfood]", root).forEach(b => b.addEventListener("click", () => {
    const cid = b.dataset.delfood; const row = b.closest(".lg-row"); row.classList.add("leaving");
    setTimeout(async () => {
      const item = removeLocalFoodLog(day, cid);
      await mutate("food_log", cid, { deleted: 1 });
      renderFood(); if (isToday) renderToday();
      toast("Removed", item ? () => { addLocalFoodLog(day, item); return mutate("food_log", cid, Object.assign({}, item, { deleted: 0 })).then(() => { renderFood(); if (isToday) renderToday(); }); } : null);
    }, 240);
  }));
  $$("[data-copy]", root).forEach(b => b.addEventListener("click", async () => { try { const d = await api("POST", "/api/food_logs/copy", { to_date: date, slot: b.dataset.copy }); FOODDAYS[date] = d; if (isToday) S.food = d; renderFood(); if (isToday) renderToday(); toast("Copied from yesterday"); } catch (e) { toast(e.message); } }));
  $$("[data-savemeal]", root).forEach(b => b.addEventListener("click", () => {
    openSheet(`<div class="handle"></div><h2>Save ${SLOT_NAMES[b.dataset.savemeal].toLowerCase()} as a meal</h2><label class="field mb"><span>Name</span><input type="text" id="mealName" placeholder="Usual breakfast"></label><div class="row"><button class="primary big" id="mealSave">Save</button><button class="ghost" id="mealCancel">Cancel</button></div>`, sh => {
      $("#mealCancel", sh).addEventListener("click", closeSheet);
      $("#mealSave", sh).addEventListener("click", async () => { try { await api("POST", "/api/meals", { name: $("#mealName", sh).value.trim() || "Meal", from_date: date, slot: b.dataset.savemeal }); closeSheet(); toast("Meal saved"); } catch (e) { toast(e.message); } });
    });
  }));
}
function slotCard(slot, day, date) {
  const items = day.slots[slot] || [];
  const kcal = items.reduce((a, i) => a + (i.kcal || 0), 0), prot = items.reduce((a, i) => a + (i.protein || 0), 0);
  return `<div class="card slot"><div class="sh"><h3>${SLOT_NAMES[slot]}</h3><span class="tot">${items.length ? `${n0(kcal)} kcal, ${n0(prot)} g protein` : ""}</span><span class="spacer"></span>
      <div class="acts">${ONLINE ? `<button class="ghost" data-copy="${slot}" title="Copy this slot from yesterday">Copy yesterday</button>` : ""}${items.length && ONLINE ? `<button class="ghost" data-savemeal="${slot}">Save as meal</button>` : ""}</div></div>
    ${items.length ? items.map(i => `<div class="lg-row"><div class="lg-what"><div class="t">${esc(i.name || "Food")}${i.approx ? '<span class="approx">approx</span>' : ""}</div><div class="c">${esc(i.portion_label ? (i.qty && i.qty !== 1 ? n1(i.qty) + " x " : "") + i.portion_label + ", " : "")}${n0(i.grams)} ${i.unit || "g"} · ${n0(i.protein)} p, ${n0(i.carb)} c, ${n0(i.fat)} f</div></div><div class="lg-amt num">${n0(i.kcal)}<small>kcal</small></div><button class="x" data-delfood="${i.client_id}" aria-label="Remove">×</button></div>`).join("") : `<div class="muted small" style="padding:8px 0">Nothing yet</div>`}</div>`;
}
function removeLocalFoodLog(day, cid) {
  for (const slot of SLOTS) {
    const idx = (day.slots[slot] || []).findIndex(i => i.client_id === cid);
    if (idx >= 0) { const [item] = day.slots[slot].splice(idx, 1); recalcDay(day); return item; }
  }
  return null;
}
function addLocalFoodLog(day, item) { (day.slots[item.slot] = day.slots[item.slot] || []).push(item); recalcDay(day); }
function recalcDay(day) {
  const t = { kcal: 0, protein: 0, carb: 0, fat: 0 };
  SLOTS.forEach(s => (day.slots[s] || []).forEach(i => { t.kcal += i.kcal || 0; t.protein += i.protein || 0; t.carb += i.carb || 0; t.fat += i.fat || 0; }));
  day.totals = t;
  if (S && day.date === S.today && S.targets && S.targets.complete) { S.targets.eaten = t.kcal; S.targets.left = S.targets.budget - t.kcal; }
}
function portionSheet(f, date, preSlot) {
  if (!f) return;
  const portions = (f.portions || []).map(p => ({ label: p[0], grams: p[1] })).concat([{ label: "100 " + f.unit, grams: 100 }, { label: "Custom amount", grams: null }]);
  openSheet(`<div class="handle"></div><h2>${esc(f.name)}</h2><p class="hint">${esc(f.brand || "")}${f.brand ? ". " : ""}${n0(f.kcal_100)} kcal, ${n1(f.protein_100)} g protein per 100 ${esc(f.unit)}${f.approx ? ". Typical values, treat as approximate" : ""}.</p>
    <div class="f-row"><label class="field grow"><span>Portion</span><select id="p-portion">${portions.map((p, i) => `<option value="${i}">${esc(p.label)}${p.grams ? ` (${n0(p.grams)} ${esc(f.unit)})` : ""}</option>`).join("")}</select></label>
      <label class="field narrow"><span>How many</span><div class="stepper"><button data-step="q" data-d="-0.5">−</button><div><input type="number" inputmode="decimal" step="0.5" id="p-qty" value="1"></div><button data-step="q" data-d="0.5">+</button></div></label>
      <label class="field narrow" id="p-customWrap" hidden><span>${esc(f.unit === "ml" ? "Millilitres" : "Grams")}</span><input type="number" inputmode="decimal" id="p-grams" value="100"></label></div>
    <div class="portion-sum" id="p-sum"></div>
    <label class="field mb"><span>Meal</span><select id="p-slot">${SLOTS.map(s => `<option value="${s}"${(preSlot || defaultSlot()) === s ? " selected" : ""}>${SLOT_NAMES[s]}</option>`).join("")}</select></label>
    <div class="row"><button class="primary big" id="p-add">Add to ${isTodayDate(date) ? "today" : fmtShort(date)}</button><button class="ghost" id="p-cancel">Cancel</button></div>`, sh => {
    const sel = $("#p-portion", sh), qty = $("#p-qty", sh), custom = $("#p-grams", sh), wrap = $("#p-customWrap", sh), sum = $("#p-sum", sh);
    const grams = () => { const p = portions[+sel.value]; return (p.grams == null ? (parseFloat(custom.value) || 0) : p.grams) * (parseFloat(qty.value) || 0); };
    const draw = () => {
      wrap.hidden = portions[+sel.value].grams != null;
      const g = grams(), k = g / 100;
      sum.innerHTML = `<div><b>${n0(f.kcal_100 * k)}</b><span>kcal</span></div><div><b>${n1(f.protein_100 * k)}</b><span>protein g</span></div><div><b>${n1(f.carb_100 * k)}</b><span>carbs g</span></div><div><b>${n1(f.fat_100 * k)}</b><span>fat g</span></div>`;
    };
    sel.addEventListener("change", draw); qty.addEventListener("input", draw); custom.addEventListener("input", draw);
    $$("[data-step]", sh).forEach(b => b.addEventListener("click", () => { qty.value = Math.max(0.5, (parseFloat(qty.value) || 0) + parseFloat(b.dataset.d)); draw(); }));
    draw();
    $("#p-cancel", sh).addEventListener("click", closeSheet);
    $("#p-add", sh).addEventListener("click", async () => {
      const g = grams(); if (!g) { toast("How much?"); return; }
      const p = portions[+sel.value], slot = $("#p-slot", sh).value, k = g / 100;
      const cid = uid();
      const item = { client_id: cid, date, slot, food_id: f.id || null, food_client_id: f.id ? null : f.client_id, grams: Math.round(g * 10) / 10, portion_label: p.grams == null ? null : p.label, qty: p.grams == null ? 1 : parseFloat(qty.value) || 1,
        kcal: f.kcal_100 * k, protein: f.protein_100 * k, carb: f.carb_100 * k, fat: f.fat_100 * k, name: f.name, brand: f.brand, unit: f.unit, approx: f.approx };
      const day = await foodDay(date);
      addLocalFoodLog(day, item);
      f.times_used = (f.times_used || 0) + 1; f.last_used = date;
      closeSheet();
      await mutate("food_log", cid, { date, slot, food_id: item.food_id, food_client_id: item.food_client_id, grams: item.grams, portion_label: item.portion_label, qty: item.qty, kcal: item.kcal, protein: item.protein, carb: item.carb, fat: item.fat });
      UI.foodQ = ""; renderFood(); if (isTodayDate(date)) renderToday();
      toast(`${esc(f.name)} added`);
    });
  });
}
const isTodayDate = d => d === todayIso();
async function onlineSearchSheet(q, date) {
  if (!navigator.onLine) { toast("Online search needs the internet"); return; }
  openSheet(`<div class="handle"></div><h2>Search Open Food Facts</h2><p class="hint">Packaged products by name. Anything you pick is saved to your list, so next time it works offline.</p>
    <div class="row"><input type="search" id="os-q" value="${esc(q)}" placeholder="Product name" style="flex:1"><button class="primary" id="os-go">Search</button></div><div id="os-res" class="mt"></div>`, sh => {
    const run = async () => {
      const term = $("#os-q", sh).value.trim(); if (!term) return;
      $("#os-res", sh).innerHTML = `<div class="empty">Searching</div>`;
      try {
        const hits = await api("GET", "/api/foods/online?q=" + encodeURIComponent(term), undefined, { timeout: 25000 });
        $("#os-res", sh).innerHTML = hits.length ? hits.map((h, i) => `<div class="result" data-i="${i}"><div><div class="n">${esc(h.name)}</div><div class="b">${esc(h.brand || "")}${h.quantity ? " · " + esc(h.quantity) : ""}${h.approx ? " · calories estimated" : ""}</div></div><div class="k">${n0(h.kcal_100)}<small>kcal / 100 ${esc(h.unit)}</small></div></div>`).join("") : `<div class="empty">Nothing found. Try fewer words, or add it as a new food.</div>`;
        $$(".result", sh).forEach(r => r.addEventListener("click", () => acceptOnline(hits[+r.dataset.i], date)));
      } catch (e) { $("#os-res", sh).innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
    };
    $("#os-go", sh).addEventListener("click", run);
    $("#os-q", sh).addEventListener("keydown", e => { if (e.key === "Enter") run(); });
    if (q) run();
  });
}
async function acceptOnline(h, date) {
  try {
    const f = await api("POST", "/api/foods", Object.assign({}, h, { client_id: uid() }));
    f._tokens = tokens(f.name + " " + (f.brand || ""));
    if (!FOODS.some(x => x.id === f.id)) FOODS.push(f);
    portionSheet(f, date);
  } catch (e) { toast(e.message); }
}
function barcodeSheet(date, scan) {
  openSheet(`<div class="handle"></div><h2>Barcode</h2><p class="hint">${scan ? "Point the camera at the barcode." : "Type the number under the barcode."}</p>
    ${scan ? `<video class="scan" id="bc-video" playsinline muted></video>` : ""}
    <div class="row mt"><input type="text" inputmode="numeric" id="bc-code" placeholder="9300633000000" style="flex:1"><button class="primary" id="bc-go">Look up</button></div><div id="bc-res" class="mt"></div>`, sh => {
    let stream = null, loop = null;
    const stop = () => { if (loop) clearInterval(loop); if (stream) stream.getTracks().forEach(t => t.stop()); };
    const lookup = async code => {
      code = String(code || "").replace(/\D/g, ""); if (!code) return;
      $("#bc-res", sh).innerHTML = `<div class="empty">Looking up ${esc(code)}</div>`;
      try {
        const h = await api("GET", "/api/foods/barcode/" + code, undefined, { timeout: 25000 });
        stop();
        $("#bc-res", sh).innerHTML = `<div class="result" id="bc-hit"><div><div class="n">${esc(h.name)}</div><div class="b">${esc(h.brand || "")}${h.quantity ? " · " + esc(h.quantity) : ""}</div></div><div class="k">${n0(h.kcal_100)}<small>kcal / 100 ${esc(h.unit)}</small></div></div>`;
        $("#bc-hit", sh).addEventListener("click", () => acceptOnline(h, date));
      } catch (e) { $("#bc-res", sh).innerHTML = `<div class="empty">${esc(e.message)}. You can add it as a new food instead.</div>`; }
    };
    $("#bc-go", sh).addEventListener("click", () => lookup($("#bc-code", sh).value));
    $("#bc-code", sh).addEventListener("keydown", e => { if (e.key === "Enter") lookup($("#bc-code", sh).value); });
    const local = code => FOODS.find(f => f.barcode === code);
    if (scan) {
      (async () => {
        try {
          const det = new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a"] });
          stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
          const v = $("#bc-video", sh); v.srcObject = stream; await v.play();
          loop = setInterval(async () => {
            try {
              const codes = await det.detect(v);
              if (codes.length) { const code = codes[0].rawValue; $("#bc-code", sh).value = code; if (navigator.vibrate) navigator.vibrate(60); const hit = local(code); if (hit) { stop(); closeSheet(); portionSheet(hit, date); } else lookup(code); clearInterval(loop); }
            } catch (e) {}
          }, 400);
        } catch (e) { $("#bc-res", sh).innerHTML = `<div class="empty">Camera not available: ${esc(e.message)}. Type the number instead.</div>`; }
      })();
    }
    $("#sheetBack").addEventListener("click", stop, { once: true });
  });
}
function newFoodSheet(date, name) {
  openSheet(`<div class="handle"></div><h2>New food</h2><p class="hint">Values per 100 g or 100 ml from the label. It is saved to your list.</p>
    <div class="f-row"><label class="field grow"><span>Name</span><input type="text" id="nf-name" value="${esc(name)}"></label><label class="field narrow"><span>Brand, optional</span><input type="text" id="nf-brand"></label>
    <label class="field narrow"><span>Unit</span><select id="nf-unit"><option value="g">grams</option><option value="ml">millilitres</option></select></label></div>
    <div class="f-row"><label class="field grow"><span>Calories per 100</span><input type="number" inputmode="decimal" id="nf-kcal"></label><label class="field grow"><span>Protein g</span><input type="number" inputmode="decimal" id="nf-p"></label><label class="field grow"><span>Carbs g</span><input type="number" inputmode="decimal" id="nf-c"></label><label class="field grow"><span>Fat g</span><input type="number" inputmode="decimal" id="nf-f"></label></div>
    <div class="f-row"><label class="field grow"><span>A serving, optional</span><input type="text" id="nf-plabel" placeholder="1 scoop"></label><label class="field grow"><span>Its weight</span><input type="number" inputmode="decimal" id="nf-pg" placeholder="35"></label></div>
    <div class="row"><button class="primary big" id="nf-save">Save and add</button><button class="ghost" id="nf-cancel">Cancel</button></div>`, sh => {
    $("#nf-cancel", sh).addEventListener("click", closeSheet);
    $("#nf-save", sh).addEventListener("click", async () => {
      const f = { client_id: uid(), name: $("#nf-name", sh).value.trim(), brand: $("#nf-brand", sh).value.trim() || null, unit: $("#nf-unit", sh).value, source: "custom", kcal_100: parseFloat($("#nf-kcal", sh).value), protein_100: parseFloat($("#nf-p", sh).value) || 0, carb_100: parseFloat($("#nf-c", sh).value) || 0, fat_100: parseFloat($("#nf-f", sh).value) || 0, approx: 0, portions: [], times_used: 0, last_used: null, id: null };
      if (!f.name) { toast("Give it a name"); return; }
      if (isNaN(f.kcal_100)) { toast("Calories per 100 are needed"); return; }
      const pl = $("#nf-plabel", sh).value.trim(), pg = parseFloat($("#nf-pg", sh).value);
      if (pl && pg) f.portions.push([pl, pg]);
      try {
        const saved = await api("POST", "/api/foods", { client_id: f.client_id, name: f.name, brand: f.brand, unit: f.unit, source: "custom", kcal_100: f.kcal_100, protein_100: f.protein_100, carb_100: f.carb_100, fat_100: f.fat_100, portions: f.portions });
        FOODS = null; await loadFoods();
        closeSheet(); portionSheet(FOODS.find(x => x.id === saved.id) || saved, date);
      } catch (e) { toast(e.message); }
    });
  });
}
async function mealsSheet(date) {
  let meals = [];
  try { meals = await api("GET", "/api/meals"); } catch (e) { toast(e.message); return; }
  openSheet(`<div class="handle"></div><h2>Saved meals</h2><p class="hint">One tap adds every item. Save a meal from any slot's menu.</p>
    ${meals.length ? meals.map(m => `<div class="lg-row"><div class="lg-what"><div class="t">${esc(m.name)}</div><div class="c">${m.items.map(i => esc(i.name)).join(", ")}</div></div><div class="lg-amt num">${n0(m.kcal)}<small>kcal</small></div><div class="row"><select data-mslot="${m.id}" aria-label="Meal slot" style="min-width:110px">${SLOTS.map(s => `<option value="${s}"${defaultSlot() === s ? " selected" : ""}>${SLOT_NAMES[s]}</option>`).join("")}</select><button class="primary" data-madd="${m.id}">Add</button><button class="x" data-mdel="${m.id}" aria-label="Delete meal">×</button></div></div>`).join("") : `<div class="empty">No saved meals yet.</div>`}`, sh => {
    $$("[data-madd]", sh).forEach(b => b.addEventListener("click", async () => {
      try { const d = await api("POST", "/api/food_logs/meal", { meal_id: +b.dataset.madd, date, slot: $(`[data-mslot="${b.dataset.madd}"]`, sh).value }); FOODDAYS[date] = d; if (isTodayDate(date) && S) { S.food = d; recalcDay(d); } closeSheet(); renderFood(); if (isTodayDate(date)) renderToday(); toast("Meal added"); } catch (e) { toast(e.message); }
    }));
    $$("[data-mdel]", sh).forEach(b => b.addEventListener("click", async () => { try { await api("DELETE", "/api/meals/" + b.dataset.mdel); closeSheet(); mealsSheet(date); } catch (e) { toast(e.message); } }));
  });
}

/* ---------------------------------------------------------- charts */
const PALETTE = ["#3E6B48", "#35639C", "#C06A2C", "#7A5C99", "#4E8F86", "#B04A4A", "#8A7A2E", "#5A6E86", "#9C6B3E", "#6B8E4E"];
function chart(root, cats, series, opts = {}) {
  const W = 1000, H = opts.h || 250, m = { t: 14, r: 16, b: 34, l: 56 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const n = cats.length;
  if (!n) { root.innerHTML = `<div class="empty">${esc(opts.empty || "Nothing to show yet.")}</div>`; return; }
  const hasStack = series.some(s => s.stack);
  const stackTotals = hasStack ? cats.map((_, i) => series.filter(s => s.stack).reduce((a, s) => a + (s.values[i] || 0), 0)) : [];
  const all = series.filter(s => !s.stack).flatMap(s => s.values.filter(v => v != null)).concat(stackTotals);
  (opts.extra || []).forEach(v => all.push(v));
  let hi = Math.max(...all, 0), lo = opts.zero === false ? Math.min(...all) : 0;
  if (hi === lo) { hi = lo + 1; }
  const span = hi - lo; hi = hi + span * 0.08; if (opts.zero === false) lo = lo - span * 0.08;
  if (lo < 0 && Math.min(...all) >= 0) lo = 0;
  const slot = iw / n;
  const X = i => m.l + slot * i + slot / 2;
  const Y = v => m.t + ih - ((v - lo) / (hi - lo)) * ih;
  const fmt = opts.yFmt || (v => n0(v));
  let g = "";
  for (let i = 0; i <= 4; i++) { const v = lo + (i / 4) * (hi - lo), y = Y(v); g += `<line class="gridline" x1="${m.l}" y1="${y.toFixed(1)}" x2="${W - m.r}" y2="${y.toFixed(1)}"/><text class="tick" x="${m.l - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end">${esc(fmt(v))}</text>`; }
  const bars = series.filter(s => s.type === "bar");
  const groupN = bars.filter(s => !s.stack).length || 1;
  const bw = Math.min(28, (slot * 0.7) / groupN);
  let body = "";
  const stackBase = cats.map(() => 0);
  bars.forEach((s, bi) => {
    s.values.forEach((v, i) => {
      if (v == null || v === 0) return;
      let x, y0, y1;
      if (s.stack) { y0 = stackBase[i]; y1 = y0 + v; stackBase[i] = y1; x = X(i) - Math.min(28, slot * 0.7) / 2; }
      else { const gi = bars.filter(b => !b.stack).indexOf(s); x = X(i) - (bw * groupN) / 2 + gi * bw; y0 = 0; y1 = v; }
      const w = s.stack ? Math.min(28, slot * 0.7) : bw - 2;
      body += `<rect x="${x.toFixed(1)}" y="${Y(y1).toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(0, Y(y0) - Y(y1)).toFixed(1)}" rx="3" fill="${s.color}"/>`;
    });
  });
  series.filter(s => s.type !== "bar").forEach(s => {
    let d = "", pen = false;
    s.values.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); pen = true; });
    body += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" stroke-linecap="round" stroke-linejoin="round"${s.dashed ? ' stroke-dasharray="6 5"' : ""}${s.opacity ? ` opacity="${s.opacity}"` : ""}/>`;
    if (s.dots !== false) s.values.forEach((v, i) => { if (v == null) return; const hollow = s.hollow && s.hollow[i]; body += `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="${hollow ? 4 : 3.2}" fill="${hollow ? "var(--panel)" : s.color}" stroke="${s.color}" stroke-width="${hollow ? 2 : 0}"/>`; });
  });
  const labelEvery = Math.ceil(n / (opts.maxLabels || 8));
  const labels = cats.map((c, i) => (i % labelEvery !== 0 && i !== n - 1) ? "" : `<text class="tick" x="${X(i).toFixed(1)}" y="${H - 12}" text-anchor="middle">${esc(opts.xFmt ? opts.xFmt(c) : c)}</text>`).join("");
  const hits = cats.map((c, i) => `<rect x="${(X(i) - slot / 2).toFixed(1)}" y="${m.t}" width="${slot.toFixed(1)}" height="${ih}" fill="transparent" data-i="${i}"/>`).join("");
  root.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.label || "chart")}">${g}<line class="axisline" x1="${m.l}" y1="${Y(Math.max(lo, 0)).toFixed(1)}" x2="${W - m.r}" y2="${Y(Math.max(lo, 0)).toFixed(1)}"/>${body}${labels}${hits}</svg>`;
  const tip = i => `<div class="tt-h">${esc(opts.xFmtLong ? opts.xFmtLong(cats[i]) : opts.xFmt ? opts.xFmt(cats[i]) : cats[i])}</div>` + series.map(s => s.values[i] == null ? "" : `<div class="tt-r"><span><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${s.color};margin-right:6px"></i>${esc(s.name)}</span><b>${esc(fmt(s.values[i]))}${s.hollow && s.hollow[i] ? " ~" : ""}</b></div>`).join("");
  $$("rect[data-i]", root).forEach(r => {
    r.addEventListener("mousemove", e => showTip(tip(+r.dataset.i), e));
    r.addEventListener("mouseleave", hideTip);
    r.addEventListener("touchstart", e => { const t = e.touches[0]; showTip(tip(+r.dataset.i), { clientX: t.clientX, clientY: t.clientY }); e.stopPropagation(); }, { passive: true });
  });
}
const weekLabel = iso => fmtShort(iso);

/* ---------------------------------------------------------- Progress */
let PROGRESS = null;
async function renderProgress() {
  const root = $("#p-progress");
  root.innerHTML = `<div class="empty">Loading</div>`;
  try { PROGRESS = await api("GET", "/api/progress?days=" + UI.progressDays); }
  catch (e) { root.innerHTML = `<div class="card"><h2>Progress</h2><p class="hint">${esc(e.message)}</p></div>`; return; }
  const p = PROGRESS;
  root.innerHTML = `<div class="row mb"><div class="chips">${[30, 90, 180, 365].map(d => `<button class="chip${UI.progressDays === d ? " on" : ""}" data-days="${d}">${d === 365 ? "Year" : d + " days"}</button>`).join("")}</div></div>
    <div class="card"><h2>Strength on the main lifts</h2><p class="hint">Estimated one-rep max, best set each week. Hollow points come from sets over 12 reps, where the estimate is rough.</p><div class="legend" id="strLegend"></div><div id="strChart"></div>
      <div id="relStrength" class="mt"></div></div>
    <div class="card"><h2>Strength index</h2><p class="hint">Average gain across the four main lifts against your first three weeks. A dashed segment means a lift was not trained that week and its last value carries over.</p><div id="idxChart"></div></div>
    <div class="grid g2">
      <div class="card"><h2>Weight against the pace line</h2><p class="hint">Dots are your weigh-ins, the solid line is the seven-day trend, the dashed line is the pace to your target.</p><div id="wtChart"></div></div>
      <div class="card"><h2>Calories eaten and burned</h2><p class="hint">By week. Burned is training only.</p><div class="legend"><span><i style="background:var(--fuel)"></i>Eaten</span><span><i style="background:var(--burn)"></i>Burned</span></div><div id="calChart"></div></div>
    </div>
    <div class="grid g2">
      <div class="card"><h2>Hard sets per muscle each week</h2><p class="hint">Primary muscle counts one, each secondary counts a half.</p><div class="legend" id="volLegend"></div><div id="volChart"></div></div>
      <div class="card"><h2>Effort per session</h2><p class="hint">Out of 100. Volume against your usual, share of hard sets, and calories for your size.</p><div id="effChart"></div></div>
    </div>
    <div class="grid g2">
      <div class="card"><h2>Sessions done</h2><p class="hint">Planned lifting and conditioning days you completed.</p><div class="heat" id="adhHeat"></div></div>
      <div class="card"><h2>Measurements</h2><div id="measTable"></div></div>
    </div>`;
  $$("[data-days]", root).forEach(b => b.addEventListener("click", () => { UI.progressDays = +b.dataset.days; renderProgress(); }));

  const mains = p.strength.filter(s => s.main);
  const weeks = Array.from(new Set(mains.flatMap(s => s.series.map(x => x.week)))).sort();
  chart($("#strChart"), weeks, mains.map((s, i) => ({ name: s.name, color: PALETTE[i % PALETTE.length], values: weeks.map(w => { const pt = s.series.find(x => x.week === w); return pt ? pt.e1rm : null; }), hollow: weeks.map(w => { const pt = s.series.find(x => x.week === w); return pt ? pt.low_confidence : false; }) })), { yFmt: v => n0(v) + " kg", xFmt: weekLabel, zero: false, empty: "Log a few sessions and the lines appear.", label: "Estimated one-rep max by week" });
  $("#strLegend").innerHTML = mains.map((s, i) => `<span><i style="background:${PALETTE[i % PALETTE.length]}"></i>${esc(s.name)}</span>`).join("");
  $("#relStrength").innerHTML = mains.length ? `<div class="grid g4">${mains.map(s => `<div class="stat"><div class="l">${esc(s.name)}</div><div class="v num">${s.relative != null ? n1(s.relative) + "x" : "-"}</div><div class="f">times body weight, best in 28 days</div></div>`).join("")}</div>` : "";
  chart($("#idxChart"), p.index.map(x => x.week), [{ name: "Strength index", color: "var(--accent)", values: p.index.map(x => x.index), hollow: p.index.map(x => x.carried) }], { yFmt: v => (v > 0 ? "+" : "") + n0(v) + "%", xFmt: weekLabel, zero: false, empty: "The index starts once the main lifts have a baseline.", label: "Strength index" });

  const wts = p.weights.filter(w => w.weight_kg != null);
  const wdates = wts.map(w => w.date);
  const paceVals = wdates.map(d => p.pace && p.pace[0].weight && p.pace[1].weight ? paceAt(p.pace, d) : null);
  chart($("#wtChart"), wdates, [
    { name: "Weigh-in", color: "var(--fuel)", values: wts.map(w => w.weight_kg), width: 1, opacity: 0.35 },
    { name: "Trend", color: "var(--accent)", values: wdates.map(d => { const t = p.trend.find(x => x.date === d); return t ? t.trend : null; }), dots: false, width: 2.5 },
    { name: "Pace", color: "var(--burn)", values: paceVals, dashed: true, dots: false },
  ], { yFmt: v => n1(v), xFmt: fmtShort, zero: false, empty: "Log your weight a few times to see the trend.", label: "Weight and pace" });

  chart($("#calChart"), p.calories.map(c => c.week), [
    { name: "Eaten", type: "bar", color: "var(--fuel)", values: p.calories.map(c => c.eaten || null) },
    { name: "Burned", type: "bar", color: "var(--burn)", values: p.calories.map(c => c.burned || null) },
  ], { xFmt: weekLabel, empty: "Log food and a workout to compare them.", label: "Calories eaten and burned by week" });

  const muscles = Array.from(new Set(p.volume.flatMap(v => Object.keys(v.muscles))));
  chart($("#volChart"), p.volume.map(v => v.week), muscles.map((mu, i) => ({ name: mu, type: "bar", stack: true, color: PALETTE[i % PALETTE.length], values: p.volume.map(v => v.muscles[mu] || null) })), { xFmt: weekLabel, empty: "Finish a workout to see sets per muscle.", label: "Hard sets per muscle by week" });
  $("#volLegend").innerHTML = muscles.map((mu, i) => `<span><i style="background:${PALETTE[i % PALETTE.length]}"></i>${esc(mu)}</span>`).join("");

  chart($("#effChart"), p.sessions.map(s => s.date), [{ name: "Effort", type: "bar", color: "var(--burn)", values: p.sessions.map(s => s.effort) }], { xFmt: fmtShort, xFmtLong: d => { const s = p.sessions.find(x => x.date === d); return fmtDay(d) + (s ? ", " + (s.title || "workout") : ""); }, empty: "Finish a workout to score it.", label: "Effort per session" });

  $("#adhHeat").innerHTML = p.adherence.length ? p.adherence.slice(-12).map(a => `<span class="small muted">${fmtShort(a.week)}</span><div class="bar"><span style="width:${a.planned ? a.done / a.planned * 100 : 0}%"></span></div><span class="num small">${a.done} / ${a.planned}</span>`).join("") : `<div class="empty">The plan fills this in week by week.</div>`;
  const meas = p.weights.filter(w => w.waist_cm || w.chest_cm || w.arm_cm || w.hip_cm || w.thigh_cm).slice(-8).reverse();
  $("#measTable").innerHTML = meas.length ? `<div class="tablewrap"><table><thead><tr><th>Date</th><th class="num">Waist</th><th class="num">Chest</th><th class="num">Arm</th><th class="num">Hips</th><th class="num">Thigh</th></tr></thead><tbody>${meas.map(w => `<tr><td>${fmtShort(w.date)}</td><td class="num">${n1(w.waist_cm)}</td><td class="num">${n1(w.chest_cm)}</td><td class="num">${n1(w.arm_cm)}</td><td class="num">${n1(w.hip_cm)}</td><td class="num">${n1(w.thigh_cm)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">Add measurements from the weight button on Today. Monthly is plenty.</div>`;
}
function paceAt(pace, d) {
  const [a, b] = pace; const total = daysBetween(a.date, b.date); if (total <= 0) return b.weight;
  const f = Math.min(1, Math.max(0, daysBetween(a.date, d) / total)); return a.weight + (b.weight - a.weight) * f;
}

/* ---------------------------------------------------------- History */
async function renderHistory() {
  const root = $("#p-history");
  root.innerHTML = `<div class="empty">Loading</div>`;
  const from = UI.histRange === "all" ? "2000-01-01" : addDays(todayIso(), -UI.histRange);
  let h;
  try { h = await api("GET", `/api/history?from=${from}&to=${todayIso()}&q=${encodeURIComponent(UI.histQ)}`); }
  catch (e) { root.innerHTML = `<div class="card"><h2>History</h2><p class="hint">${esc(e.message)}</p></div>`; return; }
  root.innerHTML = `<div class="row mb"><div class="chips">${[30, 90, 365, "all"].map(r => `<button class="chip${UI.histRange === r ? " on" : ""}" data-range="${r}">${r === "all" ? "Everything" : r + " days"}</button>`).join("")}</div><span class="spacer"></span><input type="search" id="histQ" placeholder="Search workouts" value="${esc(UI.histQ)}" style="max-width:240px"></div>
    <div class="card"><div class="between"><h2>Workouts</h2><button data-csv="sets">Sets as CSV</button></div><p class="hint">${plural(h.workouts.length, "workout")}. Click one for its sets.</p>
      ${h.workouts.length ? h.workouts.map(w => `<div class="lg-row click" data-view="${w.client_id}"><div class="lg-what"><div class="t">${esc(w.title || "Freestyle")}${!w.ended_at ? ' <span class="pill warn">not finished</span>' : ""}</div><div class="c">${fmtDay(w.date)} · ${plural(w.work_sets, "set")}, ${n0(w.volume)} kg, ${w.hard_sets} hard</div></div><div class="lg-amt num">${w.effort ?? "-"}<small>effort</small></div><div class="lg-amt num burn-ink">${n0(w.kcal_wearable || w.kcal_est)}<small>kcal</small></div></div>`).join("") : `<div class="empty">No workouts in this range.</div>`}</div>
    <div class="grid g2">
      <div class="card"><div class="between"><h2>Food days</h2><button data-csv="food">Food as CSV</button></div>
        ${h.food_days.length ? h.food_days.map(d => `<div class="lg-row click" data-fooday="${d.date}"><div class="lg-what"><div class="t">${fmtDay(d.date)}</div><div class="c">${plural(d.items, "item")} · ${n0(d.protein)} p, ${n0(d.carb)} c, ${n0(d.fat)} f</div></div><div class="lg-amt num fuel-ink">${n0(d.kcal)}<small>kcal</small></div></div>`).join("") : `<div class="empty">No food logged in this range.</div>`}</div>
      <div class="card"><div class="between"><h2>Body</h2><button data-csv="body">Body as CSV</button></div>
        ${h.body.length ? h.body.map(b => `<div class="lg-row"><div class="lg-what"><div class="t">${fmtDay(b.date)}</div><div class="c">${[b.waist_cm && "waist " + n1(b.waist_cm), b.chest_cm && "chest " + n1(b.chest_cm), b.arm_cm && "arm " + n1(b.arm_cm), b.hip_cm && "hips " + n1(b.hip_cm), b.thigh_cm && "thigh " + n1(b.thigh_cm)].filter(Boolean).join(", ") || (b.note ? esc(b.note) : "")}</div></div><div class="lg-amt num">${b.weight_kg ? kg(b.weight_kg) : ""}</div></div>`).join("") : `<div class="empty">No weigh-ins in this range.</div>`}</div>
    </div>`;
  $$("[data-range]", root).forEach(b => b.addEventListener("click", () => { UI.histRange = b.dataset.range === "all" ? "all" : +b.dataset.range; renderHistory(); }));
  let t; $("#histQ").addEventListener("input", e => { clearTimeout(t); t = setTimeout(() => { UI.histQ = e.target.value; renderHistory(); }, 300); });
  $$("[data-view]", root).forEach(r => r.addEventListener("click", () => showWorkoutDetail(r.dataset.view)));
  $$("[data-fooday]", root).forEach(r => r.addEventListener("click", () => { UI.foodDate = r.dataset.fooday; switchTab("food"); }));
  $$("[data-csv]", root).forEach(b => b.addEventListener("click", () => exportCsv(b.dataset.csv)));
}
async function exportCsv(what) {
  try { const text = await api("GET", "/api/export.csv?what=" + what); await downloadText(`fitness-${what}-${todayIso()}.csv`, "text/csv", text); } catch (e) { toast(e.message); }
}

/* ---------------------------------------------------------- Settings */
async function saveSettings(patch, msg) {
  try { const s = await api("PUT", "/api/settings", patch); S.settings = s; toast(msg || "Saved"); await load(true); if (UI.tab === "settings") renderSettings(); }
  catch (e) { toast(e.message); }
}
function renderSettings() {
  const root = $("#p-settings");
  if (!S) { root.innerHTML = `<div class="card"><h2>Settings</h2><p class="hint">Settings need the laptop.</p></div>`; return; }
  const st = S.settings, tg = S.targets;
  const field = (k, label, type, extra = "") => `<label class="field"><span>${label}</span><input type="${type}" id="s-${k}" value="${st[k] ?? ""}" ${extra}></label>`;
  const days = st.train_days || [];
  const kit = st.cardio_kit || [];
  root.innerHTML = `
    <div class="card"><h2>You</h2><p class="hint">Used for the calorie maths only. Nothing leaves this laptop.</p>
      <div class="f-row"><label class="field narrow"><span>Sex</span><select id="s-sex"><option value="m"${st.sex === "m" ? " selected" : ""}>Male</option><option value="f"${st.sex === "f" ? " selected" : ""}>Female</option></select></label>
      ${field("birth_date", "Birth date", "date")}${field("height_cm", "Height (cm)", "number", 'inputmode="decimal" step="0.5"')}${field("start_weight_kg", "Starting weight (kg)", "number", 'inputmode="decimal" step="0.1"')}</div></div>
    <div class="card"><h2>Your goal</h2><p class="hint">${tg && tg.complete ? `Right now that means about <b>${n0(tg.budget)} kcal</b> a day with <b>${n0(tg.protein)} g protein</b>, ${tg.mode === "losing" ? "losing" : tg.mode === "gaining" ? "gaining" : "holding at"} ${tg.mode === "maintaining" ? "your target" : n1(Math.abs(tg.weekly_pace || 0)) + " kg a week"}.` : "Set a target weight and date and the app works out the daily numbers."}</p>
      <div class="f-row">${field("target_weight_kg", "Target weight (kg)", "number", 'inputmode="decimal" step="0.1"')}${field("target_date", "Target date", "date")}
      <label class="field narrow"><span>Daily life activity</span><select id="s-neat_factor">${[[1.2, "Mostly sitting"], [1.3, "Light, some walking"], [1.4, "On my feet a lot"]].map(([v, l]) => `<option value="${v}"${+st.neat_factor === v ? " selected" : ""}>${l}</option>`).join("")}</select></label></div>
      <div class="f-row">${field("deficit_cap", "Biggest daily deficit (kcal)", "number", 'inputmode="numeric" step="50"')}${field("protein_g_per_kg", "Protein (g per kg)", "number", 'inputmode="decimal" step="0.1"')}${field("fat_g_per_kg", "Fat (g per kg)", "number", 'inputmode="decimal" step="0.1"')}${field("kcal_floor", "Calorie floor, blank for default", "number", 'inputmode="numeric" step="50"')}</div>
      ${st.goal_start_date ? `<p class="hint">Pace line runs from ${kg(st.goal_start_weight)} on ${fmtDate(st.goal_start_date)}. Changing the target starts a new line from today.</p>` : ""}</div>
    <div class="card"><h2>Training</h2><p class="hint">Changes rebuild the sessions you have not started yet, from today. Sessions already done stay as they were.</p>
      <div class="cap">Training split</div><div class="chips mb" id="s-split">${(S.splits || []).map(sp => `<button type="button" class="chip${(st.split || "upper_lower") === sp.key ? " on" : ""}" data-split="${sp.key}" title="${esc(sp.description || "")}">${esc(sp.name)}</button>`).join("")}</div>
      ${(() => { const sp = (S.splits || []).find(x => x.key === (st.split || "upper_lower")); return sp ? `<p class="hint">${esc(sp.description || "")}${sp.days && sp.days.length ? ` Works with ${sp.days.join(", ")} training days.` : ""}</p>` : ""; })()}
      <div class="cap">Days you can train</div><div class="chips mb" id="s-days">${WEEKDAYS.map((d, i) => `<button type="button" class="chip${days.includes(i + 1) ? " on" : ""}" data-day="${i + 1}">${d}</button>`).join("")}</div>
      <div class="f-row">${field("session_minutes", "Minutes per session", "number", 'inputmode="numeric" step="5" min="30" max="120"')}${field("rest_default_sec", "Default rest (seconds)", "number", 'inputmode="numeric" step="15"')}
      <label class="field narrow"><span>Experience</span><select id="s-experience"><option value="beginner"${st.experience === "beginner" ? " selected" : ""}>Beginner</option></select></label></div>
      <div class="cap">Cardio machines you will use</div><div class="chips" id="s-kit">${[["treadmill", "Treadmill"], ["bike", "Bike"], ["rower", "Rower"]].map(([k, l]) => `<button type="button" class="chip${kit.includes(k) ? " on" : ""}" data-kit="${k}">${l}</button>`).join("")}</div>
      <div class="row mt"><button id="s-regen" class="ghost">Rebuild the plan from today</button></div></div>
    <div class="card exlib"><h2>Exercise library</h2><p class="hint">Switch off anything your gym does not have and the plan stops picking it. Edit the cues to suit you, or add your own exercise.</p>
      <div class="row mb"><input type="search" id="exQ" placeholder="Search exercises" value="${esc(UI.exQ)}" style="max-width:260px"><button id="exAdd">Add an exercise</button></div><div id="exList"></div></div>
    <div class="card"><h2>Foods and meals</h2><p class="hint">Foods you added or accepted from Open Food Facts. Hide anything wrong; the bundled list stays.</p><div id="myFoods"></div><div id="myMeals" class="mt"></div></div>
    <div class="card"><h2>Backups</h2><p class="hint">Everything lives on this ${IS_ANDROID_APP ? "phone" : "device"}. If it is lost or replaced, so is your data, so export a backup now and then and keep it somewhere safe. A backup restores onto any device running this app.</p>
      <div class="row"><button class="primary" id="bkExport">Export a backup</button><label class="btn" for="restoreFile">Restore a backup</label><input type="file" id="restoreFile" accept="application/json,.json" hidden></div>
      <div class="row mt"><button id="csvSets">Sets CSV</button><button id="csvFood">Food CSV</button><button id="csvBody">Body CSV</button></div>
      <div class="row mt"><button class="danger" id="bkWipe">Start fresh</button><span class="muted small">Removes everything on this device. Export first.</span></div>
      <p class="hint mt" id="bkInfo"></p></div>`;

  const bind = (k, parse, msg) => { const el = $("#s-" + k, root); if (!el) return; el.addEventListener("change", () => { const v = el.value === "" ? null : (parse ? parse(el.value) : el.value); saveSettings({ [k]: v }, msg); }); };
  ["sex", "birth_date", "target_date", "experience"].forEach(k => bind(k));
  ["height_cm", "start_weight_kg", "target_weight_kg", "neat_factor", "deficit_cap", "protein_g_per_kg", "fat_g_per_kg", "kcal_floor", "session_minutes", "rest_default_sec"].forEach(k => bind(k, parseFloat));
  $$("#s-split .chip", root).forEach(b => b.addEventListener("click", () => saveSettings({ split: b.dataset.split }, "Plan rebuilt from today")));
  $$("#s-days .chip", root).forEach(b => b.addEventListener("click", () => {
    const on = $$("#s-days .chip.on", root).map(x => +x.dataset.day); const d = +b.dataset.day;
    const next = on.includes(d) ? on.filter(x => x !== d) : on.concat([d]).sort();
    if (next.length < 3) { toast("Keep at least three training days"); return; }
    saveSettings({ train_days: next }, "Plan rebuilt from today");
  }));
  $$("#s-kit .chip", root).forEach(b => b.addEventListener("click", () => {
    const on = $$("#s-kit .chip.on", root).map(x => x.dataset.kit); const k = b.dataset.kit;
    const next = on.includes(k) ? on.filter(x => x !== k) : on.concat([k]);
    if (!next.length) { toast("Keep at least one machine"); return; }
    saveSettings({ cardio_kit: next }, "Plan rebuilt from today");
  }));
  $("#s-regen").addEventListener("click", async () => { try { await api("POST", "/api/plan/regenerate"); toast("Plan rebuilt from today"); load(true); } catch (e) { toast(e.message); } });
  $("#bkExport").addEventListener("click", async () => { try { const data = await api("GET", "/api/backup.json"); await downloadText(`fitness-backup-${todayIso()}.json`, "application/json", JSON.stringify(data)); } catch (e) { toast(e.message); } });
  $("#csvSets").addEventListener("click", () => exportCsv("sets"));
  $("#csvFood").addEventListener("click", () => exportCsv("food"));
  $("#csvBody").addEventListener("click", () => exportCsv("body"));
  $("#bkWipe").addEventListener("click", async () => { if (!confirm("Remove everything on this device? Export a backup first if you want to keep it.")) return; try { await api("POST", "/api/wipe"); W = null; saveW(); FOODS = null; toast("Fresh start"); await load(true); renderSettings(); } catch (e) { toast(e.message); } });
  $("#restoreFile").addEventListener("change", async e => {
    const file = e.target.files[0]; if (!file) return;
    if (!confirm(`Replace everything with ${file.name}? This cannot be undone.`)) { e.target.value = ""; return; }
    try { const data = JSON.parse(await file.text()); await api("POST", "/api/restore", data); toast("Restored"); W = null; saveW(); FOODS = null; await load(true); renderSettings(); } catch (err) { toast(err.message); }
  });
  renderExLib(root);
  renderMyFoods(root);
  renderBackupInfo(root);
}
function renderExLib(root) {
  const list = $("#exList", root), q = $("#exQ", root);
  const draw = () => {
    UI.exQ = q.value;
    const t = q.value.trim().toLowerCase();
    const exs = S.exercises.filter(e => !e.pattern.startsWith("cardio") && e.pattern !== "mobility").filter(e => !t || e.name.toLowerCase().includes(t) || e.pattern.includes(t) || (e.primary_muscle || "").includes(t)).sort((a, b) => a.name.localeCompare(b.name)).slice(0, t ? 60 : 30);
    list.innerHTML = exs.map(e => `<div class="lg-row"><div class="lg-what"><div class="t">${esc(e.name)}${e.is_custom ? ' <span class="pill">yours</span>' : ""}</div><div class="c">${esc(e.pattern.replace("_", " "))}, ${esc(e.primary_muscle || "")}, ${esc(e.equipment || "")}</div></div>
      <div class="row"><button class="ghost" data-exedit="${e.id}">Edit</button><label class="switch small"><input type="checkbox" data-exact="${e.id}" ${e.active ? "checked" : ""}><span class="slider"></span></label></div></div>`).join("") + (!t && S.exercises.length > 30 ? `<div class="muted small" style="padding:8px 4px">Search to see the rest of the ${S.exercises.length} exercises.</div>` : "");
    $$("[data-exact]", list).forEach(i => i.addEventListener("change", async () => { try { await api("PUT", "/api/exercises/" + i.dataset.exact, { active: i.checked }); toast(i.checked ? "Back in the rotation" : "Hidden from the plan"); load(true); } catch (e) { toast(e.message); } }));
    $$("[data-exedit]", list).forEach(b => b.addEventListener("click", () => editExerciseSheet(S.exercises.find(x => x.id === +b.dataset.exedit))));
  };
  q.addEventListener("input", draw); draw();
  $("#exAdd", root).addEventListener("click", () => editExerciseSheet(null));
}
function editExerciseSheet(ex) {
  const patterns = ["squat", "hinge", "lunge", "horizontal_push", "vertical_push", "horizontal_pull", "vertical_pull", "shoulder_iso", "triceps", "biceps", "rear_delt", "quad_iso", "ham_iso", "glute", "calf", "core"];
  const muscles = ["chest", "shoulders", "back", "biceps", "triceps", "quads", "hamstrings", "glutes", "calves", "core"];
  const equip = ["barbell", "trap_bar", "dumbbell", "cable", "machine", "assisted", "bodyweight", "band"];
  const cues = ex ? ex.cues || [] : [];
  openSheet(`<div class="handle"></div><h2>${ex ? esc(ex.name) : "Add an exercise"}</h2>
    <div class="f-row"><label class="field grow"><span>Name</span><input type="text" id="x-name" value="${esc(ex ? ex.name : "")}"></label>
      ${ex ? "" : `<label class="field narrow"><span>Pattern</span><select id="x-pattern">${patterns.map(p => `<option value="${p}">${p.replace("_", " ")}</option>`).join("")}</select></label>
      <label class="field narrow"><span>Main muscle</span><select id="x-muscle">${muscles.map(p => `<option value="${p}">${p}</option>`).join("")}</select></label>`}
      <label class="field narrow"><span>Equipment</span><select id="x-equip">${equip.map(p => `<option value="${p}"${ex && ex.equipment === p ? " selected" : ""}>${p.replace("_", " ")}</option>`).join("")}</select></label></div>
    <div class="f-row"><label class="field grow"><span>Weight step when you progress (kg), blank for the default</span><input type="number" step="0.5" inputmode="decimal" id="x-inc" value="${ex && ex.increment_kg != null ? ex.increment_kg : ""}"></label>
      <label class="field grow"><span>Lightest load (kg), blank for the default</span><input type="number" step="0.5" inputmode="decimal" id="x-min" value="${ex && ex.min_load_kg != null ? ex.min_load_kg : ""}"></label></div>
    <div class="cap">Form cues, up to three</div>${[0, 1, 2].map(i => `<input type="text" class="mb" id="x-cue${i}" value="${esc(cues[i] || "")}" placeholder="One clear thing to remember">`).join("")}
    <div class="row mt"><button class="primary big" id="x-save">Save</button><button class="ghost" id="x-cancel">Cancel</button></div>`, sh => {
    $("#x-cancel", sh).addEventListener("click", closeSheet);
    $("#x-save", sh).addEventListener("click", async () => {
      const body = { name: $("#x-name", sh).value.trim(), equipment: $("#x-equip", sh).value, cues: [0, 1, 2].map(i => $("#x-cue" + i, sh).value.trim()).filter(Boolean),
        increment_kg: $("#x-inc", sh).value === "" ? null : +$("#x-inc", sh).value, min_load_kg: $("#x-min", sh).value === "" ? null : +$("#x-min", sh).value };
      if (!body.name) { toast("Give it a name"); return; }
      try {
        if (ex) await api("PUT", "/api/exercises/" + ex.id, body);
        else await api("POST", "/api/exercises", Object.assign(body, { pattern: $("#x-pattern", sh).value, primary_muscle: $("#x-muscle", sh).value }));
        closeSheet(); toast("Saved"); await load(true); renderSettings();
      } catch (e) { toast(e.message); }
    });
  });
}
async function renderMyFoods(root) {
  if (!FOODS) await loadFoods();
  const mine = (FOODS || []).filter(f => f.source === "custom" || f.source === "off").sort((a, b) => a.name.localeCompare(b.name));
  $("#myFoods", root).innerHTML = mine.length ? mine.slice(0, 40).map(f => `<div class="lg-row"><div class="lg-what"><div class="t">${esc(f.name)}</div><div class="c">${esc(f.brand || "")}${f.brand ? " · " : ""}${n0(f.kcal_100)} kcal, ${n1(f.protein_100)} p per 100 ${esc(f.unit)} · ${f.source === "off" ? "Open Food Facts" : "yours"}</div></div>${f.id ? `<button class="ghost" data-hidefood="${f.id}">Hide</button>` : `<span class="pill">waiting to sync</span>`}</div>`).join("") : `<div class="muted small">No foods of your own yet. Add one from the Food tab.</div>`;
  $$("[data-hidefood]", root).forEach(b => b.addEventListener("click", async () => { try { await api("DELETE", "/api/foods/" + b.dataset.hidefood); FOODS = FOODS.filter(f => String(f.id) !== b.dataset.hidefood); toast("Hidden"); renderMyFoods(root); } catch (e) { toast(e.message); } }));
  try {
    const meals = await api("GET", "/api/meals");
    $("#myMeals", root).innerHTML = `<div class="cap">Saved meals</div>` + (meals.length ? meals.map(m => `<div class="lg-row"><div class="lg-what"><div class="t">${esc(m.name)}</div><div class="c">${m.items.map(i => esc(i.name)).join(", ")} · ${n0(m.kcal)} kcal</div></div><button class="ghost" data-delmeal="${m.id}">Delete</button></div>`).join("") : `<div class="muted small">None yet. Use "Save as meal" on a slot in Food.</div>`);
    $$("[data-delmeal]", root).forEach(b => b.addEventListener("click", async () => { try { await api("DELETE", "/api/meals/" + b.dataset.delmeal); toast("Deleted"); renderMyFoods(root); } catch (e) { toast(e.message); } }));
  } catch (e) {}
}
async function renderBackupInfo(root) {
  const el = $("#bkInfo", root); if (!el) return;
  let swVersion = null;
  try {
    if (navigator.serviceWorker && navigator.serviceWorker.controller) {
      swVersion = await new Promise(res => { const ch = new MessageChannel(); ch.port1.onmessage = e => res(e.data.version); navigator.serviceWorker.controller.postMessage({ type: "version" }, [ch.port2]); setTimeout(() => res(null), 800); });
    }
  } catch (e) {}
  const counts = { workouts: (await api("GET", "/api/history?from=2000-01-01")).workouts.length };
  el.textContent = `${plural(counts.workouts, "workout")} stored. ${IS_ANDROID_APP ? "Android app" : swVersion ? "Installed for offline use, version " + swVersion : "Running in the browser"}, app version ${S.version}.`;
}
async function downloadText(name, mime, text) {
  if (IS_ANDROID_APP) { window.Android.saveFile(name, mime, text); toast(`Saved ${name} to Downloads`); return; }
  try {
    if (navigator.share && navigator.canShare) {
      const file = new File([text], name, { type: mime });
      if (navigator.canShare({ files: [file] })) { await navigator.share({ files: [file], title: name }); return; }
    }
  } catch (e) { if (e && e.name === "AbortError") return; }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: mime })); a.download = name;
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

/* ---------------------------------------------------------- boot */
(async () => {
  let version = "dev";
  try { version = (await (await fetch("./version.json", { cache: "no-store" })).json()).version || "dev"; } catch (e) {}
  try { await LocalApi.init(version); }
  catch (e) { console.error(e); $("main").innerHTML = `<div class="card"><h2>Could not start</h2><p class="hint">${esc(e.message)}. Reload the app.</p></div>`; return; }
  saveW();
  { const h = location.hash.replace("#", ""); if (["today", "workout", "plan", "food", "progress", "history", "settings"].includes(h)) UI.tab = h; }
  switchTab(UI.tab);
  await load();
  if (W) tickElapsed();
})();

