/* Fitness Tracker engine, phone edition.
   The programme, effort and nutrition maths, ported rule for rule from the
   Python modules (programme.py, effort.py, nutrition.py) so the phone gets
   the same plan, the same targets and the same scores with no server.
   Works on a plain in-memory model (see store.js) and never touches the DOM. */
"use strict";

const Engine = (() => {
  /* ------------------------------------------------------------ dates */
  const pad2 = n => String(n).padStart(2, "0");
  const isoOf = d => d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
  const D = iso => new Date(String(iso).slice(0, 10) + "T00:00:00");
  const addDays = (iso, n) => { const d = D(iso); d.setDate(d.getDate() + n); return isoOf(d); };
  const daysBetween = (a, b) => Math.round((D(b) - D(a)) / 86400000);
  const isoWeekday = iso => { const w = D(iso).getDay(); return w === 0 ? 7 : w; };
  const mondayOf = iso => addDays(iso, -(isoWeekday(iso) - 1));
  const nowIso = () => { const d = new Date(); return isoOf(d) + "T" + pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds()); };
  const tsMs = v => { if (!v) return null; const t = new Date(String(v)).getTime(); return isNaN(t) ? null : t; };

  /* ------------------------------------------------------------ nutrition */
  const KCAL_PER_KG = 7700;
  const NUTRITION_DEFAULTS = {
    sex: "m", birth_date: null, height_cm: null, start_weight_kg: null, target_weight_kg: null, target_date: null,
    goal_start_weight: null, goal_start_date: null, neat_factor: 1.3, deficit_cap: 750, surplus_cap: 300,
    protein_g_per_kg: 2.0, fat_g_per_kg: 0.8, fat_floor_g_per_kg: 0.5, carb_floor_g: 50, kcal_floor: null,
    water_target_ml: 2500, sleep_target_h: 8, steps_target: 8000,
  };

  function ageOn(birth, d) { if (!birth) return null; return Math.floor(daysBetween(birth, d) / 365.25); }

  function trendWeight(logs, d, startWeight) {
    const pairs = logs.filter(l => l.weight != null).map(l => ({ date: String(l.date).slice(0, 10), w: +l.weight }));
    const lo = addDays(d, -6);
    const window = pairs.filter(p => p.date >= lo && p.date <= d).map(p => p.w);
    if (window.length) return { weight: Math.round(window.reduce((a, b) => a + b, 0) / window.length * 100) / 100, source: "trend" };
    const before = pairs.filter(p => p.date <= d).sort((a, b) => a.date.localeCompare(b.date));
    if (before.length) return { weight: before[before.length - 1].w, source: "latest" };
    if (startWeight) return { weight: +startWeight, source: "start" };
    return { weight: null, source: "none" };
  }
  function paceWeight(s, d) {
    if (s.goal_start_weight == null || !s.goal_start_date || s.target_weight_kg == null || !s.target_date) return null;
    const total = daysBetween(s.goal_start_date, s.target_date);
    if (total <= 0) return +s.target_weight_kg;
    const frac = Math.min(1, Math.max(0, daysBetween(s.goal_start_date, d) / total));
    return Math.round((+s.goal_start_weight + (+s.target_weight_kg - +s.goal_start_weight) * frac) * 100) / 100;
  }
  function weeklyPace(s) {
    if (s.goal_start_weight == null || !s.goal_start_date || s.target_weight_kg == null || !s.target_date) return null;
    const total = daysBetween(s.goal_start_date, s.target_date);
    if (total <= 0) return 0;
    return Math.round((+s.target_weight_kg - +s.goal_start_weight) * 7 / total * 100) / 100;
  }
  function paceVerdict(trend, pace, logs14, goalStart, target) {
    if (trend == null || pace == null || goalStart == null || target == null || logs14 < 3) return { code: "no_data", text: "Log your weight a few times to see your pace" };
    const sign = +goalStart >= +target ? 1 : -1;
    const behind = (trend - pace) * sign;
    if (Math.abs(behind) <= 0.5) return { code: "on_pace", text: "On pace", kg: Math.round(behind * 10) / 10 };
    if (behind > 0) return { code: "behind", text: `Behind by ${behind.toFixed(1)} kg`, kg: Math.round(behind * 10) / 10 };
    return { code: "ahead", text: `Ahead by ${(-behind).toFixed(1)} kg`, kg: Math.round(behind * 10) / 10 };
  }
  const bmr = (sex, w, h, age) => 10 * w + 6.25 * h - 5 * age + (sex === "m" ? 5 : -161);
  const profileComplete = s => ["sex", "birth_date", "height_cm", "target_weight_kg", "target_date"].every(k => s[k] != null && s[k] !== "");

  function targets(settings, weight, d, exerciseKcal = 0, eatenKcal = 0) {
    const out = { complete: false };
    if (!profileComplete(settings) || weight == null) return out;
    const s = Object.assign({}, NUTRITION_DEFAULTS);
    Object.entries(settings).forEach(([k, v]) => { if (v != null) s[k] = v; });
    const sex = String(s.sex).toLowerCase().startsWith("f") ? "f" : "m";
    const age = ageOn(s.birth_date, d);
    const b = bmr(sex, +weight, +s.height_cm, age);
    const base = b * +s.neat_factor;
    const target = +s.target_weight_kg;
    const days = daysBetween(d, s.target_date);
    const gap = +weight - target;
    const cap = +s.deficit_cap, surplusCap = +s.surplus_cap;
    let deficit = 0, mode = "maintaining", capped = false, eta = null;
    if (Math.abs(gap) >= 0.3) {
      const needed = days < 1 ? Infinity : Math.abs(gap) * KCAL_PER_KG / Math.max(days, 1);
      if (gap > 0) { mode = "losing"; deficit = Math.min(needed, cap); capped = needed > cap; if (capped) eta = addDays(d, Math.ceil(gap * KCAL_PER_KG / cap)); }
      else { mode = "gaining"; deficit = -Math.min(needed, surplusCap); capped = needed > surplusCap; if (capped) eta = addDays(d, Math.ceil(-gap * KCAL_PER_KG / surplusCap)); }
    }
    const floor = +(s.kcal_floor || (sex === "m" ? 1500 : 1200));
    const rawBudget = base - deficit + (+exerciseKcal || 0);
    const budget = Math.max(rawBudget, floor);
    const protein = +s.protein_g_per_kg * +weight;
    let fat = +s.fat_g_per_kg * +weight;
    let carbs = (budget - 4 * protein - 9 * fat) / 4;
    const carbFloor = +s.carb_floor_g;
    if (carbs < carbFloor) { carbs = carbFloor; fat = Math.max(+s.fat_floor_g_per_kg * +weight, (budget - 4 * protein - 4 * carbFloor) / 9); }
    const r1 = x => Math.round(x * 10) / 10;
    return { complete: true, sex, age, weight: r1(+weight), bmr: r1(b), base: r1(base), mode, deficit: r1(deficit), capped, eta,
      target_passed: days < 0, days_left: days, exercise: r1(+exerciseKcal || 0), budget: r1(budget), left: r1(budget - (+eatenKcal || 0)),
      eaten: r1(+eatenKcal || 0), floored: rawBudget < floor, floor, protein: r1(protein), fat: r1(fat), carbs: r1(carbs), weekly_pace: weeklyPace(s) };
  }
  function foodLogValues(food, grams, qty = 1) {
    const g = +grams * (+qty || 1), k = g / 100, r2 = x => Math.round(x * 100) / 100;
    return { grams: Math.round(g * 10) / 10, kcal: r2(food.kcal_100 * k), protein: r2(food.protein_100 * k), carb: r2(food.carb_100 * k), fat: r2(food.fat_100 * k) };
  }

  /* ------------------------------------------------------------ effort */
  const LIFT_MET = { easy: 3.5, moderate: 5.0, hard: 6.0 };
  const DEFAULT_METS = { treadmill: { easy: 3.5, moderate: 5.5, vigorous: 9.0 }, bike: { easy: 4.0, moderate: 6.8, vigorous: 8.8 }, rower: { easy: 4.8, moderate: 7.0, vigorous: 10.0 } };
  const KCAL_REF_PER_KG = 5.0;
  const roundLoad = (x, equipment) => { if (x == null) return null; const step = equipment === "dumbbell" && x < 10 ? 1 : 2.5; return Math.floor(x / step + 0.5) * step; };
  function setLoad(weight, frac, bw, equipment) { const w = +(weight || 0), f = +(frac || 0), b = +(bw || 0); return equipment === "assisted" ? Math.max(0, f * b - w) : w + f * b; }
  const setVolume = (load, reps, perHand, timed) => timed ? 0 : +load * (+reps || 0) * (perHand ? 2 : 1);
  function e1rm(load, reps) { reps = Math.round(+reps || 0); if (reps < 1 || !load || load <= 0) return { value: null, low: false }; return { value: Math.round(+load * (1 + reps / 30) * 100) / 100, low: reps > 12 }; }
  function hardRatio(rpes) { const l = rpes.filter(r => r != null); return l.length ? l.filter(r => r >= 8).length / l.length : 0; }
  const liftingMet = m => m == null ? LIFT_MET.moderate : m < 7 ? LIFT_MET.easy : m <= 8.5 ? LIFT_MET.moderate : LIFT_MET.hard;
  function cardioMet(mets, intensity, workSec, restSec, machine) {
    const table = mets || DEFAULT_METS[machine] || DEFAULT_METS.bike;
    intensity = (intensity || "moderate").toLowerCase();
    if (intensity === "interval") { const f = workSec && restSec != null && workSec + restSec > 0 ? workSec / (workSec + restSec) : 0.4; return Math.round((f * table.vigorous + (1 - f) * table.easy) * 1000) / 1000; }
    return +(table[intensity] ?? table.moderate);
  }
  const kcal = (met, bw, minutes) => Math.round(met * bw * minutes / 60 * 10) / 10;
  function liftMinutes(startedAt, endedAt, lastSetAt, cardioMinutes = 0, planned = null) {
    const s = tsMs(startedAt), e = tsMs(endedAt) || tsMs(lastSetAt);
    if (s == null || e == null || e <= s) return planned ? Math.min(120, Math.max(15, planned)) : 45;
    return Math.min(120, Math.max(15, (e - s) / 60000 - (+cardioMinutes || 0)));
  }
  function median(xs) { const a = xs.slice().sort((x, y) => x - y); const m = a.length >> 1; return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2; }
  function effortScore(volume, refs, hard, kcalUsed, bw) {
    const r = refs.filter(v => v);
    let ref = null, partA;
    if (r.length >= 3) { ref = median(r); partA = 50 * Math.min(ref ? volume / ref : 1, 1.5) / 1.5; } else partA = 33.3;
    const partB = 30 * (+hard || 0);
    const kcalRef = KCAL_REF_PER_KG * (+bw || 80);
    const partC = 20 * Math.min((+kcalUsed || 0) / kcalRef, 1);
    const r1 = x => Math.round(x * 10) / 10;
    return { effort: Math.round(partA + partB + partC), parts: { volume: r1(partA), hard_sets: r1(partB), calories: r1(partC), ref_volume: ref ? r1(ref) : null, kcal_ref: r1(kcalRef) } };
  }
  function cardioEffort(kcalUsed, bw, intensities) {
    const kcalRef = KCAL_REF_PER_KG * (+bw || 80);
    const partA = 70 * Math.min((+kcalUsed || 0) / kcalRef, 1);
    const hard = intensities.some(i => ["vigorous", "interval"].includes((i || "").toLowerCase()));
    const partB = 30 * (hard ? 1 : 0.6);
    const r1 = x => Math.round(x * 10) / 10;
    return { effort: Math.round(partA + partB), parts: { calories: r1(partA), intensity: r1(partB), kcal_ref: r1(kcalRef) } };
  }

  const bodyLogs = db => db.all("body_logs").filter(b => b.weight_kg != null).map(b => ({ date: b.date, weight: b.weight_kg }));
  const bodyweightOn = (db, d, settings) => trendWeight(bodyLogs(db), d, settings.start_weight_kg).weight || 80;
  const exOf = (db, id) => db.get("exercises", id);
  function workingSets(db, wcid) {
    return db.all("set_logs").filter(s => s.workout_client_id === wcid && !s.is_warmup).map(s => Object.assign({}, s, { ex: exOf(db, s.exercise_id) }))
      .filter(s => s.ex).sort((a, b) => a.exercise_id - b.exercise_id || a.set_no - b.set_no);
  }
  const finishedWorkouts = db => db.all("workouts").filter(w => w.ended_at);

  function recomputeWorkout(db, wcid, settings, prog) {
    const w = db.get("workouts", wcid);
    if (!w) return null;
    const bw = bodyweightOn(db, w.date, settings);
    const sets = workingSets(db, wcid);
    let volume = 0, lastSetAt = null;
    const rpes = [];
    sets.forEach(s => { volume += setVolume(setLoad(s.weight_kg, s.ex.bodyweight_fraction, bw, s.ex.equipment), s.reps, s.ex.per_hand, s.ex.timed); rpes.push(s.rpe); if (s.done_at && (!lastSetAt || s.done_at > lastSetAt)) lastSetAt = s.done_at; });
    const logged = rpes.filter(r => r != null);
    const meanRpe = logged.length ? logged.reduce((a, b) => a + b, 0) / logged.length : null;
    const protocols = Object.fromEntries((prog.protocols || []).map(p => [p.id, p]));
    let cardioKcal = 0, cardioMin = 0;
    const intensities = [];
    db.all("cardio_logs").filter(c => c.workout_client_id === wcid).forEach(c => {
      const ex = c.exercise_id ? exOf(db, c.exercise_id) : null;
      const proto = protocols[c.protocol] || {};
      const met = cardioMet(ex && ex.mets, c.intensity, proto.work_sec, proto.rest_sec, ex && ex.equipment);
      const k = kcal(met, bw, c.minutes || 0);
      db.update("cardio_logs", c.client_id, { kcal_est: k });
      cardioKcal += k; cardioMin += +c.minutes || 0; intensities.push(c.intensity);
    });
    let minutes = 0, kcalLift = 0;
    if (sets.length) { minutes = liftMinutes(w.started_at, w.ended_at, lastSetAt, cardioMin); kcalLift = kcal(liftingMet(meanRpe), bw, minutes); }
    const kcalEst = Math.round((kcalLift + cardioKcal) * 10) / 10;
    const kcalUsed = w.kcal_wearable ? w.kcal_wearable : kcalEst;
    const hard = hardRatio(rpes);
    const hardSets = rpes.filter(r => r != null && r >= 8).length;
    let score;
    if (sets.length) {
      const sess = w.session_id ? db.get("plan_sessions", w.session_id) : null;
      const kind = sess ? sess.kind : "adhoc";
      const since = addDays(w.date, -28);
      const refs = finishedWorkouts(db).filter(o => o.client_id !== wcid && o.date >= since && o.date < w.date).filter(o => {
        const os = o.session_id ? db.get("plan_sessions", o.session_id) : null;
        return kind === "adhoc" ? !o.session_id : (os && os.kind === kind);
      }).map(o => o.volume);
      score = effortScore(volume, refs, hard, kcalUsed, bw);
    } else score = cardioEffort(kcalUsed, bw, intensities);
    db.update("workouts", wcid, { volume: Math.round(volume * 10) / 10, work_sets: sets.length, hard_sets: hardSets, lift_minutes: Math.round(minutes * 10) / 10, kcal_est: kcalEst, effort: score.effort, effort_parts: score.parts });
    return Object.assign({ kcal_used: kcalUsed }, db.get("workouts", wcid));
  }
  function historyForExercise(db, exId, excludeCid, untilDate) {
    const done = new Map(finishedWorkouts(db).filter(w => w.client_id !== excludeCid && (!untilDate || w.date <= untilDate)).map(w => [w.client_id, w]));
    return db.all("set_logs").filter(s => s.exercise_id === exId && !s.is_warmup && done.has(s.workout_client_id))
      .map(s => Object.assign({}, s, { date: done.get(s.workout_client_id).date, ended_at: done.get(s.workout_client_id).ended_at }))
      .sort((a, b) => b.date.localeCompare(a.date) || String(b.ended_at).localeCompare(String(a.ended_at)) || a.set_no - b.set_no);
  }
  function bestsForExercise(db, exId, ex, bw, excludeCid) {
    const hist = historyForExercise(db, exId, excludeCid);
    let bestE = null, bestW = null;
    const repsAt = {};
    hist.forEach(s => {
      if (ex.timed) return;
      const load = setLoad(s.weight_kg, ex.bodyweight_fraction, bw, ex.equipment);
      const e = e1rm(load, s.reps);
      if (e.value && !e.low && !ex.bodyweight_fraction) bestE = Math.max(bestE || 0, e.value);
      if (load > 0) { bestW = Math.max(bestW || 0, load); const k = String(Math.round(load * 100) / 100); repsAt[k] = Math.max(repsAt[k] || 0, Math.round(s.reps || 0)); }
    });
    const top = Object.entries(repsAt).sort((a, b) => +b[0] - +a[0]).slice(0, 5);
    return { best_e1rm: bestE, best_weight: bestW, reps_at_weight: Object.fromEntries(top), has_history: hist.length > 0 };
  }
  function prsForWorkout(db, wcid, settings) {
    const w = db.get("workouts", wcid); if (!w) return [];
    const bw = bodyweightOn(db, w.date, settings);
    const byEx = {};
    workingSets(db, wcid).forEach(s => (byEx[s.exercise_id] = byEx[s.exercise_id] || []).push(s));
    const out = [];
    Object.entries(byEx).forEach(([exId, sets]) => {
      const ex = sets[0].ex;
      const bests = bestsForExercise(db, +exId, ex, bw, wcid);
      if (!bests.has_history) return;
      let topE = null, topW = null;
      sets.forEach(s => {
        if (ex.timed) return;
        const load = setLoad(s.weight_kg, ex.bodyweight_fraction, bw, ex.equipment);
        const e = e1rm(load, s.reps);
        if (e.value && !e.low && !ex.bodyweight_fraction) topE = Math.max(topE || 0, e.value);
        topW = Math.max(topW || 0, load);
        const prev = bests.reps_at_weight[String(Math.round(load * 100) / 100)];
        if (prev != null && Math.round(s.reps || 0) > prev) out.push({ exercise: ex.name, kind: "reps", text: `${Math.round(s.reps)} reps at ${load} kg, previous best ${prev}` });
      });
      if (topE && bests.best_e1rm && topE > bests.best_e1rm) out.push({ exercise: ex.name, kind: "e1rm", text: `Estimated 1RM ${topE.toFixed(1)} kg, up from ${bests.best_e1rm.toFixed(1)}` });
      if (topW && bests.best_weight && topW > bests.best_weight) out.push({ exercise: ex.name, kind: "weight", text: `Heaviest set ${topW} kg, previous ${bests.best_weight}` });
    });
    const seen = new Set();
    return out.filter(p => { const k = p.exercise + "|" + p.kind; if (seen.has(k)) return false; seen.add(k); return true; });
  }
  function weeklyMuscleSets(db, fromDate) {
    const done = new Map(finishedWorkouts(db).filter(w => w.date >= fromDate).map(w => [w.client_id, w]));
    const out = {};
    db.all("set_logs").filter(s => !s.is_warmup && done.has(s.workout_client_id)).forEach(s => {
      const ex = exOf(db, s.exercise_id); if (!ex) return;
      const wk = out[mondayOf(done.get(s.workout_client_id).date)] = out[mondayOf(done.get(s.workout_client_id).date)] || {};
      wk[ex.primary_muscle] = (wk[ex.primary_muscle] || 0) + 1;
      (ex.secondary_muscles || []).forEach(m => { wk[m] = (wk[m] || 0) + 0.5; });
    });
    return Object.keys(out).sort().map(k => ({ week: k, muscles: Object.fromEntries(Object.entries(out[k]).sort().map(([m, v]) => [m, Math.round(v * 10) / 10])) }));
  }
  function weeklyE1rm(db, exId, bwByDate) {
    const ex = exOf(db, exId); if (!ex) return [];
    const done = new Map(finishedWorkouts(db).map(w => [w.client_id, w]));
    const weeks = {};
    db.all("set_logs").filter(s => s.exercise_id === exId && !s.is_warmup && done.has(s.workout_client_id)).forEach(s => {
      const date = done.get(s.workout_client_id).date;
      const e = e1rm(setLoad(s.weight_kg, ex.bodyweight_fraction, bwByDate(date), ex.equipment), s.reps);
      if (!e.value) return;
      const wk = mondayOf(date), cur = weeks[wk];
      if (!cur || e.value > cur.e1rm || (cur.low && !e.low && e.value >= cur.e1rm * 0.9)) weeks[wk] = { e1rm: e.value, low: e.low };
    });
    return Object.keys(weeks).sort().map(k => ({ week: k, e1rm: weeks[k].e1rm, low_confidence: weeks[k].low }));
  }
  function strengthIndex(db, mainIds, bwByDate, baselineWeeks) {
    const series = {}, all = new Set();
    mainIds.forEach(id => {
      const pts = weeklyE1rm(db, id, bwByDate).filter(p => !p.low_confidence);
      if (!pts.length) return;
      const base = pts.filter(p => baselineWeeks.has(p.week)).map(p => p.e1rm);
      const baseline = Math.max(...(base.length ? base : [pts[0].e1rm]));
      series[id] = Object.fromEntries(pts.map(p => [p.week, p.e1rm / baseline - 1]));
      pts.forEach(p => all.add(p.week));
    });
    const last = {}, out = [];
    Array.from(all).sort().forEach(wk => {
      const vals = []; let carried = false;
      Object.entries(series).forEach(([id, byWeek]) => {
        if (wk in byWeek) last[id] = byWeek[wk]; else if (last[id] != null) carried = true;
        if (last[id] != null) vals.push(last[id]);
      });
      if (vals.length) out.push({ week: wk, index: Math.round(1000 * vals.reduce((a, b) => a + b, 0) / vals.length) / 10, carried });
    });
    return out;
  }

  /* ------------------------------------------------------------ programme */
  const LIFTING_KINDS = ["upper_a", "lower_a", "upper_b", "lower_b"];
  const ADHERENCE_KINDS = LIFTING_KINDS.concat(["conditioning"]);
  const STALE_DAYS = 28;
  const TRAIN_DEFAULTS = { train_days: [1, 2, 3, 4, 5], session_minutes: 60, experience: "beginner", cardio_kit: ["treadmill", "bike", "rower"], main1_swap_every_blocks: 2, programme_start: null, split: "upper_lower" };
  const isLifting = (kind, prog) => !!(prog.sessions || {})[kind] && !["conditioning", "zone2"].includes(kind);
  const countsForAdherence = kind => kind !== "rest" && kind !== "zone2";
  function templateFor(ts, prog) {
    const n = ts.train_days.length;
    const split = (prog.splits || {})[ts.split || "upper_lower"];
    if (split && split.templates && Object.keys(split.templates).length) {
      const keys = Object.keys(split.templates).map(Number).sort((a, b) => a - b);
      const fit = keys.filter(k => k <= n);
      return split.templates[String(fit.length ? fit[fit.length - 1] : keys[0])];
    }
    return n >= 6 ? prog.template_6 : prog.template_5;
  }
  class PlanError extends Error { constructor(msg, code = 400) { super(msg); this.code = code; } }

  const CRC_TABLE = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  function crc32(str) { const bytes = new TextEncoder().encode(str); let c = 0xFFFFFFFF; for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
  const hex4 = () => Array.from(crypto.getRandomValues(new Uint8Array(4))).map(b => b.toString(16).padStart(2, "0")).join("");

  function validateSeed(prog, exByKey) {
    const problems = [];
    Object.entries(prog.sessions || {}).forEach(([kind, sess]) => {
      [sess.warmup, sess.cooldown].forEach(k => { if (k && !exByKey[k]) problems.push(`${kind}: ${k} is not in the exercise library`); });
      (sess.slots || []).forEach(slot => (slot.pool || []).forEach(k => { if (!exByKey[k]) problems.push(`${kind}/${slot.key}: ${k} missing`); }));
    });
    (prog.protocols || []).forEach(p => { if (p.machine && p.machine !== "any" && !exByKey[p.machine]) problems.push(`protocol ${p.id}: machine ${p.machine} missing`); });
    return problems;
  }
  const protocolsById = prog => Object.fromEntries((prog.protocols || []).map(p => [p.id, p]));
  function protocolMinutes(proto, minimum) {
    if ("minutes" in proto) return +(minimum && proto.minutes_min ? proto.minutes_min : proto.minutes);
    const rounds = minimum && proto.rounds_min ? proto.rounds_min : (proto.rounds || 1);
    return Math.round(rounds * ((proto.work_sec || 0) + (proto.rest_sec || 0)) / 60 * 100) / 100;
  }
  const protocolRounds = (proto, minimum) => "minutes" in proto ? null : (minimum && proto.rounds_min ? proto.rounds_min : proto.rounds);
  function trainSettings(settings) {
    const s = Object.assign({}, TRAIN_DEFAULTS);
    Object.keys(s).forEach(k => { if (settings[k] != null && settings[k] !== "") s[k] = settings[k]; });
    s.train_days = Array.from(new Set(s.train_days.map(Number))).filter(d => d >= 1 && d <= 7).sort((a, b) => a - b);
    const kit = (s.cardio_kit || []).filter(m => ["treadmill", "bike", "rower"].includes(m));
    s.cardio_kit = kit.length ? kit : ["bike"];
    return s;
  }
  function pick(pool, weekSeed, slotId, previous) {
    pool = Array.from(pool || []);
    if (!pool.length) return null;
    if (pool.length === 1) return pool[0];
    const cands = pool.filter(k => k !== previous);
    const c = cands.length ? cands : pool;
    return c[crc32(`${weekSeed}|${slotId}`) % c.length];
  }
  const activePool = (pool, exByKey) => { const live = pool.filter(k => (exByKey[k] || {}).active !== 0 && exByKey[k]); return live.length ? live : pool.slice(0, 1); };
  function estMinutes(item, overhead = 40) {
    if (item.minutes) return +item.minutes;
    let m = (item.sets || 0) * ((item.rest_sec || 0) + overhead) / 60;
    if (item.slot_key === "main1") m += 2;
    return m;
  }
  const sessionMinutes = (items, overhead = 40) => Math.round(items.reduce((a, i) => a + estMinutes(i, overhead), 0) * 100) / 100;
  function previousWeekPicks(db, weekId, kind) {
    if (!weekId) return {};
    const out = {};
    db.all("plan_sessions").filter(s => s.week_id === weekId && s.kind === kind).forEach(s => {
      db.all("plan_items").filter(i => i.session_id === s.id).forEach(i => { const ex = i.exercise_id ? exOf(db, i.exercise_id) : null; out[i.slot_key] = { exercise: ex ? ex.key : null, protocol: i.protocol }; });
    });
    return out;
  }
  const scheme = (prog, ts, name) => { const s = prog.rep_schemes[ts.experience] || prog.rep_schemes.beginner; return s[name] || s.accessory; };
  const blankItem = (ord, kw) => Object.assign({ ord, section: null, slot_key: null, exercise_key: null, sets: null, rep_low: null, rep_high: null, rest_sec: null, minutes: null, protocol: null, rounds: null, optional: 0, note: null }, kw);

  function buildLiftingItems(kind, blockNo, weekSeed, isDeload, prevPicks, prevFinisher, ts, prog, exByKey) {
    const sess = prog.sessions[kind], protos = protocolsById(prog), kit = ts.cardio_kit;
    const swapEvery = +ts.main1_swap_every_blocks || 2;
    const items = []; let n = 0;
    const add = kw => items.push(blankItem(++n, kw));
    const finPool = (prog.protocols || []).filter(p => p.group === "finisher" && kit.includes(p.machine)).map(p => p.id);
    const finId = finPool.length ? pick(finPool, weekSeed, `${kind}:finisher`, prevFinisher) : null;
    const fin = finId ? protos[finId] : null;
    const machine = fin ? fin.machine : kit[0];
    const wu = prog.warmup_cardio || { key: "wu_cardio", protocol: "warm_easy_5" };
    add({ section: "warmup", slot_key: wu.key, exercise_key: machine, protocol: wu.protocol, minutes: protocolMinutes(protos[wu.protocol] || { minutes: 5 }) });
    if (sess.warmup) add({ section: "warmup", slot_key: "wu_dynamic", exercise_key: sess.warmup, minutes: 2 });
    sess.slots.forEach(slot => {
      const pool = activePool(slot.pool, exByKey);
      let key;
      if (slot.select === "block_alternate") { const every = slot.key === "main1" ? swapEvery : 1; key = pool[Math.floor((blockNo - 1) / every) % pool.length]; }
      else if (slot.select === "fixed") key = pool[0];
      else key = pick(pool, weekSeed, `${kind}:${slot.key}`, (prevPicks[slot.key] || {}).exercise);
      const ex = exByKey[key];
      const sc = scheme(prog, ts, slot.scheme || slot.section);
      let sets = sc.sets, lo = sc.rep_low, hi = sc.rep_high;
      if (ex.timed) { lo = (prog.timed_scheme || {}).rep_low || 30; hi = (prog.timed_scheme || {}).rep_high || 60; }
      if (isDeload && ["main", "accessory", "core"].includes(slot.section)) sets = Math.max(1, sets + (+(prog.deload.set_delta ?? -1)));
      add({ section: slot.section, slot_key: slot.key, exercise_key: key, sets, rep_low: lo, rep_high: hi, rest_sec: prog.rest_sec[slot.scheme || slot.section] || 60, optional: slot.optional ? 1 : 0 });
    });
    if (fin) add({ section: "finisher", slot_key: "finisher", exercise_key: machine, protocol: finId, minutes: protocolMinutes(fin, isDeload), rounds: protocolRounds(fin, isDeload) });
    if (sess.cooldown) add({ section: "cooldown", slot_key: "cooldown", exercise_key: sess.cooldown, minutes: 3 });
    return items;
  }
  function buildConditioningItems(blockNo, weekSeed, isDeload, prevPicks, prevMachine, ts, prog, exByKey) {
    const sess = prog.sessions.conditioning, protos = protocolsById(prog), kit = ts.cardio_kit;
    const machine = pick(kit, weekSeed, "conditioning:machine", prevMachine);
    const items = []; let n = 0;
    const add = kw => items.push(blankItem(++n, kw));
    const wu = prog.warmup_cardio || { key: "wu_cardio", protocol: "warm_easy_5" };
    add({ section: "warmup", slot_key: wu.key, exercise_key: machine, protocol: wu.protocol, minutes: protocolMinutes(protos[wu.protocol] || { minutes: 5 }) });
    sess.slots.forEach(slot => {
      if (slot.protocol_group) {
        const pool = (prog.protocols || []).filter(p => p.group === slot.protocol_group && (p.machine === machine || p.machine === "any")).map(p => p.id);
        const pid = pick(pool, weekSeed, `conditioning:${slot.key}`, (prevPicks[slot.key] || {}).protocol);
        const proto = protos[pid];
        add({ section: slot.section, slot_key: slot.key, exercise_key: machine, protocol: pid, minutes: protocolMinutes(proto, isDeload), rounds: protocolRounds(proto, isDeload) });
      } else {
        const pool = activePool(slot.pool, exByKey);
        const key = pick(pool, weekSeed, `conditioning:${slot.key}`, (prevPicks[slot.key] || {}).exercise);
        const ex = exByKey[key], sc = scheme(prog, ts, slot.scheme || "circuit");
        let lo = sc.rep_low, hi = sc.rep_high, sets = sc.sets;
        if (ex.timed) { lo = (prog.timed_scheme || {}).rep_low || 30; hi = (prog.timed_scheme || {}).rep_high || 60; }
        if (isDeload) sets = Math.max(1, sets + (+(prog.deload.set_delta ?? -1)));
        add({ section: slot.section, slot_key: slot.key, exercise_key: key, sets, rep_low: lo, rep_high: hi, rest_sec: prog.rest_sec.circuit || 30 });
      }
    });
    if (sess.cooldown) add({ section: "cooldown", slot_key: "mobility", exercise_key: sess.cooldown, minutes: 10 });
    return { items, machine };
  }
  function buildZone2Items(weekSeed, condMachine, isDeload, ts, prog) {
    const protos = protocolsById(prog);
    const kit = ts.cardio_kit.filter(m => m !== condMachine); const use = kit.length ? kit : ts.cardio_kit;
    const machine = pick(use, weekSeed, "zone2:machine");
    const proto = protos.zone2_steady || (prog.protocols || []).find(p => p.group === "zone2");
    return [blankItem(1, { section: "main", slot_key: "zone2", exercise_key: machine, minutes: protocolMinutes(proto, isDeload), protocol: proto.id })];
  }
  function trimToBudget(items, budget, prog) {
    const protos = protocolsById(prog), oh = prog.set_overhead_sec || 40;
    const fits = () => sessionMinutes(items, oh) <= budget;
    if (fits()) return items;
    items = items.filter(i => !i.optional); if (fits()) return items;
    items.forEach(i => { if (i.section === "finisher" && protos[i.protocol]) { i.minutes = protocolMinutes(protos[i.protocol], true); i.rounds = protocolRounds(protos[i.protocol], true); } });
    if (fits()) return items;
    for (const key of ["acc3", "acc2", "acc1"]) { items.forEach(i => { if (i.slot_key === key && (i.sets || 0) > 2) i.sets = 2; }); if (fits()) return items; }
    items.forEach(i => { if (i.section === "core" && (i.sets || 0) > 2) i.sets = 2; }); if (fits()) return items;
    items = items.filter(i => i.slot_key !== "acc3"); if (fits()) return items;
    items = items.filter(i => i.section !== "finisher");
    items.forEach(i => { if (i.slot_key === "main1") i.note = "trimmed for time"; });
    return items;
  }
  function insertItems(db, sessionId, items, exByKey) {
    items.forEach((it, idx) => {
      const ex = it.exercise_key ? exByKey[it.exercise_key] : null;
      db.insert("plan_items", { session_id: sessionId, ord: idx + 1, section: it.section, slot_key: it.slot_key, exercise_id: ex ? ex.id : null, sets: it.sets, rep_low: it.rep_low, rep_high: it.rep_high, target_weight: null, target_source: null, rest_sec: it.rest_sec, minutes: it.minutes, protocol: it.protocol, rounds: it.rounds, optional: it.optional || 0, note: it.note });
    });
  }
  function buildSessionItems(db, session, week, block, ts, prog, exByKey, ctx) {
    const kind = session.kind;
    if (kind === "rest") return;
    const prev = previousWeekPicks(db, ctx.prev_week_id, kind);
    let items;
    if (isLifting(kind, prog)) {
      items = trimToBudget(buildLiftingItems(kind, block.block_no, week.seed, !!week.is_deload, prev, ctx.last_finisher, ts, prog, exByKey), +ts.session_minutes, prog);
      items.forEach(i => { if (i.section === "finisher") ctx.last_finisher = i.protocol; });
    } else if (kind === "conditioning") {
      const r = buildConditioningItems(block.block_no, week.seed, !!week.is_deload, prev, (prev.wu_cardio || {}).exercise, ts, prog, exByKey);
      items = r.items; ctx.conditioning_machine = r.machine;
    } else if (kind === "zone2") items = buildZone2Items(week.seed, ctx.conditioning_machine, !!week.is_deload, ts, prog);
    else return;
    insertItems(db, session.id, items, exByKey);
  }
  function weekKinds(ts, prog) { const t = templateFor(ts, prog); const k = {}; ts.train_days.slice(0, t.length).forEach((wd, i) => { k[wd] = t[i]; }); return k; }
  function titles(prog) { const t = Object.fromEntries(Object.entries(prog.sessions).map(([k, v]) => [k, v.title || k])); t.rest = "Rest"; return t; }

  function createWeek(db, block, weekNo, start, settings, prog, exByKey, prevWeekId) {
    const ts = trainSettings(settings);
    const isDeload = weekNo === +(prog.deload.week_no || 4) ? 1 : 0;
    const week = db.insert("plan_weeks", { block_id: block.id, week_no: weekNo, start_date: start, seed: `${block.seed}:${weekNo}`, is_deload: isDeload });
    const programmeStart = settings.programme_start || start;
    const kinds = weekKinds(ts, prog), names = titles(prog);
    const ctx = { prev_week_id: prevWeekId };
    for (let wd = 1; wd <= 7; wd++) {
      const kind = kinds[wd] || "rest", d = addDays(start, wd - 1);
      const status = d < programmeStart && kind !== "rest" ? "void" : "planned";
      const s = db.insert("plan_sessions", { week_id: week.id, day_offset: wd - 1, date: d, kind, title: names[kind] || kind, status, moved_from: null, note: null });
      buildSessionItems(db, s, week, block, ts, prog, exByKey, ctx);
    }
    return week;
  }
  function createBlock(db, start, settings, prog, exByKey) {
    start = mondayOf(start);
    const blockNo = db.all("blocks").length + 1;
    const block = db.insert("blocks", { block_no: blockNo, start_date: start, weeks: 4, split: "upper_lower", seed: hex4(), notes: null });
    const prev = db.all("plan_weeks").sort((a, b) => b.start_date.localeCompare(a.start_date))[0];
    let prevId = prev ? prev.id : null;
    for (let n = 1; n <= 4; n++) { const wk = createWeek(db, block, n, addDays(start, 7 * (n - 1)), settings, prog, exByKey, prevId); prevId = wk.id; }
    return block;
  }
  const lastWeek = db => db.all("plan_weeks").sort((a, b) => b.start_date.localeCompare(a.start_date))[0];
  function ensurePlanThrough(db, d, settings, prog, exByKey) {
    let last = lastWeek(db);
    if (!last) {
      if (!settings.programme_start) { settings.programme_start = d; db.setSetting("programme_start", d); }
      createBlock(db, d, settings, prog, exByKey);
      last = lastWeek(db);
    }
    let guard = 0;
    while (d > addDays(last.start_date, 6) && guard++ < 60) { createBlock(db, addDays(last.start_date, 7), settings, prog, exByKey); last = lastWeek(db); }
  }
  function sweepMissed(db, today) {
    const live = new Set(db.all("workouts").filter(w => w.session_id).map(w => w.session_id));
    db.all("plan_sessions").forEach(s => { if (s.status === "planned" && s.date < today && s.kind !== "rest" && !live.has(s.id)) db.update("plan_sessions", s.id, { status: "skipped" }); });
  }
  const liveSessionIds = (db, weekId) => new Set(db.all("workouts").filter(w => w.session_id && (db.get("plan_sessions", w.session_id) || {}).week_id === weekId).map(w => w.session_id));
  function rebuildWeek(db, weekId, settings, prog, exByKey, fromDate, today) {
    const week = db.get("plan_weeks", weekId), block = db.get("blocks", week.block_id);
    const prev = db.all("plan_weeks").filter(w => w.start_date < week.start_date).sort((a, b) => b.start_date.localeCompare(a.start_date))[0];
    const ts = trainSettings(settings), kinds = weekKinds(ts, prog), names = titles(prog);
    const live = liveSessionIds(db, weekId), programmeStart = settings.programme_start || week.start_date;
    const ctx = { prev_week_id: prev ? prev.id : null };
    for (let wd = 1; wd <= 7; wd++) {
      const d = addDays(week.start_date, wd - 1);
      const row = db.all("plan_sessions").find(s => s.week_id === weekId && s.day_offset === wd - 1);
      const untouched = !row || (!live.has(row.id) && ["planned", "void", "skipped"].includes(row.status) && (!fromDate || d >= fromDate));
      if (row && !untouched) {
        db.all("plan_items").filter(i => i.session_id === row.id).forEach(it => {
          if (it.slot_key === "finisher") ctx.last_finisher = it.protocol;
          if (row.kind === "conditioning" && it.slot_key === "wu_cardio") { const ex = exOf(db, it.exercise_id); ctx.conditioning_machine = ex ? ex.key : null; }
        });
        continue;
      }
      const kind = kinds[wd] || "rest";
      let status = d < programmeStart && kind !== "rest" ? "void" : "planned";
      if (row && row.status === "skipped" && d < today) status = "skipped";
      let sid;
      if (row) { db.all("plan_items").filter(i => i.session_id === row.id).forEach(i => db.remove("plan_items", i.id)); db.update("plan_sessions", row.id, { kind, title: names[kind] || kind, status, note: null }); sid = row.id; }
      else sid = db.insert("plan_sessions", { week_id: weekId, day_offset: wd - 1, date: d, kind, title: names[kind] || kind, status, moved_from: null, note: null }).id;
      buildSessionItems(db, { id: sid, kind, date: d }, week, block, ts, prog, exByKey, ctx);
    }
  }
  function shuffleWeek(db, weekId, settings, prog, exByKey, today) {
    const week = db.get("plan_weeks", weekId); if (!week) throw new PlanError("That week does not exist.", 404);
    db.update("plan_weeks", weekId, { seed: hex4() });
    rebuildWeek(db, weekId, settings, prog, exByKey, null, today);
    db.all("plan_weeks").filter(w => w.block_id === week.block_id && w.start_date > week.start_date).sort((a, b) => a.start_date.localeCompare(b.start_date)).forEach(w => rebuildWeek(db, w.id, settings, prog, exByKey, null, today));
  }
  function regenerateFrom(db, fromDate, settings, prog, exByKey) {
    db.all("plan_weeks").filter(w => addDays(w.start_date, 6) >= fromDate).sort((a, b) => a.start_date.localeCompare(b.start_date)).forEach(w => rebuildWeek(db, w.id, settings, prog, exByKey, fromDate, fromDate));
  }
  function swapItem(db, itemId, exerciseKey, prog, exByKey) {
    const item = db.get("plan_items", itemId); if (!item) throw new PlanError("That item does not exist.", 404);
    const sess = db.get("plan_sessions", item.session_id);
    if (db.all("set_logs").some(s => s.plan_item_id === itemId)) throw new PlanError("You have already logged a set on this exercise today. Finish it or delete the set first.", 409);
    const current = item.exercise_id ? exOf(db, item.exercise_id) : null;
    const slot = ((prog.sessions[sess.kind] || {}).slots || []).find(s => s.key === item.slot_key);
    const pool = slot ? activePool(slot.pool, exByKey) : [];
    if (exerciseKey) {
      const ex = exByKey[exerciseKey];
      if (!ex || ex.active === 0) throw new PlanError("That exercise is not in the library.", 404);
      if (!pool.includes(exerciseKey) && current && ex.pattern !== current.pattern) throw new PlanError("Pick an exercise with the same movement pattern.", 400);
    } else {
      const prevWeek = db.all("plan_weeks").filter(w => w.start_date < db.get("plan_weeks", sess.week_id).start_date).sort((a, b) => b.start_date.localeCompare(a.start_date))[0];
      const prevKey = prevWeek ? (previousWeekPicks(db, prevWeek.id, sess.kind)[item.slot_key] || {}).exercise : null;
      let options = pool.filter(k => k !== (current && current.key) && k !== prevKey);
      if (!options.length) options = pool.filter(k => k !== (current && current.key));
      if (!options.length && current) options = Object.values(exByKey).filter(e => e.pattern === current.pattern && e.active !== 0 && e.key !== current.key).map(e => e.key).sort();
      if (!options.length) throw new PlanError("There is nothing to swap this for.", 400);
      exerciseKey = options[crc32(`${itemId}|${options.length}`) % options.length];
    }
    const ex = exByKey[exerciseKey];
    let lo = item.rep_low, hi = item.rep_high;
    if (ex.timed) { lo = (prog.timed_scheme || {}).rep_low || 30; hi = (prog.timed_scheme || {}).rep_high || 60; }
    else if (current && current.timed) { const sc = scheme(prog, trainSettings({}), ["main1", "main2"].includes(item.slot_key) ? item.slot_key : item.section); lo = sc.rep_low; hi = sc.rep_high; }
    db.update("plan_items", itemId, { exercise_id: ex.id, rep_low: lo, rep_high: hi, target_weight: null, target_source: null, note: "swapped" });
    return ex;
  }
  function moveSession(db, sessionId, today) {
    const s = db.get("plan_sessions", sessionId); if (!s) throw new PlanError("That session does not exist.", 404);
    if (!["planned", "skipped", "void"].includes(s.status)) throw new PlanError("That session is already done.", 409);
    if (Math.abs(daysBetween(today, s.date)) > 14) throw new PlanError("Only sessions within two weeks can be moved.", 400);
    if (s.date === today) return;
    const t = db.all("plan_sessions").find(x => x.date === today); if (!t) throw new PlanError("Today is not in the plan yet.", 409);
    if (db.all("workouts").some(w => w.session_id === t.id)) throw new PlanError("You have already started today's session.", 409);
    // Rows are live objects, so copy the source's place before the first update overwrites it.
    const from = { date: s.date, day_offset: s.day_offset, week_id: s.week_id };
    const to = { day_offset: t.day_offset, week_id: t.week_id, status: t.status };
    db.update("plan_sessions", s.id, { date: today, day_offset: to.day_offset, week_id: to.week_id, moved_from: from.date, status: "planned" });
    db.update("plan_sessions", t.id, { date: from.date, day_offset: from.day_offset, week_id: from.week_id, moved_from: today, status: to.status === "void" ? "void" : "planned" });
    sweepMissed(db, today);
  }
  function markRest(db, sessionId) {
    const s = db.get("plan_sessions", sessionId); if (!s) throw new PlanError("That session does not exist.", 404);
    if (s.status === "done") throw new PlanError("That session is already done.", 409);
    db.update("plan_sessions", sessionId, { status: "skipped", note: "rest" });
  }

  const stepOf = (ex, w) => ex.equipment === "dumbbell" && (w || 0) < 10 ? 1 : 2.5;
  function incrementOf(ex, w) {
    if (ex.increment_kg) return +ex.increment_kg;
    if (["squat", "hinge"].includes(ex.pattern) && ["barbell", "trap_bar", "machine"].includes(ex.equipment)) return 5;
    if (ex.equipment === "dumbbell") return (w || 0) < 10 ? 1 : 2.5;
    return 2.5;
  }
  const minLoadOf = (ex, w) => ex.min_load_kg != null ? +ex.min_load_kg : ex.equipment === "barbell" ? 20 : stepOf(ex, w);
  function referenceWorkout(db, exId, excludeCid) {
    const deloadWeeks = new Set(db.all("plan_weeks").filter(w => w.is_deload).map(w => w.id));
    const cands = finishedWorkouts(db).filter(w => w.client_id !== excludeCid).filter(w => { const s = w.session_id ? db.get("plan_sessions", w.session_id) : null; return !(s && deloadWeeks.has(s.week_id)); });
    const withSets = cands.filter(w => db.all("set_logs").some(s => s.workout_client_id === w.client_id && s.exercise_id === exId && !s.is_warmup));
    withSets.sort((a, b) => b.date.localeCompare(a.date) || String(b.ended_at).localeCompare(String(a.ended_at)));
    return withSets[0] || null;
  }
  function referenceSets(db, wcid, exId) {
    return db.all("set_logs").filter(s => s.workout_client_id === wcid && s.exercise_id === exId && !s.is_warmup).sort((a, b) => a.set_no - b.set_no)
      .map(s => Object.assign({}, s, { planned_sets: s.plan_item_id ? (db.get("plan_items", s.plan_item_id) || {}).sets : null }));
  }
  function progression(ex, sets, repLow, repHigh, plannedSets) {
    if (!sets || !sets.length) return { weight: null, label: "first" };
    const assisted = ex.equipment === "assisted";
    const weights = sets.map(s => +(s.weight_kg || 0));
    const w = assisted ? Math.min(...weights) : Math.max(...weights);
    const top = sets.filter(s => +(s.weight_kg || 0) === w);
    const rpes = sets.filter(s => s.rpe != null).map(s => +s.rpe);
    const meanRpe = rpes.length ? rpes.reduce((a, b) => a + b, 0) / rpes.length : 8;
    const nHi = rpes.filter(r => r >= 9.5).length;
    const planned = plannedSets || 3;
    const reps = s => Math.round(s.reps || 0);
    const hitAllHigh = top.length >= planned && top.every(s => reps(s) >= repHigh);
    const anyLow = sets.some(s => reps(s) < repLow);
    const partial = sets.length < planned;
    if (ex.timed) { if (anyLow || nHi >= 2) return { weight: null, label: "hold_time" }; return { weight: null, label: hitAllHigh ? "add_time" : "hold_time" }; }
    if (ex.bodyweight_fraction && ex.equipment === "bodyweight") return { weight: null, label: hitAllHigh ? "add_reps" : "hold_reps" };
    const step = stepOf(ex, w), inc = incrementOf(ex, w);
    if (assisted) {
      if (anyLow || nHi >= 2) return { weight: roundLoad(w + step, ex.equipment), label: anyLow ? "decrease_reps" : "decrease_rpe" };
      if (partial) return { weight: w, label: "hold_partial" };
      if (hitAllHigh && meanRpe <= 8.5) return { weight: Math.max(0, roundLoad(w - inc, ex.equipment)), label: "increase" };
      return { weight: w, label: hitAllHigh ? "hold_rpe" : "hold_reps" };
    }
    if (anyLow || nHi >= 2) return { weight: Math.max(minLoadOf(ex, w), Math.min(roundLoad(0.95 * w, ex.equipment), w - step)), label: anyLow ? "decrease_reps" : "decrease_rpe" };
    if (partial) return { weight: w, label: "hold_partial" };
    if (hitAllHigh && meanRpe <= 8.5) return { weight: roundLoad(w + inc, ex.equipment), label: "increase" };
    if (hitAllHigh) return { weight: w, label: "hold_rpe" };
    return { weight: w, label: "hold_reps" };
  }
  function targetText(ex, weight, label, lo, hi) {
    const unit = ex.timed ? "s" : "reps";
    return {
      first: `First time. Find a weight you can do for ${lo + 2} ${unit} with two in reserve.`,
      guess: "A starting guess from a related lift. Adjust freely.",
      increase: "You hit every set last time. Go up.",
      hold_reps: "Same weight. Try for more reps.",
      hold_rpe: "You hit the reps but it was hard. Same weight, make it smoother.",
      hold_partial: "You did not get every set in last time. Same weight, all sets.",
      decrease_reps: "Reps fell short last time. A little lighter, own it.",
      decrease_rpe: "Last time was a grind. A little lighter.",
      stale: "It has been a while. Repeat your last weight.",
      deload: "Deload week. Lighter on purpose, keep the reps crisp.",
      add_time: "Add five seconds to each hold.",
      hold_time: `Hold ${lo} to ${hi} seconds.`,
      add_reps: "Add a rep or two each set.",
    }[label] || "";
  }
  function targetFor(db, ex, item, today, isDeload, excludeCid, exByKey, bw) {
    const lo = item.rep_low || 8, hi = item.rep_high || 12;
    const ref = referenceWorkout(db, ex.id, excludeCid);
    let weight = null, label = "first", last = null;
    if (ref) {
      const sets = referenceSets(db, ref.client_id, ex.id);
      const planned = (sets.find(s => s.planned_sets) || {}).planned_sets || item.sets || 3;
      const p = progression(ex, sets, lo, hi, planned);
      weight = p.weight; label = p.label;
      last = { date: ref.date, sets: sets.map(s => ({ reps: s.reps, weight: s.weight_kg, rpe: s.rpe })) };
      if (daysBetween(ref.date, today) > STALE_DAYS && weight != null) { const ws = sets.map(s => +(s.weight_kg || 0)); weight = ex.equipment === "assisted" ? Math.min(...ws) : Math.max(...ws); label = "stale"; }
    } else if (ex.variation_of && exByKey && ex.carry) {
      const old = exByKey[ex.variation_of];
      if (old) {
        const oref = referenceWorkout(db, old.id);
        if (oref) {
          let best = 0;
          referenceSets(db, oref.client_id, old.id).forEach(s => { const e = e1rm(setLoad(s.weight_kg, old.bodyweight_fraction, bw || 80, old.equipment), s.reps); if (e.value && !e.low) best = Math.max(best, e.value); });
          if (best) { weight = roundLoad(+ex.carry * best / (1 + lo / 30), ex.equipment); label = "guess"; }
        }
      }
    }
    if (isDeload && weight != null && label !== "first") { weight = roundLoad(weight * 0.9, ex.equipment); label = "deload"; }
    return { weight, source: label, last, text: targetText(ex, weight, label, lo, hi) };
  }
  function freezeTargets(db, sessionId, today, settings, exByKey) {
    const sess = db.get("plan_sessions", sessionId); if (!sess) return;
    const week = db.get("plan_weeks", sess.week_id);
    const isDeload = !!(week && week.is_deload), bw = bodyweightOn(db, today, settings);
    db.all("plan_items").filter(i => i.session_id === sessionId && !i.target_source).forEach(it => {
      if (!["main", "accessory", "core"].includes(it.section) || !it.exercise_id) return;
      const ex = exOf(db, it.exercise_id); if (!ex) return;
      const t = targetFor(db, ex, it, today, isDeload, null, exByKey, bw);
      db.update("plan_items", it.id, { target_weight: t.weight, target_source: t.source });
    });
  }
  const weekForDate = (db, d) => db.all("plan_weeks").filter(w => w.start_date <= d && addDays(w.start_date, 6) >= d).sort((a, b) => b.start_date.localeCompare(a.start_date))[0] || null;
  function sessionView(db, session, today, settings, prog, exByKey, bw, withTargets = true, excludeCid = null) {
    const s = Object.assign({}, session);
    const week = db.get("plan_weeks", s.week_id);
    const isDeload = !!(week && week.is_deload), protos = protocolsById(prog);
    let total = 0;
    s.items = db.all("plan_items").filter(i => i.session_id === s.id).sort((a, b) => a.ord - b.ord).map(i => {
      const it = Object.assign({}, i);
      const ex = it.exercise_id ? exOf(db, it.exercise_id) : null;
      it.exercise = ex ? Object.assign({}, ex) : null;
      it.est_minutes = Math.round(estMinutes(it, prog.set_overhead_sec || 40) * 10) / 10;
      total += it.est_minutes;
      if (it.protocol && protos[it.protocol]) { const p = protos[it.protocol]; it.protocol_text = p.text; it.protocol_detail = { work_sec: p.work_sec, rest_sec: p.rest_sec, intensity: p.intensity, machine: p.machine }; }
      if (withTargets && ex && ["main", "accessory", "core"].includes(it.section)) {
        const t = targetFor(db, ex, it, today, isDeload, excludeCid, exByKey, bw);
        it.target = it.target_source ? { weight: it.target_weight, source: it.target_source, last: t.last, text: targetText(ex, it.target_weight, it.target_source, it.rep_low || 8, it.rep_high || 12) } : t;
      }
      return it;
    });
    s.est_minutes = Math.round(total * 10) / 10;
    s.is_deload = isDeload;
    s.week_no = week ? week.week_no : null;
    const w = db.all("workouts").filter(x => x.session_id === s.id).sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)))[0];
    s.workout = w ? { client_id: w.client_id, started_at: w.started_at, ended_at: w.ended_at, effort: w.effort, kcal_est: w.kcal_est, kcal_wearable: w.kcal_wearable, volume: w.volume, work_sets: w.work_sets } : null;
    return s;
  }
  function weekView(db, d, today, settings, prog, exByKey) {
    const week = weekForDate(db, d); if (!week) return null;
    const block = db.get("blocks", week.block_id);
    const bw = bodyweightOn(db, today, settings);
    const sessions = db.all("plan_sessions").filter(s => s.week_id === week.id).sort((a, b) => a.date.localeCompare(b.date)).map(s => sessionView(db, s, today, settings, prog, exByKey, bw));
    const planned = sessions.filter(s => countsForAdherence(s.kind) && s.status !== "void");
    const ts = trainSettings(settings), splitDef = (prog.splits || {})[ts.split] || null;
    return { week: Object.assign({}, week, { block_no: block.block_no, block_seed: block.seed }), sessions, split: ts.split, split_name: splitDef ? splitDef.name : "Upper / Lower", weeks_in_block: db.all("plan_weeks").filter(w => w.block_id === week.block_id).length, adherence: { done: planned.filter(s => s.status === "done").length, planned: planned.length } };
  }
  function adherenceByWeek(db) {
    const out = {};
    db.all("plan_sessions").filter(s => countsForAdherence(s.kind) && s.status !== "void").forEach(s => {
      const w = db.get("plan_weeks", s.week_id); if (!w) return;
      const b = db.get("blocks", w.block_id);
      const o = out[w.id] = out[w.id] || { week: w.start_date, block_no: b ? b.block_no : null, week_no: w.week_no, done: 0, planned: 0 };
      o.planned++; if (s.status === "done") o.done++;
    });
    return Object.values(out).sort((a, b) => a.week.localeCompare(b.week));
  }

  return {
    isoOf, D, addDays, daysBetween, mondayOf, nowIso, crc32,
    NUTRITION_DEFAULTS, TRAIN_DEFAULTS, LIFTING_KINDS, ADHERENCE_KINDS, PlanError,
    ageOn, trendWeight, paceWeight, weeklyPace, paceVerdict, bmr, profileComplete, targets, foodLogValues,
    roundLoad, setLoad, setVolume, e1rm, hardRatio, liftingMet, cardioMet, kcal, liftMinutes, effortScore, cardioEffort,
    bodyLogs, bodyweightOn, recomputeWorkout, historyForExercise, bestsForExercise, prsForWorkout, weeklyMuscleSets, weeklyE1rm, strengthIndex,
    validateSeed, protocolsById, protocolMinutes, trainSettings, templateFor, isLifting, pick, estMinutes, sessionMinutes, trimToBudget,
    createBlock, ensurePlanThrough, sweepMissed, rebuildWeek, shuffleWeek, regenerateFrom, swapItem, moveSession, markRest,
    progression, targetFor, targetText, freezeTargets, weekForDate, sessionView, weekView, adherenceByWeek,
  };
})();
if (typeof module !== "undefined") module.exports = Engine;
