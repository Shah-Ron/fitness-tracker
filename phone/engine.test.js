"use strict";
/* Tests for the phone engine (phone/engine.js).

   Run from the project folder:  node --test phone/engine.test.js

   Node's built-in runner, no packages. One describe block per module, mirroring
   tests.py: nutrition (targets, trend, pace), programme (rules, rotation, blocks,
   trimming, session management) and effort (per-set maths, calories, the effort
   score, PRs, aggregates). Database tests run on a tiny in-memory fake of the
   store.js model, seeded from data\exercises.json the way store.js seeds it.
   Every engine call takes the fixed date TODAY, Thursday 24 September 2026;
   nothing here calls new Date() for a date. */

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const E = require("./engine.js");

const ROOT = path.join(__dirname, "..");
const readJson = p => JSON.parse(fs.readFileSync(p, "utf8"));
const EXJ = readJson(path.join(ROOT, "data", "exercises.json"));
const PROG = readJson(path.join(ROOT, "data", "programme.json"));
const EXJ_BY_KEY = Object.fromEntries(EXJ.exercises.map(e => [e.key, e]));

const TODAY = "2026-09-24";            // a Thursday
const MONDAY = "2026-09-21";           // the Monday of that week
const day = n => E.addDays(TODAY, n);
const monday = n => E.addDays(MONDAY, n);

// The fixture person: an 80 kg, 180 cm, 30-year-old man losing 8 kg in 100 days.
const MAN = {
  sex: "m", birth_date: "1996-03-15", height_cm: 180, start_weight_kg: 80,
  target_weight_kg: 72, target_date: day(100), goal_start_weight: 80, goal_start_date: TODAY,
};

/* ----------------------------------------------------------------- fixtures */

function settingsFor(over = {}) {
  return Object.assign({}, E.NUTRITION_DEFAULTS, E.TRAIN_DEFAULTS, { train_days: [1, 2, 3, 4, 5], programme_start: TODAY }, MAN, over);
}
const targets = ({ weight = 80, exercise = 0, eaten = 0, ...over } = {}) => E.targets(settingsFor(over), weight, TODAY, exercise, eaten);

/* A stand-in for the store.js model: Maps per collection, an id counter for
   collections keyed by "id", UUIDs for those keyed by "client_id". */
const CLIENT_KEYED = new Set(["workouts", "set_logs", "cardio_logs", "food_logs", "body_logs", "daily_logs"]);
function makeDb() {
  const mem = new Map(), settings = {};
  let nextId = 1;
  const coll = c => { if (!mem.has(c)) mem.set(c, new Map()); return mem.get(c); };
  const keyOf = c => (CLIENT_KEYED.has(c) ? "client_id" : "id");
  return {
    all: c => Array.from(coll(c).values()),
    get: (c, k) => coll(c).get(k) || null,
    insert(c, row) {
      const k = keyOf(c);
      if (row[k] == null) row[k] = k === "id" ? nextId++ : crypto.randomUUID();
      coll(c).set(row[k], row);
      return row;
    },
    update(c, k, patch) { const row = coll(c).get(k); if (!row) return null; Object.assign(row, patch); return row; },
    remove: (c, k) => coll(c).delete(k),
    settings: () => Object.assign({}, settings),
    setSetting(k, v) { settings[k] = v; },
  };
}

function seedExercises(db) {
  EXJ.exercises.forEach(ex => db.insert("exercises", {
    key: ex.key, name: ex.name, pattern: ex.pattern, primary_muscle: ex.primary_muscle, secondary_muscles: ex.secondary_muscles || [],
    equipment: ex.equipment, per_hand: ex.per_hand ? 1 : 0, timed: ex.timed ? 1 : 0, unilateral: ex.unilateral ? 1 : 0,
    bodyweight_fraction: +(ex.bodyweight_fraction || 0), increment_kg: ex.increment_kg ?? null, min_load_kg: ex.min_load_kg ?? null,
    variation_of: ex.variation_of || null, carry: ex.carry ?? null, mets: ex.mets || null, cues: ex.cues || [], is_custom: 0, active: 1,
  }));
}

/** A private seeded db, its exByKey index and the fixture settings (plus overrides). */
function fresh(over = {}) {
  const db = makeDb();
  seedExercises(db);
  const exByKey = Object.fromEntries(db.all("exercises").map(e => [e.key, e]));
  const settings = settingsFor(over);
  Object.entries(settings).forEach(([k, v]) => db.setSetting(k, v));
  return { db, exByKey, settings };
}

/** A workout row on a day, finished unless told otherwise. Marks its session done. */
function addWorkout(db, date, sessionId = null, ended = true, extra = {}) {
  const w = db.insert("workouts", Object.assign({
    client_id: crypto.randomUUID(), session_id: sessionId, date, started_at: `${date}T18:00:00`, ended_at: ended ? `${date}T19:00:00` : null,
    session_rpe: null, work_sets: 0, hard_sets: 0, volume: 0, lift_minutes: 0, kcal_est: 0, kcal_wearable: null, hr_avg: null,
    effort: null, effort_parts: null, notes: null,
  }, extra));
  if (sessionId && ended) db.update("plan_sessions", sessionId, { status: "done" });
  return w.client_id;
}

/** Working sets of one exercise; rows are [reps, weight_kg, rpe]. */
function addSets(db, exByKey, wcid, key, rows, planItemId = null) {
  rows.forEach(([reps, weight, rpe], i) => db.insert("set_logs", {
    client_id: crypto.randomUUID(), workout_client_id: wcid, plan_item_id: planItemId, exercise_id: exByKey[key].id,
    set_no: i + 1, reps, weight_kg: weight, rpe, is_warmup: 0, done_at: null,
  }));
}

const repeat = (row, n) => Array.from({ length: n }, () => row.slice());
const weeks = db => db.all("plan_weeks").sort((a, b) => a.start_date.localeCompare(b.start_date));
const sessionsOf = (db, weekId) => db.all("plan_sessions").filter(s => s.week_id === weekId).sort((a, b) => a.date.localeCompare(b.date));
const sessionOn = (db, date) => db.all("plan_sessions").find(s => s.date === date);
const kindOf = (db, weekId, kind) => sessionsOf(db, weekId).find(s => s.kind === kind);
const itemsOf = (db, sessionId) => db.all("plan_items").filter(i => i.session_id === sessionId).sort((a, b) => a.ord - b.ord)
  .map(i => Object.assign({}, i, { exercise_key: i.exercise_id ? (db.get("exercises", i.exercise_id) || {}).key || null : null }));
const item = (items, slot) => items.find(i => i.slot_key === slot);
const sets = rows => rows.map(([reps, weight_kg, rpe]) => ({ reps, weight_kg, rpe }));
/** Run the progression rule on an exercise from exercises.json; returns [weight, label]. */
const rule = (key, rows, lo = 6, hi = 10, planned = 3) => { const p = E.progression(EXJ_BY_KEY[key], sets(rows), lo, hi, planned); return [p.weight, p.label]; };
const makeBlock = (db, settings, exByKey, start = MONDAY) => E.createBlock(db, start, settings, PROG, exByKey);
/** Blocks from MONDAY covering nWeeks, created through ensurePlanThrough. */
function planWeeks(db, settings, exByKey, nWeeks) {
  settings.programme_start = MONDAY;
  E.ensurePlanThrough(db, MONDAY, settings, PROG, exByKey);
  E.ensurePlanThrough(db, monday(7 * nWeeks - 1), settings, PROG, exByKey);
  return weeks(db);
}
const ITEM = { rep_low: 6, rep_high: 10, sets: 3 };
/** The code of the PlanError fn throws, or null when it does not throw. */
function errorCode(fn) {
  try { fn(); } catch (e) { if (e instanceof E.PlanError) return e.code; throw e; }
  return null;
}

function planItem(ord, section, slot, kw = {}) {
  return Object.assign({ ord, section, slot_key: slot, exercise_key: null, sets: null, rep_low: null, rep_high: null, rest_sec: null,
    minutes: null, protocol: null, rounds: null, optional: 0, note: null }, kw);
}
/** The default Upper day before trimming: 58.0 minutes with a 10-minute finisher. */
function upperItems() {
  return [
    planItem(1, "warmup", "wu_cardio", { minutes: 5, protocol: "warm_easy_5" }),
    planItem(2, "warmup", "wu_dynamic", { minutes: 2 }),
    planItem(3, "main", "main1", { sets: 3, rest_sec: 150 }),
    planItem(4, "main", "main2", { sets: 3, rest_sec: 90 }),
    planItem(5, "accessory", "acc1", { sets: 3, rest_sec: 60 }),
    planItem(6, "accessory", "acc2", { sets: 3, rest_sec: 60 }),
    planItem(7, "accessory", "acc3", { sets: 3, rest_sec: 60 }),
    planItem(8, "accessory", "acc4", { sets: 3, rest_sec: 60, optional: 1 }),
    planItem(9, "finisher", "finisher", { minutes: 10, protocol: "fin_tread_incline_walk" }),
    planItem(10, "cooldown", "cooldown", { minutes: 3 }),
  ];
}

/* ================================================================ nutrition */

describe("nutrition", () => {
  it("bmr: Mifflin-St Jeor for the fixture man is 1780", () => {
    assert.equal(E.bmr("m", 80, 180, 30), 1780);
  });

  it("bmr: a 60 kg, 165 cm, 28-year-old woman is 1330.25", () => {
    assert.equal(E.bmr("f", 60, 165, 28), 1330.25);
  });

  it("ageOn floors partial years", () => {
    assert.equal(E.ageOn("1996-03-15", TODAY), 30);
    assert.equal(E.ageOn("1996-09-25", TODAY), 29);
  });

  it("maintenance is bmr x 1.3 = 2314", () => {
    const t = targets();
    assert.equal(t.bmr, 1780);
    assert.equal(t.base, 2314);
  });

  it("deficit within the cap: 8 kg in 100 days needs 616 a day", () => {
    const t = targets();
    assert.equal(t.deficit, 616);
    assert.equal(t.mode, "losing");
    assert.equal(t.capped, false);
    assert.equal(t.eta, null);
  });

  it("deficit clamped to 750 lands 83 days out", () => {
    const t = targets({ target_date: day(50) });
    assert.equal(t.deficit, 750);
    assert.equal(t.capped, true);
    assert.equal(t.eta, day(83));
    assert.equal(t.target_passed, false);
  });

  it("a passed target date keeps the capped figures and says so", () => {
    const t = targets({ target_date: day(-1) });
    assert.equal(t.deficit, 750);
    assert.equal(t.capped, true);
    assert.equal(t.target_passed, true);
  });

  it("surplus capped at 300 with an eta 154 days out", () => {
    const t = targets({ weight: 70, goal_start_weight: 70, target_weight_kg: 76, target_date: day(30) });
    assert.equal(t.deficit, -300);
    assert.equal(t.mode, "gaining");
    assert.equal(t.capped, true);
    assert.equal(t.eta, day(154));
  });

  it("within 0.3 kg of target is maintaining", () => {
    const t = targets({ target_weight_kg: 79.8 });
    assert.equal(t.deficit, 0);
    assert.equal(t.mode, "maintaining");
    assert.equal(t.capped, false);
  });

  it("budget with no workout is 1698", () => {
    const t = targets({ eaten: 500 });
    assert.equal(t.budget, 1698);
    assert.equal(t.left, 1198);
    assert.equal(t.floored, false);
  });

  it("budget after a 350 kcal session is 2048", () => {
    assert.equal(targets({ exercise: 350 }).budget, 2048);
  });

  it("a wearable figure of 420 replaces the estimate: budget 2118", () => {
    assert.equal(targets({ exercise: 420 }).budget, 2118);
  });

  it("budget held at the 1500 floor for a man", () => {
    const t = targets({ deficit_cap: 914, target_date: day(50) });
    assert.equal(t.deficit, 914);
    assert.equal(t.budget, 1500);
    assert.equal(t.floored, true);
  });

  it("floor defaults to 1200 for a woman", () => {
    const t = targets({ weight: 60, sex: "f", birth_date: "1998-03-15", height_cm: 165, goal_start_weight: 60, target_weight_kg: 52, target_date: day(30) });
    assert.equal(t.floor, 1200);
    assert.equal(t.budget, 1200);
    assert.equal(t.floored, true);
  });

  it("default macros are protein 160, fat 64, carbs 120.5", () => {
    const t = targets();
    assert.deepEqual([t.protein, t.fat, t.carbs], [160, 64, 120.5]);
  });

  it("carb floor holds carbs at 50 and drops fat to 55.6", () => {
    const t = targets({ weight: 100, goal_start_weight: 100, target_weight_kg: 90, target_date: day(50), deficit_cap: 1074 });
    assert.equal(t.budget, 1500);
    assert.deepEqual([t.protein, t.carbs, t.fat], [200, 50, 55.6]);
  });

  it("an incomplete profile gives no numbers", () => {
    assert.deepEqual(E.targets(settingsFor({ height_cm: null }), 80, TODAY), { complete: false });
    assert.equal(E.targets(settingsFor(), null, TODAY).complete, false);
  });

  it("trend falls back to the start weight, then to nothing", () => {
    assert.deepEqual(E.trendWeight([], TODAY, 80), { weight: 80, source: "start" });
    assert.deepEqual(E.trendWeight([], TODAY, null), { weight: null, source: "none" });
  });

  it("trend is the seven-day mean", () => {
    const logs = [{ date: day(-2), weight: 80 }, { date: day(-1), weight: 81 }, { date: TODAY, weight: 79 }];
    assert.deepEqual(E.trendWeight(logs, TODAY, 70), { weight: 80, source: "trend" });
    // a log seven days back is outside the window; six days back is inside it
    assert.deepEqual(E.trendWeight(logs.concat({ date: day(-7), weight: 100 }), TODAY, 70), { weight: 80, source: "trend" });
    assert.deepEqual(E.trendWeight(logs.concat({ date: day(-6), weight: 84 }), TODAY, 70), { weight: 81, source: "trend" });
  });

  it("trend carries the latest log forward when the window is empty", () => {
    const logs = [{ date: day(-20), weight: 82 }, { date: day(-10), weight: 81.5 }, { date: day(1), weight: 70 }];
    assert.deepEqual(E.trendWeight(logs, TODAY, 80), { weight: 81.5, source: "latest" });
  });

  it("pace line: midpoint 76.0, clamped to the goal interval, weekly pace -0.56", () => {
    const s = settingsFor();
    assert.equal(E.paceWeight(s, day(50)), 76);
    assert.equal(E.paceWeight(s, day(-5)), 80);
    assert.equal(E.paceWeight(s, day(200)), 72);
    assert.equal(E.weeklyPace(s), -0.56);
  });

  it("verdict on pace within 0.5 kg", () => {
    assert.equal(E.paceVerdict(80.0, 79.5, 3, 80, 72).code, "on_pace");
  });

  it("verdict behind by 1.1 kg", () => {
    const v = E.paceVerdict(80.6, 79.5, 3, 80, 72);
    assert.equal(v.code, "behind");
    assert.equal(v.text.toLowerCase(), "behind by 1.1 kg");
  });

  it("verdict flips for a gain goal", () => {
    assert.equal(E.paceVerdict(73.0, 72.0, 5, 70, 76).code, "ahead");
    assert.equal(E.paceVerdict(72.0, 73.0, 5, 70, 76).code, "behind");
    assert.equal(E.paceVerdict(78.0, 79.5, 5, 80, 72).text.toLowerCase(), "ahead by 1.5 kg");
  });

  it("verdict needs three logs in the last 14 days", () => {
    assert.equal(E.paceVerdict(80.6, 79.5, 2, 80, 72).code, "no_data");
    assert.equal(E.paceVerdict(null, 79.5, 5, 80, 72).code, "no_data");
  });
});

/* ================================================================ programme */

describe("programme", () => {
  describe("rounding and progression", () => {
    it("roundLoad rounds half up to 2.5 kg", () => {
      assert.equal(E.roundLoad(41.25, "barbell"), 42.5);
      assert.equal(E.roundLoad(41.24, "barbell"), 40);
      assert.equal(E.roundLoad(43.75), 45);
    });

    it("roundLoad uses 1 kg steps for dumbbells under 10 kg", () => {
      assert.equal(E.roundLoad(7.6, "dumbbell"), 8);
      assert.equal(E.roundLoad(7.4, "dumbbell"), 7);
      assert.equal(E.roundLoad(11.3, "dumbbell"), 12.5);
    });

    it("increase upper: 3 x 10 at 40 goes to 42.5", () => {
      assert.deepEqual(rule("barbell_bench_press", [[10, 40, 7], [10, 40, 7], [10, 40, 8]]), [42.5, "increase"]);
    });

    it("increase lower: squat and hinge patterns on a bar go up 5 kg", () => {
      assert.deepEqual(rule("back_squat", repeat([10, 60, 8], 3)), [65, "increase"]);
      assert.deepEqual(rule("trap_bar_deadlift", repeat([10, 80, 8], 3)), [85, "increase"]);
    });

    it("hold_reps when the top of the range is not reached", () => {
      assert.deepEqual(rule("barbell_bench_press", repeat([8, 40, 7], 3)), [40, "hold_reps"]);
    });

    it("hold_rpe when every set hit the top but the mean RPE is over 8.5", () => {
      assert.deepEqual(rule("barbell_bench_press", repeat([10, 40, 9], 3)), [40, "hold_rpe"]);
    });

    it("decrease_reps when a set fell below the range", () => {
      assert.deepEqual(rule("barbell_bench_press", [[10, 40, 8], [8, 40, 8], [5, 40, 9]]), [37.5, "decrease_reps"]);
    });

    it("decrease_rpe on two sets at RPE 9.5 or more", () => {
      assert.deepEqual(rule("barbell_bench_press", [[10, 40, 9.5], [10, 40, 10], [10, 40, 8]]), [37.5, "decrease_rpe"]);
    });

    it("a decrease is at least one plate step: cable 10 kg goes to 7.5", () => {
      assert.deepEqual(rule("cable_pushdown", [[12, 10, 8], [10, 10, 9], [7, 10, 10]], 10, 15), [7.5, "decrease_reps"]);
    });

    it("a barbell never drops below 20 kg", () => {
      assert.deepEqual(rule("barbell_bench_press", [[6, 20, 9], [5, 20, 10], [4, 20, 10]]), [20, "decrease_reps"]);
    });

    it("hold_partial when fewer sets than planned were done", () => {
      assert.deepEqual(rule("barbell_bench_press", [[10, 40, 7], [10, 40, 7]]), [40, "hold_partial"]);
    });

    it("missing RPE is neutral: 3 x 10 with no RPE still increases", () => {
      assert.deepEqual(rule("barbell_bench_press", repeat([10, 40, null], 3)), [42.5, "increase"]);
    });

    it("dumbbell steps: 8 kg goes to 9, 10 kg goes to 12.5", () => {
      assert.deepEqual(rule("db_lateral_raise", repeat([15, 8, 7], 3), 10, 15), [9, "increase"]);
      assert.deepEqual(rule("db_lateral_raise", repeat([15, 10, 7], 3), 10, 15), [12.5, "increase"]);
    });

    it("assisted lifts invert: less help on success, more on failure", () => {
      assert.deepEqual(rule("assisted_pull_up", repeat([12, 30, 7], 3), 8, 12), [27.5, "increase"]);
      assert.deepEqual(rule("assisted_pull_up", [[12, 30, 7], [6, 30, 9], [5, 30, 10]], 8, 12), [32.5, "decrease_reps"]);
    });

    it("timed moves add seconds when every hold reaches the top", () => {
      assert.deepEqual(rule("plank", repeat([60, null, 7], 3), 30, 60), [null, "add_time"]);
      assert.deepEqual(rule("plank", repeat([45, null, 7], 3), 30, 60), [null, "hold_time"]);
    });

    it("pure bodyweight moves add reps when every set reaches the top", () => {
      assert.deepEqual(rule("push_up", repeat([15, null, 7], 3), 10, 15), [null, "add_reps"]);
      assert.deepEqual(rule("push_up", repeat([12, null, 7], 3), 10, 15), [null, "hold_reps"]);
    });

    it("no sets is a first exposure", () => {
      assert.deepEqual(rule("barbell_bench_press", []), [null, "first"]);
    });
  });

  describe("targets against the database", () => {
    it("skips the deload week as a progression reference", () => {
      const { db, exByKey, settings } = fresh({ programme_start: MONDAY });
      makeBlock(db, settings, exByKey);
      const wk = weeks(db);
      assert.deepEqual(wk.map(w => w.is_deload), [0, 0, 0, 1]);
      const s3 = kindOf(db, wk[2].id, "lower_a"), s4 = kindOf(db, wk[3].id, "lower_a");
      const w3 = addWorkout(db, s3.date, s3.id);
      addSets(db, exByKey, w3, "back_squat", repeat([10, 60, 8], 3));
      const w4 = addWorkout(db, s4.date, s4.id);
      addSets(db, exByKey, w4, "back_squat", repeat([10, 55, 7], 3));
      const t = E.targetFor(db, exByKey.back_squat, ITEM, "2026-10-20", false, null, exByKey, 80);
      assert.deepEqual([t.weight, t.source], [65, "increase"]);
      assert.equal(t.last.date, s3.date);
    });

    it("first exposure is blank with a find-your-weight hint", () => {
      const { db, exByKey } = fresh();
      const t = E.targetFor(db, exByKey.barbell_bench_press, ITEM, TODAY, false, null, exByKey, 80);
      assert.deepEqual([t.weight, t.source, t.last], [null, "first", null]);
      assert.match(t.text, /8 reps/);
    });

    it("increase after 3 x 10 at 40 RPE 7 gives 42.5", () => {
      const { db, exByKey } = fresh();
      const w = addWorkout(db, day(-7));
      addSets(db, exByKey, w, "barbell_bench_press", repeat([10, 40, 7], 3));
      const t = E.targetFor(db, exByKey.barbell_bench_press, ITEM, TODAY, false, null, exByKey, 80);
      assert.deepEqual([t.weight, t.source], [42.5, "increase"]);
      assert.equal(t.last.date, day(-7));
      assert.equal(t.last.sets.length, 3);
    });

    it("guess from a variation: flat bench e1RM 100 gives incline 67.5 at rep_low 6", () => {
      const { db, exByKey } = fresh();
      const w = addWorkout(db, day(-7));
      addSets(db, exByKey, w, "barbell_bench_press", [[10, 75, 8]]);      // e1RM exactly 100
      const t = E.targetFor(db, exByKey.incline_barbell_bench_press, ITEM, TODAY, false, null, exByKey, 80);
      assert.deepEqual([t.weight, t.source], [67.5, "guess"]);
    });

    it("a reference older than 28 days holds the last weight as stale", () => {
      const { db, exByKey } = fresh();
      const w = addWorkout(db, day(-40));
      addSets(db, exByKey, w, "barbell_bench_press", repeat([10, 40, 7], 3));
      const ex = exByKey.barbell_bench_press;
      let t = E.targetFor(db, ex, ITEM, TODAY, false, null, exByKey, 80);
      assert.deepEqual([t.weight, t.source], [40, "stale"]);
      // exactly 28 days old is still fresh
      t = E.targetFor(db, ex, ITEM, day(-12), false, null, exByKey, 80);
      assert.deepEqual([t.weight, t.source], [42.5, "increase"]);
    });

    it("deload target is 90 per cent of normal: 42.5 becomes 37.5", () => {
      const { db, exByKey } = fresh();
      const w = addWorkout(db, day(-7));
      addSets(db, exByKey, w, "barbell_bench_press", repeat([10, 40, 7], 3));
      const t = E.targetFor(db, exByKey.barbell_bench_press, ITEM, TODAY, true, null, exByKey, 80);
      assert.deepEqual([t.weight, t.source], [37.5, "deload"]);
    });
  });

  describe("rotation", () => {
    it("pick is deterministic for the same seed and slot", () => {
      const pool = ["a", "b", "c"];
      assert.equal(E.pick(pool, "seed:1", "upper_a:acc1"), E.pick(pool, "seed:1", "upper_a:acc1"));
      assert.equal(E.pick(pool, "seed:1", "upper_a:acc1", "b"), E.pick(pool, "seed:1", "upper_a:acc1", "b"));
    });

    it("pick never repeats the previous member when the pool is bigger than one", () => {
      const pool = ["a", "b", "c"];
      for (let i = 0; i < 60; i++) assert.notEqual(E.pick(pool, `s${i}:2`, "lower_a:acc1", "b"), "b");
    });

    it("a pool of two alternates strictly", () => {
      let prev = null;
      const seq = [];
      for (let i = 0; i < 6; i++) { prev = E.pick(["A", "B"], `x:${i}`, "slot", prev); seq.push(prev); }
      assert.notEqual(seq[0], seq[1]);
      assert.deepEqual(seq, [seq[0], seq[1], seq[0], seq[1], seq[0], seq[1]]);
    });

    it("a pool of one is constant and an empty pool gives null", () => {
      assert.equal(E.pick(["only"], "s:1", "slot", "only"), "only");
      assert.equal(E.pick([], "s:1", "slot"), null);
    });

    function fourBlocks() {
      const { db, exByKey, settings } = fresh({ programme_start: MONDAY });
      const main1 = [], main2 = [];
      for (let b = 0; b < 4; b++) {
        const block = makeBlock(db, settings, exByKey, monday(28 * b));
        assert.equal(block.block_no, b + 1);
        const its = itemsOf(db, kindOf(db, weeks(db)[4 * b].id, "upper_a").id);
        main1.push(item(its, "main1").exercise_key);
        main2.push(item(its, "main2").exercise_key);
      }
      return { main1, main2 };
    }

    it("Main 1 swaps every two blocks", () => {
      assert.deepEqual(fourBlocks().main1, ["barbell_bench_press", "barbell_bench_press", "incline_barbell_bench_press", "incline_barbell_bench_press"]);
    });

    it("Main 2 alternates every block", () => {
      assert.deepEqual(fourBlocks().main2, ["lat_pulldown", "seated_cable_row", "lat_pulldown", "seated_cable_row"]);
    });
  });

  describe("blocks and layout", () => {
    it("five days: Mon upper_a, Tue lower_a, Wed conditioning, Thu upper_b, Fri lower_b, weekend rest", () => {
      const { db, exByKey, settings } = fresh({ programme_start: MONDAY });
      makeBlock(db, settings, exByKey);
      const week = sessionsOf(db, weeks(db)[0].id);
      assert.deepEqual(week.map(s => s.kind), ["upper_a", "lower_a", "conditioning", "upper_b", "lower_b", "rest", "rest"]);
      assert.equal(week[0].date, MONDAY);
      assert.equal(week[0].title, "Upper A");
    });

    it("six days: zone2 on Saturday, 35 minutes, on a machine other than the conditioning one", () => {
      const { db, exByKey, settings } = fresh({ programme_start: MONDAY, train_days: [1, 2, 3, 4, 5, 6] });
      makeBlock(db, settings, exByKey);
      const week = sessionsOf(db, weeks(db)[0].id);
      assert.deepEqual(week.map(s => s.kind).slice(5), ["zone2", "rest"]);
      const z = itemsOf(db, week[5].id);
      assert.equal(z.length, 1);
      assert.deepEqual([z[0].protocol, z[0].minutes], ["zone2_steady", 35]);
      const condMachine = item(itemsOf(db, week[2].id), "wu_cardio").exercise_key;
      assert.notEqual(z[0].exercise_key, condMachine);
    });

    it("createBlock on the Thursday: starts Monday, 4 weeks x 7 sessions, Mon to Wed void, week 4 deload", () => {
      const { db, exByKey, settings } = fresh();               // programme_start is TODAY
      const block = makeBlock(db, settings, exByKey, TODAY);
      assert.equal(block.start_date, MONDAY);
      assert.equal(block.block_no, 1);
      const wk = weeks(db);
      assert.equal(wk.length, 4);
      assert.deepEqual(wk.map(w => w.start_date), [MONDAY, monday(7), monday(14), monday(21)]);
      assert.deepEqual(wk.map(w => w.seed), wk.map((w, i) => `${block.seed}:${i + 1}`));
      assert.deepEqual(wk.map(w => w.is_deload), [0, 0, 0, 1]);
      wk.forEach(w => assert.equal(sessionsOf(db, w.id).length, 7));
      const week1 = sessionsOf(db, wk[0].id);
      assert.deepEqual(week1.map(s => s.status), ["void", "void", "void", "planned", "planned", "planned", "planned"]);
      assert.deepEqual(week1.map(s => s.kind), ["upper_a", "lower_a", "conditioning", "upper_b", "lower_b", "rest", "rest"]);
      assert.equal(item(itemsOf(db, kindOf(db, wk[3].id, "upper_a").id), "main1").sets, 2);
    });

    it("deload week: one set fewer, rep ranges unchanged, finisher at its minimum", () => {
      const { db, exByKey, settings } = fresh({ programme_start: MONDAY });
      makeBlock(db, settings, exByKey);
      const wk = weeks(db);
      const ua1 = itemsOf(db, kindOf(db, wk[0].id, "upper_a").id);
      const ua4 = itemsOf(db, kindOf(db, wk[3].id, "upper_a").id);
      assert.equal(item(ua1, "main1").sets, 3);
      assert.equal(item(ua4, "main1").sets, 2);
      assert.equal(item(ua4, "acc1").sets, 2);
      assert.deepEqual([item(ua4, "main1").rep_low, item(ua4, "main1").rep_high], [6, 10]);
      const fin = item(ua4, "finisher");
      const proto = E.protocolsById(PROG)[fin.protocol];
      assert.equal(fin.minutes, E.protocolMinutes(proto, true));
    });

    it("every lifting session over 12 weeks (three blocks), five and six day layouts, fits 60 minutes", () => {
      for (const days of [[1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 6]]) {
        const { db, exByKey, settings } = fresh({ train_days: days });
        const wks = planWeeks(db, settings, exByKey, 12);
        assert.equal(wks.length, 12);
        assert.equal(db.all("blocks").length, 3);
        for (const wk of wks) {
          for (const sess of sessionsOf(db, wk.id)) {
            if (!E.isLifting(sess.kind, PROG)) continue;
            const est = E.sessionMinutes(itemsOf(db, sess.id), PROG.set_overhead_sec);
            assert.ok(est <= 60, `${sess.kind} on ${sess.date} takes ${est} min`);
          }
        }
      }
    });
  });

  describe("time budget", () => {
    it("default estimates: Main 1 11.5, accessory 5, finisher by minutes, upper day 58.0", () => {
      assert.equal(E.estMinutes({ slot_key: "main1", sets: 3, rest_sec: 150 }), 11.5);
      assert.equal(E.estMinutes({ slot_key: "acc1", sets: 3, rest_sec: 60 }), 5);
      assert.equal(E.estMinutes({ slot_key: "finisher", minutes: 10, sets: 8 }), 10);
      assert.equal(E.sessionMinutes(upperItems()), 58);
    });

    it("trim drops the optional accessory first", () => {
      const out = E.trimToBudget(upperItems(), 55, PROG);
      assert.ok(!out.some(i => i.slot_key === "acc4"));
      assert.deepEqual(out.filter(i => ["main", "accessory"].includes(i.section)).map(i => i.sets), [3, 3, 3, 3, 3]);
      assert.equal(item(out, "finisher").minutes, 10);
      assert.equal(E.sessionMinutes(out), 53);
    });

    it("at 50 minutes the finisher hits its minimum before acc3 loses a set", () => {
      const out = E.trimToBudget(upperItems(), 50, PROG);
      assert.equal(item(out, "finisher").minutes, 8);
      assert.equal(item(out, "acc3").sets, 2);
      assert.deepEqual([item(out, "acc1").sets, item(out, "acc2").sets], [3, 3]);
      assert.deepEqual([item(out, "main1").sets, item(out, "main2").sets], [3, 3]);
      assert.ok(E.sessionMinutes(out) <= 50);
    });

    it("trimming never touches warm-up, mains or cool-down", () => {
      const out = E.trimToBudget(upperItems(), 30, PROG);
      assert.deepEqual(out.map(i => i.slot_key), ["wu_cardio", "wu_dynamic", "main1", "main2", "acc1", "acc2", "cooldown"]);
      assert.deepEqual([item(out, "main1").sets, item(out, "main2").sets], [3, 3]);
      assert.equal(item(out, "main1").note, "trimmed for time");
    });
  });

  describe("variety", () => {
    it("no rotating slot repeats in consecutive weeks over 12 weeks", () => {
      const { db, exByKey, settings } = fresh();
      const wks = planWeeks(db, settings, exByKey, 12);
      const rotate = new Set(["acc1", "acc2", "acc3", "acc4", "core1", "circ1", "circ2", "circ3", "cond"]);
      let prev = null;
      for (const wk of wks) {
        const cur = new Map();
        for (const sess of sessionsOf(db, wk.id)) {
          for (const it of itemsOf(db, sess.id)) {
            if (rotate.has(it.slot_key)) cur.set(`${sess.kind}/${it.slot_key}`, it.exercise_key || it.protocol);
            if (sess.kind === "conditioning" && it.slot_key === "wu_cardio") cur.set("conditioning/machine", it.exercise_key);
          }
        }
        assert.equal(cur.size, 4 * 4 + 4 + 1);
        if (prev) for (const [k, v] of cur) if (prev.has(k)) assert.notEqual(v, prev.get(k), `${k} repeated in the week of ${wk.start_date}`);
        prev = cur;
      }
    });

    it("the finisher never repeats between consecutive lifting sessions and matches the warm-up machine", () => {
      const { db, exByKey, settings } = fresh();
      const wks = planWeeks(db, settings, exByKey, 8);
      for (const wk of wks) {
        const lifting = sessionsOf(db, wk.id).filter(s => E.isLifting(s.kind, PROG));
        const protos = lifting.map(s => item(itemsOf(db, s.id), "finisher").protocol);
        assert.equal(protos.length, 4);
        protos.slice(1).forEach((p, i) => assert.notEqual(p, protos[i], `finisher ${p} repeated in the week of ${wk.start_date}`));
        lifting.forEach(s => {
          const its = itemsOf(db, s.id);
          assert.equal(item(its, "wu_cardio").exercise_key, item(its, "finisher").exercise_key);
        });
      }
    });
  });

  describe("managing sessions", () => {
    const block = over => { const f = fresh(Object.assign({ programme_start: MONDAY }, over)); makeBlock(f.db, f.settings, f.exByKey); return f; };

    it("shuffle leaves a done session alone, rebuilds the rest and cascades to later weeks", () => {
      const { db, exByKey, settings } = block();
      const [w1, w2] = weeks(db);
      const seed1 = w1.seed, seed2 = w2.seed;
      const mon = sessionOn(db, MONDAY), tue = sessionOn(db, monday(1));
      addWorkout(db, MONDAY, mon.id);
      const doneBefore = itemsOf(db, mon.id).map(i => [i.id, i.exercise_key]);
      const tueBefore = new Set(itemsOf(db, tue.id).map(i => i.id));
      const w2Before = new Set(sessionsOf(db, w2.id).flatMap(s => itemsOf(db, s.id).map(i => i.id)));
      E.shuffleWeek(db, w1.id, settings, PROG, exByKey, TODAY);
      const after = weeks(db);
      assert.notEqual(after[0].seed, seed1);
      assert.equal(after[1].seed, seed2);
      assert.deepEqual(itemsOf(db, mon.id).map(i => [i.id, i.exercise_key]), doneBefore);
      assert.equal(db.get("plan_sessions", mon.id).status, "done");
      const tueAfter = new Set(itemsOf(db, tue.id).map(i => i.id));
      assert.equal(tueAfter.size, tueBefore.size);
      assert.ok(![...tueAfter].some(id => tueBefore.has(id)), "an untouched session kept its old items");
      const w2After = new Set(sessionsOf(db, w2.id).flatMap(s => itemsOf(db, s.id).map(i => i.id)));
      assert.equal(w2After.size, w2Before.size);
      assert.ok(![...w2After].some(id => w2Before.has(id)), "the later week did not cascade");
    });

    it("swap picks from the pool and refuses once a set is logged (409)", () => {
      const { db, exByKey } = block();
      const thu = sessionOn(db, TODAY);
      assert.equal(thu.kind, "upper_b");
      const acc1 = item(itemsOf(db, thu.id), "acc1");
      const pool = PROG.sessions.upper_b.slots.find(sl => sl.key === "acc1").pool;
      const nu = E.swapItem(db, acc1.id, null, PROG, exByKey);
      assert.ok(pool.includes(nu.key));
      assert.notEqual(nu.key, acc1.exercise_key);
      assert.equal(item(itemsOf(db, thu.id), "acc1").note, "swapped");
      const w = addWorkout(db, TODAY, thu.id, false);
      addSets(db, exByKey, w, nu.key, [[12, 20, 7]], acc1.id);
      assert.equal(errorCode(() => E.swapItem(db, acc1.id, null, PROG, exByKey)), 409);
    });

    it("swap rejects another pattern (400) and an unknown key (404)", () => {
      const { db, exByKey } = block();
      const acc1 = item(itemsOf(db, sessionOn(db, TODAY).id), "acc1");
      assert.equal(errorCode(() => E.swapItem(db, acc1.id, "back_squat", PROG, exByKey)), 400);
      assert.equal(errorCode(() => E.swapItem(db, acc1.id, "no_such_lift", PROG, exByKey)), 404);
    });

    it("sweep skips past planned sessions but not one with a workout", () => {
      const { db } = block();
      const tue = sessionOn(db, monday(1));
      addWorkout(db, monday(1), tue.id, false);
      E.sweepMissed(db, TODAY);
      assert.deepEqual(sessionsOf(db, weeks(db)[0].id).map(s => s.status), ["skipped", "planned", "skipped", "planned", "planned", "planned", "planned"]);
    });

    it("move exchanges dates, sets moved_from on both, and refuses when today has a workout (409)", () => {
      const { db } = block();
      const fri = sessionOn(db, day(1)), thu = sessionOn(db, TODAY);
      const friOffset = fri.day_offset, thuOffset = thu.day_offset;
      E.moveSession(db, fri.id, TODAY);
      const friAfter = db.get("plan_sessions", fri.id), thuAfter = db.get("plan_sessions", thu.id);
      assert.deepEqual([friAfter.date, friAfter.moved_from, friAfter.status], [TODAY, day(1), "planned"]);
      assert.deepEqual([thuAfter.date, thuAfter.moved_from], [day(1), TODAY]);
      assert.deepEqual([friAfter.day_offset, thuAfter.day_offset], [thuOffset, friOffset]);
      // today's session has a live workout: refuse
      addWorkout(db, TODAY, fri.id, false);
      assert.equal(errorCode(() => E.moveSession(db, sessionOn(db, day(4)).id, TODAY)), 409);
    });

    it("move rejects a session beyond 14 days (400) and a done one (409)", () => {
      const { db } = block();
      assert.equal(errorCode(() => E.moveSession(db, sessionOn(db, day(21)).id, TODAY)), 400);
      const mon = sessionOn(db, MONDAY);
      addWorkout(db, MONDAY, mon.id);
      assert.equal(errorCode(() => E.moveSession(db, mon.id, TODAY)), 409);
    });

    it("adherence excludes void and zone2: week 1 is 3 of 4, week 2 is 4 of 5", () => {
      const { db, exByKey, settings } = block({ programme_start: monday(1), train_days: [1, 2, 3, 4, 5, 6] });
      const mark = (d, status) => db.update("plan_sessions", sessionOn(db, d).id, { status });
      assert.equal(sessionOn(db, MONDAY).status, "void");
      [1, 2, 3].forEach(o => mark(monday(o), "done"));
      mark(monday(5), "skipped");
      [7, 8, 9, 10].forEach(o => mark(monday(o), "done"));
      mark(monday(12), "skipped");
      const rows = E.adherenceByWeek(db);
      assert.deepEqual([rows[0].done, rows[0].planned], [3, 4]);
      assert.deepEqual([rows[1].done, rows[1].planned], [4, 5]);
      assert.equal(rows[1].done / rows[1].planned, 0.8);
      const view = E.weekView(db, monday(7), TODAY, settings, PROG, exByKey);
      assert.deepEqual(view.adherence, { done: 4, planned: 5 });
    });
  });

  describe("templates and seed", () => {
    it("templateFor picks the 5-day and 6-day upper_lower templates", () => {
      assert.deepEqual(E.templateFor({ train_days: [1, 2, 3, 4, 5] }, PROG), ["upper_a", "lower_a", "conditioning", "upper_b", "lower_b"]);
      assert.deepEqual(E.templateFor({ train_days: [1, 2, 3, 4, 5, 6] }, PROG), ["upper_a", "lower_a", "conditioning", "upper_b", "lower_b", "zone2"]);
      assert.deepEqual(E.templateFor({ train_days: [1, 2, 3, 4, 5], split: "upper_lower" }, PROG), PROG.template_5);
      assert.deepEqual(E.templateFor({ train_days: [1, 2, 3, 4, 5, 6], split: "upper_lower" }, PROG), PROG.template_6);
    });

    it("templateFor falls back to the largest template at or below the day count", () => {
      const three = ["x_a", "x_b", "x_c"], five = ["x_a", "x_b", "conditioning", "x_c", "x_d"];
      const prog = { template_5: PROG.template_5, template_6: PROG.template_6, splits: { demo: { name: "Demo", templates: { 3: three, 5: five } } } };
      assert.deepEqual(E.templateFor({ train_days: [1, 2, 3, 4], split: "demo" }, prog), three);
      assert.deepEqual(E.templateFor({ train_days: [1, 2, 3, 4, 5], split: "demo" }, prog), five);
      assert.deepEqual(E.templateFor({ train_days: [1, 2, 3, 4, 5, 6, 7], split: "demo" }, prog), five);
      assert.deepEqual(E.templateFor({ train_days: [1, 2], split: "demo" }, prog), three);
    });

    it("templateFor with split ppl and six days gives six kinds starting with push_a", () => {
      const t = E.templateFor({ train_days: [1, 2, 3, 4, 5, 6], split: "ppl" }, PROG);
      assert.equal(t.length, 6);
      assert.equal(t[0], "push_a");
      t.forEach(k => assert.ok(PROG.sessions[k], `${k} is not a session in programme.json`));
    });

    it("every pool key exists and rotating pools share one movement pattern", () => {
      const { exByKey } = fresh();
      assert.deepEqual(E.validateSeed(PROG, exByKey), []);
      Object.entries(PROG.sessions).forEach(([kind, sess]) => sess.slots.forEach(slot => {
        if (slot.select === "rotate" && slot.pool.length) {
          const patterns = new Set(slot.pool.map(k => exByKey[k].pattern));
          assert.equal(patterns.size, 1, `${kind}/${slot.key} mixes ${[...patterns].join(", ")}`);
        }
      }));
      const broken = structuredClone(PROG);
      broken.sessions.upper_a.slots[2].pool.push("no_such_lift");
      assert.ok(E.validateSeed(broken, exByKey).length > 0);
    });
  });
});

/* ================================================================ effort */

describe("effort", () => {
  describe("per-set maths and calories", () => {
    it("e1rm Epley: 100 x 5 is 116.67", () => {
      assert.deepEqual(E.e1rm(100, 5), { value: 116.67, low: false });
    });

    it("e1rm over 12 reps is low confidence; 12 is not; zero load is nothing", () => {
      assert.deepEqual(E.e1rm(60, 15), { value: 90, low: true });
      assert.deepEqual(E.e1rm(60, 12), { value: 84, low: false });
      assert.deepEqual(E.e1rm(0, 5), { value: null, low: false });
    });

    it("volume doubles per hand and is zero for timed moves", () => {
      assert.equal(E.setVolume(12, 10, true), 240);
      assert.equal(E.setVolume(12, 10), 120);
      assert.equal(E.setVolume(12, 45, false, true), 0);
    });

    it("bodyweight fraction: push-up 0.65 at 80 kg for 15 reps is 780", () => {
      const load = E.setLoad(0, 0.65, 80);
      assert.equal(load, 52);
      assert.equal(E.setVolume(load, 15), 780);
    });

    it("assisted load is bodyweight minus the help, never below zero", () => {
      assert.equal(E.setLoad(30, 0.95, 80, "assisted"), 46);
      assert.equal(E.setLoad(90, 0.95, 80, "assisted"), 0);
    });

    it("lifting MET by RPE: under 7 is 3.5, up to 8.5 is 5.0, above is 6.0, none is 5.0", () => {
      assert.deepEqual([6.5, 7.5, 9, null].map(E.liftingMet), [3.5, 5, 6, 5]);
      assert.equal(E.liftingMet(8.5), 5);
    });

    it("kcal lift: MET 5 at 80 kg for 45 minutes is 300", () => {
      assert.equal(E.kcal(5, 80, 45), 300);
    });

    it("interval bike 30 s on / 60 s off for 12 minutes at 80 kg is 89.6", () => {
      const met = E.cardioMet(EXJ_BY_KEY.bike.mets, "interval", 30, 60);
      assert.equal(met, 5.6);
      assert.equal(E.kcal(met, 80, 12), 89.6);
      assert.equal(E.cardioMet(null, "interval", 30, 60, "bike"), 5.6);
    });

    it("zone 2 bike for 35 minutes at 80 kg is 317.3", () => {
      const met = E.cardioMet(EXJ_BY_KEY.bike.mets, "moderate");
      assert.equal(met, 6.8);
      assert.equal(E.kcal(met, 80, 35), 317.3);
    });

    it("an unknown interval protocol uses a 0.4 work fraction: bike MET 5.92", () => {
      assert.equal(E.cardioMet(null, "interval", undefined, undefined, "bike"), 5.92);
    });

    it("lift minutes are clamped to 15-120 and cardio minutes come off", () => {
      assert.equal(E.liftMinutes("2026-09-24T10:00:00", "2026-09-24T14:00:00", null), 120);
      assert.equal(E.liftMinutes("2026-09-24T10:00:00", "2026-09-24T10:05:00", null), 15);
      assert.equal(E.liftMinutes("2026-09-24T10:00:00", null, "2026-09-24T10:45:00", 10), 35);
    });

    it("hard ratio counts RPE 8 and over among logged RPEs", () => {
      assert.equal(E.hardRatio([8, 7, 9, null]), 2 / 3);
      assert.equal(E.hardRatio([null, null]), 0);
    });
  });

  describe("effort score", () => {
    it("on par: volume at the median, all hard, calories at reference is 83", () => {
      const r = E.effortScore(1000, [900, 1000, 1100], 1.0, 400, 80);
      assert.equal(r.effort, 83);
      assert.deepEqual([r.parts.volume, r.parts.hard_sets, r.parts.calories, r.parts.ref_volume], [33.3, 30, 20, 1000]);
    });

    it("capped at 100 when volume is double the median", () => {
      assert.equal(E.effortScore(2000, [1000, 1000, 1000], 1.0, 400, 80).effort, 100);
    });

    it("no RPE logged gives part B zero", () => {
      const r = E.effortScore(1000, [1000, 1000, 1000], E.hardRatio([null, null, null]), 400, 80);
      assert.equal(r.parts.hard_sets, 0);
      assert.equal(r.effort, 53);
    });

    it("fewer than three references gives part A 33.3 and no reference volume", () => {
      const r = E.effortScore(1000, [1000, 1000], 0.5, 0, 80);
      assert.equal(r.parts.volume, 33.3);
      assert.equal(r.parts.ref_volume, null);
    });

    it("cardio-only: intervals at the calorie reference score 100, easy scores 88", () => {
      assert.equal(E.cardioEffort(400, 80, ["interval"]).effort, 100);
      assert.equal(E.cardioEffort(400, 80, ["easy"]).effort, 88);
    });
  });

  describe("personal records", () => {
    function prs(earlier, later) {
      const { db, exByKey, settings } = fresh();
      if (earlier.length) {
        const w1 = addWorkout(db, day(-7));
        addSets(db, exByKey, w1, "barbell_bench_press", earlier);
      }
      const w2 = addWorkout(db, TODAY);
      addSets(db, exByKey, w2, "barbell_bench_press", later);
      return E.prsForWorkout(db, w2, settings);
    }

    it("a heavier triple is both an e1RM and a weight PR", () => {
      assert.deepEqual(new Set(prs(repeat([10, 40, 8], 3), repeat([10, 42.5, 8], 3)).map(p => p.kind)), new Set(["e1rm", "weight"]));
    });

    it("more reps at a weight used before is a reps PR", () => {
      const reps = prs(repeat([8, 40, 8], 3), [[10, 40, 8]]).filter(p => p.kind === "reps");
      assert.equal(reps.length, 1);
      assert.equal(reps[0].text, "10 reps at 40 kg, previous best 8");
    });

    it("no PR on a first exposure", () => {
      assert.deepEqual(prs([], repeat([10, 40, 8], 3)), []);
    });

    it("sets over 12 reps never make an e1RM PR", () => {
      assert.deepEqual(prs([[10, 40, 8]], [[15, 30, 8]]), []);
    });
  });

  describe("aggregates", () => {
    it("strength index carries an untrained week forward and flags it", () => {
      const { db, exByKey } = fresh();
      const w1 = addWorkout(db, MONDAY);
      addSets(db, exByKey, w1, "barbell_bench_press", [[10, 40, 8]]);
      addSets(db, exByKey, w1, "back_squat", [[10, 60, 8]]);
      const w2 = addWorkout(db, monday(7));
      addSets(db, exByKey, w2, "barbell_bench_press", [[10, 42.5, 8]]);
      const out = E.strengthIndex(db, [exByKey.barbell_bench_press.id, exByKey.back_squat.id], () => 80, new Set([MONDAY]));
      assert.deepEqual(out[0], { week: MONDAY, index: 0, carried: false });
      assert.equal(out[1].week, monday(7));
      assert.equal(out[1].carried, true);
      const gain = E.e1rm(42.5, 10).value / E.e1rm(40, 10).value - 1;
      assert.equal(out[1].index, Math.round(1000 * gain / 2) / 10);
    });

    it("weekly e1RM flags a week built only on sets over 12 reps", () => {
      const { db, exByKey } = fresh();
      const w1 = addWorkout(db, MONDAY);
      addSets(db, exByKey, w1, "barbell_bench_press", [[15, 30, 8]]);
      const w2 = addWorkout(db, monday(7));
      addSets(db, exByKey, w2, "barbell_bench_press", [[10, 40, 8], [15, 30, 8]]);
      assert.deepEqual(E.weeklyE1rm(db, exByKey.barbell_bench_press.id, () => 80), [
        { week: MONDAY, e1rm: 45, low_confidence: true },
        { week: monday(7), e1rm: 53.33, low_confidence: false },
      ]);
    });

    it("weekly muscle sets give secondary muscles half credit: chest 3, triceps 1.5, shoulders 1.5", () => {
      const { db, exByKey } = fresh();
      const w = addWorkout(db, TODAY);
      addSets(db, exByKey, w, "barbell_bench_press", repeat([10, 40, 8], 3));
      assert.deepEqual(E.weeklyMuscleSets(db, MONDAY), [{ week: MONDAY, muscles: { chest: 3, shoulders: 1.5, triceps: 1.5 } }]);
    });

    it("mondayOf: Sunday 2026-10-04 belongs to the week of 2026-09-28", () => {
      assert.equal(E.mondayOf("2026-10-04"), "2026-09-28");
      assert.equal(E.mondayOf("2026-09-28"), "2026-09-28");
      assert.equal(E.mondayOf("2026-10-03"), "2026-09-28");
      assert.equal(E.mondayOf(TODAY), MONDAY);
    });
  });

  describe("recomputeWorkout", () => {
    it("a finished workout with 3 x 10 x 40 has volume 1200 and kcal above 100", () => {
      const { db, exByKey, settings } = fresh();
      const w = addWorkout(db, TODAY, null, true, { ended_at: `${TODAY}T18:45:00` });
      addSets(db, exByKey, w, "barbell_bench_press", repeat([10, 40, 8], 3));
      const row = E.recomputeWorkout(db, w, settings, PROG);
      assert.equal(row.volume, 1200);
      assert.equal(row.work_sets, 3);
      assert.equal(row.hard_sets, 3);
      assert.equal(row.lift_minutes, 45);
      assert.ok(row.kcal_est > 100, `kcal_est ${row.kcal_est}`);
      assert.equal(row.kcal_est, 300);                 // MET 5 x 80 kg x 45 min / 60
      assert.equal(row.kcal_used, 300);
      assert.equal(row.effort, 78);                    // 33.3 (no baseline) + 30 (all hard) + 15 (300 of 400 kcal)
      assert.equal(db.get("workouts", w).volume, 1200);
    });

    it("a set arriving after Finish turns a 0 kcal workout into 45 minutes of lifting", () => {
      const { db, exByKey, settings } = fresh();
      const w = addWorkout(db, TODAY, null, true, { ended_at: `${TODAY}T18:45:00` });
      let row = E.recomputeWorkout(db, w, settings, PROG);
      assert.deepEqual([row.kcal_est, row.work_sets, row.volume], [0, 0, 0]);
      addSets(db, exByKey, w, "barbell_bench_press", [[10, 40, null]]);
      row = E.recomputeWorkout(db, w, settings, PROG);
      assert.deepEqual([row.kcal_est, row.work_sets, row.volume, row.lift_minutes], [300, 1, 400, 45]);
    });

    it("a cardio row gets its own kcal and a cardio-only workout scores as cardio", () => {
      const { db, exByKey, settings } = fresh();
      const w = addWorkout(db, TODAY, null, true, { ended_at: `${TODAY}T18:15:00` });
      const c = db.insert("cardio_logs", { client_id: crypto.randomUUID(), workout_client_id: w, plan_item_id: null, exercise_id: exByKey.bike.id,
        minutes: 12, distance_km: null, intensity: "interval", protocol: "fin_bike_30_60", kcal_est: null });
      const row = E.recomputeWorkout(db, w, settings, PROG);
      assert.equal(db.get("cardio_logs", c.client_id).kcal_est, 89.6);
      assert.equal(row.kcal_est, 89.6);
      assert.equal(row.effort, E.cardioEffort(89.6, 80, ["interval"]).effort);
    });
  });
});
