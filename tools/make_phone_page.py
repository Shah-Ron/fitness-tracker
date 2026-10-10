"""Derive phone/index.html and phone/app.js from app.html (the laptop page)."""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html = open(os.path.join(ROOT, "app.html"), encoding="utf-8").read()
m = re.search(r"<script>\n(.*)</script>\n</body>", html, re.S)
js = m.group(1)
page = html[:m.start()] + "__SCRIPTS__" + html[m.end():]

def cut(s, start_marker, end_marker, replacement, keep_end=True):
    a = s.index(start_marker)
    b = s.index(end_marker, a)
    return s[:a] + replacement + (s[b:] if keep_end else s[b + len(end_marker):])

def rep(s, old, new, count=1):
    assert s.count(old) == count, (old[:80], s.count(old))
    return s.replace(old, new)

# ---- page
page = rep(page, '<link rel="manifest" href="/manifest.webmanifest">', '<link rel="manifest" href="./manifest.webmanifest">')
page = rep(page, '<link rel="icon" href="/icon-192.png">\n<link rel="apple-touch-icon" href="/icon-180.png">', '<link rel="icon" href="./icon-192.png">\n<link rel="apple-touch-icon" href="./icon-180.png">')
page = rep(page, "Private to this laptop and your phone. Calorie and strength figures are estimates, not medical advice.", "Everything is stored on this device. Calorie and strength figures are estimates, not medical advice.")
page = rep(page, "__SCRIPTS__", '<script src="./engine.js"></script>\n<script src="./store.js"></script>\n<script src="./local-api.js"></script>\n<script src="./app.js"></script>\n</body>')

# ---- script: state block
js = rep(js, 'let ONLINE = true;\nlet PAIRING = false;\nconst DEVICE = ls.get("ft-device") || (() => { const d = uid(); ls.set("ft-device", d); return d; })();\nlet KEY = ls.get("ft-key");\n{ const p = new URLSearchParams(location.search); if (p.get("key")) { KEY = p.get("key"); ls.set("ft-key", KEY); } }\n',
         'let ONLINE = true;\n')

# ---- api, queue, mutate, flush, notice -> local versions
js = cut(js, "/* ---------------------------------------------------------- api */", "/* ---------------------------------------------------------- load */", '''/* ---------------------------------------------------------- local api */
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
function updateNotice() {
  let n = $("#updbar");
  if (!n) { const m = $("main"); if (!m) return; n = document.createElement("div"); n.id = "updbar"; m.prepend(n); }
  const st = updateState();
  const snoozed = st.latest && st.latest === st.dismissed && (!st.dismissedAt || Date.now() - st.dismissedAt < SNOOZE_MS);
  if (!st.newer || !st.latest || snoozed || W) { n.innerHTML = ""; return; }
  const notes = (st.notes || []).slice(0, 6);
  n.innerHTML = `<div class="upd"><span><b>Version ${esc(st.latest)}</b> is ready${st.cur ? `, you have ${esc(st.cur)}` : ""}${st.size ? ` (${esc(st.size)})` : ""}.</span><span class="acts"><button class="primary" id="updNow">Update</button><button class="ghost" id="updLater">Later</button></span>
    ${notes.length ? `<details><summary>What is new${st.published ? ", " + esc(fmtShort(st.published)) : ""}</summary><ul>${notes.map(x => `<li>${esc(x)}</li>`).join("")}</ul></details>` : ""}<span class="state" id="updState" hidden></span></div>`;
  $("#updNow").addEventListener("click", () => applyUpdate(st));
  $("#updLater").addEventListener("click", () => { ls.set("ft-update", Object.assign(updateState(), { dismissed: st.latest, dismissedAt: Date.now() })); n.innerHTML = ""; });
}

''')

# ---- load
js = cut(js, "/* ---------------------------------------------------------- load */", "function saveW()", '''/* ---------------------------------------------------------- load */
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
''')

# ---- pairing card and service worker block
js = cut(js, "function showPairing() {", "/* Service worker:", "")
js = cut(js, "/* Service worker:", "/* ---------------------------------------------------------- shared bits */", '''/* Service worker: the whole app is cached, so it opens with no connection. Not used inside the Android package. */
if ("serviceWorker" in navigator && !IS_ANDROID_APP && location.protocol.startsWith("http")) {
  navigator.serviceWorker.register("./sw.js").then(reg => {
    let hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (UPDATING) { location.reload(); return; }
      if (hadController) toast("Updated. Tap to reload", () => location.reload(), 12000);
      hadController = true;
    });
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") reg.update().catch(() => {}); });
  }).catch(() => {});
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
}

''')

# ---- wording that assumed a laptop
js = rep(js, "Used for the calorie maths only. Nothing leaves this laptop.", "Used for the calorie maths only. Nothing leaves this device.")
js = rep(js, "Changes rebuild the sessions you have not started yet, from today. Sessions already done stay as they were.", "Changes rebuild the sessions you have not started yet, from today. Sessions already done stay as they were. Pick a split that suits how many days you train.")
js = rep(js, '''  if (!S) { root.innerHTML = `<div class="card"><h2>Offline</h2><p class="hint">Today's numbers need the laptop. Your workout is still available under Workout.</p></div>`; return; }''',
         '''  if (!S) { root.innerHTML = `<div class="card"><h2>Loading</h2></div>`; return; }''')
js = rep(js, '${ONLINE ? "" : " You are offline; the plan below was saved on this device."}', '')
js = rep(js, '  if (!ONLINE) { toast("Swapping needs the laptop. Skip it for now."); return; }\n', '')
js = rep(js, '''  try { wk = await api("GET", "/api/plan/week?date=" + UI.planDate); ONLINE = true; }
  catch (e) {
    if (e instanceof PairError) { showPairing(); return; }
    ONLINE = false;
    if (S && S.week && S.week.week.start_date <= UI.planDate && addDays(S.week.week.start_date, 6) >= UI.planDate) wk = S.week;
  }
  updateNotice();
  if (!wk) { root.innerHTML = `<div class="card"><h2>Plan</h2><p class="hint">That week is not available offline. Connect to home wifi and try again.</p><div class="row"><button id="planToday">Back to this week</button></div></div>`; $("#planToday").addEventListener("click", () => { UI.planDate = todayIso(); renderPlan(); }); return; }''',
         '''  try { wk = await api("GET", "/api/plan/week?date=" + UI.planDate); }
  catch (e) { toast(e.message); }
  if (!wk) { root.innerHTML = `<div class="card"><h2>Plan</h2><p class="hint">That week could not be loaded.</p><div class="row"><button id="planToday">Back to this week</button></div></div>`; $("#planToday").addEventListener("click", () => { UI.planDate = todayIso(); renderPlan(); }); return; }''')
js = rep(js, '''  try {
    const blob = await api("GET", "/api/foods/list", undefined, { timeout: 20000 });
    FOODS = blob.foods.map(r => { const o = {}; blob.fields.forEach((f, i) => { o[f] = r[i]; }); o._tokens = tokens(o.name + " " + (o.brand || "") + " " + (o.search || "")); return o; });
    ls.set("ft-foods-at", nowIso());
  } catch (e) {
    if (e instanceof PairError) { showPairing(); return; }
    FOODS = FOODS || [];
  }
  const custom = ls.get("ft-custom-foods", []);
  custom.forEach(c => { if (!FOODS.some(f => f.client_id === c.client_id || (f.id && f.id === c.id))) { c._tokens = tokens(c.name + " " + (c.brand || "")); FOODS.push(c); } });
}''',
         '''  try {
    const blob = await api("GET", "/api/foods/list");
    FOODS = blob.foods.map(r => { const o = {}; blob.fields.forEach((f, i) => { o[f] = r[i]; }); o._tokens = tokens(o.name + " " + (o.brand || "") + " " + (o.search || "")); return o; });
  } catch (e) { toast(e.message); FOODS = FOODS || []; }
}''')
js = rep(js, '''    ${SLOTS.map(slot => slotCard(slot, day, date)).join("")}
    <p class="hint mt2">Search works offline over the bundled list. Foods marked <span class="approx">approx</span> use typical label values. Online search asks USDA FoodData Central for dishes and drinks and Open Food Facts for packaged products, and needs internet.</p>`;''',
         '''    ${SLOTS.map(slot => slotCard(slot, day, date)).join("")}
    <p class="hint mt2">Search works offline over the bundled list, which includes New Zealand staples and Kerala and Indian dishes. Foods marked <span class="approx">approx</span> use typical values. Online search asks USDA FoodData Central for dishes and drinks (curries, biryani, beer, wine) and Open Food Facts for packaged products, and needs internet.</p>`;''')
js = rep(js, '  if (!ONLINE) { toast("Online search needs the internet"); return; }', '  if (!navigator.onLine) { toast("Online search needs the internet"); return; }')
js = rep(js, '  try { meals = await api("GET", "/api/meals"); } catch (e) { toast("Saved meals need the laptop"); return; }', '  try { meals = await api("GET", "/api/meals"); } catch (e) { toast(e.message); return; }')
js = rep(js, '''      f._tokens = tokens(f.name + " " + (f.brand || ""));
      FOODS.push(f);
      const custom = ls.get("ft-custom-foods", []); custom.push(Object.assign({}, f, { _tokens: undefined })); ls.set("ft-custom-foods", custom);
      await mutate("food", f.client_id, { name: f.name, brand: f.brand, unit: f.unit, source: "custom", kcal_100: f.kcal_100, protein_100: f.protein_100, carb_100: f.carb_100, fat_100: f.fat_100, portions: f.portions });
      closeSheet(); portionSheet(f, date);''',
         '''      try {
        const saved = await api("POST", "/api/foods", { client_id: f.client_id, name: f.name, brand: f.brand, unit: f.unit, source: "custom", kcal_100: f.kcal_100, protein_100: f.protein_100, carb_100: f.carb_100, fat_100: f.fat_100, portions: f.portions });
        FOODS = null; await loadFoods();
        closeSheet(); portionSheet(FOODS.find(x => x.id === saved.id) || saved, date);
      } catch (e) { toast(e.message); }''')
js = rep(js, '''  catch (e) { root.innerHTML = `<div class="card"><h2>Progress</h2><p class="hint">Charts need the laptop. ${esc(e.message)}</p></div>`; return; }''',
         '''  catch (e) { root.innerHTML = `<div class="card"><h2>Progress</h2><p class="hint">${esc(e.message)}</p></div>`; return; }''')
js = rep(js, '''  catch (e) { root.innerHTML = `<div class="card"><h2>History</h2><p class="hint">History needs the laptop. ${esc(e.message)}</p></div>`; return; }''',
         '''  catch (e) { root.innerHTML = `<div class="card"><h2>History</h2><p class="hint">${esc(e.message)}</p></div>`; return; }''')
js = rep(js, '<div class="card"><div class="between"><h2>Workouts</h2><a class="btn" href="/api/export.csv?what=sets" download>Sets as CSV</a></div>', '<div class="card"><div class="between"><h2>Workouts</h2><button data-csv="sets">Sets as CSV</button></div>')
js = rep(js, '<div class="card"><div class="between"><h2>Food days</h2><a class="btn" href="/api/export.csv?what=food" download>Food as CSV</a></div>', '<div class="card"><div class="between"><h2>Food days</h2><button data-csv="food">Food as CSV</button></div>')
js = rep(js, '<div class="card"><div class="between"><h2>Body</h2><a class="btn" href="/api/export.csv?what=body" download>Body as CSV</a></div>', '<div class="card"><div class="between"><h2>Body</h2><button data-csv="body">Body as CSV</button></div>')
js = rep(js, '''  $$("[data-view]", root).forEach(r => r.addEventListener("click", () => showWorkoutDetail(r.dataset.view)));
  $$("[data-fooday]", root).forEach(r => r.addEventListener("click", () => { UI.foodDate = r.dataset.fooday; switchTab("food"); }));
}''',
         '''  $$("[data-view]", root).forEach(r => r.addEventListener("click", () => showWorkoutDetail(r.dataset.view)));
  $$("[data-fooday]", root).forEach(r => r.addEventListener("click", () => { UI.foodDate = r.dataset.fooday; switchTab("food"); }));
  $$("[data-csv]", root).forEach(b => b.addEventListener("click", () => exportCsv(b.dataset.csv)));
}
async function exportCsv(what) {
  try { const text = await api("GET", "/api/export.csv?what=" + what); await downloadText(`fitness-${what}-${todayIso()}.csv`, "text/csv", text); } catch (e) { toast(e.message); }
}''')

# ---- settings: phone, data and server cards become one Backups card
js = cut(js, '    ${fold("phone", "Phone", "", ', '''<button class="danger" id="s-stop">Stop the server</button></div>`)}`;''',
         '''    ${fold("backups", "Backups", "", `<p class="hint">Everything lives on this ${IS_ANDROID_APP ? "phone" : "device"}. If it is lost or replaced, so is your data, so export a backup now and then and keep it somewhere safe. A backup restores onto any device running this app.</p>
      <div class="row"><button class="primary" id="bkExport">Export a backup</button><label class="btn" for="restoreFile">Restore a backup</label><input type="file" id="restoreFile" accept="application/json,.json" hidden></div>
      <div class="row mt"><button id="csvSets">Sets CSV</button><button id="csvFood">Food CSV</button><button id="csvBody">Body CSV</button></div>
      <div class="row mt"><button class="danger" id="bkWipe">Start fresh</button><span class="muted small">Removes everything on this device. Export first.</span></div>
      <p class="hint mt" id="bkInfo"></p>`)}
    ${fold("updates", "Updates", updateState().newer ? "one waiting" : "", `<p class="hint">New versions are published on GitHub. The app checks by itself when it opens, at most every six hours, and shows a banner with what is new. ${IS_ANDROID_APP ? "Updating downloads the new package and opens the installer; your data stays." : "Updating reloads the app into the newest build."}</p>
      <div class="row"><label class="switch"><input type="checkbox" id="s-autoupdate" ${st.auto_update_check === false ? "" : "checked"}><span class="slider"></span><span>Check for updates automatically</span></label></div>
      <div class="row mt"><button id="upCheck">Check now</button><span class="muted small" id="upInfo"></span></div>
      <p class="hint mt" id="upLast">${lastCheckedText()}</p>
      ${BUNDLE.whats_new && BUNDLE.whats_new.notes && BUNDLE.whats_new.notes.length ? `<div class="cap mt">This version${appVersion() ? ", " + esc(appVersion()) : ""}${BUNDLE.whats_new.date ? ", " + esc(fmtShort(BUNDLE.whats_new.date)) : ""}</div><ul class="steps">${BUNDLE.whats_new.notes.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}`)}`;''', keep_end=False)
js = rep(js, '''  $("#s-stay").addEventListener("change", e => saveSettings({ stay_running: e.target.checked }));
  $("#s-stop").addEventListener("click", async () => { if (!confirm("Stop the server? The phone will not be able to sync until you start it again.")) return; try { await api("POST", "/api/stop"); $("main").innerHTML = `<div class="card"><h2>Stopped</h2><p class="hint">Fitness Tracker has stopped. Double-click the .exe to start it again.</p></div>`; } catch (e) { toast(e.message); } });
  $("#restoreFile").addEventListener("change", async e => {
    const file = e.target.files[0]; if (!file) return;
    if (!confirm(`Replace everything with ${file.name}? This cannot be undone.`)) { e.target.value = ""; return; }
    try { const data = JSON.parse(await file.text()); await api("POST", "/api/restore", data); toast("Restored"); FOODS = null; await load(true); renderSettings(); } catch (err) { toast(err.message); }
  });
  renderExLib(root);
  renderMyFoods(root);
  renderPhone(root);
}''',
         '''  $("#bkExport").addEventListener("click", async () => { try { const data = await api("GET", "/api/backup.json"); await downloadText(`fitness-backup-${todayIso()}.json`, "application/json", JSON.stringify(data)); } catch (e) { toast(e.message); } });
  $("#csvSets").addEventListener("click", () => exportCsv("sets"));
  $("#csvFood").addEventListener("click", () => exportCsv("food"));
  $("#csvBody").addEventListener("click", () => exportCsv("body"));
  $("#bkWipe").addEventListener("click", async () => { if (!confirm("Remove everything on this device? Export a backup first if you want to keep it.")) return; try { await api("POST", "/api/wipe"); W = null; saveW(); FOODS = null; toast("Fresh start"); await load(true); renderSettings(); } catch (e) { toast(e.message); } });
  $("#restoreFile").addEventListener("change", async e => {
    const file = e.target.files[0]; if (!file) return;
    if (!confirm(`Replace everything with ${file.name}? This cannot be undone.`)) { e.target.value = ""; return; }
    try { const data = JSON.parse(await file.text()); await api("POST", "/api/restore", data); toast("Restored"); W = null; saveW(); FOODS = null; await load(true); renderSettings(); } catch (err) { toast(err.message); }
  });
  $("#upCheck").onclick = checkForUpdate;
  $("#s-autoupdate").addEventListener("change", e => { saveSettings({ auto_update_check: e.target.checked }); if (e.target.checked) autoUpdateCheck(true); });
  renderExLib(root);
  renderMyFoods(root);
  renderBackupInfo(root);
}''')
js = cut(js, "async function renderPhone(root) {", "/* ---------------------------------------------------------- boot */", '''async function renderBackupInfo(root) {
  const el = $("#bkInfo", root); if (!el) return;
  let swVersion = null;
  try {
    if (navigator.serviceWorker && navigator.serviceWorker.controller) {
      swVersion = await new Promise(res => { const ch = new MessageChannel(); ch.port1.onmessage = e => res(e.data.version); navigator.serviceWorker.controller.postMessage({ type: "version" }, [ch.port2]); setTimeout(() => res(null), 800); });
    }
  } catch (e) {}
  const counts = { workouts: (await api("GET", "/api/history?from=2000-01-01")).workouts.length };
  const appVer = IS_ANDROID_APP && window.Android.appVersion ? window.Android.appVersion() : null;
  el.textContent = `${plural(counts.workouts, "workout")} stored. ${IS_ANDROID_APP ? "Android app " + (appVer || "") : swVersion ? "Installed for offline use, version " + swVersion : "Running in the browser"}, build ${S.version}.`;
}
/* Updates. The Android app fetches the latest GitHub release and installs it; the web app reloads into the newest
   build. The check runs by itself on start and when the app comes back to the front, at most every six hours, and
   shows a banner with what is new; it never interrupts a workout, and Later rests that version for three days. The
   first open after an update lands shows what changed. */
const REPO = "Shah-Ron/fitness-tracker";
const UPDATE_EVERY_MS = 6 * 60 * 60 * 1000;
const SNOOZE_MS = 3 * 24 * 60 * 60 * 1000;
let BUNDLE = {};          // version.json of this build: its version and what is new in it
let UPDATING = false;     // a web update is in flight, so the next controllerchange reloads straight away
const verParts = v => String(v || "").replace(/^v/, "").split(".").map(n => parseInt(n, 10) || 0);
function newerVersion(a, b) { const x = verParts(a), y = verParts(b); for (let i = 0; i < Math.max(x.length, y.length); i++) { if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); } return false; }
function updateState() { return ls.get("ft-update", {}) || {}; }
const appVersion = () => IS_ANDROID_APP && window.Android.appVersion ? window.Android.appVersion() : (S ? S.version : null);
async function latestVersion() {
  if (IS_ANDROID_APP) {
    const cur = window.Android.appVersion ? window.Android.appVersion() : "0";
    const rel = await LocalApi.fetchJson(`https://api.github.com/repos/${REPO}/releases/latest`);
    const latest = String(rel.tag_name || "").replace(/^v/, "");
    const apk = (rel.assets || []).find(a => String(a.name || "").toLowerCase().endsWith(".apk"));
    const notes = String(rel.body || "").split(/\\r?\\n/).map(l => l.trim()).filter(l => /^[-*] /.test(l)).map(l => l.replace(/^[-*] /, "").replace(/\\*\\*/g, ""));
    return { latest, cur, url: apk ? apk.browser_download_url : null, size: apk && apk.size ? n1(apk.size / 1048576) + " MB" : null, notes, published: rel.published_at ? String(rel.published_at).slice(0, 10) : null, newer: !!(latest && apk && newerVersion(latest, cur)) };
  }
  const v = await (await fetch("./version.json?fresh=1&ts=" + Date.now(), { cache: "no-store" })).json();
  const cur = S ? S.version : null, e = v.whats_new || {};
  return { latest: v.version || null, cur, url: null, size: null, notes: e.notes || [], title: e.title || null, published: e.date || null, newer: !!(v.version && cur && v.version !== cur) };
}
function lastCheckedText() {
  const st = updateState(); if (!st.at) return "Not checked yet.";
  const when = new Date(st.at);
  return `Last checked ${when.toLocaleDateString("en-NZ", { day: "numeric", month: "short" })} at ${when.toLocaleTimeString("en-NZ", { hour: "2-digit", minute: "2-digit" })}${st.newer ? `, version ${st.latest} is available` : st.error ? ", could not reach GitHub" : ", up to date"}.`;
}
async function autoUpdateCheck(force) {
  if (!S || S.settings.auto_update_check === false || !navigator.onLine) return;
  const st = updateState();
  if (!force && st.at && Date.now() - st.at < UPDATE_EVERY_MS) { updateNotice(); return; }
  try {
    const r = await latestVersion();
    ls.set("ft-update", { at: Date.now(), latest: r.latest, cur: r.cur, url: r.url, size: r.size, notes: r.notes, title: r.title, published: r.published, newer: r.newer, dismissed: st.dismissed || null, dismissedAt: st.dismissedAt || null });
  } catch (e) { ls.set("ft-update", Object.assign(st, { at: Date.now(), error: e.message })); }
  updateNotice();
  const l = $("#upLast"); if (l) l.textContent = lastCheckedText();
}
/* Progress of an update, written into the banner when it is up, else into the Updates fold. */
function updateSay(msg, pct) {
  const el = $("#updState") || $("#upInfo"); if (!el) return;
  el.hidden = false;
  el.innerHTML = esc(msg) + (pct != null ? `<div class="meter" style="margin-top:6px"><span style="width:${Math.max(0, Math.min(100, pct))}%"></span></div>` : "");
}
async function applyUpdate(r) {
  const now = $("#updNow");
  if (IS_ANDROID_APP) {
    if (!r.url) { toast("The latest release has no package to install"); return; }
    let res;
    try { res = window.Android.installUpdate(r.url); } catch (e) { toast(e.message); return; }
    if (res !== "started" && res !== "running") { toast(res, null, 6000); return; }
    if (now) now.disabled = true;
    updateSay("Downloading", 0);
    if (!window.Android.updateStatus) { toast("Downloading. The installer opens when it is ready; tap Install there.", null, 8000); return; }
    let polls = 0;
    const poll = () => {
      let st; try { st = JSON.parse(window.Android.updateStatus()); } catch (e) { st = { status: "unknown" }; }
      if (st.status === "running" || st.status === "pending") {
        updateSay(`Downloading${st.total > 0 ? `, ${n1(st.bytes / 1048576)} of ${n1(st.total / 1048576)} MB` : ""}`, st.total > 0 ? st.bytes / st.total * 100 : 0);
        setTimeout(poll, 700);
      } else if (st.status === "done") {
        updateSay("Downloaded. The installer opens now; tap Install there, and your data stays.", 100);
        try { window.Android.openInstaller(); } catch (e) {}
        if (now) now.disabled = false;
      } else if (st.status === "failed") {
        updateSay(`The download failed${st.reason ? ", " + st.reason : ""}. Check the connection and try again.`);
        if (now) { now.disabled = false; now.textContent = "Try again"; }
      } else if (++polls < 80) setTimeout(poll, 700);
      else { updateSay("Still downloading. The installer opens when it is done."); if (now) now.disabled = false; }
    };
    setTimeout(poll, 500);
    return;
  }
  UPDATING = true;
  if (now) now.disabled = true;
  updateSay("Fetching the new version");
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    if (reg) {
      await reg.update();
      const sw = reg.installing || reg.waiting;
      if (sw && sw.state !== "activated") await new Promise(res => { const t = setTimeout(res, 25000); sw.addEventListener("statechange", () => { if (sw.state === "activated" || sw.state === "redundant") { clearTimeout(t); res(); } }); });
    }
  } catch (e) {}
  updateSay("Reloading");
  setTimeout(() => location.reload(), 300);
}
async function checkForUpdate() {
  const info = $("#upInfo"), btn = $("#upCheck");
  if (!info || !btn) return;
  info.textContent = "Checking";
  btn.disabled = true;
  try {
    const r = await latestVersion();
    ls.set("ft-update", Object.assign(updateState(), { at: Date.now(), latest: r.latest, cur: r.cur, url: r.url, size: r.size, notes: r.notes, title: r.title, published: r.published, newer: r.newer, dismissed: null, dismissedAt: null, error: null }));
    if (r.newer) {
      info.textContent = IS_ANDROID_APP ? `Version ${r.latest} is available${r.size ? ", " + r.size : ""}. You have ${r.cur}.` : `A newer build is available${r.title ? ": " + r.title : ""}.`;
      btn.textContent = IS_ANDROID_APP ? `Install ${r.latest}` : "Reload into it"; btn.classList.add("primary");
      btn.onclick = () => { applyUpdate(r); btn.disabled = true; };
    } else {
      info.textContent = `You have the latest version${r.cur ? " (" + r.cur + ")" : ""}.`;
    }
    updateNotice();
  } catch (e) { info.textContent = "Could not check: " + e.message; }
  finally { btn.disabled = false; const l = $("#upLast"); if (l) l.textContent = lastCheckedText(); }
}
/* The first open after an update: a short sheet with what changed. Nothing on a first install. */
function whatsNewOnce() {
  const cur = appVersion(); if (!cur) return;
  const seen = ls.get("ft-seen-version");
  if (!seen) { ls.set("ft-seen-version", cur); return; }
  if (seen === cur || W) return;
  const e = BUNDLE.whats_new;
  ls.set("ft-seen-version", cur);
  if (!e || !e.notes || !e.notes.length) return;
  setTimeout(() => openSheet(`<div class="handle"></div><h2>Updated to ${esc(cur)}</h2><p class="hint">${esc(e.title || "What is new")}${e.date ? ", " + esc(fmtShort(e.date)) : ""}.</p>
    <ul class="steps">${e.notes.map(x => `<li>${esc(x)}</li>`).join("")}</ul><div class="row mt2"><button class="primary big" id="wnClose">Got it</button></div>`, sh => $("#wnClose", sh).addEventListener("click", closeSheet)), 900);
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

''')

# ---- boot
js = cut(js, "/* ---------------------------------------------------------- boot */", "\n", '''/* ---------------------------------------------------------- boot */
(async () => {
  let version = "dev";
  try { BUNDLE = await (await fetch("./version.json", { cache: "no-store" })).json(); version = BUNDLE.version || "dev"; } catch (e) { BUNDLE = {}; }
  try { await LocalApi.init(version); }
  catch (e) { console.error(e); $("main").innerHTML = `<div class="card"><h2>Could not start</h2><p class="hint">${esc(e.message)}. Reload the app.</p></div>`; return; }
  saveW();
  { const h = location.hash.replace("#", ""); if (["today", "workout", "plan", "food", "progress", "history", "settings"].includes(h)) UI.tab = h; }
  switchTab(UI.tab);
  await load();
  if (W) { tickElapsed(); resumeRest(); }
  whatsNewOnce();
  autoUpdateCheck();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") autoUpdateCheck(); });
})();
''', keep_end=False)
js = re.sub(r"\nsaveW\(\);\n\{ const h = location\.hash.*?\nswitchTab\(UI\.tab\);\nload\(\);\nif \(W\) \{ tickElapsed\(\); resumeRest\(\); \}\n", "\n", js, flags=re.S)
assert js.count("\nload();\n") == 0, "the laptop boot block is still in the phone page"
assert "PairError" not in js.replace("class PairError", ""), "PairError still referenced"
assert "/api/ping" not in js and "ft-key" not in js and "renderPhone" not in js
open(os.path.join(ROOT, "phone", "index.html"), "w", encoding="utf-8").write(page)
open(os.path.join(ROOT, "phone", "app.js"), "w", encoding="utf-8").write('"use strict";\n' + js)
print("wrote phone/index.html and phone/app.js", len(js))
