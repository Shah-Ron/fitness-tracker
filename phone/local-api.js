/* Fitness Tracker local API, phone edition.
   The same routes the laptop server offered, answered on the phone from the
   store and the engine. The screens call api(method, path, body) exactly as
   before; nothing here touches the network except the Open Food Facts lookups. */
"use strict";

const LocalApi = (() => {
  const E = Engine;
  const today = () => E.isoOf(new Date());
  const SLOTS = ["breakfast", "lunch", "dinner", "snack"];
  const INTENSITIES = ["easy", "moderate", "vigorous", "interval"];
  let db = null, PROG = null, EX_BY_KEY = {}, VERSION = "dev";

  class BadRequest extends Error { constructor(msg, code = 400) { super(msg); this.code = code; } }

  const settings = () => { const s = Object.assign({}, E.NUTRITION_DEFAULTS, E.TRAIN_DEFAULTS, { split: "upper_lower", stay_running: true, keep_awake: true, theme: null, contact_email: null, rest_default_sec: 90 }); Object.assign(s, db.settings()); return s; };
  const refreshExercises = () => { EX_BY_KEY = {}; db.all("exercises").forEach(e => { EX_BY_KEY[e.key] = e; }); };
  const exPublic = e => Object.assign({}, e);

  async function init(version) {
    db = await Store.init();
    VERSION = version || "dev";
    PROG = Store.db.bundled().programme;
    refreshExercises();
    const problems = E.validateSeed(PROG, EX_BY_KEY);
    if (problems.length) console.warn("programme.json does not match the exercise library:", problems);
  }

  /* ---------------------------------------------------- validation */
  const num = (v, name, lo, hi, allowNull) => {
    if (v == null || v === "") { if (allowNull) return null; throw new BadRequest(`${name} is required`); }
    const x = +v; if (!isFinite(x)) throw new BadRequest(`${name} must be a number`);
    if (lo != null && x < lo) throw new BadRequest(`${name} must be at least ${lo}`);
    if (hi != null && x > hi) throw new BadRequest(`${name} must be at most ${hi}`);
    return x;
  };
  const int = (v, name, lo, hi, allowNull) => { const x = num(v, name, lo, hi, allowNull); return x == null ? null : Math.round(x); };
  const dateV = (v, name = "date", allowNull) => { if (v == null || v === "") { if (allowNull) return null; throw new BadRequest(`${name} is required`); } const s = String(v).slice(0, 10); if (!/^\d{4}-\d{2}-\d{2}$/.test(s) || isNaN(E.D(s).getTime())) throw new BadRequest(`'${v}' is not a date`); return s; };
  const text = (v, name, max = 200, allowNull = true) => { if (v == null) { if (allowNull) return null; throw new BadRequest(`${name} is required`); } const s = String(v).trim(); if (!s && !allowNull) throw new BadRequest(`${name} is required`); return s ? s.slice(0, max) : null; };
  const choice = (v, name, list, allowNull) => { if (v == null || v === "") { if (allowNull) return null; throw new BadRequest(`${name} is required`); } if (!list.includes(v)) throw new BadRequest(`${name} must be one of ${list.join(", ")}`); return v; };

  /* ---------------------------------------------------- writes (the old sync ops) */
  function applyOp(type, cid, p) {
    p = p || {};
    const s = settings();
    const deleted = p.deleted === 1 || p.deleted === true || p.deleted === "1";
    if (type === "workout") {
      const ex = db.get("workouts", cid);
      if (deleted) { if (ex) { db.remove("workouts", cid); db.all("set_logs").filter(x => x.workout_client_id === cid).forEach(x => db.remove("set_logs", x.client_id)); db.all("cardio_logs").filter(x => x.workout_client_id === cid).forEach(x => db.remove("cardio_logs", x.client_id)); if (ex.session_id) updateSessionStatus(ex.session_id, ex.date); } return { ok: true }; }
      const fields = {};
      if ("session_id" in p) fields.session_id = int(p.session_id, "session_id", 1, null, true);
      if ("date" in p || !ex) fields.date = dateV(p.date || (ex && ex.date) || today());
      if ("started_at" in p) fields.started_at = p.started_at || null;
      if ("ended_at" in p) fields.ended_at = p.ended_at || null;
      if ("session_rpe" in p) fields.session_rpe = num(p.session_rpe, "session RPE", 1, 10, true);
      if ("kcal_wearable" in p) fields.kcal_wearable = num(p.kcal_wearable, "calories from the watch", 0, 5000, true);
      if ("hr_avg" in p) fields.hr_avg = num(p.hr_avg, "average heart rate", 30, 250, true);
      if ("notes" in p) fields.notes = text(p.notes, "notes", 2000);
      let row;
      if (ex) row = db.update("workouts", cid, fields);
      else row = db.insert("workouts", Object.assign({ client_id: cid, session_id: null, started_at: E.nowIso(), ended_at: null, session_rpe: null, work_sets: 0, hard_sets: 0, volume: 0, lift_minutes: 0, kcal_est: 0, kcal_wearable: null, hr_avg: null, effort: null, effort_parts: null, notes: null }, fields));
      if (!ex && row.session_id) E.freezeTargets(db, row.session_id, row.date, s, EX_BY_KEY);
      E.recomputeWorkout(db, cid, s, PROG);
      if (row.session_id) updateSessionStatus(row.session_id, row.date);
      return { ok: true, id: cid };
    }
    if (type === "set" || type === "cardio") {
      const coll = type === "set" ? "set_logs" : "cardio_logs";
      const ex = db.get(coll, cid);
      const wcid = p.workout_client_id || (ex && ex.workout_client_id);
      if (deleted) { if (ex) db.remove(coll, cid); if (wcid && db.get("workouts", wcid)) { E.recomputeWorkout(db, wcid, s, PROG); } return { ok: true }; }
      if (!db.get("workouts", wcid)) throw new BadRequest("That workout does not exist");
      const fields = { workout_client_id: wcid };
      if (type === "set") {
        const exId = int(p.exercise_id ?? (ex && ex.exercise_id), "exercise_id", 1);
        if (!db.get("exercises", exId)) throw new BadRequest("That exercise is not in the library");
        fields.exercise_id = exId;
        if ("plan_item_id" in p) fields.plan_item_id = int(p.plan_item_id, "plan_item_id", 1, null, true);
        if ("set_no" in p) fields.set_no = int(p.set_no, "set number", 1, 50);
        if ("reps" in p) fields.reps = int(p.reps, "reps", 0, 600, true);
        if ("weight_kg" in p) fields.weight_kg = num(p.weight_kg, "weight", 0, 1000, true);
        if ("rpe" in p) fields.rpe = num(p.rpe, "RPE", 1, 10, true);
        if ("is_warmup" in p) fields.is_warmup = p.is_warmup ? 1 : 0;
        if ("done_at" in p) fields.done_at = p.done_at || null;
        if (!ex) { if (fields.set_no == null) fields.set_no = db.all("set_logs").filter(x => x.workout_client_id === wcid && x.exercise_id === exId).length + 1; if (!fields.done_at) fields.done_at = E.nowIso(); }
      } else {
        if ("plan_item_id" in p) fields.plan_item_id = int(p.plan_item_id, "plan_item_id", 1, null, true);
        if ("exercise_id" in p) fields.exercise_id = int(p.exercise_id, "exercise_id", 1, null, true);
        if ("minutes" in p || !ex) fields.minutes = num(p.minutes, "minutes", 0, 600);
        if ("distance_km" in p) fields.distance_km = num(p.distance_km, "distance", 0, 500, true);
        if ("intensity" in p || !ex) fields.intensity = choice(p.intensity || "moderate", "intensity", INTENSITIES);
        if ("protocol" in p) fields.protocol = text(p.protocol, "protocol", 60);
      }
      if (ex) db.update(coll, cid, fields);
      else db.insert(coll, Object.assign({ client_id: cid, plan_item_id: null, reps: null, weight_kg: null, rpe: null, is_warmup: 0, done_at: null, distance_km: null, protocol: null, kcal_est: null }, fields));
      E.recomputeWorkout(db, wcid, s, PROG);
      return { ok: true, id: cid };
    }
    if (type === "food") {
      const name = text(p.name, "name", 120, false);
      const row = { client_id: cid, name, brand: text(p.brand, "brand", 60), unit: choice(p.unit || "g", "unit", ["g", "ml"]), source: choice(p.source || "custom", "source", ["custom", "off"]),
        source_id: text(p.source_id, "source_id", 64), barcode: text(p.barcode, "barcode", 32), kcal_100: num(p.kcal_100, "calories per 100", 0, 1000),
        protein_100: num(p.protein_100, "protein", 0, 100, true) || 0, carb_100: num(p.carb_100, "carbs", 0, 100, true) || 0, fat_100: num(p.fat_100, "fat", 0, 100, true) || 0,
        approx: p.approx ? 1 : 0, portions: (p.portions || []).filter(x => x && x[0]).map(x => [text(x[0], "portion", 80), num(x[1], "grams", 0.1, 20000)]), active: deleted ? 0 : 1 };
      const existing = db.all("foods").find(f => f.client_id === cid) || (row.source === "off" && row.source_id ? db.all("foods").find(f => f.source === "off" && f.source_id === row.source_id) : null);
      if (existing) { db.update("foods", existing.id, Object.assign(row, { id: existing.id, times_used: existing.times_used || 0, last_used: existing.last_used || null, portions: row.portions.length ? row.portions : existing.portions })); return { ok: true, id: existing.id }; }
      const id = (row.source === "off" && row.barcode ? "off:" + row.barcode : "c:" + cid);
      db.insert("foods", Object.assign(row, { id, times_used: 0, last_used: null }));
      return { ok: true, id };
    }
    if (type === "food_log") {
      const ex = db.get("food_logs", cid);
      if (deleted) { if (ex) db.remove("food_logs", cid); return { ok: true }; }
      const date = dateV(p.date || (ex && ex.date) || today());
      const slot = choice(p.slot || (ex && ex.slot) || "snack", "slot", SLOTS);
      let foodId = p.food_id ?? (ex && ex.food_id);
      if (foodId == null && p.food_client_id) { const f = db.all("foods").find(x => x.client_id === p.food_client_id); if (f) foodId = f.id; }
      const food = Store.foodById(foodId);
      if (!food) throw new BadRequest("Pick a food");
      const grams = num(p.grams ?? (ex && ex.grams), "amount", 0.1, 20000);
      const qty = num(p.qty ?? (ex && ex.qty) ?? 1, "quantity", 0.01, 1000, true) || 1;
      const vals = E.foodLogValues(food, grams, 1);
      const row = { client_id: cid, date, slot, food_id: foodId, grams, portion_label: "portion_label" in p ? text(p.portion_label, "portion", 80) : (ex ? ex.portion_label : null), qty, kcal: vals.kcal, protein: vals.protein, carb: vals.carb, fat: vals.fat };
      if (ex) db.update("food_logs", cid, row); else { db.insert("food_logs", row); Store.noteFoodUsed(foodId, date); }
      return { ok: true, id: cid };
    }
    if (type === "body" || type === "daily") {
      const coll = type === "body" ? "body_logs" : "daily_logs";
      const ex = db.get(coll, cid);
      if (deleted) { if (ex) db.remove(coll, cid); return { ok: true }; }
      const date = dateV(p.date || (ex && ex.date) || today());
      const fields = { date };
      if (type === "body") {
        if ("weight_kg" in p) fields.weight_kg = num(p.weight_kg, "weight", 20, 400, true);
        ["waist_cm", "chest_cm", "arm_cm", "hip_cm", "thigh_cm"].forEach(k => { if (k in p) fields[k] = num(p[k], k.replace("_cm", ""), 10, 300, true); });
        if ("note" in p) fields.note = text(p.note, "note", 500);
      } else {
        if ("water_ml" in p) fields.water_ml = num(p.water_ml, "water", 0, 20000, true);
        if ("sleep_h" in p) fields.sleep_h = num(p.sleep_h, "sleep", 0, 24, true);
        if ("steps" in p) fields.steps = int(p.steps, "steps", 0, 200000, true);
      }
      if (ex) db.update(coll, cid, fields); else db.insert(coll, Object.assign({ client_id: cid }, fields));
      return { ok: true, id: cid };
    }
    throw new BadRequest(`unknown op type ${type}`);
  }
  function updateSessionStatus(sessionId, date) {
    const s = db.get("plan_sessions", sessionId); if (!s) return;
    const done = db.all("workouts").some(w => w.session_id === sessionId && w.ended_at);
    if (done) db.update("plan_sessions", sessionId, { status: "done" });
    else if (s.status === "done") db.update("plan_sessions", sessionId, { status: (date || s.date) >= today() ? "planned" : "skipped" });
  }
  function applySync(body) {
    const order = { workout: 0, food: 1, set: 2, cardio: 3, food_log: 4, body: 5, daily: 6 };
    const ops = (body.ops || []).slice().sort((a, b) => (order[a.type] ?? 9) - (order[b.type] ?? 9) || String(a.at || "").localeCompare(String(b.at || "")));
    const applied = [], rejected = [], ids = {};
    ops.forEach(op => { try { const r = applyOp(op.type, String(op.client_id || ""), op.payload); applied.push(op.client_id); if (r.id != null) ids[op.client_id] = r.id; } catch (e) { rejected.push({ client_id: op.client_id, error: e.message, retry: false }); } });
    return { applied, rejected, ids, server_time: E.nowIso() };
  }

  /* ---------------------------------------------------- views */
  function planReady(d) { const s = settings(); E.ensurePlanThrough(db, d, s, PROG, EX_BY_KEY); E.sweepMissed(db, today()); }
  const bodyLogPairs = () => E.bodyLogs(db);
  const exerciseKcalOn = d => db.all("workouts").filter(w => w.date === d && w.ended_at).reduce((a, w) => a + (w.kcal_wearable || w.kcal_est || 0), 0);
  function foodDay(d) {
    const slots = {}; SLOTS.forEach(s => { slots[s] = []; });
    const totals = { kcal: 0, protein: 0, carb: 0, fat: 0 };
    db.all("food_logs").filter(f => f.date === d).sort((a, b) => a.slot.localeCompare(b.slot) || String(a.client_id).localeCompare(String(b.client_id))).forEach(f => {
      const food = Store.foodById(f.food_id) || {};
      const row = Object.assign({}, f, { name: food.name, brand: food.brand, unit: food.unit, approx: food.approx, source: food.source });
      (slots[f.slot] = slots[f.slot] || []).push(row);
      Object.keys(totals).forEach(k => { totals[k] += +(f[k] || 0); });
    });
    return { date: d, slots, totals: Object.fromEntries(Object.entries(totals).map(([k, v]) => [k, Math.round(v * 10) / 10])) };
  }
  function weightBlock(s, d) {
    const logs = bodyLogPairs();
    const t = E.trendWeight(logs, d, s.start_weight_kg);
    const latest = db.all("body_logs").filter(b => b.weight_kg != null).sort((a, b) => b.date.localeCompare(a.date))[0];
    const n14 = db.all("body_logs").filter(b => b.weight_kg != null && b.date >= E.addDays(d, -13)).length;
    const pace = E.paceWeight(s, d);
    return { trend: t.weight, source: t.source, latest: latest ? { date: latest.date, weight_kg: latest.weight_kg } : null, pace, verdict: E.paceVerdict(t.weight, pace, n14, s.goal_start_weight, s.target_weight_kg), logs_last_14: n14, weekly_pace: E.weeklyPace(s) };
  }
  function splitsPublic() { return Object.entries(PROG.splits || {}).map(([key, v]) => ({ key, name: v.name, description: v.description, days: Object.keys(v.templates || {}).map(Number) })); }
  function buildState() {
    const s = settings(), d = today();
    planReady(d);
    const wb = weightBlock(s, d);
    const fd = foodDay(d);
    const tg = E.targets(s, wb.trend, d, exerciseKcalOn(d), fd.totals.kcal);
    const daily = db.all("daily_logs").find(x => x.date === d) || { water_ml: null, sleep_h: null, steps: null };
    const week = E.weekView(db, d, d, s, PROG, EX_BY_KEY);
    let sessionToday = null; const strip = [];
    if (week) week.sessions.forEach(x => { strip.push({ id: x.id, date: x.date, kind: x.kind, title: x.title, status: x.status, workout: x.workout }); if (x.date === d) sessionToday = x; });
    const inProgress = db.all("workouts").filter(w => !w.ended_at).sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)))[0] || null;
    const last = db.all("workouts").filter(w => w.ended_at).sort((a, b) => b.date.localeCompare(a.date) || String(b.ended_at).localeCompare(String(a.ended_at)))[0];
    const adh = E.adherenceByWeek(db);
    let streak = 0;
    for (let i = adh.length - 1; i >= 0; i--) { const wk = adh[i]; if (wk.week > d) continue; if (wk.planned && wk.done / wk.planned >= 0.8) streak++; else if (wk.week <= E.addDays(d, -7)) break; }
    return { app: "fitness-tracker", version: VERSION, build: VERSION, today: d, settings: s, splits: splitsPublic(), profile_complete: E.profileComplete(s), targets: tg, weight: wb, food: fd,
      daily: { water_ml: daily.water_ml, sleep_h: daily.sleep_h, steps: daily.steps }, session_today: sessionToday, week, strip,
      in_progress: inProgress ? { client_id: inProgress.client_id, session_id: inProgress.session_id, date: inProgress.date, started_at: inProgress.started_at } : null,
      recent_prs: last ? E.prsForWorkout(db, last.client_id, s) : [], weeks_streak: streak, phone: null, exercises: db.all("exercises").map(exPublic) };
  }
  function todayPayload() {
    const s = settings(), d = today();
    planReady(E.addDays(d, 6));
    const bw = E.bodyweightOn(db, d, s);
    const sessions = db.all("plan_sessions").filter(x => x.date >= d && x.date <= E.addDays(d, 6)).sort((a, b) => a.date.localeCompare(b.date)).map(x => E.sessionView(db, x, d, s, PROG, EX_BY_KEY, bw));
    const bests = {};
    sessions.forEach(x => x.items.forEach(it => { if (it.exercise_id && !bests[it.exercise_id]) { const ex = db.get("exercises", it.exercise_id); if (ex && ex.pattern !== "mobility" && !ex.pattern.startsWith("cardio")) bests[String(it.exercise_id)] = E.bestsForExercise(db, it.exercise_id, ex, bw); } }));
    const ip = db.all("workouts").filter(w => !w.ended_at).sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)))[0];
    return { date: d, sessions, bests, bodyweight: bw, in_progress: ip ? workoutDetail(ip.client_id) : null, protocols: PROG.protocols || [], rest_default_sec: s.rest_default_sec || 90, warmup_moves: PROG.warmup_moves, cooldown_stretches: PROG.cooldown_stretches };
  }
  function workoutDetail(cid) {
    const w = db.get("workouts", cid); if (!w) throw new BadRequest("That workout does not exist", 404);
    const s = settings();
    const out = Object.assign({}, w);
    out.sets = db.all("set_logs").filter(x => x.workout_client_id === cid).sort((a, b) => a.exercise_id - b.exercise_id || a.set_no - b.set_no).map(x => { const ex = db.get("exercises", x.exercise_id) || {}; return Object.assign({}, x, { exercise_name: ex.name, exercise_key: ex.key }); });
    out.cardio = db.all("cardio_logs").filter(x => x.workout_client_id === cid).map(x => { const ex = x.exercise_id ? db.get("exercises", x.exercise_id) : null; return Object.assign({}, x, { exercise_name: ex ? ex.name : null }); });
    out.session = w.session_id ? db.get("plan_sessions", w.session_id) : null;
    out.prs = w.ended_at ? E.prsForWorkout(db, cid, s) : [];
    out.kcal_used = w.kcal_wearable || w.kcal_est;
    return out;
  }
  function progressPayload(days) {
    const s = settings(), d = today(), since = E.addDays(d, -days);
    const logs = bodyLogPairs(), cache = {};
    const bwByDate = ds => { if (!(ds in cache)) cache[ds] = E.trendWeight(logs, ds, s.start_weight_kg).weight || 80; return cache[ds]; };
    const block1 = db.all("blocks").find(b => b.block_no === 1);
    const week1ids = block1 ? new Set(db.all("plan_weeks").filter(w => w.block_id === block1.id).map(w => w.id)) : new Set();
    const mainIds = Array.from(new Set(db.all("plan_items").filter(i => i.slot_key === "main1" && i.exercise_id && week1ids.has((db.get("plan_sessions", i.session_id) || {}).week_id)).map(i => i.exercise_id)));
    const baselineWeeks = new Set(db.all("plan_weeks").filter(w => block1 && w.block_id === block1.id && w.week_no <= 3).map(w => w.start_date));
    const done = new Map(db.all("workouts").filter(w => w.ended_at).map(w => [w.client_id, w]));
    const trained = Array.from(new Set(db.all("set_logs").filter(x => !x.is_warmup && done.has(x.workout_client_id)).map(x => x.exercise_id)));
    const strength = [];
    mainIds.concat(trained.filter(t => !mainIds.includes(t))).forEach(id => {
      const ex = db.get("exercises", id); if (!ex || ex.pattern.startsWith("cardio") || ex.pattern === "mobility" || ex.timed) return;
      const series = E.weeklyE1rm(db, id, bwByDate); if (!series.length) return;
      const recent = series.filter(p => p.week >= E.addDays(d, -28) && !p.low_confidence).map(p => p.e1rm);
      strength.push({ exercise_id: id, name: ex.name, main: mainIds.includes(id), series, relative: recent.length ? Math.round(Math.max(...recent) / bwByDate(d) * 100) / 100 : null });
    });
    const sessions = db.all("workouts").filter(w => w.ended_at && w.date >= since).sort((a, b) => a.date.localeCompare(b.date)).map(w => { const ps = w.session_id ? db.get("plan_sessions", w.session_id) : null; return { client_id: w.client_id, date: w.date, effort: w.effort, kcal_est: w.kcal_est, kcal_wearable: w.kcal_wearable, volume: w.volume, work_sets: w.work_sets, hard_sets: w.hard_sets, kind: ps ? ps.kind : null, title: ps ? ps.title : null }; });
    const weights = db.all("body_logs").sort((a, b) => a.date.localeCompare(b.date)).map(b => ({ date: b.date, weight_kg: b.weight_kg, waist_cm: b.waist_cm, chest_cm: b.chest_cm, arm_cm: b.arm_cm, hip_cm: b.hip_cm, thigh_cm: b.thigh_cm, note: b.note }));
    const trend = weights.filter(w => w.weight_kg != null).map(w => ({ date: w.date, trend: E.trendWeight(logs, w.date, s.start_weight_kg).weight }));
    const pace = s.goal_start_date && s.target_date ? [{ date: s.goal_start_date, weight: s.goal_start_weight }, { date: s.target_date, weight: s.target_weight_kg }] : null;
    const eaten = {}, daysLogged = {}, burned = {};
    db.all("food_logs").filter(f => f.date >= since).forEach(f => { const wk = E.mondayOf(f.date); eaten[wk] = (eaten[wk] || 0) + (f.kcal || 0); (daysLogged[wk] = daysLogged[wk] || new Set()).add(f.date); });
    db.all("workouts").filter(w => w.ended_at && w.date >= since).forEach(w => { const wk = E.mondayOf(w.date); burned[wk] = (burned[wk] || 0) + (w.kcal_wearable || w.kcal_est || 0); });
    const weeks = Array.from(new Set(Object.keys(eaten).concat(Object.keys(burned)))).sort();
    return { since, strength, index: mainIds.length ? E.strengthIndex(db, mainIds, bwByDate, baselineWeeks) : [], volume: E.weeklyMuscleSets(db, since), sessions, weights, trend, pace,
      calories: weeks.map(w => ({ week: w, eaten: Math.round(eaten[w] || 0), burned: Math.round(burned[w] || 0), days: daysLogged[w] ? daysLogged[w].size : 0 })), adherence: E.adherenceByWeek(db), targets: { weekly_pace: E.weeklyPace(s) } };
  }
  function historyPayload(q) {
    const frm = q.from || E.addDays(today(), -90), to = q.to || today(), t = (q.q || "").trim().toLowerCase();
    let workouts = db.all("workouts").filter(w => w.date >= frm && w.date <= to).sort((a, b) => b.date.localeCompare(a.date) || String(b.started_at).localeCompare(String(a.started_at))).map(w => { const ps = w.session_id ? db.get("plan_sessions", w.session_id) : null; return Object.assign({}, w, { kind: ps ? ps.kind : null, title: ps ? ps.title : null }); });
    if (t) workouts = workouts.filter(w => { const names = db.all("set_logs").filter(x => x.workout_client_id === w.client_id).map(x => (db.get("exercises", x.exercise_id) || {}).name || "").join(" "); return [w.title || "", w.notes || "", names].join(" ").toLowerCase().includes(t); });
    const fd = {};
    db.all("food_logs").filter(f => f.date >= frm && f.date <= to).forEach(f => { const o = fd[f.date] = fd[f.date] || { date: f.date, kcal: 0, protein: 0, carb: 0, fat: 0, items: 0 }; o.kcal += f.kcal || 0; o.protein += f.protein || 0; o.carb += f.carb || 0; o.fat += f.fat || 0; o.items++; });
    const food_days = Object.values(fd).map(o => Object.assign(o, { kcal: Math.round(o.kcal), protein: Math.round(o.protein), carb: Math.round(o.carb), fat: Math.round(o.fat) })).sort((a, b) => b.date.localeCompare(a.date));
    const body = db.all("body_logs").filter(b => b.date >= frm && b.date <= to).sort((a, b) => b.date.localeCompare(a.date));
    return { from: frm, to, workouts, food_days, body };
  }

  /* ---------------------------------------------------- foods, meals */
  function foodsList() {
    const fields = ["id", "name", "brand", "unit", "source", "kcal_100", "protein_100", "carb_100", "fat_100", "approx", "times_used", "last_used", "portions", "search", "barcode"];
    return { fields, foods: Store.foodsAll().map(f => fields.map(k => f[k] ?? null)) };
  }
  function foodRow(id) { const f = Store.foodById(id); if (!f) throw new BadRequest("That food does not exist", 404); return Object.assign({}, f); }
  function updateFood(id, body) {
    const f = db.get("foods", id); if (!f) throw new BadRequest("Only foods you added can be edited", 400);
    const fields = {};
    if ("name" in body) fields.name = text(body.name, "name", 120, false);
    if ("brand" in body) fields.brand = text(body.brand, "brand", 60);
    [["kcal_100", 1000], ["protein_100", 100], ["carb_100", 100], ["fat_100", 100]].forEach(([k, hi]) => { if (k in body) fields[k] = num(body[k], k, 0, hi); });
    if ("unit" in body) fields.unit = choice(body.unit, "unit", ["g", "ml"]);
    if ("active" in body) fields.active = body.active ? 1 : 0;
    if ("portions" in body && Array.isArray(body.portions)) fields.portions = body.portions.filter(x => x && x[0]).map(x => [text(x[0], "portion", 80), num(x[1], "grams", 0.1, 20000)]);
    db.update("foods", id, fields); return foodRow(id);
  }
  const mealsList = () => db.all("meals").filter(m => m.active !== 0).sort((a, b) => a.name.localeCompare(b.name)).map(m => {
    const items = (m.items || []).map(i => Object.assign({}, i, Store.foodById(i.food_id) || {}));
    return { id: m.id, name: m.name, items, kcal: Math.round(items.reduce((a, i) => a + (i.kcal_100 || 0) * i.grams / 100, 0)), protein: Math.round(items.reduce((a, i) => a + (i.protein_100 || 0) * i.grams / 100, 0)) };
  });
  function saveMeal(body) {
    const name = text(body.name, "name", 60, false);
    let items = [];
    if (body.from_date && body.slot) items = db.all("food_logs").filter(f => f.date === dateV(body.from_date) && f.slot === choice(body.slot, "slot", SLOTS) && f.food_id != null).map(f => ({ food_id: f.food_id, grams: f.grams, portion_label: f.portion_label, qty: f.qty }));
    (body.items || []).forEach(i => items.push({ food_id: i.food_id, grams: num(i.grams, "grams", 0.1, 20000), portion_label: text(i.portion_label, "portion", 80), qty: num(i.qty, "qty", 0.01, 1000, true) || 1 }));
    if (!items.length) throw new BadRequest("Nothing to save: that slot is empty");
    return db.insert("meals", { name, items, active: 1 }).id;
  }
  function addMeal(body) {
    const m = db.get("meals", int(body.meal_id, "meal_id", 1)); if (!m || !(m.items || []).length) throw new BadRequest("That meal is empty or missing", 404);
    const d = dateV(body.date || today()), slot = choice(body.slot || "snack", "slot", SLOTS);
    m.items.forEach(i => applyOp("food_log", crypto.randomUUID(), { date: d, slot, food_id: i.food_id, grams: i.grams, portion_label: i.portion_label, qty: i.qty }));
    return foodDay(d);
  }
  function copySlot(body) {
    const to = dateV(body.to_date || today()), slot = choice(body.slot || "breakfast", "slot", SLOTS);
    const from = dateV(body.from_date || E.addDays(to, -1));
    const rows = db.all("food_logs").filter(f => f.date === from && f.slot === slot);
    if (!rows.length) throw new BadRequest("Nothing to copy", 404);
    rows.forEach(r => applyOp("food_log", crypto.randomUUID(), { date: to, slot, food_id: r.food_id, grams: r.grams, portion_label: r.portion_label, qty: r.qty }));
    return foodDay(to);
  }

  /* ---------------------------------------------------- Open Food Facts from the phone */
  const OFF_FIELDS = "code,product_name,product_name_en,brands,quantity,serving_size,nutriments,countries_tags";
  const offCache = {};
  async function offGet(url) {
    const now = Date.now();
    if (offCache[url] && offCache[url].t > now) return offCache[url].v;
    let r;
    const native = window.Android && window.Android.fetchJson ? androidFetch : null;
    if (native) { const v = await native(url); offCache[url] = { t: now + 20000, v }; return v; }
    try { r = await fetch(url, { headers: { Accept: "application/json" } }); }
    catch (e) { throw new BadRequest("Could not reach Open Food Facts. Check the internet connection.", 502); }
    if (r.status === 429) throw new BadRequest("Open Food Facts is rate limiting us. Try again in half a minute.", 503);
    if (r.status === 404) return { status: 0 };
    if (r.status >= 500) throw new BadRequest("Open Food Facts is busy right now. Try again in a minute, or add the food yourself with New food.", 503);
    if (!r.ok) throw new BadRequest(`Open Food Facts answered ${r.status}.`, 502);
    const v = await r.json(); offCache[url] = { t: now + 20000, v }; return v;
  }
  let androidReq = 0; const androidWaiting = {};
  window.__androidFetchDone = (id, ok, payload) => { const w = androidWaiting[id]; if (!w) return; delete androidWaiting[id]; if (ok) { try { w.res(JSON.parse(payload)); } catch (e) { w.rej(new BadRequest("Open Food Facts sent something that was not JSON.", 502)); } } else w.rej(new BadRequest(payload || "Could not reach Open Food Facts.", 502)); };
  function androidFetch(url) { return new Promise((res, rej) => { const id = ++androidReq; androidWaiting[id] = { res, rej }; window.Android.fetchJson(id, url); setTimeout(() => { if (androidWaiting[id]) { delete androidWaiting[id]; rej(new BadRequest("Open Food Facts took too long.", 502)); } }, 15000); }); }
  const parseServing = s => { const m = /(\d+(?:[.,]\d+)?)\s*(g|ml)\b/i.exec(String(s || "")); return m ? parseFloat(m[1].replace(",", ".")) : null; };
  function mapOff(p) {
    if (!p) return null;
    const n = p.nutriments || {}, name = (p.product_name_en || p.product_name || "").trim(); if (!name) return null;
    const numv = v => (v == null || v === "" || isNaN(+v)) ? null : +v;
    let kcal = numv(n["energy-kcal_100g"]), approx = 0;
    const protein = numv(n.proteins_100g) || 0, carb = numv(n.carbohydrates_100g) || 0, fat = numv(n.fat_100g) || 0;
    if (kcal == null) { const kj = numv(n.energy_100g) ?? numv(n["energy-kj_100g"]); if (kj != null) kcal = kj / 4.184; else if (["proteins_100g", "carbohydrates_100g", "fat_100g"].some(k => k in n)) { kcal = 4 * protein + 4 * carb + 9 * fat; approx = 1; } else return null; }
    const brands = p.brands || ""; const brand = Array.isArray(brands) ? (String(brands[0] || "").trim() || null) : (String(brands).split(",")[0].trim() || null);
    const grams = parseServing(p.serving_size);
    const unit = /\bml\b|\bl\b|litre|liter/i.test(String(p.quantity || "") + " " + String(p.serving_size || "")) ? "ml" : "g";
    const r1 = x => Math.round(x * 10) / 10;
    return { name: name.slice(0, 120), brand, unit, source: "off", source_id: String(p.code || ""), barcode: String(p.code || "") || null, kcal_100: r1(kcal), protein_100: r1(protein), carb_100: r1(carb), fat_100: r1(fat), approx, portions: grams ? [[`1 serving (${String(p.serving_size).trim()})`, grams]] : [], quantity: p.quantity };
  }
  async function offSearch(q) {
    const terms = String(q || "").trim(); if (!terms) return [];
    const results = [], seen = new Set();
    const add = list => (list || []).forEach(p => { const c = mapOff(p); if (c && !seen.has(c.source_id)) { seen.add(c.source_id); results.push(c); } });
    if (window.Android && window.Android.fetchJson) {
      try {
        add((await offGet(`https://search.openfoodfacts.org/search?q=${encodeURIComponent(terms + ' countries_tags:"en:new-zealand"')}&page_size=20&fields=${OFF_FIELDS}`)).hits);
        if (results.length < 3) add((await offGet(`https://search.openfoodfacts.org/search?q=${encodeURIComponent(terms)}&page_size=20&fields=${OFF_FIELDS}`)).hits);
        return results;
      } catch (e) { /* fall through to the classic endpoint */ }
    }
    const legacy = host => `https://${host}.openfoodfacts.org/cgi/search.pl?search_terms=${encodeURIComponent(terms)}&search_simple=1&action=process&json=1&page_size=20&sort_by=unique_scans_n&fields=${OFF_FIELDS}`;
    let lastErr = null;
    for (const host of ["nz", "world"]) {
      for (let attempt = 0; attempt < 2; attempt++) {
        try { add((await offGet(legacy(host))).products); lastErr = null; break; }
        catch (e) { lastErr = e; if (e.code !== 503) break; await new Promise(r => setTimeout(r, 1500)); }
      }
      if (results.length >= 3) break;
    }
    if (!results.length && lastErr) throw lastErr;
    return results;
  }
  async function offBarcode(code) {
    code = String(code || "").replace(/\D/g, ""); if (!code) throw new BadRequest("That is not a barcode.");
    const p = await offGet(`https://world.openfoodfacts.org/api/v2/product/${code}.json?fields=${OFF_FIELDS}`);
    if (p.status !== 1 || !p.product) return null;
    return mapOff(p.product);
  }

  /* ---------------------------------------------------- settings, exercises */
  const SETTING_KEYS = Object.keys(E.NUTRITION_DEFAULTS).concat(Object.keys(E.TRAIN_DEFAULTS), ["split", "stay_running", "keep_awake", "theme", "contact_email", "display_name", "rest_default_sec"]);
  const TRAINING_KEYS = ["train_days", "session_minutes", "experience", "cardio_kit", "main1_swap_every_blocks", "split"];
  function updateSettings(patch) {
    if (!patch || typeof patch !== "object") throw new BadRequest("Send an object of settings");
    const s = settings();
    let goal = false, training = false;
    Object.entries(patch).forEach(([k, v]) => {
      if (!SETTING_KEYS.includes(k)) throw new BadRequest(`${k} is not a setting`);
      if (k === "height_cm") v = num(v, "height", 100, 250, true);
      else if (["start_weight_kg", "target_weight_kg", "goal_start_weight"].includes(k)) v = num(v, k.replace(/_/g, " "), 20, 400, true);
      else if (["birth_date", "target_date", "goal_start_date", "programme_start"].includes(k)) v = dateV(v, k, true);
      else if (k === "sex") v = choice(v, "sex", ["m", "f"]);
      else if (k === "neat_factor") v = num(v, "activity factor", 1, 2);
      else if (["deficit_cap", "surplus_cap"].includes(k)) v = num(v, k, 0, 2000);
      else if (["protein_g_per_kg", "fat_g_per_kg", "fat_floor_g_per_kg"].includes(k)) v = num(v, k, 0.2, 4);
      else if (["carb_floor_g", "kcal_floor", "water_target_ml", "sleep_target_h", "steps_target", "rest_default_sec", "session_minutes"].includes(k)) v = num(v, k, 0, 100000, true);
      else if (k === "train_days") { if (!Array.isArray(v) || !v.length) throw new BadRequest("Pick at least one training day"); v = Array.from(new Set(v.map(Number).filter(x => x >= 1 && x <= 7))).sort((a, b) => a - b); if (v.length < 3) throw new BadRequest("Pick at least three training days"); }
      else if (k === "cardio_kit") { if (!Array.isArray(v)) throw new BadRequest("cardio_kit must be a list"); v = v.filter(m => ["treadmill", "bike", "rower"].includes(m)); if (!v.length) throw new BadRequest("Keep at least one cardio machine"); }
      else if (k === "experience") v = choice(v, "experience", Object.keys(PROG.rep_schemes));
      else if (k === "split") v = choice(v, "split", Object.keys(PROG.splits || { upper_lower: 1 }));
      else if (k === "main1_swap_every_blocks") v = int(v, k, 1, 6);
      else if (k === "stay_running" || k === "keep_awake") v = !!v;
      else if (["theme", "contact_email", "display_name"].includes(k)) v = text(v, k, 120);
      if (JSON.stringify(s[k]) !== JSON.stringify(v)) { if (["target_weight_kg", "target_date"].includes(k)) goal = true; if (TRAINING_KEYS.includes(k)) training = true; }
      db.setSetting(k, v); s[k] = v;
    });
    if (goal && s.target_weight_kg) { const t = E.trendWeight(bodyLogPairs(), today(), s.start_weight_kg).weight || s.start_weight_kg; db.setSetting("goal_start_weight", t); db.setSetting("goal_start_date", today()); s.goal_start_weight = t; s.goal_start_date = today(); }
    if ("start_weight_kg" in patch && !s.goal_start_weight && s.start_weight_kg) { db.setSetting("goal_start_weight", s.start_weight_kg); db.setSetting("goal_start_date", today()); }
    if (training && db.all("plan_weeks").length) E.regenerateFrom(db, today(), settings(), PROG, EX_BY_KEY);
    return settings();
  }
  const PATTERNS = ["squat", "hinge", "lunge", "horizontal_push", "vertical_push", "horizontal_pull", "vertical_pull", "shoulder_iso", "triceps", "biceps", "rear_delt", "quad_iso", "ham_iso", "glute", "calf", "core", "mobility"];
  const MUSCLES = ["chest", "shoulders", "back", "biceps", "triceps", "quads", "hamstrings", "glutes", "calves", "core"];
  const EQUIP = ["barbell", "trap_bar", "dumbbell", "cable", "machine", "assisted", "bodyweight", "band", "none"];
  function createExercise(b) {
    const row = db.insert("exercises", { key: "", name: text(b.name, "name", 80, false), pattern: choice(b.pattern, "pattern", PATTERNS), primary_muscle: choice(b.primary_muscle, "primary muscle", MUSCLES), secondary_muscles: b.secondary_muscles || [], equipment: choice(b.equipment || "machine", "equipment", EQUIP),
      per_hand: b.per_hand ? 1 : 0, timed: b.timed ? 1 : 0, unilateral: b.unilateral ? 1 : 0, bodyweight_fraction: num(b.bodyweight_fraction, "bodyweight fraction", 0, 1, true) || 0, increment_kg: num(b.increment_kg, "increment", 0.5, 20, true), min_load_kg: num(b.min_load_kg, "minimum load", 0, 100, true), variation_of: null, carry: null, mets: null, cues: (b.cues || []).filter(Boolean).slice(0, 3).map(c => text(c, "cue", 160)), is_custom: 1, active: 1 });
    db.update("exercises", row.id, { key: "custom_" + row.id }); refreshExercises(); return exPublic(db.get("exercises", row.id));
  }
  function updateExercise(id, b) {
    if (!db.get("exercises", id)) throw new BadRequest("That exercise does not exist", 404);
    const f = {};
    if ("name" in b) f.name = text(b.name, "name", 80, false);
    if ("cues" in b) f.cues = (b.cues || []).filter(Boolean).slice(0, 3).map(c => text(c, "cue", 160));
    if ("active" in b) f.active = b.active ? 1 : 0;
    if ("increment_kg" in b) f.increment_kg = num(b.increment_kg, "increment", 0.5, 20, true);
    if ("min_load_kg" in b) f.min_load_kg = num(b.min_load_kg, "minimum load", 0, 100, true);
    if ("equipment" in b) f.equipment = choice(b.equipment, "equipment", EQUIP);
    db.update("exercises", id, f); refreshExercises(); return exPublic(db.get("exercises", id));
  }

  /* ---------------------------------------------------- exports */
  function exportCsv(what) {
    const esc = v => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const rows = [];
    if (what === "food") {
      rows.push(["date", "slot", "food", "brand", "grams", "portion", "qty", "kcal", "protein", "carb", "fat"]);
      db.all("food_logs").sort((a, b) => a.date.localeCompare(b.date) || a.slot.localeCompare(b.slot)).forEach(f => { const fo = Store.foodById(f.food_id) || {}; rows.push([f.date, f.slot, fo.name, fo.brand, f.grams, f.portion_label, f.qty, f.kcal, f.protein, f.carb, f.fat]); });
    } else if (what === "body") {
      rows.push(["date", "weight_kg", "waist_cm", "chest_cm", "arm_cm", "hip_cm", "thigh_cm", "water_ml", "sleep_h", "steps", "note"]);
      db.all("body_logs").sort((a, b) => a.date.localeCompare(b.date)).forEach(b => { const d = db.all("daily_logs").find(x => x.date === b.date) || {}; rows.push([b.date, b.weight_kg, b.waist_cm, b.chest_cm, b.arm_cm, b.hip_cm, b.thigh_cm, d.water_ml, d.sleep_h, d.steps, b.note]); });
    } else {
      rows.push(["date", "session", "exercise", "set", "reps", "weight_kg", "rpe", "warmup", "done_at", "workout_effort", "workout_kcal"]);
      const ws = new Map(db.all("workouts").map(w => [w.client_id, w]));
      db.all("set_logs").filter(s => ws.has(s.workout_client_id)).sort((a, b) => ws.get(a.workout_client_id).date.localeCompare(ws.get(b.workout_client_id).date) || a.exercise_id - b.exercise_id || a.set_no - b.set_no)
        .forEach(s => { const w = ws.get(s.workout_client_id), ps = w.session_id ? db.get("plan_sessions", w.session_id) : null, ex = db.get("exercises", s.exercise_id) || {}; rows.push([w.date, ps ? ps.title : "", ex.name, s.set_no, s.reps, s.weight_kg, s.rpe, s.is_warmup, s.done_at, w.effort, w.kcal_wearable || w.kcal_est]); });
    }
    return rows.map(r => r.map(esc).join(",")).join("\n") + "\n";
  }

  /* ---------------------------------------------------- the dispatcher */
  const parse = path => { const u = new URL(path, "http://local/"); const q = {}; u.searchParams.forEach((v, k) => { q[k] = v; }); return { p: u.pathname.replace(/\/$/, "") || "/", q }; };
  async function call(method, path, body) {
    const { p, q } = parse(path);
    if (!p.startsWith("/api/")) throw new BadRequest("not found", 404);
    const api = p.slice(5);
    if (method === "GET") {
      if (api === "ping") return { ok: true, app: "fitness-tracker", build: VERSION, version: VERSION };
      if (api === "state") return buildState();
      if (api === "today") return todayPayload();
      if (api === "settings") return settings();
      if (api === "exercises") return db.all("exercises").map(exPublic);
      if (api === "plan/week") { let d = q.date ? dateV(q.date) : today(); if (d > E.addDays(today(), 28)) d = E.addDays(today(), 28); planReady(d); return E.weekView(db, d, today(), settings(), PROG, EX_BY_KEY); }
      if (api.startsWith("workouts/")) return workoutDetail(api.slice(9));
      if (api === "foods/list") return foodsList();
      if (api === "foods/online") return offSearch(q.q || "");
      if (api.startsWith("foods/barcode/")) { const r = await offBarcode(api.slice(14)); if (!r) throw new BadRequest("No product with that barcode on Open Food Facts", 404); return r; }
      if (api.startsWith("foods/")) return foodRow(api.slice(6));
      if (api === "meals") return mealsList();
      if (api === "food/day") return foodDay(dateV(q.date || today()));
      if (api === "progress") return progressPayload(int(q.days || 90, "days", 7, 3650));
      if (api === "history") return historyPayload(q);
      if (api === "export.csv") return exportCsv(q.what || "sets");
      if (api === "backup.json") return Store.backup();
      throw new BadRequest("not found", 404);
    }
    body = body || {};
    if (method === "POST") {
      if (api === "sync") return applySync(body);
      if (api === "workouts") {
        const cid = body.client_id || crypto.randomUUID(), sid = int(body.session_id, "session_id", 1, null, true);
        if (sid) { const s = db.get("plan_sessions", sid); if (!s) throw new BadRequest("That session is not in the plan", 404); if (s.date !== today()) E.moveSession(db, sid, today()); }
        applyOp("workout", cid, { session_id: sid, date: today(), started_at: body.started_at || E.nowIso() });
        return workoutDetail(cid);
      }
      if (api === "sets") { const cid = body.client_id || crypto.randomUUID(); const r = applyOp("set", cid, body); return { ok: true, client_id: cid, id: r.id }; }
      if (api === "cardio") { const cid = body.client_id || crypto.randomUUID(); const r = applyOp("cardio", cid, body); return { ok: true, client_id: cid, id: r.id }; }
      if (api === "food_logs") { applyOp("food_log", body.client_id || crypto.randomUUID(), body); return foodDay(body.date || today()); }
      if (api === "food_logs/meal") return addMeal(body);
      if (api === "food_logs/copy") return copySlot(body);
      if (api === "body") { const d = dateV(body.date || today()); applyOp("body", body.client_id || "body-" + d, Object.assign({}, body, { date: d })); return { ok: true }; }
      if (api === "daily") { const d = dateV(body.date || today()); applyOp("daily", body.client_id || "daily-" + d, Object.assign({}, body, { date: d })); return { ok: true }; }
      if (api === "foods") { const r = applyOp("food", body.client_id || crypto.randomUUID(), body); return foodRow(r.id); }
      if (api === "meals") { const id = saveMeal(body); return { ok: true, id, meals: mealsList() }; }
      if (api === "exercises") return createExercise(body);
      if (api === "plan/shuffle") { E.shuffleWeek(db, int(body.week_id, "week_id", 1), settings(), PROG, EX_BY_KEY, today()); return { ok: true }; }
      if (api === "plan/regenerate") { E.regenerateFrom(db, today(), settings(), PROG, EX_BY_KEY); return { ok: true }; }
      if (api === "plan/swap") { const ex = E.swapItem(db, int(body.item_id, "item_id", 1), body.exercise_key || null, PROG, EX_BY_KEY); return { ok: true, exercise: exPublic(ex) }; }
      if (api === "plan/move") { E.moveSession(db, int(body.session_id, "session_id", 1), today()); return { ok: true }; }
      if (api === "plan/rest") { E.markRest(db, int(body.session_id, "session_id", 1)); return { ok: true }; }
      if (api === "restore") { await Store.restore(body); refreshExercises(); return { ok: true }; }
      if (api === "wipe") { await Store.wipe(); refreshExercises(); return { ok: true }; }
      throw new BadRequest("not found", 404);
    }
    if (method === "PUT") {
      if (api === "settings") return updateSettings(body);
      if (api.startsWith("workouts/")) { const cid = api.slice(9); applyOp("workout", cid, body); return workoutDetail(cid); }
      if (api.startsWith("foods/")) return updateFood(api.slice(6), body);
      if (api.startsWith("exercises/")) return updateExercise(+api.slice(10), body);
      throw new BadRequest("not found", 404);
    }
    if (method === "DELETE") {
      if (api.startsWith("workouts/")) { applyOp("workout", api.slice(9), { deleted: 1 }); return { ok: true }; }
      if (api.startsWith("sets/")) { applyOp("set", api.slice(5), { deleted: 1 }); return { ok: true }; }
      if (api.startsWith("cardio/")) { applyOp("cardio", api.slice(7), { deleted: 1 }); return { ok: true }; }
      if (api.startsWith("food_logs/")) { applyOp("food_log", api.slice(10), { deleted: 1 }); return { ok: true }; }
      if (api.startsWith("meals/")) { db.update("meals", +api.slice(6), { active: 0 }); return { ok: true }; }
      if (api.startsWith("foods/")) { const id = api.slice(6); if (db.get("foods", id)) db.update("foods", id, { active: 0 }); return { ok: true, hidden: true }; }
      if (api.startsWith("exercises/")) { db.update("exercises", +api.slice(10), { active: 0 }); refreshExercises(); return { ok: true, hidden: true }; }
      throw new BadRequest("not found", 404);
    }
    throw new BadRequest("method not allowed", 405);
  }

  /* JSON from anywhere on the internet: through the Android app's native call when present, else the browser. */
  async function fetchJson(url) {
    if (window.Android && window.Android.fetchJson) return androidFetch(url);
    let r;
    try { r = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" }); }
    catch (e) { throw new BadRequest("Could not reach the internet.", 502); }
    if (!r.ok) throw new BadRequest(`The server answered ${r.status}.`, 502);
    return r.json();
  }

  return { init, call, settings, exportCsv, fetchJson, BadRequest, get db() { return db; }, get prog() { return PROG; } };
})();
if (typeof module !== "undefined") module.exports = LocalApi;
