"""Fitness Tracker.

A private training and food tracker that runs on your own laptop. One Python
file serves one page from a SQLite database. A second, HTTPS listener lets
your phone on home wifi open the same page, install it as an app, log sets at
the gym with no connection and sync when it gets home.

Run it with:  python fitness_tracker.py
Options:      --no-browser   do not open a browser tab
              --idle N       stop N seconds after the last request (testing)
              --verbose      log every dropped connection

Standard library only. The maths lives in nutrition.py, effort.py and
programme.py next to this file.
"""

import csv
import gzip
import hashlib
import hmac
import http.client
import io
import json
import os
import secrets
import socket
import sqlite3
import ssl
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import effort
import nutrition
import programme
from programme import PlanError

APP_ID = "fitness-tracker"
APP_VERSION = "1.0"

HOST = "127.0.0.1"
HTTP_PORT = 8778
HTTP_FALLBACK = range(8800, 8820)       # 8779 is the HTTPS port, so the fallback skips it
LAN_HOST = "0.0.0.0"
HTTPS_PORT = 8779

FROZEN = bool(getattr(sys, "frozen", False))
HERE = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
BUNDLE = getattr(sys, "_MEIPASS", HERE)
DB_PATH = os.path.join(HERE, "fitness.db")
LOG_PATH = os.path.join(HERE, "fitness_tracker.log")
PORT_FILE = os.path.join(HERE, "fitness_tracker.port")
CERT_DIR = os.path.join(HERE, "certs")
CERT_PEM = os.path.join(CERT_DIR, "server.pem")
CERT_KEY = os.path.join(CERT_DIR, "server-key.pem")
CA_PEM = os.path.join(CERT_DIR, "ca.pem")
CERT_SIDECAR = os.path.join(CERT_DIR, "server.json")

VERBOSE = "--verbose" in sys.argv
IDLE_SECONDS = 12 * 3600
if "--idle" in sys.argv:
    try:
        IDLE_SECONDS = int(sys.argv[sys.argv.index("--idle") + 1])
    except (IndexError, ValueError):
        pass

STOP = threading.Event()
LAST_SEEN = {"t": time.time()}
SETTINGS_CACHE = {}
PHONE = {"https": False, "reason": None, "cert": None}
TLS_CTX = None
BUILD = {"stamp": None, "sig": None}
FOODS_CACHE = {"key": None, "raw": None, "gz": None}
SEED_LOCK = threading.Lock()
PROG = None
EX_BY_KEY = {}
EX_BY_ID = {}


# ----------------------------------------------------------------- small helpers

def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    if sys.stdout:
        try:
            print(line)
        except OSError:
            pass
    if FROZEN or "--log" in sys.argv:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def alert(msg):
    if FROZEN and sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, "Fitness Tracker", 0x10)
            return
        except Exception:
            pass
    log(msg)


def static_path(name):
    """A file next to the exe wins over the copy packed inside it."""
    local = os.path.join(HERE, *name.split("/"))
    if os.path.exists(local):
        return local
    return os.path.join(BUNDLE, *name.split("/"))


def read_static(name):
    try:
        with open(static_path(name), "rb") as fh:
            return fh.read()
    except OSError:
        return None


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def today():
    return date.today()


class BadRequest(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


class Unauthorised(Exception):
    pass


class Retry(Exception):
    """A sync op that cannot be applied yet but will be, once its parent arrives."""


# ----------------------------------------------------------------- database

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS exercises (
  id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, name TEXT NOT NULL, pattern TEXT NOT NULL,
  primary_muscle TEXT, secondary_muscles TEXT NOT NULL DEFAULT '[]', equipment TEXT,
  per_hand INTEGER NOT NULL DEFAULT 0, timed INTEGER NOT NULL DEFAULT 0, unilateral INTEGER NOT NULL DEFAULT 0,
  bodyweight_fraction REAL NOT NULL DEFAULT 0, increment_kg REAL, min_load_kg REAL,
  variation_of TEXT, carry REAL, mets TEXT, cues TEXT NOT NULL DEFAULT '[]',
  is_custom INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);

CREATE TABLE IF NOT EXISTS blocks (
  id INTEGER PRIMARY KEY, block_no INTEGER NOT NULL, start_date TEXT NOT NULL, weeks INTEGER NOT NULL DEFAULT 4,
  split TEXT, seed TEXT NOT NULL, notes TEXT);

CREATE TABLE IF NOT EXISTS plan_weeks (
  id INTEGER PRIMARY KEY, block_id INTEGER NOT NULL REFERENCES blocks(id), week_no INTEGER NOT NULL,
  start_date TEXT NOT NULL, seed TEXT NOT NULL, is_deload INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS plan_sessions (
  id INTEGER PRIMARY KEY, week_id INTEGER NOT NULL REFERENCES plan_weeks(id), day_offset INTEGER NOT NULL,
  date TEXT NOT NULL, kind TEXT NOT NULL, title TEXT, status TEXT NOT NULL DEFAULT 'planned',
  moved_from TEXT, note TEXT);

CREATE TABLE IF NOT EXISTS plan_items (
  id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES plan_sessions(id) ON DELETE CASCADE,
  ord INTEGER NOT NULL, section TEXT NOT NULL, slot_key TEXT, exercise_id INTEGER REFERENCES exercises(id),
  sets INTEGER, rep_low INTEGER, rep_high INTEGER, target_weight REAL, target_source TEXT,
  rest_sec INTEGER, minutes REAL, protocol TEXT, rounds INTEGER, optional INTEGER NOT NULL DEFAULT 0, note TEXT);

CREATE TABLE IF NOT EXISTS workouts (
  id INTEGER PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, session_id INTEGER REFERENCES plan_sessions(id),
  date TEXT NOT NULL, started_at TEXT, ended_at TEXT, session_rpe REAL,
  work_sets INTEGER NOT NULL DEFAULT 0, hard_sets INTEGER NOT NULL DEFAULT 0, volume REAL NOT NULL DEFAULT 0,
  lift_minutes REAL NOT NULL DEFAULT 0, kcal_est REAL NOT NULL DEFAULT 0, kcal_wearable REAL, hr_avg REAL,
  effort INTEGER, effort_parts TEXT, notes TEXT, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS set_logs (
  id INTEGER PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, workout_client_id TEXT NOT NULL,
  plan_item_id INTEGER, exercise_id INTEGER NOT NULL REFERENCES exercises(id), set_no INTEGER NOT NULL DEFAULT 1,
  reps INTEGER, weight_kg REAL, rpe REAL, is_warmup INTEGER NOT NULL DEFAULT 0, done_at TEXT,
  updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS cardio_logs (
  id INTEGER PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, workout_client_id TEXT NOT NULL,
  plan_item_id INTEGER, exercise_id INTEGER REFERENCES exercises(id), minutes REAL, distance_km REAL,
  intensity TEXT, protocol TEXT, kcal_est REAL, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS foods (
  id INTEGER PRIMARY KEY, client_id TEXT UNIQUE, name TEXT NOT NULL, brand TEXT, unit TEXT NOT NULL DEFAULT 'g',
  source TEXT NOT NULL, source_id TEXT, barcode TEXT, kcal_100 REAL NOT NULL, protein_100 REAL NOT NULL DEFAULT 0,
  carb_100 REAL NOT NULL DEFAULT 0, fat_100 REAL NOT NULL DEFAULT 0, approx INTEGER NOT NULL DEFAULT 0,
  search TEXT, times_used INTEGER NOT NULL DEFAULT 0, last_used TEXT, active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (source, source_id));

CREATE TABLE IF NOT EXISTS food_portions (
  id INTEGER PRIMARY KEY, food_id INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
  label TEXT NOT NULL, grams REAL NOT NULL, is_default INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS meals (id INTEGER PRIMARY KEY, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);

CREATE TABLE IF NOT EXISTS meal_items (
  id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
  food_id INTEGER NOT NULL REFERENCES foods(id), grams REAL NOT NULL, portion_label TEXT, qty REAL NOT NULL DEFAULT 1);

CREATE TABLE IF NOT EXISTS food_logs (
  id INTEGER PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, date TEXT NOT NULL, slot TEXT NOT NULL,
  food_id INTEGER REFERENCES foods(id), food_client_id TEXT, grams REAL NOT NULL, portion_label TEXT,
  qty REAL NOT NULL DEFAULT 1, kcal REAL NOT NULL DEFAULT 0, protein REAL NOT NULL DEFAULT 0,
  carb REAL NOT NULL DEFAULT 0, fat REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS body_logs (
  id INTEGER PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, date TEXT NOT NULL, weight_kg REAL, waist_cm REAL,
  chest_cm REAL, arm_cm REAL, hip_cm REAL, thigh_cm REAL, note TEXT, updated_at TEXT NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS daily_logs (
  id INTEGER PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, date TEXT NOT NULL, water_ml REAL, sleep_h REAL,
  steps INTEGER, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);

CREATE INDEX IF NOT EXISTS ix_sets_workout ON set_logs(workout_client_id);
CREATE INDEX IF NOT EXISTS ix_sets_exercise ON set_logs(exercise_id);
CREATE INDEX IF NOT EXISTS ix_cardio_workout ON cardio_logs(workout_client_id);
CREATE INDEX IF NOT EXISTS ix_food_logs_date ON food_logs(date);
CREATE INDEX IF NOT EXISTS ix_workouts_date ON workouts(date);
CREATE INDEX IF NOT EXISTS ix_sessions_date ON plan_sessions(date);
CREATE INDEX IF NOT EXISTS ix_items_session ON plan_items(session_id);
CREATE INDEX IF NOT EXISTS ix_foods_name ON foods(name);
"""

SETTING_DEFAULTS = {}
SETTING_DEFAULTS.update(nutrition.DEFAULTS)
SETTING_DEFAULTS.update(programme.TRAIN_DEFAULTS)
SETTING_DEFAULTS.update({
    "stay_running": True,
    "theme": None,
    "contact_email": None,
    "display_name": None,
    "rest_default_sec": 90,
    "seed_version": 0,
})
HIDDEN_SETTINGS = {"pair_key"}
TRAINING_KEYS = {"train_days", "session_minutes", "experience", "cardio_kit", "main1_swap_every_blocks", "split"}
GOAL_KEYS = {"target_weight_kg", "target_date"}
SEED_VERSION = 2


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_column(conn, table, column, decl):
    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in have:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def get_settings(conn):
    out = dict(SETTING_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM settings"):
        try:
            out[row["key"]] = json.loads(row["value"])
        except (ValueError, TypeError):
            out[row["key"]] = row["value"]
    return out


def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(value)))


def public_settings(settings):
    return {k: v for k, v in settings.items() if k not in HIDDEN_SETTINGS}


def refresh_settings_cache(conn):
    SETTINGS_CACHE.clear()
    SETTINGS_CACHE.update(get_settings(conn))


def init_db():
    fresh = not os.path.exists(DB_PATH)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(SCHEMA)
        have = {r["key"] for r in conn.execute("SELECT key FROM settings")}
        for k, v in SETTING_DEFAULTS.items():
            if k not in have:
                set_setting(conn, k, v)
        if "pair_key" not in have:
            set_setting(conn, "pair_key", secrets.token_urlsafe(9))
        conn.commit()
        with SEED_LOCK:
            seed(conn)
        refresh_settings_cache(conn)
    finally:
        conn.close()
    log(("Created " if fresh else "Opened ") + DB_PATH)


def load_programme_files():
    global PROG
    PROG = programme.load_programme(static_path("data/programme.json"))


def refresh_exercises(conn):
    EX_BY_KEY.clear()
    EX_BY_ID.clear()
    for r in conn.execute("SELECT * FROM exercises"):
        d = dict(r)
        for k in ("cues", "secondary_muscles", "mets"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    pass
        EX_BY_KEY[d["key"]] = d
        EX_BY_ID[d["id"]] = d


def seed(conn):
    """Load the exercise library and the food lists the first time, or when the seed version moves."""
    settings = get_settings(conn)
    have_version = int(settings.get("seed_version") or 0)
    ex_count = conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
    if ex_count == 0 or have_version < SEED_VERSION:
        blob = json.loads(read_static("data/exercises.json").decode("utf-8"))
        for ex in blob["exercises"]:
            conn.execute("""INSERT INTO exercises (key, name, pattern, primary_muscle, secondary_muscles, equipment, per_hand, timed,
                            unilateral, bodyweight_fraction, increment_kg, min_load_kg, variation_of, carry, mets, cues, is_custom, active)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,1)
                            ON CONFLICT(key) DO UPDATE SET name = excluded.name, pattern = excluded.pattern,
                              primary_muscle = excluded.primary_muscle, secondary_muscles = excluded.secondary_muscles,
                              equipment = excluded.equipment, per_hand = excluded.per_hand, timed = excluded.timed,
                              unilateral = excluded.unilateral, bodyweight_fraction = excluded.bodyweight_fraction,
                              increment_kg = excluded.increment_kg, min_load_kg = excluded.min_load_kg,
                              variation_of = excluded.variation_of, carry = excluded.carry, mets = excluded.mets, cues = excluded.cues""",
                         (ex["key"], ex["name"], ex["pattern"], ex.get("primary_muscle"), json.dumps(ex.get("secondary_muscles") or []),
                          ex.get("equipment"), int(ex.get("per_hand") or 0), int(ex.get("timed") or 0), int(ex.get("unilateral") or 0),
                          float(ex.get("bodyweight_fraction") or 0), ex.get("increment_kg"), ex.get("min_load_kg"),
                          ex.get("variation_of"), ex.get("carry"), json.dumps(ex["mets"]) if ex.get("mets") else None,
                          json.dumps(ex.get("cues") or [])))
        log(f"Exercise library loaded: {len(blob['exercises'])} exercises")
    food_count = conn.execute("SELECT COUNT(*) FROM foods WHERE source IN ('usda', 'nz', 'in')").fetchone()[0]
    if food_count == 0 or have_version < SEED_VERSION:
        rows = list(nutrition.iter_usda_foods(static_path("data/foods_usda.json")))
        rows += list(nutrition.iter_nz_foods(static_path("data/foods_nz.csv"), "nz"))
        if os.path.exists(static_path("data/foods_indian.csv")):
            rows += list(nutrition.iter_nz_foods(static_path("data/foods_indian.csv"), "in"))
        n = 0
        for row in rows:
            n += insert_food(conn, row, seeding=True)
        log(f"Food list loaded: {n} foods added")
    if have_version < SEED_VERSION:
        set_setting(conn, "seed_version", SEED_VERSION)
    conn.commit()
    refresh_exercises(conn)
    problems = programme.validate_seed(PROG, EX_BY_KEY)
    if problems:
        raise RuntimeError("programme.json does not match exercises.json:\n  " + "\n  ".join(problems))


def insert_food(conn, row, seeding=False):
    """Insert or refresh one food and its portions. Returns 1 when a row was added."""
    existing = None
    if row.get("source_id"):
        existing = conn.execute("SELECT id FROM foods WHERE source = ? AND source_id = ?", (row["source"], row["source_id"])).fetchone()
    if existing:
        if seeding:
            conn.execute("""UPDATE foods SET name = ?, brand = ?, unit = ?, kcal_100 = ?, protein_100 = ?, carb_100 = ?, fat_100 = ?,
                            approx = ?, search = ? WHERE id = ?""",
                         (row["name"], row.get("brand"), row.get("unit") or "g", row["kcal_100"], row.get("protein_100") or 0,
                          row.get("carb_100") or 0, row.get("fat_100") or 0, int(row.get("approx") or 0), row.get("search"), existing["id"]))
            conn.execute("DELETE FROM food_portions WHERE food_id = ?", (existing["id"],))
            for i, (label, grams) in enumerate(row.get("portions") or []):
                conn.execute("INSERT INTO food_portions (food_id, label, grams, is_default) VALUES (?,?,?,?)",
                             (existing["id"], label, grams, 1 if i == 0 else 0))
        return 0
    cur = conn.execute("""INSERT INTO foods (client_id, name, brand, unit, source, source_id, barcode, kcal_100, protein_100, carb_100,
                          fat_100, approx, search, active) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                       (row.get("client_id"), row["name"], row.get("brand"), row.get("unit") or "g", row["source"], row.get("source_id"),
                        row.get("barcode"), row["kcal_100"], row.get("protein_100") or 0, row.get("carb_100") or 0,
                        row.get("fat_100") or 0, int(row.get("approx") or 0), row.get("search")))
    fid = cur.lastrowid
    for i, (label, grams) in enumerate(row.get("portions") or []):
        conn.execute("INSERT INTO food_portions (food_id, label, grams, is_default) VALUES (?,?,?,?)", (fid, label, grams, 1 if i == 0 else 0))
    return 1


# ----------------------------------------------------------------- validation

def v_num(v, name, lo=None, hi=None, allow_none=False):
    if v is None or v == "":
        if allow_none:
            return None
        raise BadRequest(f"{name} is required")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise BadRequest(f"{name} must be a number")
    if x != x or x in (float("inf"), float("-inf")):
        raise BadRequest(f"{name} must be a number")
    if lo is not None and x < lo:
        raise BadRequest(f"{name} must be at least {lo:g}")
    if hi is not None and x > hi:
        raise BadRequest(f"{name} must be at most {hi:g}")
    return x


def v_int(v, name, lo=None, hi=None, allow_none=False):
    x = v_num(v, name, lo, hi, allow_none)
    return None if x is None else int(round(x))


def v_date(v, name="date", allow_none=False):
    if v is None or v == "":
        if allow_none:
            return None
        raise BadRequest(f"{name} is required")
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise BadRequest(f"'{v}' is not a date (use YYYY-MM-DD)")


def v_text(v, name, maxlen=200, allow_none=True):
    if v is None:
        if allow_none:
            return None
        raise BadRequest(f"{name} is required")
    s = str(v).strip()
    if not s and not allow_none:
        raise BadRequest(f"{name} is required")
    return s[:maxlen] if s else None


def v_ts(v):
    if v in (None, ""):
        return None
    s = str(v)
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise BadRequest(f"'{v}' is not a timestamp")
    return s[:25]


def v_choice(v, name, choices, allow_none=False):
    if v in (None, ""):
        if allow_none:
            return None
        raise BadRequest(f"{name} is required")
    if v not in choices:
        raise BadRequest(f"{name} must be one of {', '.join(choices)}")
    return v


def v_client_id(v):
    s = str(v or "").strip()
    if not s or len(s) > 64:
        raise BadRequest("client_id is missing")
    return s


# ----------------------------------------------------------------- sync engine

SYNC_TABLES = {
    "workout": ("workouts", ["session_id", "date", "started_at", "ended_at", "session_rpe", "kcal_wearable", "hr_avg", "notes"]),
    "set": ("set_logs", ["workout_client_id", "plan_item_id", "exercise_id", "set_no", "reps", "weight_kg", "rpe", "is_warmup", "done_at"]),
    "cardio": ("cardio_logs", ["workout_client_id", "plan_item_id", "exercise_id", "minutes", "distance_km", "intensity", "protocol"]),
    "food_log": ("food_logs", ["date", "slot", "food_id", "food_client_id", "grams", "portion_label", "qty", "kcal", "protein", "carb", "fat"]),
    "body": ("body_logs", ["date", "weight_kg", "waist_cm", "chest_cm", "arm_cm", "hip_cm", "thigh_cm", "note"]),
    "daily": ("daily_logs", ["date", "water_ml", "sleep_h", "steps"]),
    "food": ("foods", []),
}
SYNC_ORDER = {"workout": 0, "food": 1, "set": 2, "cardio": 3, "food_log": 4, "body": 5, "daily": 6}
SLOTS = ("breakfast", "lunch", "dinner", "snack")
INTENSITIES = ("easy", "moderate", "vigorous", "interval")


def validate_payload(typ, p, existing):
    """Type-check the fields a sync op carries. Missing fields keep the stored value."""
    out = {}
    if typ == "workout":
        if "session_id" in p:
            out["session_id"] = v_int(p["session_id"], "session_id", 1, allow_none=True)
        if "date" in p or not existing:
            out["date"] = v_date(p.get("date") or (existing["date"] if existing else None) or today().isoformat())
        for k in ("started_at", "ended_at"):
            if k in p:
                out[k] = v_ts(p[k])
        if "session_rpe" in p:
            out["session_rpe"] = v_num(p["session_rpe"], "session RPE", 1, 10, allow_none=True)
        if "kcal_wearable" in p:
            out["kcal_wearable"] = v_num(p["kcal_wearable"], "calories from the watch", 0, 5000, allow_none=True)
        if "hr_avg" in p:
            out["hr_avg"] = v_num(p["hr_avg"], "average heart rate", 30, 250, allow_none=True)
        if "notes" in p:
            out["notes"] = v_text(p["notes"], "notes", 2000)
    elif typ == "set":
        if "workout_client_id" in p or not existing:
            out["workout_client_id"] = v_client_id(p.get("workout_client_id") or (existing["workout_client_id"] if existing else None))
        if "plan_item_id" in p:
            out["plan_item_id"] = v_int(p["plan_item_id"], "plan_item_id", 1, allow_none=True)
        if "exercise_id" in p or not existing:
            out["exercise_id"] = v_int(p.get("exercise_id") or (existing["exercise_id"] if existing else None), "exercise_id", 1)
        if "set_no" in p:
            out["set_no"] = v_int(p["set_no"], "set number", 1, 50)
        if "reps" in p:
            out["reps"] = v_int(p["reps"], "reps", 0, 600, allow_none=True)
        if "weight_kg" in p:
            out["weight_kg"] = v_num(p["weight_kg"], "weight", 0, 1000, allow_none=True)
        if "rpe" in p:
            out["rpe"] = v_num(p["rpe"], "RPE", 1, 10, allow_none=True)
        if "is_warmup" in p:
            out["is_warmup"] = 1 if p["is_warmup"] in (1, True, "1", "true") else 0
        if "done_at" in p:
            out["done_at"] = v_ts(p["done_at"])
    elif typ == "cardio":
        if "workout_client_id" in p or not existing:
            out["workout_client_id"] = v_client_id(p.get("workout_client_id") or (existing["workout_client_id"] if existing else None))
        if "plan_item_id" in p:
            out["plan_item_id"] = v_int(p["plan_item_id"], "plan_item_id", 1, allow_none=True)
        if "exercise_id" in p:
            out["exercise_id"] = v_int(p["exercise_id"], "exercise_id", 1, allow_none=True)
        if "minutes" in p or not existing:
            out["minutes"] = v_num(p.get("minutes"), "minutes", 0, 600)
        if "distance_km" in p:
            out["distance_km"] = v_num(p["distance_km"], "distance", 0, 500, allow_none=True)
        if "intensity" in p or not existing:
            out["intensity"] = v_choice(p.get("intensity") or "moderate", "intensity", INTENSITIES)
        if "protocol" in p:
            out["protocol"] = v_text(p["protocol"], "protocol", 60)
    elif typ == "food_log":
        if "date" in p or not existing:
            out["date"] = v_date(p.get("date") or (existing["date"] if existing else None) or today().isoformat())
        if "slot" in p or not existing:
            out["slot"] = v_choice(p.get("slot") or (existing["slot"] if existing else "snack"), "slot", SLOTS)
        if "food_id" in p:
            out["food_id"] = v_int(p["food_id"], "food_id", 1, allow_none=True)
        if "food_client_id" in p:
            out["food_client_id"] = v_text(p["food_client_id"], "food_client_id", 64)
        if "grams" in p or not existing:
            out["grams"] = v_num(p.get("grams"), "amount", 0.1, 20000)
        if "portion_label" in p:
            out["portion_label"] = v_text(p["portion_label"], "portion", 80)
        if "qty" in p:
            out["qty"] = v_num(p["qty"], "quantity", 0.01, 1000, allow_none=True) or 1
        for k in ("kcal", "protein", "carb", "fat"):
            if k in p:
                out[k] = v_num(p[k], k, 0, 100000, allow_none=True) or 0
    elif typ == "body":
        if "date" in p or not existing:
            out["date"] = v_date(p.get("date") or (existing["date"] if existing else None) or today().isoformat())
        if "weight_kg" in p:
            out["weight_kg"] = v_num(p["weight_kg"], "weight", 20, 400, allow_none=True)
        for k in ("waist_cm", "chest_cm", "arm_cm", "hip_cm", "thigh_cm"):
            if k in p:
                out[k] = v_num(p[k], k.replace("_cm", ""), 10, 300, allow_none=True)
        if "note" in p:
            out["note"] = v_text(p["note"], "note", 500)
    elif typ == "daily":
        if "date" in p or not existing:
            out["date"] = v_date(p.get("date") or (existing["date"] if existing else None) or today().isoformat())
        if "water_ml" in p:
            out["water_ml"] = v_num(p["water_ml"], "water", 0, 20000, allow_none=True)
        if "sleep_h" in p:
            out["sleep_h"] = v_num(p["sleep_h"], "sleep", 0, 24, allow_none=True)
        if "steps" in p:
            out["steps"] = v_int(p["steps"], "steps", 0, 200000, allow_none=True)
    return out


_TABLE_DEFAULTS = {}


def table_defaults(conn, table):
    """Defaults of the NOT NULL columns, so a partial row can be inserted."""
    if table not in _TABLE_DEFAULTS:
        d = {}
        for r in conn.execute(f"PRAGMA table_info({table})"):
            if r["notnull"] and r["dflt_value"] is not None:
                raw = str(r["dflt_value"])
                try:
                    d[r["name"]] = json.loads(raw)
                except ValueError:
                    d[r["name"]] = raw.strip("'")
        _TABLE_DEFAULTS[table] = d
    return _TABLE_DEFAULTS[table]


def upsert_by_client_id(conn, table, cols, client_id, fields, updated_at, deleted):
    """Insert or update a synced row. Missing fields keep what is stored. Returns (row, inserted)."""
    existing = conn.execute(f"SELECT * FROM {table} WHERE client_id = ?", (client_id,)).fetchone()
    row = {c: (existing[c] if existing else None) for c in cols}
    row.update({k: v for k, v in fields.items() if k in cols})
    for c, v in table_defaults(conn, table).items():
        if c in row and row[c] is None:
            row[c] = v
    row["client_id"] = client_id
    row["updated_at"] = updated_at
    row["deleted"] = deleted
    all_cols = ["client_id"] + cols + ["updated_at", "deleted"]
    assignments = ", ".join(f"{c} = excluded.{c}" for c in all_cols if c != "client_id")
    conn.execute(f"""INSERT INTO {table} ({', '.join(all_cols)}) VALUES ({', '.join('?' for _ in all_cols)})
                     ON CONFLICT(client_id) DO UPDATE SET {assignments} WHERE excluded.updated_at >= {table}.updated_at""",
                 [row[c] for c in all_cols])
    fresh = conn.execute(f"SELECT * FROM {table} WHERE client_id = ?", (client_id,)).fetchone()
    return dict(fresh), existing is None


def apply_food_op(conn, client_id, p):
    """A custom food made on the phone or laptop."""
    name = v_text(p.get("name"), "name", 120, allow_none=False)
    row = {
        "client_id": client_id, "name": name, "brand": v_text(p.get("brand"), "brand", 60),
        "unit": v_choice(p.get("unit") or "g", "unit", ("g", "ml")),
        "source": v_choice(p.get("source") or "custom", "source", ("custom", "off")),
        "source_id": v_text(p.get("source_id"), "source_id", 64), "barcode": v_text(p.get("barcode"), "barcode", 32),
        "kcal_100": v_num(p.get("kcal_100"), "calories per 100", 0, 1000),
        "protein_100": v_num(p.get("protein_100"), "protein", 0, 100, allow_none=True) or 0,
        "carb_100": v_num(p.get("carb_100"), "carbs", 0, 100, allow_none=True) or 0,
        "fat_100": v_num(p.get("fat_100"), "fat", 0, 100, allow_none=True) or 0,
        "approx": 1 if p.get("approx") else 0, "search": None,
        "portions": [(v_text(x[0], "portion", 80), v_num(x[1], "grams", 0.1, 20000)) for x in (p.get("portions") or []) if x and x[0]],
    }
    existing = conn.execute("SELECT id FROM foods WHERE client_id = ?", (client_id,)).fetchone()
    if existing:
        conn.execute("""UPDATE foods SET name = ?, brand = ?, unit = ?, kcal_100 = ?, protein_100 = ?, carb_100 = ?, fat_100 = ?, approx = ?,
                        barcode = COALESCE(?, barcode), active = ? WHERE id = ?""",
                     (row["name"], row["brand"], row["unit"], row["kcal_100"], row["protein_100"], row["carb_100"], row["fat_100"],
                      row["approx"], row["barcode"], 0 if p.get("deleted") else 1, existing["id"]))
        if row["portions"]:
            conn.execute("DELETE FROM food_portions WHERE food_id = ?", (existing["id"],))
            for i, (label, grams) in enumerate(row["portions"]):
                conn.execute("INSERT INTO food_portions (food_id, label, grams, is_default) VALUES (?,?,?,?)", (existing["id"], label, grams, 1 if i == 0 else 0))
        return existing["id"]
    if row["source"] == "off" and row["source_id"]:
        dup = conn.execute("SELECT id FROM foods WHERE source = 'off' AND source_id = ?", (row["source_id"],)).fetchone()
        if dup:
            conn.execute("UPDATE foods SET client_id = COALESCE(client_id, ?) WHERE id = ?", (client_id, dup["id"]))
            return dup["id"]
    insert_food(conn, row)
    return conn.execute("SELECT id FROM foods WHERE client_id = ?", (client_id,)).fetchone()["id"]


def resolve_food(conn, fields, batch_foods):
    fid = fields.get("food_id")
    if not fid and fields.get("food_client_id"):
        fid = batch_foods.get(fields["food_client_id"])
        if not fid:
            r = conn.execute("SELECT id FROM foods WHERE client_id = ?", (fields["food_client_id"],)).fetchone()
            fid = r["id"] if r else None
        if not fid:
            raise Retry("food not synced yet")
        fields["food_id"] = fid
    if not fid:
        raise BadRequest("Pick a food")
    food = conn.execute("SELECT * FROM foods WHERE id = ?", (fid,)).fetchone()
    if not food:
        raise BadRequest("That food is not in the list")
    return dict(food)


def apply_op(conn, op, settings, batch_workouts, batch_foods, touched):
    typ = op.get("type")
    cid = v_client_id(op.get("client_id"))
    p = op.get("payload") or {}
    if not isinstance(p, dict):
        raise BadRequest("payload must be an object")
    updated_at = v_ts(p.get("updated_at")) or now_iso()
    deleted = 1 if p.get("deleted") in (1, True, "1", "true") else 0
    if typ not in SYNC_TABLES:
        raise BadRequest(f"unknown op type {typ}")
    if typ == "food":
        fid = apply_food_op(conn, cid, dict(p, deleted=deleted))
        batch_foods[cid] = fid
        touched["foods"] = True
        return {"id": fid}
    table, cols = SYNC_TABLES[typ]
    existing = conn.execute(f"SELECT * FROM {table} WHERE client_id = ?", (cid,)).fetchone()
    fields = validate_payload(typ, p, existing)

    if typ == "set" or typ == "cardio":
        wcid = fields.get("workout_client_id") or (existing["workout_client_id"] if existing else None)
        parent = conn.execute("SELECT client_id FROM workouts WHERE client_id = ?", (wcid,)).fetchone()
        if not parent:
            raise Retry("workout not synced yet")
        if typ == "set":
            ex_id = fields.get("exercise_id") or (existing["exercise_id"] if existing else None)
            if ex_id not in EX_BY_ID:
                raise BadRequest("That exercise is not in the library")
            if "set_no" not in fields and not existing:
                n = conn.execute("SELECT COALESCE(MAX(set_no), 0) FROM set_logs WHERE workout_client_id = ? AND exercise_id = ? AND deleted = 0",
                                 (wcid, ex_id)).fetchone()[0]
                fields["set_no"] = n + 1
            if "done_at" not in fields and not existing:
                fields["done_at"] = now_iso()
        touched["workouts"].add(wcid)
    if typ == "workout":
        if not existing:
            fields.setdefault("started_at", now_iso())
        touched["workouts"].add(cid)
    if typ == "food_log":
        if not deleted:
            food = resolve_food(conn, fields if "food_id" in fields or "food_client_id" in fields else
                                dict(fields, food_id=existing["food_id"] if existing else None), batch_foods)
            fields["food_id"] = food["id"]
            grams = fields.get("grams") or (existing["grams"] if existing else None)
            qty = fields.get("qty") or (existing["qty"] if existing else 1) or 1
            if grams:
                vals = nutrition.food_log_values(food, grams, 1)
                fields.update({"kcal": vals["kcal"], "protein": vals["protein"], "carb": vals["carb"], "fat": vals["fat"], "grams": grams, "qty": qty})
        touched["foods"] = True
    if typ in ("body", "daily") and not existing:
        pass

    row, inserted = upsert_by_client_id(conn, table, cols, cid, fields, updated_at, deleted)
    if typ == "workout" and inserted and row.get("session_id"):
        programme.freeze_targets(conn, row["session_id"], row["date"], settings, EX_BY_ID, EX_BY_KEY, PROG)
    if typ == "food_log" and inserted and not deleted and row.get("food_id"):
        conn.execute("UPDATE foods SET times_used = times_used + 1, last_used = ? WHERE id = ?", (row["date"], row["food_id"]))
    return {"id": row["id"], "workout_client_id": row.get("workout_client_id") or (cid if typ == "workout" else None)}


def apply_sync(conn, body, settings):
    ops = body.get("ops")
    if not isinstance(ops, list):
        raise BadRequest("ops must be a list")
    ops = sorted(ops, key=lambda o: (SYNC_ORDER.get(o.get("type"), 9), str(o.get("at") or "")))
    applied, rejected, ids = [], [], {}
    touched = {"workouts": set(), "foods": False}
    batch_workouts = {o.get("client_id") for o in ops if o.get("type") == "workout"}
    batch_foods = {}
    conn.isolation_level = None
    conn.execute("BEGIN IMMEDIATE")
    try:
        for op in ops:
            cid = str(op.get("client_id") or "")
            conn.execute("SAVEPOINT op")
            try:
                result = apply_op(conn, op, settings, batch_workouts, batch_foods, touched)
                conn.execute("RELEASE op")
                applied.append(cid)
                if result.get("id") is not None:
                    ids[cid] = result["id"]
            except Retry as e:
                conn.execute("ROLLBACK TO op")
                conn.execute("RELEASE op")
                rejected.append({"client_id": cid, "error": str(e), "retry": True})
            except (BadRequest, PlanError) as e:
                conn.execute("ROLLBACK TO op")
                conn.execute("RELEASE op")
                rejected.append({"client_id": cid, "error": str(e), "retry": False})
        for wcid in touched["workouts"]:
            effort.recompute_workout(conn, wcid, settings, PROG)
            update_session_status(conn, wcid)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.isolation_level = ""
    if touched["foods"]:
        FOODS_CACHE["key"] = None
    return {"applied": applied, "rejected": rejected, "ids": ids, "server_time": now_iso()}


def update_session_status(conn, workout_client_id):
    w = conn.execute("SELECT session_id, ended_at, deleted, date FROM workouts WHERE client_id = ?", (workout_client_id,)).fetchone()
    if not w or not w["session_id"]:
        return
    other = conn.execute("SELECT COUNT(*) FROM workouts WHERE session_id = ? AND deleted = 0 AND ended_at IS NOT NULL AND client_id != ?",
                         (w["session_id"], workout_client_id)).fetchone()[0]
    if w["deleted"]:
        if not other:
            status = "planned" if w["date"] >= today().isoformat() else "skipped"
            conn.execute("UPDATE plan_sessions SET status = ? WHERE id = ? AND status = 'done'", (status, w["session_id"]))
    elif w["ended_at"]:
        conn.execute("UPDATE plan_sessions SET status = 'done' WHERE id = ?", (w["session_id"],))


def one_op(conn, settings, typ, client_id, payload):
    """Route helper: apply a single operation through the same path the phone uses."""
    res = apply_sync(conn, {"ops": [{"type": typ, "client_id": client_id, "payload": payload, "at": now_iso()}]}, settings)
    if res["rejected"]:
        r = res["rejected"][0]
        raise BadRequest(r["error"], 409 if r.get("retry") else 400)
    return res


# ----------------------------------------------------------------- views

def plan_ready(conn, settings, d):
    programme.ensure_plan_through(conn, d, settings, PROG, EX_BY_KEY, lambda k, v: set_setting(conn, k, v))
    programme.sweep_missed(conn, today())


def body_log_pairs(conn):
    return [(r["date"], r["weight_kg"]) for r in conn.execute(
        "SELECT date, weight_kg FROM body_logs WHERE deleted = 0 AND weight_kg IS NOT NULL")]


def exercise_kcal_on(conn, d):
    r = conn.execute("""SELECT COALESCE(SUM(COALESCE(NULLIF(kcal_wearable, 0), kcal_est)), 0) FROM workouts
                        WHERE date = ? AND deleted = 0 AND ended_at IS NOT NULL""", (d,)).fetchone()
    return float(r[0] or 0)


def food_day(conn, d):
    rows = [dict(r) for r in conn.execute("""
        SELECT fl.*, f.name, f.brand, f.unit, f.approx, f.source FROM food_logs fl LEFT JOIN foods f ON f.id = fl.food_id
        WHERE fl.date = ? AND fl.deleted = 0 ORDER BY fl.slot, fl.id""", (d,))]
    slots = {s: [] for s in SLOTS}
    totals = {"kcal": 0.0, "protein": 0.0, "carb": 0.0, "fat": 0.0}
    for r in rows:
        slots.setdefault(r["slot"], []).append(r)
        for k in totals:
            totals[k] += float(r.get(k) or 0)
    return {"date": d, "slots": slots, "totals": {k: round(v, 1) for k, v in totals.items()}}


def weight_block(conn, settings, d):
    logs = body_log_pairs(conn)
    trend, source = nutrition.trend_weight(logs, d, settings.get("start_weight_kg"))
    latest = conn.execute("SELECT date, weight_kg FROM body_logs WHERE deleted = 0 AND weight_kg IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    n14 = conn.execute("SELECT COUNT(*) FROM body_logs WHERE deleted = 0 AND weight_kg IS NOT NULL AND date >= ?",
                       ((d - timedelta(days=13)).isoformat(),)).fetchone()[0]
    pace = nutrition.pace_weight(settings, d)
    verdict = nutrition.pace_verdict(trend, pace, n14, settings.get("goal_start_weight"), settings.get("target_weight_kg"))
    return {"trend": trend, "source": source, "latest": dict(latest) if latest else None, "pace": pace,
            "verdict": verdict, "logs_last_14": n14, "weekly_pace": nutrition.weekly_pace(settings)}


def targets_block(conn, settings, d, trend):
    fd = food_day(conn, d.isoformat())
    return nutrition.targets(settings, trend, d, exercise_kcal_on(conn, d.isoformat()), fd["totals"]["kcal"]), fd


def build_state(conn, settings, loopback):
    d = today()
    plan_ready(conn, settings, d)
    wb = weight_block(conn, settings, d)
    tg, fd = targets_block(conn, settings, d, wb["trend"])
    bw = wb["trend"] or float(settings.get("start_weight_kg") or 80)
    daily = conn.execute("SELECT water_ml, sleep_h, steps FROM daily_logs WHERE date = ? AND deleted = 0", (d.isoformat(),)).fetchone()
    week = programme.week_view(conn, d, d, settings, PROG, EX_BY_ID, EX_BY_KEY)
    session_today = None
    strip = []
    if week:
        for s in week["sessions"]:
            strip.append({"id": s["id"], "date": s["date"], "kind": s["kind"], "title": s["title"], "status": s["status"],
                          "workout": s.get("workout")})
            if s["date"] == d.isoformat():
                session_today = s
    in_progress = conn.execute("SELECT client_id, session_id, date, started_at FROM workouts WHERE deleted = 0 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1").fetchone()
    last = conn.execute("SELECT client_id FROM workouts WHERE deleted = 0 AND ended_at IS NOT NULL ORDER BY date DESC, ended_at DESC LIMIT 1").fetchone()
    prs = effort.prs_for_workout(conn, last["client_id"], settings) if last else []
    adh = programme.adherence_by_week(conn)
    streak = 0
    for wk in reversed(adh):
        if wk["week"] > d.isoformat():
            continue
        if wk["planned"] and wk["done"] / wk["planned"] >= 0.8:
            streak += 1
        elif wk["week"] <= (d - timedelta(days=7)).isoformat():
            break
    queue_pending = conn.execute("SELECT COUNT(*) FROM workouts WHERE deleted = 0 AND ended_at IS NULL").fetchone()[0]
    return {
        "app": APP_ID, "version": APP_VERSION, "build": build_stamp(), "today": d.isoformat(),
        "settings": public_settings(settings), "profile_complete": nutrition.profile_complete(settings),
        "splits": [{"key": k, "name": v.get("name", k), "description": v.get("description", ""), "days": sorted(int(d) for d in v.get("templates", {}))} for k, v in PROG.get("splits", {}).items()],
        "targets": tg, "weight": wb, "food": fd,
        "daily": dict(daily) if daily else {"water_ml": None, "sleep_h": None, "steps": None},
        "session_today": session_today, "week": week, "strip": strip,
        "in_progress": dict(in_progress) if in_progress else None,
        "recent_prs": prs, "weeks_streak": streak, "open_workouts": queue_pending,
        "phone": phone_summary() if loopback else None,
        "exercises": [programme._exercise_public(e) for e in EX_BY_ID.values()],
    }


def today_payload(conn, settings):
    """What the phone caches for the gym: this week's sessions, last-time numbers and bests."""
    d = today()
    plan_ready(conn, settings, d + timedelta(days=6))
    bw = effort.bodyweight_on(conn, d, settings)
    sessions = []
    ex_ids = set()
    for s in conn.execute("SELECT * FROM plan_sessions WHERE date >= ? AND date <= ? ORDER BY date",
                          (d.isoformat(), (d + timedelta(days=6)).isoformat())).fetchall():
        view = programme.session_view(conn, s, d, settings, PROG, EX_BY_ID, EX_BY_KEY, bw)
        sessions.append(view)
        for it in view["items"]:
            if it.get("exercise_id"):
                ex_ids.add(it["exercise_id"])
    bests = {}
    for ex_id in ex_ids:
        ex = EX_BY_ID.get(ex_id)
        if ex and ex["pattern"] not in ("mobility",) and not ex["pattern"].startswith("cardio"):
            bests[str(ex_id)] = effort.bests_for_exercise(conn, ex_id, ex, bw)
    in_progress = conn.execute("SELECT * FROM workouts WHERE deleted = 0 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1").fetchone()
    detail = workout_detail(conn, in_progress["client_id"], settings) if in_progress else None
    return {"date": d.isoformat(), "sessions": sessions, "bests": bests, "bodyweight": bw, "in_progress": detail,
            "protocols": PROG.get("protocols", []), "rest_default_sec": settings.get("rest_default_sec") or 90,
            "warmup_moves": PROG.get("warmup_moves"), "cooldown_stretches": PROG.get("cooldown_stretches")}


def workout_detail(conn, client_id, settings):
    w = conn.execute("SELECT * FROM workouts WHERE client_id = ?", (client_id,)).fetchone()
    if not w:
        raise BadRequest("That workout does not exist", 404)
    w = dict(w)
    if w.get("effort_parts"):
        try:
            w["effort_parts"] = json.loads(w["effort_parts"])
        except ValueError:
            pass
    w["sets"] = [dict(r) for r in conn.execute("""SELECT s.*, e.name AS exercise_name, e.key AS exercise_key FROM set_logs s
                                                  JOIN exercises e ON e.id = s.exercise_id WHERE s.workout_client_id = ? AND s.deleted = 0
                                                  ORDER BY s.exercise_id, s.set_no""", (client_id,))]
    w["cardio"] = [dict(r) for r in conn.execute("""SELECT c.*, e.name AS exercise_name FROM cardio_logs c LEFT JOIN exercises e ON e.id = c.exercise_id
                                                    WHERE c.workout_client_id = ? AND c.deleted = 0""", (client_id,))]
    sess = conn.execute("SELECT * FROM plan_sessions WHERE id = ?", (w.get("session_id"),)).fetchone() if w.get("session_id") else None
    w["session"] = dict(sess) if sess else None
    w["prs"] = effort.prs_for_workout(conn, client_id, settings) if w.get("ended_at") else []
    w["kcal_used"] = w.get("kcal_wearable") or w.get("kcal_est")
    return w


def progress_payload(conn, settings, days):
    d = today()
    since = (d - timedelta(days=days)).isoformat()
    logs = body_log_pairs(conn)
    bw_cache = {}

    def bw_by_date(ds):
        if ds not in bw_cache:
            w, _ = nutrition.trend_weight(logs, nutrition.to_date(ds), settings.get("start_weight_kg"))
            bw_cache[ds] = w or 80.0
        return bw_cache[ds]

    mains = [r for r in conn.execute("""SELECT DISTINCT pi.exercise_id FROM plan_items pi JOIN plan_sessions ps ON ps.id = pi.session_id
                                        JOIN plan_weeks pw ON pw.id = ps.week_id JOIN blocks b ON b.id = pw.block_id
                                        WHERE b.block_no = 1 AND pi.slot_key = 'main1' AND pi.exercise_id IS NOT NULL""")]
    main_ids = [r["exercise_id"] for r in mains]
    baseline_weeks = {r["start_date"] for r in conn.execute("""SELECT pw.start_date FROM plan_weeks pw JOIN blocks b ON b.id = pw.block_id
                                                                WHERE b.block_no = 1 AND pw.week_no <= 3""")}
    trained = [r["exercise_id"] for r in conn.execute("""SELECT DISTINCT s.exercise_id FROM set_logs s JOIN workouts w ON w.client_id = s.workout_client_id
                                                          WHERE s.deleted = 0 AND s.is_warmup = 0 AND w.deleted = 0 AND w.ended_at IS NOT NULL""")]
    strength = []
    for ex_id in main_ids + [t for t in trained if t not in main_ids]:
        ex = EX_BY_ID.get(ex_id)
        if not ex or ex["pattern"].startswith("cardio") or ex["pattern"] == "mobility" or ex.get("timed"):
            continue
        series = effort.weekly_e1rm(conn, ex_id, bw_by_date)
        if not series:
            continue
        recent = [p["e1rm"] for p in series if p["week"] >= (d - timedelta(days=28)).isoformat() and not p["low_confidence"]]
        strength.append({"exercise_id": ex_id, "name": ex["name"], "main": ex_id in main_ids, "series": series,
                         "relative": round(max(recent) / bw_by_date(d.isoformat()), 2) if recent else None})
    index = effort.strength_index(conn, main_ids, bw_by_date, baseline_weeks) if main_ids else []
    volume = effort.weekly_muscle_sets(conn, since, bw_by_date(d.isoformat()))
    sessions = [dict(r) for r in conn.execute("""SELECT w.client_id, w.date, w.effort, w.kcal_est, w.kcal_wearable, w.volume, w.work_sets,
                                                  w.hard_sets, ps.kind, ps.title FROM workouts w LEFT JOIN plan_sessions ps ON ps.id = w.session_id
                                                  WHERE w.deleted = 0 AND w.ended_at IS NOT NULL AND w.date >= ? ORDER BY w.date""", (since,))]
    weights = [dict(r) for r in conn.execute("SELECT date, weight_kg, waist_cm, chest_cm, arm_cm, hip_cm, thigh_cm, note FROM body_logs WHERE deleted = 0 ORDER BY date")]
    trend_series = []
    for r in weights:
        if r["weight_kg"] is not None:
            t, _ = nutrition.trend_weight(logs, nutrition.to_date(r["date"]), settings.get("start_weight_kg"))
            trend_series.append({"date": r["date"], "trend": t})
    pace_pts = None
    if settings.get("goal_start_date") and settings.get("target_date"):
        pace_pts = [{"date": settings["goal_start_date"], "weight": settings.get("goal_start_weight")},
                    {"date": settings["target_date"], "weight": settings.get("target_weight_kg")}]
    eaten = {r["week"]: r["kcal"] for r in conn.execute("""SELECT date(date, '-6 days', 'weekday 1') AS week, SUM(kcal) AS kcal, COUNT(DISTINCT date) AS days
                                                          FROM food_logs WHERE deleted = 0 AND date >= ? GROUP BY week""", (since,))}
    days_logged = {r["week"]: r["days"] for r in conn.execute("""SELECT date(date, '-6 days', 'weekday 1') AS week, COUNT(DISTINCT date) AS days
                                                                 FROM food_logs WHERE deleted = 0 AND date >= ? GROUP BY week""", (since,))}
    burned = {r["week"]: r["kcal"] for r in conn.execute("""SELECT date(date, '-6 days', 'weekday 1') AS week,
                                                           SUM(COALESCE(NULLIF(kcal_wearable, 0), kcal_est)) AS kcal
                                                           FROM workouts WHERE deleted = 0 AND ended_at IS NOT NULL AND date >= ? GROUP BY week""", (since,))}
    weeks = sorted(set(eaten) | set(burned))
    calories = [{"week": w, "eaten": round(eaten.get(w) or 0), "burned": round(burned.get(w) or 0), "days": days_logged.get(w, 0)} for w in weeks]
    return {"since": since, "strength": strength, "index": index, "volume": volume, "sessions": sessions,
            "weights": weights, "trend": trend_series, "pace": pace_pts, "calories": calories,
            "adherence": programme.adherence_by_week(conn), "targets": {"weekly_pace": nutrition.weekly_pace(settings)}}


def history_payload(conn, q):
    frm = q.get("from") or (today() - timedelta(days=90)).isoformat()
    to = q.get("to") or today().isoformat()
    text = (q.get("q") or "").strip().lower()
    workouts = [dict(r) for r in conn.execute("""SELECT w.client_id, w.date, w.started_at, w.ended_at, w.effort, w.kcal_est, w.kcal_wearable, w.volume,
                                                  w.work_sets, w.hard_sets, w.notes, ps.kind, ps.title FROM workouts w LEFT JOIN plan_sessions ps ON ps.id = w.session_id
                                                  WHERE w.deleted = 0 AND w.date >= ? AND w.date <= ? ORDER BY w.date DESC, w.started_at DESC""", (frm, to))]
    if text:
        keep = []
        for w in workouts:
            names = " ".join(r["name"] for r in conn.execute("""SELECT DISTINCT e.name FROM set_logs s JOIN exercises e ON e.id = s.exercise_id
                                                                 WHERE s.workout_client_id = ? AND s.deleted = 0""", (w["client_id"],)))
            hay = " ".join([w.get("title") or "", w.get("notes") or "", names]).lower()
            if text in hay:
                keep.append(w)
        workouts = keep
    food_days = [dict(r) for r in conn.execute("""SELECT date, ROUND(SUM(kcal)) AS kcal, ROUND(SUM(protein)) AS protein, ROUND(SUM(carb)) AS carb,
                                                   ROUND(SUM(fat)) AS fat, COUNT(*) AS items FROM food_logs WHERE deleted = 0 AND date >= ? AND date <= ?
                                                   GROUP BY date ORDER BY date DESC""", (frm, to))]
    body = [dict(r) for r in conn.execute("SELECT * FROM body_logs WHERE deleted = 0 AND date >= ? AND date <= ? ORDER BY date DESC", (frm, to))]
    return {"from": frm, "to": to, "workouts": workouts, "food_days": food_days, "body": body}


# ----------------------------------------------------------------- foods

def foods_list_bytes(conn, gz):
    stamp = conn.execute("SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(SUM(times_used), 0) FROM foods WHERE active = 1").fetchone()
    key = tuple(stamp)
    if FOODS_CACHE["key"] != key:
        portions = {}
        for r in conn.execute("SELECT food_id, label, grams FROM food_portions ORDER BY food_id, is_default DESC, id"):
            portions.setdefault(r["food_id"], []).append([r["label"], r["grams"]])
        rows = []
        for r in conn.execute("""SELECT id, name, brand, unit, source, kcal_100, protein_100, carb_100, fat_100, approx, times_used, last_used, search, barcode
                                 FROM foods WHERE active = 1 ORDER BY name"""):
            rows.append([r["id"], r["name"], r["brand"], r["unit"], r["source"], r["kcal_100"], r["protein_100"], r["carb_100"], r["fat_100"],
                         r["approx"], r["times_used"], r["last_used"], portions.get(r["id"], []), r["search"], r["barcode"]])
        raw = json.dumps({"fields": ["id", "name", "brand", "unit", "source", "kcal_100", "protein_100", "carb_100", "fat_100", "approx",
                                     "times_used", "last_used", "portions", "search", "barcode"], "foods": rows},
                         separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        FOODS_CACHE.update({"key": key, "raw": raw, "gz": gzip.compress(raw, 6)})
    return FOODS_CACHE["gz"] if gz else FOODS_CACHE["raw"]


def food_row(conn, fid):
    f = conn.execute("SELECT * FROM foods WHERE id = ?", (fid,)).fetchone()
    if not f:
        raise BadRequest("That food does not exist", 404)
    f = dict(f)
    f["portions"] = [[r["label"], r["grams"]] for r in conn.execute("SELECT label, grams FROM food_portions WHERE food_id = ? ORDER BY is_default DESC, id", (fid,))]
    return f


def save_food(conn, body):
    """Accept an online result or make a custom food. Returns the food row."""
    cid = body.get("client_id") or str(uuid.uuid4())
    fid = apply_food_op(conn, cid, body)
    conn.commit()
    FOODS_CACHE["key"] = None
    return food_row(conn, fid)


def update_food(conn, fid, body):
    f = conn.execute("SELECT * FROM foods WHERE id = ?", (fid,)).fetchone()
    if not f:
        raise BadRequest("That food does not exist", 404)
    fields = {}
    if "name" in body:
        fields["name"] = v_text(body["name"], "name", 120, allow_none=False)
    if "brand" in body:
        fields["brand"] = v_text(body["brand"], "brand", 60)
    for k, hi in (("kcal_100", 1000), ("protein_100", 100), ("carb_100", 100), ("fat_100", 100)):
        if k in body:
            fields[k] = v_num(body[k], k, 0, hi)
    if "unit" in body:
        fields["unit"] = v_choice(body["unit"], "unit", ("g", "ml"))
    if "active" in body:
        fields["active"] = 1 if body["active"] in (1, True, "1", "true") else 0
    if "approx" in body:
        fields["approx"] = 1 if body["approx"] else 0
    if fields:
        conn.execute(f"UPDATE foods SET {', '.join(k + ' = ?' for k in fields)} WHERE id = ?", list(fields.values()) + [fid])
    if "portions" in body and isinstance(body["portions"], list):
        conn.execute("DELETE FROM food_portions WHERE food_id = ?", (fid,))
        for i, x in enumerate(body["portions"]):
            if x and x[0]:
                conn.execute("INSERT INTO food_portions (food_id, label, grams, is_default) VALUES (?,?,?,?)",
                             (fid, v_text(x[0], "portion", 80), v_num(x[1], "grams", 0.1, 20000), 1 if i == 0 else 0))
    conn.commit()
    FOODS_CACHE["key"] = None
    return food_row(conn, fid)


def meals_list(conn):
    out = []
    for m in conn.execute("SELECT * FROM meals WHERE active = 1 ORDER BY name"):
        items = [dict(r) for r in conn.execute("""SELECT mi.*, f.name, f.brand, f.kcal_100, f.protein_100, f.carb_100, f.fat_100 FROM meal_items mi
                                                  JOIN foods f ON f.id = mi.food_id WHERE mi.meal_id = ?""", (m["id"],))]
        kcal = sum(float(i["kcal_100"]) * float(i["grams"]) / 100 for i in items)
        protein = sum(float(i["protein_100"]) * float(i["grams"]) / 100 for i in items)
        out.append({"id": m["id"], "name": m["name"], "items": items, "kcal": round(kcal), "protein": round(protein)})
    return out


def save_meal(conn, body):
    name = v_text(body.get("name"), "name", 60, allow_none=False)
    items = []
    if body.get("from_date") and body.get("slot"):
        for r in conn.execute("SELECT food_id, grams, portion_label, qty FROM food_logs WHERE date = ? AND slot = ? AND deleted = 0 AND food_id IS NOT NULL",
                              (v_date(body["from_date"]), v_choice(body["slot"], "slot", SLOTS))):
            items.append((r["food_id"], r["grams"], r["portion_label"], r["qty"]))
    for it in body.get("items") or []:
        items.append((v_int(it.get("food_id"), "food_id", 1), v_num(it.get("grams"), "grams", 0.1, 20000),
                      v_text(it.get("portion_label"), "portion", 80), v_num(it.get("qty"), "qty", 0.01, 1000, allow_none=True) or 1))
    if not items:
        raise BadRequest("Nothing to save: that slot is empty")
    cur = conn.execute("INSERT INTO meals (name, active) VALUES (?, 1)", (name,))
    mid = cur.lastrowid
    for food_id, grams, label, qty in items:
        conn.execute("INSERT INTO meal_items (meal_id, food_id, grams, portion_label, qty) VALUES (?,?,?,?,?)", (mid, food_id, grams, label, qty))
    conn.commit()
    return mid


def add_meal(conn, settings, body):
    mid = v_int(body.get("meal_id"), "meal_id", 1)
    d = v_date(body.get("date") or today().isoformat())
    slot = v_choice(body.get("slot") or "snack", "slot", SLOTS)
    items = conn.execute("SELECT * FROM meal_items WHERE meal_id = ?", (mid,)).fetchall()
    if not items:
        raise BadRequest("That meal is empty or missing", 404)
    ops = []
    for it in items:
        ops.append({"type": "food_log", "client_id": str(uuid.uuid4()), "at": now_iso(),
                    "payload": {"date": d, "slot": slot, "food_id": it["food_id"], "grams": it["grams"], "portion_label": it["portion_label"], "qty": it["qty"]}})
    return apply_sync(conn, {"ops": ops}, settings)


def copy_slot(conn, settings, body):
    to_date_s = v_date(body.get("to_date") or today().isoformat())
    slot = v_choice(body.get("slot") or "breakfast", "slot", SLOTS)
    from_date_s = v_date(body.get("from_date") or (nutrition.to_date(to_date_s) - timedelta(days=1)).isoformat())
    rows = conn.execute("SELECT * FROM food_logs WHERE date = ? AND slot = ? AND deleted = 0", (from_date_s, slot)).fetchall()
    if not rows:
        raise BadRequest("Nothing to copy", 404)
    ops = []
    for r in rows:
        ops.append({"type": "food_log", "client_id": str(uuid.uuid4()), "at": now_iso(),
                    "payload": {"date": to_date_s, "slot": slot, "food_id": r["food_id"], "grams": r["grams"], "portion_label": r["portion_label"],
                                "qty": r["qty"]}})
    return apply_sync(conn, {"ops": ops}, settings)


# ----------------------------------------------------------------- settings

def update_settings(conn, settings, patch):
    if not isinstance(patch, dict):
        raise BadRequest("Send an object of settings")
    changed_goal = False
    changed_training = False
    for k, v in patch.items():
        if k not in SETTING_DEFAULTS or k in HIDDEN_SETTINGS:
            raise BadRequest(f"{k} is not a setting")
        if k in ("height_cm",):
            v = v_num(v, "height", 100, 250, allow_none=True)
        elif k in ("start_weight_kg", "target_weight_kg", "goal_start_weight"):
            v = v_num(v, k.replace("_", " "), 20, 400, allow_none=True)
        elif k in ("birth_date", "target_date", "goal_start_date", "programme_start"):
            v = v_date(v, k, allow_none=True)
        elif k == "sex":
            v = v_choice(v, "sex", ("m", "f"))
        elif k == "neat_factor":
            v = v_num(v, "activity factor", 1.0, 2.0)
        elif k in ("deficit_cap", "surplus_cap"):
            v = v_num(v, k, 0, 2000)
        elif k in ("protein_g_per_kg", "fat_g_per_kg", "fat_floor_g_per_kg"):
            v = v_num(v, k, 0.2, 4)
        elif k in ("carb_floor_g", "kcal_floor", "water_target_ml", "sleep_target_h", "steps_target", "rest_default_sec", "session_minutes"):
            v = v_num(v, k, 0, 100000, allow_none=True)
        elif k == "train_days":
            if not isinstance(v, list) or not v:
                raise BadRequest("Pick at least one training day")
            v = sorted({int(x) for x in v if 1 <= int(x) <= 7})
            if len(v) < 3:
                raise BadRequest("Pick at least three training days")
        elif k == "cardio_kit":
            if not isinstance(v, list):
                raise BadRequest("cardio_kit must be a list")
            v = [m for m in v if m in ("treadmill", "bike", "rower")]
            if not v:
                raise BadRequest("Keep at least one cardio machine")
        elif k == "experience":
            v = v_choice(v, "experience", tuple(PROG["rep_schemes"].keys()))
        elif k == "split":
            v = v_choice(v, "split", tuple(PROG.get("splits", {"upper_lower": 1}).keys()))
        elif k == "main1_swap_every_blocks":
            v = v_int(v, k, 1, 6)
        elif k == "stay_running":
            v = bool(v)
        elif k in ("theme", "contact_email", "display_name"):
            v = v_text(v, k, 120)
        if settings.get(k) != v:
            if k in GOAL_KEYS:
                changed_goal = True
            if k in TRAINING_KEYS:
                changed_training = True
        set_setting(conn, k, v)
        settings[k] = v
    if changed_goal and settings.get("target_weight_kg"):
        trend, _ = nutrition.trend_weight(body_log_pairs(conn), today(), settings.get("start_weight_kg"))
        set_setting(conn, "goal_start_weight", trend or settings.get("start_weight_kg"))
        set_setting(conn, "goal_start_date", today().isoformat())
        settings["goal_start_weight"] = trend or settings.get("start_weight_kg")
        settings["goal_start_date"] = today().isoformat()
    if "start_weight_kg" in patch and not settings.get("goal_start_weight") and settings.get("start_weight_kg"):
        set_setting(conn, "goal_start_weight", settings["start_weight_kg"])
        set_setting(conn, "goal_start_date", today().isoformat())
    conn.commit()
    if changed_training and conn.execute("SELECT COUNT(*) FROM plan_weeks").fetchone()[0]:
        programme.regenerate_from(conn, today(), settings, PROG, EX_BY_KEY)
        conn.commit()
    refresh_settings_cache(conn)
    return settings


# ----------------------------------------------------------------- exports and backups

TABLES = ("settings", "exercises", "blocks", "plan_weeks", "plan_sessions", "plan_items", "workouts", "set_logs", "cardio_logs",
          "foods", "food_portions", "meals", "meal_items", "food_logs", "body_logs", "daily_logs")


def export_csv(conn, what):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if what == "food":
        w.writerow(["date", "slot", "food", "brand", "grams", "portion", "qty", "kcal", "protein", "carb", "fat"])
        for r in conn.execute("""SELECT fl.date, fl.slot, f.name, f.brand, fl.grams, fl.portion_label, fl.qty, fl.kcal, fl.protein, fl.carb, fl.fat
                                 FROM food_logs fl LEFT JOIN foods f ON f.id = fl.food_id WHERE fl.deleted = 0 ORDER BY fl.date, fl.slot"""):
            w.writerow(list(r))
    elif what == "body":
        w.writerow(["date", "weight_kg", "waist_cm", "chest_cm", "arm_cm", "hip_cm", "thigh_cm", "water_ml", "sleep_h", "steps", "note"])
        for r in conn.execute("""SELECT b.date, b.weight_kg, b.waist_cm, b.chest_cm, b.arm_cm, b.hip_cm, b.thigh_cm, d.water_ml, d.sleep_h, d.steps, b.note
                                 FROM body_logs b LEFT JOIN daily_logs d ON d.date = b.date AND d.deleted = 0 WHERE b.deleted = 0 ORDER BY b.date"""):
            w.writerow(list(r))
    else:
        w.writerow(["date", "session", "exercise", "set", "reps", "weight_kg", "rpe", "warmup", "done_at", "workout_effort", "workout_kcal"])
        for r in conn.execute("""SELECT w.date, ps.title, e.name, s.set_no, s.reps, s.weight_kg, s.rpe, s.is_warmup, s.done_at, w.effort,
                                 COALESCE(NULLIF(w.kcal_wearable, 0), w.kcal_est) FROM set_logs s JOIN workouts w ON w.client_id = s.workout_client_id
                                 JOIN exercises e ON e.id = s.exercise_id LEFT JOIN plan_sessions ps ON ps.id = w.session_id
                                 WHERE s.deleted = 0 AND w.deleted = 0 ORDER BY w.date, w.started_at, e.name, s.set_no"""):
            w.writerow(list(r))
    return buf.getvalue()


def backup_json(conn):
    out = {"app": APP_ID, "version": APP_VERSION, "made": now_iso(), "tables": {}}
    for t in TABLES:
        out["tables"][t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
    return out


def restore_json(conn, data):
    tables = (data or {}).get("tables")
    if not isinstance(tables, dict) or (data or {}).get("app") != APP_ID:
        raise BadRequest("That is not a Fitness Tracker backup")
    conn.isolation_level = None
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in reversed(TABLES):
            conn.execute(f"DELETE FROM {t}")
        for t in TABLES:
            rows = tables.get(t) or []
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}
            for row in rows:
                cols = [c for c in row if c in have]
                conn.execute(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [row[c] for c in cols])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.isolation_level = ""
    refresh_exercises(conn)
    refresh_settings_cache(conn)
    FOODS_CACHE["key"] = None


def backup_db_bytes():
    tmp = os.path.join(HERE, f"fitness-backup-{int(time.time())}.db")
    conn = connect()
    try:
        conn.execute("VACUUM INTO ?", (tmp,))
    finally:
        conn.close()
    with open(tmp, "rb") as fh:
        data = fh.read()
    os.remove(tmp)
    return data


# ----------------------------------------------------------------- phone, certificates, build stamp

def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def cert_info(path):
    try:
        raw = ssl._ssl._test_decode_cert(path)   # noqa: private, but the standard library has nothing public for this
        ips = [v for k, v in raw.get("subjectAltName", ()) if k == "IP Address"]
        dns = [v for k, v in raw.get("subjectAltName", ()) if k == "DNS"]
        not_after = raw.get("notAfter")
        exp = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc).date().isoformat() if not_after else None
        return {"ips": ips, "dns": dns, "not_after": exp}
    except Exception:
        pass
    try:
        with open(CERT_SIDECAR, encoding="utf-8") as fh:
            side = json.load(fh)
        return {"ips": side.get("ips", []), "dns": side.get("dns", []), "not_after": (side.get("not_after") or "")[:10] or None}
    except (OSError, ValueError):
        return None


def check_cert():
    info = cert_info(CERT_PEM) if os.path.exists(CERT_PEM) else None
    ip = lan_ip()
    status = {"info": info, "lan_ip": ip, "covers_lan": None, "expires_soon": False}
    if not info:
        PHONE["cert"] = status
        return status
    if ip:
        status["covers_lan"] = ip in info["ips"]
        if not status["covers_lan"]:
            log(f"WARNING  This laptop's wifi address {ip} is not in certs\\server.pem (it covers {', '.join(info['ips']) or 'nothing'}). "
                "The phone will refuse to connect. Run tools\\make_cert.bat, then press Reload certificate in Settings > Phone.")
    else:
        log("Not on a network yet; skipped the certificate address check.")
    if info.get("not_after"):
        try:
            days = (date.fromisoformat(info["not_after"]) - today()).days
            if days < 30:
                status["expires_soon"] = True
                log(f"WARNING  certs\\server.pem expires on {info['not_after']}. Run tools\\make_cert.bat.")
        except ValueError:
            pass
    PHONE["cert"] = status
    return status


def phone_summary():
    return {"https": PHONE["https"], "reason": PHONE["reason"], "lan_ip": lan_ip(), "port": HTTPS_PORT, "cert": PHONE.get("cert")}


def phone_info():
    key = SETTINGS_CACHE.get("pair_key")
    ip = lan_ip()
    url = f"https://{ip}:{HTTPS_PORT}/?key={key}" if ip else None
    return {"https": PHONE["https"], "reason": PHONE["reason"], "lan_ip": ip, "port": HTTPS_PORT, "url": url, "key": key,
            "ca_url": f"https://{ip}:{HTTPS_PORT}/ca.crt" if ip else None, "cert": PHONE.get("cert"),
            "has_ca": os.path.exists(CA_PEM), "build": build_stamp(), "hostname": socket.gethostname()}


def build_stamp():
    sig = []
    for name in ("app.html", "sw.js", "manifest.webmanifest"):
        try:
            sig.append(os.path.getmtime(static_path(name)))
        except OSError:
            sig.append(0)
    if BUILD["sig"] != sig:
        h = hashlib.sha1()
        for name in ("app.html", "sw.js", "manifest.webmanifest"):
            h.update(read_static(name) or b"")
        BUILD["stamp"] = h.hexdigest()[:12]
        BUILD["sig"] = sig
    return BUILD["stamp"]


# ----------------------------------------------------------------- HTTP

STATIC = {
    "/": ("app.html", "text/html; charset=utf-8"),
    "/index.html": ("app.html", "text/html; charset=utf-8"),
    "/app.html": ("app.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/icon-maskable-512.png": ("icon-maskable-512.png", "image/png"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
}
PUBLIC_PATHS = {"/api/ping", "/ca.crt"}
NAV_PATHS = {"/", "/index.html", "/app.html"}

PAIR_HTML = """<!doctype html><html lang="en-NZ"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fitness Tracker</title><style>body{font-family:Bahnschrift,"Segoe UI",system-ui,sans-serif;background:#F2F1EC;color:#1E2A26;margin:0;padding:40px 20px}
.card{max-width:420px;margin:0 auto;background:#fff;border-radius:16px;padding:28px;box-shadow:0 8px 24px rgba(30,42,38,.08)}
h1{font-size:22px;margin:0 0 10px}p{line-height:1.5;color:#4A5A55}input{font:inherit;font-size:18px;padding:12px;width:100%;box-sizing:border-box;border:1px solid #C7CDC8;border-radius:10px;margin:14px 0}
button{font:inherit;font-size:16px;font-weight:600;padding:12px 18px;border:0;border-radius:10px;background:#3E6B48;color:#fff;width:100%}</style></head>
<body><div class="card"><h1>This phone is not paired</h1><p>On the laptop open Fitness Tracker, go to Settings then Phone, and scan the code again. Or type the pairing code here.</p>
<form method="get" action="/"><input name="key" autocomplete="off" autocapitalize="off" placeholder="Pairing code"><button type="submit">Pair this phone</button></form></div></body></html>"""


class AppServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, addr, handler, tls=False):
        self.tls = tls
        super().__init__(addr, handler)

    def get_request(self):
        """Wrap each accepted connection with the current TLS context.

        The handshake itself runs later, in the request thread, so a client
        that connects and says nothing cannot stall the accept loop. Wrapping
        per connection also means a reloaded certificate applies at once.
        """
        sock, addr = self.socket.accept()
        if self.tls:
            sock = TLS_CTX.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        ip = client_address[0] if client_address else "?"
        reason = getattr(exc, "reason", "") or ""
        if isinstance(exc, ssl.SSLError):
            if reason in ("TLSV1_ALERT_UNKNOWN_CA", "SSLV3_ALERT_CERTIFICATE_UNKNOWN", "SSLV3_ALERT_BAD_CERTIFICATE", "TLSV1_ALERT_UNKNOWN_CA"):
                log(f"Phone at {ip} does not trust the certificate yet. Install /ca.crt on it (Settings > Phone explains how).")
                return
            if reason in ("HTTP_REQUEST", "WRONG_VERSION_NUMBER"):
                log(f"Plain http request on the https port from {ip}. Use https://")
                return
            if isinstance(exc, ssl.SSLEOFError) or not VERBOSE:
                return
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, TimeoutError, socket.timeout, ConnectionAbortedError)):
            if VERBOSE:
                log(f"Connection from {ip} dropped: {type(exc).__name__}")
            return
        log(f"Error handling a request from {ip}: {type(exc).__name__}: {exc}")
        if VERBOSE:
            log(traceback.format_exc())


class Handler(BaseHTTPRequestHandler):
    server_version = f"FitnessTracker/{APP_VERSION}"
    timeout = 30

    def setup(self):
        if isinstance(self.request, ssl.SSLSocket):
            self.request.settimeout(10)
            self.request.do_handshake()
        super().setup()

    def log_message(self, fmt, *args):
        if VERBOSE:
            log("%s %s" % (self.client_address[0], fmt % args))

    # -- responses
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.timeout, ssl.SSLError):
            pass

    def _json(self, obj, code=200, extra=None):
        self._send(code, json.dumps(obj, default=str), extra=extra)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        if n > 20 * 1024 * 1024:
            raise BadRequest("That request is too large", 413)
        raw = self.rfile.read(n)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise BadRequest("The request body is not JSON")
        return data if isinstance(data, dict) else {"_": data}

    def _is_loopback(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _cookie(self, name):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k == name:
                    return v
        return None

    def _authorise(self, parsed, query):
        if self._is_loopback():
            return None
        if parsed.path in PUBLIC_PATHS:
            return None
        key = SETTINGS_CACHE.get("pair_key") or ""
        offered = (query.get("key", [None])[0] or self.headers.get("X-Pair-Key") or self._cookie("fit_pair") or "")
        if key and offered and hmac.compare_digest(str(offered), str(key)):
            if parsed.path in NAV_PATHS:
                extra = {"Set-Cookie": f"fit_pair={key}; Path=/; HttpOnly; SameSite=Lax; Max-Age=34560000" + ("; Secure" if self.server.tls else "")}
                if query.get("key"):
                    self._send(302, b"", "text/plain", dict(extra, Location="/"))
                    return "done"
                return extra
            return None
        raise Unauthorised()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, verb):
        LAST_SEEN["t"] = time.time()
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"
        try:
            extra = self._authorise(parsed, query)
            if extra == "done":
                return
            self.route(verb, path, query, extra if isinstance(extra, dict) else None)
        except Unauthorised:
            if path in NAV_PATHS or not path.startswith("/api/"):
                self._send(401, PAIR_HTML, "text/html; charset=utf-8")
            else:
                self._json({"error": "pair"}, 401)
        except PlanError as e:
            self._json({"error": str(e)}, e.code)
        except BadRequest as e:
            self._json({"error": str(e)}, e.code)
        except nutrition.OffRateLimited as e:
            self._json({"error": str(e), "retry_after": 30}, 503)
        except nutrition.OffError as e:
            self._json({"error": str(e)}, 502)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass
        except Exception as e:
            log(f"500 on {verb} {path}: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            self._json({"error": f"server error: {e}"}, 500)

    # -- routing
    def route(self, verb, path, query, extra):
        q = {k: v[0] for k, v in query.items()}
        if verb == "GET" and path in STATIC:
            name, ctype = STATIC[path]
            data = read_static(name)
            if data is None:
                return self._send(500, f"{name} is missing from this folder.", "text/plain; charset=utf-8")
            if name == "sw.js":
                data = data.replace(b"__BUILD__", build_stamp().encode("ascii"))
            return self._send(200, data, ctype, extra)
        if verb == "GET" and path == "/ca.crt":
            if not os.path.exists(CA_PEM):
                return self._send(404, "No certificate authority yet. Run tools\\make_cert.bat on the laptop.", "text/plain; charset=utf-8")
            with open(CA_PEM, encoding="ascii") as fh:
                der = ssl.PEM_cert_to_DER_cert(fh.read())
            return self._send(200, der, "application/x-x509-ca-cert", {"Content-Disposition": 'attachment; filename="fitness-tracker-ca.crt"'})
        if verb == "GET" and path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if not path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        api = path[5:]
        conn = connect()
        try:
            settings = get_settings(conn)
            return self.api(verb, api, q, conn, settings)
        finally:
            conn.close()

    def api(self, verb, api, q, conn, settings):
        loop = self._is_loopback()
        if verb == "GET":
            if api == "ping":
                return self._json({"ok": True, "app": APP_ID, "https": PHONE["https"], "build": build_stamp(), "version": APP_VERSION})
            if api == "state":
                out = build_state(conn, settings, loop)
                conn.commit()
                return self._json(out)
            if api == "today":
                out = today_payload(conn, settings)
                conn.commit()
                return self._json(out)
            if api == "settings":
                return self._json(public_settings(settings))
            if api == "exercises":
                return self._json([programme._exercise_public(e) for e in EX_BY_ID.values()])
            if api == "plan/week":
                d = nutrition.to_date(q.get("date")) or today()
                d = min(d, today() + timedelta(days=28))
                plan_ready(conn, settings, d)
                out = programme.week_view(conn, d, today(), settings, PROG, EX_BY_ID, EX_BY_KEY)
                conn.commit()
                return self._json(out)
            if api.startswith("workouts/"):
                return self._json(workout_detail(conn, api.split("/", 1)[1], settings))
            if api == "foods/list":
                gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
                data = foods_list_bytes(conn, gz)
                return self._send(200, data, "application/json; charset=utf-8", {"Content-Encoding": "gzip"} if gz else None)
            if api == "foods/online":
                return self._json(nutrition.off_search(q.get("q", ""), settings.get("contact_email")))
            if api.startswith("foods/barcode/"):
                res = nutrition.off_barcode(api.rsplit("/", 1)[1], settings.get("contact_email"))
                if not res:
                    return self._json({"error": "No product with that barcode on Open Food Facts"}, 404)
                return self._json(res)
            if api.startswith("foods/") and api[6:].isdigit():
                return self._json(food_row(conn, int(api[6:])))
            if api == "meals":
                return self._json(meals_list(conn))
            if api == "food/day":
                return self._json(food_day(conn, v_date(q.get("date") or today().isoformat())))
            if api == "progress":
                return self._json(progress_payload(conn, settings, int(q.get("days") or 90)))
            if api == "history":
                return self._json(history_payload(conn, q))
            if api == "export.csv":
                what = q.get("what") or "sets"
                return self._send(200, export_csv(conn, what), "text/csv; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="fitness-{what}-{today().isoformat()}.csv"'})
            if api == "backup.json":
                return self._send(200, json.dumps(backup_json(conn), default=str), "application/json; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="fitness-backup-{today().isoformat()}.json"'})
            if api == "backup.db":
                conn.close()
                return self._send(200, backup_db_bytes(), "application/octet-stream",
                                  {"Content-Disposition": f'attachment; filename="fitness-{today().isoformat()}.db"'})
            if api == "phone":
                if not loop:
                    return self._json({"error": "Only the laptop can see this"}, 403)
                return self._json(phone_info())
            return self._json({"error": "not found"}, 404)

        body = self._body()
        if verb == "POST":
            if api == "sync":
                return self._json(apply_sync(conn, body, settings))
            if api == "workouts":
                cid = body.get("client_id") or str(uuid.uuid4())
                sid = v_int(body.get("session_id"), "session_id", 1, allow_none=True)
                d = today().isoformat()
                if sid:
                    s = conn.execute("SELECT * FROM plan_sessions WHERE id = ?", (sid,)).fetchone()
                    if not s:
                        raise BadRequest("That session is not in the plan", 404)
                    if s["date"] != d:
                        programme.move_session(conn, sid, today())
                        conn.commit()
                payload = {"session_id": sid, "date": d, "started_at": body.get("started_at") or now_iso()}
                one_op(conn, settings, "workout", cid, payload)
                return self._json(workout_detail(conn, cid, settings))
            if api == "sets":
                cid = body.get("client_id") or str(uuid.uuid4())
                res = one_op(conn, settings, "set", cid, body)
                return self._json({"ok": True, "client_id": cid, "id": res["ids"].get(cid)})
            if api == "cardio":
                cid = body.get("client_id") or str(uuid.uuid4())
                res = one_op(conn, settings, "cardio", cid, body)
                return self._json({"ok": True, "client_id": cid, "id": res["ids"].get(cid)})
            if api == "food_logs":
                cid = body.get("client_id") or str(uuid.uuid4())
                one_op(conn, settings, "food_log", cid, body)
                return self._json(food_day(conn, body.get("date") or today().isoformat()))
            if api == "food_logs/meal":
                add_meal(conn, settings, body)
                return self._json(food_day(conn, body.get("date") or today().isoformat()))
            if api == "food_logs/copy":
                copy_slot(conn, settings, body)
                return self._json(food_day(conn, body.get("to_date") or today().isoformat()))
            if api == "body":
                d = v_date(body.get("date") or today().isoformat())
                one_op(conn, settings, "body", body.get("client_id") or f"body-{d}", dict(body, date=d))
                return self._json({"ok": True})
            if api == "daily":
                d = v_date(body.get("date") or today().isoformat())
                one_op(conn, settings, "daily", body.get("client_id") or f"daily-{d}", dict(body, date=d))
                return self._json({"ok": True})
            if api == "foods":
                return self._json(save_food(conn, body))
            if api == "meals":
                mid = save_meal(conn, body)
                return self._json({"ok": True, "id": mid, "meals": meals_list(conn)})
            if api == "exercises":
                return self._json(create_exercise(conn, body))
            if api == "plan/shuffle":
                week_id = v_int(body.get("week_id"), "week_id", 1)
                programme.shuffle_week(conn, week_id, settings, PROG, EX_BY_KEY)
                conn.commit()
                return self._json({"ok": True})
            if api == "plan/regenerate":
                programme.regenerate_from(conn, today(), settings, PROG, EX_BY_KEY)
                conn.commit()
                return self._json({"ok": True})
            if api == "plan/swap":
                ex = programme.swap_item(conn, v_int(body.get("item_id"), "item_id", 1), body.get("exercise_key"), PROG, EX_BY_KEY)
                conn.commit()
                return self._json({"ok": True, "exercise": programme._exercise_public(ex)})
            if api == "plan/move":
                programme.move_session(conn, v_int(body.get("session_id"), "session_id", 1), today())
                conn.commit()
                return self._json({"ok": True})
            if api == "plan/rest":
                programme.mark_rest(conn, v_int(body.get("session_id"), "session_id", 1))
                conn.commit()
                return self._json({"ok": True})
            if api == "restore":
                restore_json(conn, body)
                return self._json({"ok": True})
            if api == "phone/reload-cert":
                if not loop:
                    return self._json({"error": "Only the laptop can do this"}, 403)
                ok, reason = reload_tls()
                check_cert()
                return self._json({"ok": ok, "reason": reason, "phone": phone_info()})
            if api == "phone/new-key":
                if not loop:
                    return self._json({"error": "Only the laptop can do this"}, 403)
                set_setting(conn, "pair_key", secrets.token_urlsafe(9))
                conn.commit()
                refresh_settings_cache(conn)
                return self._json(phone_info())
            if api == "stop":
                self._json({"ok": True})
                log("Stop requested from the page")
                threading.Timer(0.3, STOP.set).start()
                return None
            return self._json({"error": "not found"}, 404)

        if verb == "PUT":
            if api == "settings":
                return self._json(public_settings(update_settings(conn, settings, body)))
            if api.startswith("workouts/"):
                cid = api.split("/", 1)[1]
                one_op(conn, settings, "workout", cid, body)
                return self._json(workout_detail(conn, cid, settings))
            if api.startswith("foods/") and api[6:].isdigit():
                return self._json(update_food(conn, int(api[6:]), body))
            if api.startswith("exercises/") and api[10:].isdigit():
                return self._json(update_exercise(conn, int(api[10:]), body))
            return self._json({"error": "not found"}, 404)

        if verb == "DELETE":
            if api.startswith("workouts/"):
                cid = api.split("/", 1)[1]
                one_op(conn, settings, "workout", cid, {"deleted": 1})
                return self._json({"ok": True})
            if api.startswith("sets/"):
                one_op(conn, settings, "set", api.split("/", 1)[1], {"deleted": 1})
                return self._json({"ok": True})
            if api.startswith("cardio/"):
                one_op(conn, settings, "cardio", api.split("/", 1)[1], {"deleted": 1})
                return self._json({"ok": True})
            if api.startswith("food_logs/"):
                one_op(conn, settings, "food_log", api.split("/", 1)[1], {"deleted": 1})
                return self._json({"ok": True})
            if api.startswith("meals/") and api[6:].isdigit():
                conn.execute("UPDATE meals SET active = 0 WHERE id = ?", (int(api[6:]),))
                conn.commit()
                return self._json({"ok": True})
            if api.startswith("foods/") and api[6:].isdigit():
                conn.execute("UPDATE foods SET active = 0 WHERE id = ?", (int(api[6:]),))
                conn.commit()
                FOODS_CACHE["key"] = None
                return self._json({"ok": True, "hidden": True})
            if api.startswith("exercises/") and api[10:].isdigit():
                conn.execute("UPDATE exercises SET active = 0 WHERE id = ?", (int(api[10:]),))
                conn.commit()
                refresh_exercises(conn)
                return self._json({"ok": True, "hidden": True})
            return self._json({"error": "not found"}, 404)
        return self._json({"error": "method not allowed"}, 405)


def create_exercise(conn, body):
    name = v_text(body.get("name"), "name", 80, allow_none=False)
    pattern = v_choice(body.get("pattern"), "pattern", ("squat", "hinge", "lunge", "horizontal_push", "vertical_push", "horizontal_pull",
                                                         "vertical_pull", "shoulder_iso", "triceps", "biceps", "rear_delt", "quad_iso", "ham_iso",
                                                         "glute", "calf", "core", "mobility"))
    muscle = v_choice(body.get("primary_muscle"), "primary muscle", ("chest", "shoulders", "back", "biceps", "triceps", "quads", "hamstrings",
                                                                     "glutes", "calves", "core"))
    equipment = v_choice(body.get("equipment") or "machine", "equipment", ("barbell", "trap_bar", "dumbbell", "cable", "machine", "assisted",
                                                                            "bodyweight", "band", "none"))
    cues = [v_text(c, "cue", 160) for c in (body.get("cues") or []) if c][:3]
    cur = conn.execute("""INSERT INTO exercises (key, name, pattern, primary_muscle, secondary_muscles, equipment, per_hand, timed, unilateral,
                          bodyweight_fraction, increment_kg, min_load_kg, mets, cues, is_custom, active)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,1,1)""",
                       (f"custom_{uuid.uuid4().hex[:8]}", name, pattern, muscle, json.dumps(body.get("secondary_muscles") or []), equipment,
                        1 if body.get("per_hand") else 0, 1 if body.get("timed") else 0, 1 if body.get("unilateral") else 0,
                        v_num(body.get("bodyweight_fraction"), "bodyweight fraction", 0, 1, allow_none=True) or 0,
                        v_num(body.get("increment_kg"), "increment", 0.5, 20, allow_none=True), v_num(body.get("min_load_kg"), "minimum load", 0, 100, allow_none=True),
                        json.dumps(cues)))
    conn.execute("UPDATE exercises SET key = ? WHERE id = ?", (f"custom_{cur.lastrowid}", cur.lastrowid))
    conn.commit()
    refresh_exercises(conn)
    return programme._exercise_public(EX_BY_ID[cur.lastrowid])


def update_exercise(conn, ex_id, body):
    if ex_id not in EX_BY_ID:
        raise BadRequest("That exercise does not exist", 404)
    fields = {}
    if "name" in body:
        fields["name"] = v_text(body["name"], "name", 80, allow_none=False)
    if "cues" in body:
        fields["cues"] = json.dumps([v_text(c, "cue", 160) for c in (body.get("cues") or []) if c][:3])
    if "active" in body:
        fields["active"] = 1 if body["active"] in (1, True, "1", "true") else 0
    if "increment_kg" in body:
        fields["increment_kg"] = v_num(body["increment_kg"], "increment", 0.5, 20, allow_none=True)
    if "min_load_kg" in body:
        fields["min_load_kg"] = v_num(body["min_load_kg"], "minimum load", 0, 100, allow_none=True)
    if "equipment" in body:
        fields["equipment"] = v_choice(body["equipment"], "equipment", ("barbell", "trap_bar", "dumbbell", "cable", "machine", "assisted", "bodyweight", "band", "none"))
    if fields:
        conn.execute(f"UPDATE exercises SET {', '.join(k + ' = ?' for k in fields)} WHERE id = ?", list(fields.values()) + [ex_id])
        conn.commit()
        refresh_exercises(conn)
    return programme._exercise_public(EX_BY_ID[ex_id])


# ----------------------------------------------------------------- listeners and lifecycle

def make_tls_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(CERT_PEM, CERT_KEY)
    return ctx


def reload_tls():
    global TLS_CTX
    if not (os.path.exists(CERT_PEM) and os.path.exists(CERT_KEY)):
        return False, "certs\\server.pem not found. Run tools\\make_cert.bat."
    try:
        TLS_CTX = make_tls_context()
    except ssl.SSLError as e:
        return False, f"The certificate could not be loaded: {e}"
    if not PHONE["https"]:
        return False, "Certificate loaded. Restart the app to start the phone listener."
    return True, None


def bind_https():
    if not (os.path.exists(CERT_PEM) and os.path.exists(CERT_KEY)):
        return None, "certs\\server.pem not found. Run tools\\make_cert.bat, then restart."
    global TLS_CTX
    try:
        TLS_CTX = make_tls_context()
    except ssl.SSLError as e:
        return None, f"The certificate could not be loaded: {e}"
    try:
        srv = AppServer((LAN_HOST, HTTPS_PORT), Handler, tls=True)
    except OSError:
        return None, f"Port {HTTPS_PORT} is in use by another program."
    return srv, None


def bind_http():
    ports = [HTTP_PORT] + list(HTTP_FALLBACK)
    for port in ports:
        try:
            return AppServer((HOST, port), Handler, tls=False), port
        except OSError:
            continue
    return None, None


def already_running():
    candidates = []
    try:
        with open(PORT_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
            candidates.append(int(data.get("http")))
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    if HTTP_PORT not in candidates:
        candidates.append(HTTP_PORT)
    for port in candidates:
        try:
            s = socket.create_connection((HOST, port), timeout=0.4)
            s.close()
        except OSError:
            continue
        try:
            c = http.client.HTTPConnection(HOST, port, timeout=1.5)
            c.request("GET", "/api/ping")
            body = c.getresponse().read().decode("utf-8")
            c.close()
            if json.loads(body).get("app") == APP_ID:
                return port
        except Exception:
            continue
    return None


def watchdog():
    while not STOP.is_set():
        time.sleep(5)
        if SETTINGS_CACHE.get("stay_running", True) and "--idle" not in sys.argv:
            continue
        idle = time.time() - LAST_SEEN["t"]
        if idle > IDLE_SECONDS:
            log(f"Quiet for {int(idle)} seconds, stopping")
            STOP.set()
            return


def main():
    if "--help" in sys.argv:
        print(__doc__)
        return 0
    running = already_running()
    if running:
        log(f"Already running on port {running}, opening the page")
        if "--no-browser" not in sys.argv:
            webbrowser.open(f"http://{HOST}:{running}/")
        return 0

    load_programme_files()
    init_db()

    http_srv, http_port = bind_http()
    if not http_srv:
        alert("Could not find a free port for Fitness Tracker. Close other copies and try again.")
        return 1
    https_srv, reason = bind_https()
    PHONE["https"] = https_srv is not None
    PHONE["reason"] = reason
    check_cert()

    try:
        with open(PORT_FILE, "w", encoding="utf-8") as fh:
            json.dump({"http": http_port, "https": HTTPS_PORT if https_srv else None}, fh)
    except OSError:
        pass

    servers = [s for s in (http_srv, https_srv) if s]
    for s in servers:
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()

    url = f"http://{HOST}:{http_port}/"
    log(f"Fitness Tracker {APP_VERSION} ready at {url}")
    if https_srv:
        log(f"Phone listener on https://{lan_ip() or LAN_HOST}:{HTTPS_PORT}/")
    else:
        log(f"Phone listener off: {reason}")
    log(f"Build {build_stamp()}")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        while not STOP.wait(1.0):
            pass
    except KeyboardInterrupt:
        STOP.set()
    finally:
        for s in servers:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
        try:
            os.remove(PORT_FILE)
        except OSError:
            pass
        log("Stopped")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        log(tb)
        alert("Fitness Tracker could not start:\n\n" + tb[-1500:])
        sys.exit(1)
