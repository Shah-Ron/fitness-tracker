/* Fitness Tracker store, phone edition.
   Everything lives in memory as plain objects and is written through to
   IndexedDB on every change, so the app opens instantly and never loses a
   tap. Bundled data (the exercise library, the programme template, the food
   lists) is loaded from data\ and merged with what the user has changed. */
"use strict";

const Store = (() => {
  const DB_NAME = "fitness-phone";
  const DB_VERSION = 1;
  const COLLECTIONS = ["settings", "exercises", "blocks", "plan_weeks", "plan_sessions", "plan_items", "workouts", "set_logs",
    "cardio_logs", "foods", "food_usage", "meals", "food_logs", "body_logs", "daily_logs", "meta"];
  const KEY_OF = { settings: "key", workouts: "client_id", set_logs: "client_id", cardio_logs: "client_id", food_logs: "client_id",
    body_logs: "client_id", daily_logs: "client_id", food_usage: "food_id", meta: "key" };
  const keyOf = coll => KEY_OF[coll] || "id";

  let idb = null;
  const mem = {};
  COLLECTIONS.forEach(c => { mem[c] = new Map(); });
  let writeChain = Promise.resolve();
  let bundled = { exercises: [], programme: null, foods: [] };

  function openIdb() {
    return new Promise((res, rej) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => { COLLECTIONS.forEach(c => { if (!req.result.objectStoreNames.contains(c)) req.result.createObjectStore(c, { keyPath: keyOf(c) }); }); };
      req.onsuccess = () => res(req.result);
      req.onerror = () => rej(req.error);
    });
  }
  function readAll(coll) {
    return new Promise((res, rej) => { const r = idb.transaction(coll, "readonly").objectStore(coll).getAll(); r.onsuccess = () => res(r.result || []); r.onerror = () => rej(r.error); });
  }
  function queueWrite(fn) {
    writeChain = writeChain.then(() => new Promise((res, rej) => { try { fn(res, rej); } catch (e) { rej(e); } })).catch(e => { console.error("store write", e); });
    return writeChain;
  }
  const persistPut = (coll, row) => idb && queueWrite((res, rej) => { const tx = idb.transaction(coll, "readwrite"); tx.objectStore(coll).put(row); tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
  const persistDelete = (coll, key) => idb && queueWrite((res, rej) => { const tx = idb.transaction(coll, "readwrite"); tx.objectStore(coll).delete(key); tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
  const persistClear = coll => idb && queueWrite((res, rej) => { const tx = idb.transaction(coll, "readwrite"); tx.objectStore(coll).clear(); tx.oncomplete = res; tx.onerror = () => rej(tx.error); });

  /* ---- the model the engine works on */
  const db = {
    all: coll => Array.from(mem[coll].values()),
    get: (coll, key) => mem[coll].get(key) || null,
    nextId() { const m = mem.meta.get("next_id") || { key: "next_id", value: 1 }; const id = m.value; m.value = id + 1; mem.meta.set("next_id", m); persistPut("meta", m); return id; },
    insert(coll, row) {
      const k = keyOf(coll);
      if (row[k] == null) row[k] = k === "id" ? db.nextId() : crypto.randomUUID();
      mem[coll].set(row[k], row); persistPut(coll, row); return row;
    },
    update(coll, key, patch) { const row = mem[coll].get(key); if (!row) return null; Object.assign(row, patch); persistPut(coll, row); return row; },
    remove(coll, key) { if (!mem[coll].has(key)) return false; mem[coll].delete(key); persistDelete(coll, key); return true; },
    settings() { const out = {}; mem.settings.forEach(r => { out[r.key] = r.value; }); return out; },
    setSetting(key, value) { const row = { key, value }; mem.settings.set(key, row); persistPut("settings", row); },
    bundled: () => bundled,
    flush: () => writeChain,
  };

  /* ---- bundled data and first-run seeding */
  async function fetchJson(path) { const r = await fetch(path, { cache: "no-store" }); if (!r.ok) throw new Error(`Could not load ${path} (${r.status})`); return r.json(); }

  function seedExercises(list) {
    const byKey = new Map(db.all("exercises").map(e => [e.key, e]));
    list.forEach(ex => {
      const have = byKey.get(ex.key);
      const row = { key: ex.key, name: ex.name, pattern: ex.pattern, primary_muscle: ex.primary_muscle, secondary_muscles: ex.secondary_muscles || [], equipment: ex.equipment,
        per_hand: ex.per_hand ? 1 : 0, timed: ex.timed ? 1 : 0, unilateral: ex.unilateral ? 1 : 0, bodyweight_fraction: +(ex.bodyweight_fraction || 0),
        increment_kg: ex.increment_kg ?? null, min_load_kg: ex.min_load_kg ?? null, variation_of: ex.variation_of || null, carry: ex.carry ?? null, mets: ex.mets || null, cues: ex.cues || [], is_custom: 0 };
      if (have) db.update("exercises", have.id, Object.assign(row, { active: have.active, cues: have.cues && have.cues.length ? have.cues : row.cues, increment_kg: have.increment_kg ?? row.increment_kg, min_load_kg: have.min_load_kg ?? row.min_load_kg }));
      else db.insert("exercises", Object.assign(row, { active: 1 }));
    });
  }

  /* Foods: the bundled list is read-only and lives in memory only; usage counts and the user's own foods persist. */
  function foodsAll() {
    const usage = mem.food_usage;
    const out = bundled.foods.map(f => { const u = usage.get(f.id); return u ? Object.assign({}, f, { times_used: u.times_used, last_used: u.last_used }) : f; });
    mem.foods.forEach(f => { if (f.active !== 0) out.push(f); });
    return out;
  }
  function foodById(id) {
    if (id == null) return null;
    const own = mem.foods.get(id); if (own) return own;
    const f = bundled.foodIndex ? bundled.foodIndex.get(id) : null;
    if (!f) return null;
    const u = mem.food_usage.get(id);
    return u ? Object.assign({}, f, { times_used: u.times_used, last_used: u.last_used }) : f;
  }
  function noteFoodUsed(id, date) {
    const own = mem.foods.get(id);
    if (own) { db.update("foods", id, { times_used: (own.times_used || 0) + 1, last_used: date }); return; }
    const u = mem.food_usage.get(id) || { food_id: id, times_used: 0, last_used: null };
    u.times_used++; u.last_used = date; mem.food_usage.set(id, u); persistPut("food_usage", u);
  }

  async function init(dataBase = "data/") {
    idb = await openIdb();
    await Promise.all(COLLECTIONS.map(async c => { (await readAll(c)).forEach(row => mem[c].set(row[keyOf(c)], row)); }));
    const [ex, prog, foods] = await Promise.all([fetchJson(dataBase + "exercises.json"), fetchJson(dataBase + "programme.json"), fetchJson(dataBase + "foods.json")]);
    bundled = { exercises: ex.exercises, programme: prog, foods: foods.foods.map(r => { const o = {}; foods.fields.forEach((f, i) => { o[f] = r[i]; }); o.times_used = 0; o.last_used = null; return o; }) };
    bundled.foodIndex = new Map(bundled.foods.map(f => [f.id, f]));
    const seeded = mem.meta.get("seed_version");
    if (!seeded || seeded.value < (ex.version || 1)) { seedExercises(bundled.exercises); const m = { key: "seed_version", value: ex.version || 1 }; mem.meta.set("seed_version", m); persistPut("meta", m); }
    return db;
  }

  /* ---- backup and restore */
  function backup() {
    const out = { app: "fitness-tracker", edition: "phone", version: 2, made: new Date().toISOString(), collections: {} };
    COLLECTIONS.forEach(c => { out.collections[c] = db.all(c); });
    return out;
  }
  async function restore(data) {
    if (!data || data.app !== "fitness-tracker" || !data.collections) throw new Error("That is not a Fitness Tracker backup");
    for (const c of COLLECTIONS) { mem[c].clear(); await persistClear(c); (data.collections[c] || []).forEach(row => { mem[c].set(row[keyOf(c)], row); persistPut(c, row); }); }
    if (!mem.exercises.size) seedExercises(bundled.exercises);
    await db.flush();
  }
  async function wipe() { for (const c of COLLECTIONS) { mem[c].clear(); await persistClear(c); } seedExercises(bundled.exercises); await db.flush(); }

  return { init, db, foodsAll, foodById, noteFoodUsed, backup, restore, wipe, COLLECTIONS };
})();
if (typeof module !== "undefined") module.exports = Store;
