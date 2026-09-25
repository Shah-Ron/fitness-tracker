"""Unit tests for the Fitness Tracker engines.

Run from the project folder:  python -m unittest tests -v

One class per module: nutrition (targets, trend, pace), programme, effort,
the food side of nutrition plus the sync write path in fitness_tracker, and
the pure helpers in tools/build_food_db.py. Standard library only.

Database tests run against an in-memory SQLite copy of a seeded template
(real schema, default settings, the exercise library and both food lists),
so each test starts clean and seeding happens once. Every engine call takes
the fixed date TODAY, Thursday 24 September 2026; the tests never call
date.today() themselves.
"""

import importlib.util
import json
import os
import sqlite3
import unittest
import urllib.error
import uuid
from datetime import date, timedelta

import effort
import nutrition
import programme
import fitness_tracker as ft
from programme import PlanError

HERE = os.path.dirname(os.path.abspath(__file__))
TODAY = date(2026, 9, 24)            # a Thursday
MONDAY = date(2026, 9, 21)           # the Monday of that week
ISO = date.isoformat

with open(os.path.join(HERE, "data", "exercises.json"), encoding="utf-8") as _fh:
    EXJ = {e["key"]: e for e in json.load(_fh)["exercises"]}

# The fixture person: an 80 kg, 180 cm, 30-year-old man losing 8 kg in 100 days.
MAN = {
    "sex": "m", "birth_date": "1996-03-15", "height_cm": 180, "start_weight_kg": 80,
    "target_weight_kg": 72, "target_date": ISO(TODAY + timedelta(days=100)),
    "goal_start_weight": 80, "goal_start_date": ISO(TODAY),
}


# ----------------------------------------------------------------- fixtures

def settings_for(**over):
    """Default settings with the fixture profile, plus any overrides."""
    s = dict(ft.SETTING_DEFAULTS)
    s.update(MAN)
    s.update(over)
    return s


def targets(weight=80, exercise=0.0, eaten=0.0, **over):
    return nutrition.targets(settings_for(**over), weight, TODAY, exercise, eaten)


_TEMPLATE = None


def template_conn():
    """Seed the real schema, settings, exercises and food lists once."""
    global _TEMPLATE
    if _TEMPLATE is None:
        ft.load_programme_files()
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(ft.SCHEMA)
        for k, v in ft.SETTING_DEFAULTS.items():
            ft.set_setting(conn, k, v)
        ft.set_setting(conn, "pair_key", "test-pair-key")
        conn.commit()
        quiet, ft.log = ft.log, lambda msg: None
        try:
            ft.seed(conn)
        finally:
            ft.log = quiet
        _TEMPLATE = conn
    return _TEMPLATE


def fresh_conn():
    """A private in-memory copy of the seeded template."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    template_conn().backup(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    ft.refresh_exercises(conn)
    return conn


def ex_id(key):
    return ft.EX_BY_KEY[key]["id"]


def add_workout(conn, d, session_id=None, ended=True, kcal_est=0.0, kcal_wearable=None):
    """A workout row on a day, finished unless told otherwise. Marks its session done."""
    cid = str(uuid.uuid4())
    ended_at = f"{ISO(d)}T19:00:00" if ended else None
    conn.execute("""INSERT INTO workouts (client_id, session_id, date, started_at, ended_at, kcal_est, kcal_wearable, updated_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                 (cid, session_id, ISO(d), f"{ISO(d)}T18:00:00", ended_at, kcal_est, kcal_wearable, f"{ISO(d)}T19:00:00"))
    if session_id and ended:
        conn.execute("UPDATE plan_sessions SET status = 'done' WHERE id = ?", (session_id,))
    return cid


def add_sets(conn, wcid, key, rows, plan_item_id=None):
    """Working sets of one exercise; rows are (reps, weight_kg, rpe)."""
    for n, (reps, weight, rpe) in enumerate(rows, start=1):
        conn.execute("""INSERT INTO set_logs (client_id, workout_client_id, plan_item_id, exercise_id, set_no, reps, weight_kg, rpe,
                        is_warmup, done_at, updated_at) VALUES (?,?,?,?,?,?,?,?,0,NULL,?)""",
                     (str(uuid.uuid4()), wcid, plan_item_id, ex_id(key), n, reps, weight, rpe, "2026-09-24T19:00:00"))


def sync(conn, settings, ops):
    """Apply sync ops the way the phone does, from a clean transaction state."""
    conn.commit()
    return ft.apply_sync(conn, {"ops": ops}, settings)


def make_block(conn, settings, start=MONDAY):
    return programme.create_block(conn, start, settings, ft.PROG, ft.EX_BY_KEY)


def plan_weeks(conn, settings, n_weeks):
    """Blocks from MONDAY covering n_weeks, created through ensure_plan_through."""
    settings["programme_start"] = ISO(MONDAY)
    setter = lambda k, v: ft.set_setting(conn, k, v)
    programme.ensure_plan_through(conn, MONDAY, settings, ft.PROG, ft.EX_BY_KEY, setter)
    programme.ensure_plan_through(conn, MONDAY + timedelta(days=7 * n_weeks - 1), settings, ft.PROG, ft.EX_BY_KEY, setter)
    return weeks(conn)


def weeks(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM plan_weeks ORDER BY start_date")]


def sessions(conn, week_id):
    return [dict(r) for r in conn.execute("SELECT * FROM plan_sessions WHERE week_id = ? ORDER BY date", (week_id,))]


def session_on(conn, d):
    return dict(conn.execute("SELECT * FROM plan_sessions WHERE date = ?", (ISO(d),)).fetchone())


def session_by_id(conn, sid):
    return dict(conn.execute("SELECT * FROM plan_sessions WHERE id = ?", (sid,)).fetchone())


def items(conn, session_id):
    return [dict(r) for r in conn.execute("""SELECT pi.*, e.key AS exercise_key FROM plan_items pi
                                             LEFT JOIN exercises e ON e.id = pi.exercise_id
                                             WHERE pi.session_id = ? ORDER BY pi.ord""", (session_id,))]


def item(session_items, slot_key):
    return next(i for i in session_items if i["slot_key"] == slot_key)


def sets(*rows):
    return [{"reps": r, "weight_kg": w, "rpe": rpe} for r, w, rpe in rows]


def prog(key, rows, lo=6, hi=10, planned=3):
    """Run the progression rule on an exercise from exercises.json."""
    return programme.progression(EXJ[key], sets(*rows), lo, hi, planned)


def plan_item(ord_, section, slot, **kw):
    base = {"ord": ord_, "section": section, "slot_key": slot, "exercise_key": None, "sets": None, "rep_low": None,
            "rep_high": None, "rest_sec": None, "minutes": None, "protocol": None, "rounds": None, "optional": 0, "note": None}
    base.update(kw)
    return base


def upper_items():
    """The default Upper day before trimming: 58.0 minutes with a 10-minute finisher."""
    return [
        plan_item(1, "warmup", "wu_cardio", minutes=5.0, protocol="warm_easy_5"),
        plan_item(2, "warmup", "wu_dynamic", minutes=2.0),
        plan_item(3, "main", "main1", sets=3, rest_sec=150),
        plan_item(4, "main", "main2", sets=3, rest_sec=90),
        plan_item(5, "accessory", "acc1", sets=3, rest_sec=60),
        plan_item(6, "accessory", "acc2", sets=3, rest_sec=60),
        plan_item(7, "accessory", "acc3", sets=3, rest_sec=60),
        plan_item(8, "accessory", "acc4", sets=3, rest_sec=60, optional=1),
        plan_item(9, "finisher", "finisher", minutes=10.0, protocol="fin_tread_incline_walk"),
        plan_item(10, "cooldown", "cooldown", minutes=3.0),
    ]


def food(name, source="usda", brand=None, times_used=0, last_used=None):
    return {"name": name, "brand": brand, "source": source, "times_used": times_used, "last_used": last_used}


def food_fixture():
    return [
        food("Chicken, breast, meat only, cooked, roasted"),
        food("Chicken, thigh, meat only, cooked, roasted"),
        food("Chicken breast, skinless, raw", source="nz", brand="Tegel"),
        food("Chicken and rice roll", source="nz"),
        food("Bread, white, commercially prepared"),
        food("Egg, whole, raw"),
        food("Eggplant, raw"),
        food("Milk, whole, 3.25% milkfat"),
        food("Anchor Blue milk, standard", source="nz", brand="Anchor"),
        food("Anchor Trim milk", source="nz", brand="Anchor"),
        food("Rice, white, cooked", times_used=5),
        food("Rice, brown, cooked"),
    ]


def add_food(conn, name="Test oats", kcal=380, protein=13, carb=60, fat=8):
    cur = conn.execute("""INSERT INTO foods (client_id, name, source, source_id, kcal_100, protein_100, carb_100, fat_100)
                          VALUES (?,?,?,?,?,?,?,?)""", (str(uuid.uuid4()), name, "custom", None, kcal, protein, carb, fat))
    return cur.lastrowid


def food_log_op(fid, d, slot, grams, qty=1):
    return {"type": "food_log", "client_id": str(uuid.uuid4()),
            "payload": {"date": ISO(d), "slot": slot, "food_id": fid, "grams": grams, "qty": qty}}


OFF_PRODUCT = {
    "code": "9400000000001", "product_name": "Test bar", "product_name_en": "Test bar EN", "brands": "Brandy, Other",
    "quantity": "5 x 33 g", "serving_size": "1 bar (33 g)",
    "nutriments": {"energy-kcal_100g": 450, "proteins_100g": 10, "carbohydrates_100g": 60, "fat_100g": 18},
}


class _Resp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_opener(payload, calls):
    """Stands in for urllib.request.urlopen and records every URL asked for."""
    def opener(req, timeout=None):
        calls.append(req.full_url)
        if isinstance(payload, Exception):
            raise payload
        return _Resp(payload)
    return opener


def load_food_db_tool():
    spec = importlib.util.spec_from_file_location("build_food_db", os.path.join(HERE, "tools", "build_food_db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ================================================================= nutrition

class NutritionTests(unittest.TestCase):
    """Targets, weight trend, pace line and verdict in nutrition.py."""

    def test_bmr_male(self):
        """Mifflin-St Jeor for the fixture man."""
        self.assertEqual(nutrition.bmr("m", 80, 180, 30), 1780)

    def test_bmr_female(self):
        """Mifflin-St Jeor for a 60 kg, 165 cm, 28-year-old woman."""
        self.assertEqual(nutrition.bmr("f", 60, 165, 28), 1330.25)

    def test_age_floors_partial_years(self):
        self.assertEqual(nutrition.age_on("1996-03-15", TODAY), 30)
        self.assertEqual(nutrition.age_on(date(1996, 9, 25), TODAY), 29)

    def test_maintenance_neat(self):
        t = targets()
        self.assertEqual(t["bmr"], 1780)
        self.assertEqual(t["base"], 2314)

    def test_deficit_within_cap(self):
        """8 kg in 100 days needs 616 kcal a day."""
        t = targets()
        self.assertEqual(t["deficit"], 616)
        self.assertEqual(t["mode"], "losing")
        self.assertFalse(t["capped"])
        self.assertIsNone(t["eta"])

    def test_deficit_clamped_and_eta(self):
        """8 kg in 50 days is clamped to 750 and lands 83 days out."""
        t = targets(target_date=ISO(TODAY + timedelta(days=50)))
        self.assertEqual(t["deficit"], 750)
        self.assertTrue(t["capped"])
        self.assertEqual(t["eta"], ISO(TODAY + timedelta(days=83)))
        self.assertFalse(t["target_passed"])

    def test_deficit_target_date_passed(self):
        t = targets(target_date=ISO(TODAY - timedelta(days=1)))
        self.assertEqual(t["deficit"], 750)
        self.assertTrue(t["capped"])
        self.assertTrue(t["target_passed"])

    def test_surplus_capped(self):
        """70 to 76 kg in 30 days is a surplus capped at 300 with an eta 154 days out."""
        t = targets(weight=70, goal_start_weight=70, target_weight_kg=76, target_date=ISO(TODAY + timedelta(days=30)))
        self.assertEqual(t["deficit"], -300)
        self.assertEqual(t["mode"], "gaining")
        self.assertTrue(t["capped"])
        self.assertEqual(t["eta"], ISO(TODAY + timedelta(days=154)))

    def test_at_target_band(self):
        t = targets(target_weight_kg=79.8)
        self.assertEqual(t["deficit"], 0)
        self.assertEqual(t["mode"], "maintaining")
        self.assertFalse(t["capped"])

    def test_budget_no_workout(self):
        t = targets(eaten=500)
        self.assertEqual(t["budget"], 1698)
        self.assertEqual(t["left"], 1198)
        self.assertFalse(t["floored"])

    def test_budget_with_workout_350(self):
        self.assertEqual(targets(exercise=350)["budget"], 2048)

    def test_budget_wearable_overrides_estimate(self):
        """A wearable figure on the finished workout replaces the estimate."""
        conn = fresh_conn()
        add_workout(conn, TODAY, kcal_est=350, kcal_wearable=420)
        burned = ft.exercise_kcal_on(conn, ISO(TODAY))
        self.assertEqual(burned, 420)
        self.assertEqual(targets(exercise=burned)["budget"], 2118)

    def test_exercise_kcal_counts_finished_workouts_only(self):
        conn = fresh_conn()
        add_workout(conn, TODAY, ended=False, kcal_est=350)
        self.assertEqual(ft.exercise_kcal_on(conn, ISO(TODAY)), 0)
        add_workout(conn, TODAY, kcal_est=350)
        self.assertEqual(ft.exercise_kcal_on(conn, ISO(TODAY)), 350)
        self.assertEqual(targets(exercise=350)["budget"], 2048)

    def test_budget_floor_male(self):
        """base 2314 minus a 914 deficit is 1400, held at the 1500 floor."""
        t = targets(deficit_cap=914, target_date=ISO(TODAY + timedelta(days=50)))
        self.assertEqual(t["deficit"], 914)
        self.assertEqual(t["budget"], 1500)
        self.assertTrue(t["floored"])

    def test_budget_floor_female_default_1200(self):
        t = targets(weight=60, sex="f", birth_date="1998-03-15", height_cm=165, goal_start_weight=60,
                    target_weight_kg=52, target_date=ISO(TODAY + timedelta(days=30)))
        self.assertEqual(t["floor"], 1200)
        self.assertEqual(t["budget"], 1200)
        self.assertTrue(t["floored"])

    def test_macros_default(self):
        t = targets()
        self.assertEqual((t["protein"], t["fat"], t["carbs"]), (160, 64, 120.5))

    def test_macros_carb_floor_reduces_fat(self):
        """100 kg on a 1500 budget: carbs held at 50 g, fat drops to 55.6 g."""
        t = targets(weight=100, goal_start_weight=100, target_weight_kg=90,
                    target_date=ISO(TODAY + timedelta(days=50)), deficit_cap=1074)
        self.assertEqual(t["budget"], 1500)
        self.assertEqual((t["protein"], t["carbs"], t["fat"]), (200, 50, 55.6))

    def test_profile_incomplete_gives_no_numbers(self):
        t = nutrition.targets(settings_for(height_cm=None), 80, TODAY)
        self.assertEqual(t, {"complete": False})
        self.assertFalse(nutrition.targets(settings_for(), None, TODAY)["complete"])

    def test_current_weight_falls_back_to_start(self):
        self.assertEqual(nutrition.trend_weight([], TODAY, 80), (80.0, "start"))
        self.assertEqual(nutrition.trend_weight([], TODAY, None), (None, "none"))

    def test_trend_seven_day_mean(self):
        logs = [(TODAY - timedelta(days=2), 80), (TODAY - timedelta(days=1), 81), (TODAY, 79)]
        self.assertEqual(nutrition.trend_weight(logs, TODAY, 70), (80.0, "trend"))
        # a log eight days back is outside the window
        self.assertEqual(nutrition.trend_weight(logs + [(TODAY - timedelta(days=7), 100)], TODAY, 70), (80.0, "trend"))
        self.assertEqual(nutrition.trend_weight(logs + [(TODAY - timedelta(days=6), 84)], TODAY, 70), (81.0, "trend"))

    def test_trend_carries_forward_when_window_empty(self):
        logs = [(ISO(TODAY - timedelta(days=20)), 82), (ISO(TODAY - timedelta(days=10)), 81.5), (TODAY + timedelta(days=1), 70)]
        self.assertEqual(nutrition.trend_weight(logs, TODAY, 80), (81.5, "latest"))

    def test_pace_line_midpoint(self):
        s = settings_for()
        self.assertEqual(nutrition.pace_weight(s, TODAY + timedelta(days=50)), 76.0)
        self.assertEqual(nutrition.pace_weight(s, TODAY - timedelta(days=5)), 80.0)
        self.assertEqual(nutrition.pace_weight(s, TODAY + timedelta(days=200)), 72.0)
        self.assertEqual(nutrition.weekly_pace(s), -0.56)

    def test_verdict_on_pace(self):
        v = nutrition.pace_verdict(80.0, 79.5, 3, 80, 72)
        self.assertEqual(v["code"], "on_pace")

    def test_verdict_behind(self):
        v = nutrition.pace_verdict(80.6, 79.5, 3, 80, 72)
        self.assertEqual(v["code"], "behind")
        self.assertEqual(v["text"].lower(), "behind by 1.1 kg")

    def test_verdict_ahead_for_gain_goal(self):
        """Gaining: above the line is ahead. Losing: below the line is ahead."""
        self.assertEqual(nutrition.pace_verdict(73.0, 72.0, 5, 70, 76)["code"], "ahead")
        self.assertEqual(nutrition.pace_verdict(72.0, 73.0, 5, 70, 76)["code"], "behind")
        self.assertEqual(nutrition.pace_verdict(78.0, 79.5, 5, 80, 72)["text"].lower(), "ahead by 1.5 kg")

    def test_verdict_needs_three_logs(self):
        self.assertEqual(nutrition.pace_verdict(80.6, 79.5, 2, 80, 72)["code"], "no_data")
        self.assertEqual(nutrition.pace_verdict(None, 79.5, 5, 80, 72)["code"], "no_data")


# ================================================================= programme

class ProgrammeTests(unittest.TestCase):
    """Rounding, progression, rotation, blocks, trimming and session management in programme.py."""

    # ---- pure rules

    def test_round_load_half_up(self):
        self.assertEqual(effort.round_load(41.25, "barbell"), 42.5)
        self.assertEqual(effort.round_load(41.24, "barbell"), 40.0)
        self.assertEqual(effort.round_load(43.75), 45.0)

    def test_round_load_dumbbell_under_10(self):
        self.assertEqual(effort.round_load(7.6, "dumbbell"), 8.0)
        self.assertEqual(effort.round_load(7.4, "dumbbell"), 7.0)
        self.assertEqual(effort.round_load(11.3, "dumbbell"), 12.5)

    def test_progression_increase_upper(self):
        self.assertEqual(prog("barbell_bench_press", [(10, 40, 7), (10, 40, 7), (10, 40, 8)]), (42.5, "increase"))

    def test_progression_increase_lower(self):
        """Squat and hinge patterns on a bar go up 5 kg."""
        self.assertEqual(prog("back_squat", [(10, 60, 8)] * 3), (65.0, "increase"))
        self.assertEqual(prog("trap_bar_deadlift", [(10, 80, 8)] * 3), (85.0, "increase"))

    def test_progression_hold_reps(self):
        self.assertEqual(prog("barbell_bench_press", [(8, 40, 7)] * 3), (40, "hold_reps"))

    def test_progression_hold_rpe(self):
        self.assertEqual(prog("barbell_bench_press", [(10, 40, 9)] * 3), (40, "hold_rpe"))

    def test_progression_decrease_below_low(self):
        self.assertEqual(prog("barbell_bench_press", [(10, 40, 8), (8, 40, 8), (5, 40, 9)]), (37.5, "decrease_reps"))

    def test_progression_decrease_two_high_rpe(self):
        self.assertEqual(prog("barbell_bench_press", [(10, 40, 9.5), (10, 40, 10), (10, 40, 8)]), (37.5, "decrease_rpe"))

    def test_progression_decrease_at_least_one_step(self):
        """95 per cent of 10 kg rounds back to 10, so the drop is a full plate step."""
        self.assertEqual(prog("cable_pushdown", [(12, 10, 8), (10, 10, 9), (7, 10, 10)], 10, 15), (7.5, "decrease_reps"))

    def test_progression_barbell_floor(self):
        self.assertEqual(prog("barbell_bench_press", [(6, 20, 9), (5, 20, 10), (4, 20, 10)]), (20.0, "decrease_reps"))

    def test_progression_partial_sets_hold(self):
        self.assertEqual(prog("barbell_bench_press", [(10, 40, 7), (10, 40, 7)]), (40, "hold_partial"))

    def test_progression_missing_rpe_neutral(self):
        self.assertEqual(prog("barbell_bench_press", [(10, 40, None)] * 3), (42.5, "increase"))

    def test_progression_dumbbell_steps(self):
        self.assertEqual(prog("db_lateral_raise", [(15, 8, 7)] * 3, 10, 15), (9.0, "increase"))
        self.assertEqual(prog("db_lateral_raise", [(15, 10, 7)] * 3, 10, 15), (12.5, "increase"))

    def test_progression_assisted_inverts(self):
        """Less assistance is the increase; a failed set adds assistance."""
        self.assertEqual(prog("assisted_pull_up", [(12, 30, 7)] * 3, 8, 12), (27.5, "increase"))
        self.assertEqual(prog("assisted_pull_up", [(12, 30, 7), (6, 30, 9), (5, 30, 10)], 8, 12), (32.5, "decrease_reps"))

    def test_progression_timed_adds_seconds(self):
        self.assertEqual(prog("plank", [(60, None, 7)] * 3, 30, 60), (None, "add_time"))
        self.assertEqual(prog("plank", [(45, None, 7)] * 3, 30, 60), (None, "hold_time"))

    def test_progression_empty_is_first(self):
        self.assertEqual(programme.progression(EXJ["barbell_bench_press"], [], 6, 10, 3), (None, "first"))

    # ---- targets against the database

    def _item(self, lo=6, hi=10):
        return {"rep_low": lo, "rep_high": hi, "sets": 3}

    def test_progression_skips_deload_reference(self):
        """The week 3 squat, not the week 4 deload, sets next block's target."""
        conn = fresh_conn()
        s = ft.get_settings(conn)
        s["programme_start"] = ISO(MONDAY)
        make_block(conn, s)
        wk = weeks(conn)
        self.assertEqual([w["is_deload"] for w in wk], [0, 0, 0, 1])
        s3 = next(x for x in sessions(conn, wk[2]["id"]) if x["kind"] == "lower_a")
        s4 = next(x for x in sessions(conn, wk[3]["id"]) if x["kind"] == "lower_a")
        w3 = add_workout(conn, date.fromisoformat(s3["date"]), s3["id"])
        add_sets(conn, w3, "back_squat", [(10, 60, 8)] * 3)
        w4 = add_workout(conn, date.fromisoformat(s4["date"]), s4["id"])
        add_sets(conn, w4, "back_squat", [(10, 55, 7)] * 3)
        t = programme.target_for(conn, ft.EX_BY_KEY["back_squat"], self._item(), date(2026, 10, 20))
        self.assertEqual((t["weight"], t["source"]), (65.0, "increase"))
        self.assertEqual(t["last"]["date"], s3["date"])

    def test_progression_first_exposure_blank(self):
        conn = fresh_conn()
        t = programme.target_for(conn, ft.EX_BY_KEY["barbell_bench_press"], self._item(), TODAY, ex_by_key=ft.EX_BY_KEY)
        self.assertEqual((t["weight"], t["source"], t["last"]), (None, "first", None))
        self.assertIn("8 reps", t["text"])

    def test_progression_guess_from_variation(self):
        """Flat bench e1RM 100 gives the incline a 0.8 carry guess of 67.5 at rep_low 6."""
        conn = fresh_conn()
        w = add_workout(conn, TODAY - timedelta(days=7))
        add_sets(conn, w, "barbell_bench_press", [(10, 75, 8)])      # e1RM exactly 100
        t = programme.target_for(conn, ft.EX_BY_KEY["incline_barbell_bench_press"], self._item(), TODAY,
                                 ex_by_key=ft.EX_BY_KEY, bw=80)
        self.assertEqual((t["weight"], t["source"]), (67.5, "guess"))

    def test_progression_stale_reference_holds(self):
        conn = fresh_conn()
        w = add_workout(conn, TODAY - timedelta(days=40))
        add_sets(conn, w, "barbell_bench_press", [(10, 40, 7)] * 3)
        ex = ft.EX_BY_KEY["barbell_bench_press"]
        t = programme.target_for(conn, ex, self._item(), TODAY)
        self.assertEqual((t["weight"], t["source"]), (40.0, "stale"))
        # exactly 28 days old is still fresh
        t = programme.target_for(conn, ex, self._item(), TODAY - timedelta(days=12))
        self.assertEqual((t["weight"], t["source"]), (42.5, "increase"))

    def test_deload_target(self):
        conn = fresh_conn()
        w = add_workout(conn, TODAY - timedelta(days=7))
        add_sets(conn, w, "barbell_bench_press", [(10, 40, 7)] * 3)
        t = programme.target_for(conn, ft.EX_BY_KEY["barbell_bench_press"], self._item(), TODAY, is_deload=True)
        self.assertEqual((t["weight"], t["source"]), (37.5, "deload"))

    # ---- rotation

    def test_pick_deterministic(self):
        pool = ["a", "b", "c"]
        self.assertEqual(programme.pick(pool, "seed:1", "upper_a:acc1"), programme.pick(pool, "seed:1", "upper_a:acc1"))
        self.assertEqual(programme.pick(pool, "seed:1", "upper_a:acc1", "b"), programme.pick(pool, "seed:1", "upper_a:acc1", "b"))

    def test_pick_no_repeat(self):
        pool = ["a", "b", "c"]
        for i in range(60):
            self.assertNotEqual(programme.pick(pool, f"s{i}:2", "lower_a:acc1", "b"), "b")

    def test_pick_pool_two_alternates(self):
        prev, seq = None, []
        for i in range(6):
            prev = programme.pick(["A", "B"], f"x:{i}", "slot", prev)
            seq.append(prev)
        self.assertNotEqual(seq[0], seq[1])
        self.assertEqual(seq, [seq[0], seq[1]] * 3)

    def test_pick_pool_one_constant(self):
        self.assertEqual(programme.pick(["only"], "s:1", "slot", "only"), "only")
        self.assertIsNone(programme.pick([], "s:1", "slot"))

    def _four_blocks(self):
        conn = fresh_conn()
        s = ft.get_settings(conn)
        s["programme_start"] = ISO(MONDAY)
        main1, main2 = [], []
        for b in range(4):
            block = make_block(conn, s, MONDAY + timedelta(days=28 * b))
            self.assertEqual(block["block_no"], b + 1)
            wk = weeks(conn)[4 * b]
            ua = next(x for x in sessions(conn, wk["id"]) if x["kind"] == "upper_a")
            its = items(conn, ua["id"])
            main1.append(item(its, "main1")["exercise_key"])
            main2.append(item(its, "main2")["exercise_key"])
        return main1, main2

    def test_block_alternate_main1_every_two_blocks(self):
        main1, _ = self._four_blocks()
        self.assertEqual(main1, ["barbell_bench_press"] * 2 + ["incline_barbell_bench_press"] * 2)

    def test_block_alternate_main2_every_block(self):
        _, main2 = self._four_blocks()
        self.assertEqual(main2, ["lat_pulldown", "seated_cable_row"] * 2)

    # ---- layout

    def test_week_five_days_layout(self):
        conn = fresh_conn()
        s = ft.get_settings(conn)
        s["programme_start"] = ISO(MONDAY)
        make_block(conn, s)
        week = sessions(conn, weeks(conn)[0]["id"])
        self.assertEqual([x["kind"] for x in week], ["upper_a", "lower_a", "conditioning", "upper_b", "lower_b", "rest", "rest"])
        self.assertEqual(week[0]["date"], ISO(MONDAY))
        self.assertEqual(week[0]["title"], "Upper A")

    def test_week_six_days_zone2_last(self):
        conn = fresh_conn()
        s = ft.get_settings(conn)
        s["programme_start"] = ISO(MONDAY)
        s["train_days"] = [1, 2, 3, 4, 5, 6]
        make_block(conn, s)
        week = sessions(conn, weeks(conn)[0]["id"])
        self.assertEqual([x["kind"] for x in week][5:], ["zone2", "rest"])
        z = items(conn, week[5]["id"])
        self.assertEqual(len(z), 1)
        self.assertEqual((z[0]["protocol"], z[0]["minutes"]), ("zone2_steady", 35.0))
        cond_machine = item(items(conn, week[2]["id"]), "wu_cardio")["exercise_key"]
        self.assertNotEqual(z[0]["exercise_key"], cond_machine)

    def test_first_block_starts_monday_void_before_today(self):
        """Starting on a Thursday: Mon to Wed are void, Thu and Fri planned, rest days untouched."""
        conn = fresh_conn()
        s = ft.get_settings(conn)
        s["programme_start"] = ISO(TODAY)
        block = make_block(conn, s, TODAY)
        self.assertEqual(block["start_date"], ISO(MONDAY))
        week = sessions(conn, weeks(conn)[0]["id"])
        self.assertEqual([x["status"] for x in week], ["void", "void", "void", "planned", "planned", "planned", "planned"])

    def test_deload_week_sets(self):
        conn = fresh_conn()
        s = ft.get_settings(conn)
        s["programme_start"] = ISO(MONDAY)
        make_block(conn, s)
        wk = weeks(conn)
        ua1 = items(conn, next(x for x in sessions(conn, wk[0]["id"]) if x["kind"] == "upper_a")["id"])
        ua4 = items(conn, next(x for x in sessions(conn, wk[3]["id"]) if x["kind"] == "upper_a")["id"])
        self.assertEqual(item(ua1, "main1")["sets"], 3)
        self.assertEqual(item(ua4, "main1")["sets"], 2)
        self.assertEqual(item(ua4, "acc1")["sets"], 2)
        self.assertEqual((item(ua4, "main1")["rep_low"], item(ua4, "main1")["rep_high"]), (6, 10))
        fin = item(ua4, "finisher")
        proto = programme.protocols_by_id(ft.PROG)[fin["protocol"]]
        self.assertEqual(fin["minutes"], programme.protocol_minutes(proto, minimum=True))

    def test_lifting_day_fits_budget(self):
        """Every lifting session over 12 weeks, five and six day layouts, fits 60 minutes."""
        for days in ([1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 6]):
            conn = fresh_conn()
            s = ft.get_settings(conn)
            s["train_days"] = days
            wks = plan_weeks(conn, s, 12)
            self.assertEqual(len(wks), 12)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0], 3)
            for wk in wks:
                for sess in sessions(conn, wk["id"]):
                    if sess["kind"] in programme.LIFTING_KINDS:
                        est = programme.session_minutes(items(conn, sess["id"]), ft.PROG["set_overhead_sec"])
                        self.assertLessEqual(est, 60, f"{sess['kind']} on {sess['date']} takes {est} min")

    def test_default_upper_estimate(self):
        self.assertEqual(programme.est_minutes({"slot_key": "main1", "sets": 3, "rest_sec": 150}), 11.5)
        self.assertEqual(programme.est_minutes({"slot_key": "acc1", "sets": 3, "rest_sec": 60}), 5.0)
        self.assertEqual(programme.est_minutes({"slot_key": "finisher", "minutes": 10, "sets": 8}), 10.0)
        self.assertEqual(programme.session_minutes(upper_items()), 58.0)

    def test_trim_drops_optional_first(self):
        out = programme.trim_to_budget(upper_items(), 55, ft.PROG)
        slots = [i["slot_key"] for i in out]
        self.assertNotIn("acc4", slots)
        self.assertEqual([i["sets"] for i in out if i["section"] in ("main", "accessory")], [3, 3, 3, 3, 3])
        self.assertEqual(item(out, "finisher")["minutes"], 10.0)
        self.assertEqual(programme.session_minutes(out), 53.0)

    def test_trim_finisher_then_sets(self):
        """At 50 minutes the finisher hits its minimum before acc3 loses a set."""
        out = programme.trim_to_budget(upper_items(), 50, ft.PROG)
        self.assertEqual(item(out, "finisher")["minutes"], 8.0)
        self.assertEqual(item(out, "acc3")["sets"], 2)
        self.assertEqual((item(out, "acc1")["sets"], item(out, "acc2")["sets"]), (3, 3))
        self.assertEqual((item(out, "main1")["sets"], item(out, "main2")["sets"]), (3, 3))
        self.assertLessEqual(programme.session_minutes(out), 50)

    def test_trim_never_touches_mains(self):
        out = programme.trim_to_budget(upper_items(), 30, ft.PROG)
        slots = [i["slot_key"] for i in out]
        self.assertEqual(slots, ["wu_cardio", "wu_dynamic", "main1", "main2", "acc1", "acc2", "cooldown"])
        self.assertEqual((item(out, "main1")["sets"], item(out, "main2")["sets"]), (3, 3))
        self.assertEqual(item(out, "main1")["note"], "trimmed for time")

    def test_no_accessory_repeats_consecutive_weeks(self):
        """Over 12 weeks no rotating slot picks the same thing two weeks running."""
        conn = fresh_conn()
        wks = plan_weeks(conn, ft.get_settings(conn), 12)
        rotate = {"acc1", "acc2", "acc3", "acc4", "core1", "circ1", "circ2", "circ3", "cond"}
        prev = {}
        for wk in wks:
            cur = {}
            for sess in sessions(conn, wk["id"]):
                for it in items(conn, sess["id"]):
                    if it["slot_key"] in rotate:
                        cur[(sess["kind"], it["slot_key"])] = it["exercise_key"] or it["protocol"]
                    if sess["kind"] == "conditioning" and it["slot_key"] == "wu_cardio":
                        cur[("conditioning", "machine")] = it["exercise_key"]
            self.assertEqual(len(cur), 4 * 4 + 4 + 1)
            for k, v in cur.items():
                if k in prev:
                    self.assertNotEqual(v, prev[k], f"{k} repeated in the week of {wk['start_date']}")
            prev = cur

    def test_finisher_varies_within_week(self):
        conn = fresh_conn()
        wks = plan_weeks(conn, ft.get_settings(conn), 8)
        for wk in wks:
            protos = [item(items(conn, s["id"]), "finisher")["protocol"]
                      for s in sessions(conn, wk["id"]) if s["kind"] in programme.LIFTING_KINDS]
            self.assertEqual(len(protos), 4)
            for a, b in zip(protos, protos[1:]):
                self.assertNotEqual(a, b, f"finisher {a} repeated in the week of {wk['start_date']}")
            # the warm-up machine matches the finisher machine
            for s in sessions(conn, wk["id"]):
                if s["kind"] in programme.LIFTING_KINDS:
                    its = items(conn, s["id"])
                    self.assertEqual(item(its, "wu_cardio")["exercise_key"], item(its, "finisher")["exercise_key"])

    # ---- managing sessions

    def _block(self, **over):
        conn = fresh_conn()
        s = ft.get_settings(conn)
        s["programme_start"] = ISO(MONDAY)
        s.update(over)
        make_block(conn, s)
        return conn, s

    def test_shuffle_changes_only_untouched_sessions(self):
        conn, s = self._block()
        w1, w2 = weeks(conn)[:2]
        mon, tue = session_on(conn, MONDAY), session_on(conn, MONDAY + timedelta(days=1))
        add_workout(conn, MONDAY, mon["id"])
        done_before = [(i["id"], i["exercise_key"]) for i in items(conn, mon["id"])]
        tue_before = {i["id"] for i in items(conn, tue["id"])}
        w2_before = {i["id"] for sess in sessions(conn, w2["id"]) for i in items(conn, sess["id"])}
        programme.shuffle_week(conn, w1["id"], s, ft.PROG, ft.EX_BY_KEY)
        after = weeks(conn)
        self.assertNotEqual(after[0]["seed"], w1["seed"])
        self.assertEqual(after[1]["seed"], w2["seed"])
        self.assertEqual([(i["id"], i["exercise_key"]) for i in items(conn, mon["id"])], done_before)
        self.assertEqual(session_by_id(conn, mon["id"])["status"], "done")
        tue_after = {i["id"] for i in items(conn, tue["id"])}
        self.assertEqual(len(tue_after), len(tue_before))
        self.assertFalse(tue_after & tue_before, "an untouched session kept its old items")
        w2_after = {i["id"] for sess in sessions(conn, w2["id"]) for i in items(conn, sess["id"])}
        self.assertEqual(len(w2_after), len(w2_before))
        self.assertFalse(w2_after & w2_before, "the later week did not cascade")

    def test_swap_rejects_item_with_logged_set(self):
        conn, s = self._block()
        thu = session_on(conn, TODAY)
        acc1 = item(items(conn, thu["id"]), "acc1")
        pool = next(sl for sl in ft.PROG["sessions"]["upper_b"]["slots"] if sl["key"] == "acc1")["pool"]
        new = programme.swap_item(conn, acc1["id"], None, ft.PROG, ft.EX_BY_KEY)
        self.assertIn(new["key"], pool)
        self.assertNotEqual(new["key"], acc1["exercise_key"])
        self.assertEqual(item(items(conn, thu["id"]), "acc1")["note"], "swapped")
        w = add_workout(conn, TODAY, thu["id"], ended=False)
        add_sets(conn, w, new["key"], [(12, 20, 7)], plan_item_id=acc1["id"])
        with self.assertRaises(PlanError) as cm:
            programme.swap_item(conn, acc1["id"], None, ft.PROG, ft.EX_BY_KEY)
        self.assertEqual(cm.exception.code, 409)

    def test_swap_rejects_other_pattern(self):
        conn, s = self._block()
        acc1 = item(items(conn, session_on(conn, TODAY)["id"]), "acc1")
        with self.assertRaises(PlanError) as cm:
            programme.swap_item(conn, acc1["id"], "back_squat", ft.PROG, ft.EX_BY_KEY)
        self.assertEqual(cm.exception.code, 400)
        with self.assertRaises(PlanError) as cm:
            programme.swap_item(conn, acc1["id"], "no_such_lift", ft.PROG, ft.EX_BY_KEY)
        self.assertEqual(cm.exception.code, 404)

    def test_sweep_marks_past_planned_skipped(self):
        conn, s = self._block()
        tue = session_on(conn, MONDAY + timedelta(days=1))
        add_workout(conn, MONDAY + timedelta(days=1), tue["id"], ended=False)
        programme.sweep_missed(conn, TODAY)
        statuses = [x["status"] for x in sessions(conn, weeks(conn)[0]["id"])]
        self.assertEqual(statuses, ["skipped", "planned", "skipped", "planned", "planned", "planned", "planned"])

    def test_move_exchanges_dates_and_sets_moved_from(self):
        conn, s = self._block()
        fri, thu = session_on(conn, TODAY + timedelta(days=1)), session_on(conn, TODAY)
        programme.move_session(conn, fri["id"], TODAY)
        fri_after, thu_after = session_by_id(conn, fri["id"]), session_by_id(conn, thu["id"])
        self.assertEqual((fri_after["date"], fri_after["moved_from"], fri_after["status"]), (ISO(TODAY), ISO(TODAY + timedelta(days=1)), "planned"))
        self.assertEqual((thu_after["date"], thu_after["moved_from"]), (ISO(TODAY + timedelta(days=1)), ISO(TODAY)))
        self.assertEqual((fri_after["day_offset"], thu_after["day_offset"]), (thu["day_offset"], fri["day_offset"]))
        # today's session has a live workout: refuse
        add_workout(conn, TODAY, fri["id"], ended=False)
        with self.assertRaises(PlanError) as cm:
            programme.move_session(conn, session_on(conn, TODAY + timedelta(days=4))["id"], TODAY)
        self.assertEqual(cm.exception.code, 409)

    def test_move_rejects_far_and_done(self):
        conn, s = self._block()
        far = session_on(conn, TODAY + timedelta(days=21))
        with self.assertRaises(PlanError) as cm:
            programme.move_session(conn, far["id"], TODAY)
        self.assertEqual(cm.exception.code, 400)
        mon = session_on(conn, MONDAY)
        add_workout(conn, MONDAY, mon["id"])
        with self.assertRaises(PlanError) as cm:
            programme.move_session(conn, mon["id"], TODAY)
        self.assertEqual(cm.exception.code, 409)

    def test_adherence_excludes_zone2_and_void(self):
        """Week 1 has a void Monday and a skipped zone2 (3 of 4); week 2 is 4 of 5."""
        conn, s = self._block(programme_start=ISO(MONDAY + timedelta(days=1)), train_days=[1, 2, 3, 4, 5, 6])

        def mark(d, status):
            conn.execute("UPDATE plan_sessions SET status = ? WHERE date = ?", (status, ISO(d)))

        self.assertEqual(session_on(conn, MONDAY)["status"], "void")
        for off in (1, 2, 3):
            mark(MONDAY + timedelta(days=off), "done")
        mark(MONDAY + timedelta(days=5), "skipped")
        for off in (7, 8, 9, 10):
            mark(MONDAY + timedelta(days=off), "done")
        mark(MONDAY + timedelta(days=12), "skipped")
        rows = programme.adherence_by_week(conn)
        self.assertEqual((rows[0]["done"], rows[0]["planned"]), (3, 4))
        self.assertEqual((rows[1]["done"], rows[1]["planned"]), (4, 5))
        self.assertEqual(rows[1]["done"] / rows[1]["planned"], 0.8)
        view = programme.week_view(conn, MONDAY + timedelta(days=7), TODAY, s, ft.PROG, ft.EX_BY_ID, ft.EX_BY_KEY)
        self.assertEqual(view["adherence"], {"done": 4, "planned": 5})

    def test_seed_validation_pool_keys_exist(self):
        """Every pool key exists; rotating pools share one movement pattern."""
        self.assertEqual(programme.validate_seed(ft.PROG, ft.EX_BY_KEY), [])
        for kind, sess in ft.PROG["sessions"].items():
            for slot in sess["slots"]:
                patterns = {ft.EX_BY_KEY[k]["pattern"] for k in slot["pool"]}
                if slot.get("select") == "rotate" and slot["pool"]:
                    self.assertEqual(len(patterns), 1, f"{kind}/{slot['key']} mixes {patterns}")
        broken = json.loads(json.dumps(ft.PROG))
        broken["sessions"]["upper_a"]["slots"][2]["pool"].append("no_such_lift")
        self.assertTrue(programme.validate_seed(broken, ft.EX_BY_KEY))


# ================================================================= effort

class EffortTests(unittest.TestCase):
    """Per-set maths, calories, the effort score, PRs and weekly aggregates in effort.py."""

    def test_e1rm_epley(self):
        self.assertEqual(effort.e1rm(100, 5), (116.67, False))

    def test_e1rm_low_confidence_over_12(self):
        self.assertEqual(effort.e1rm(60, 15), (90.0, True))
        self.assertEqual(effort.e1rm(60, 12), (84.0, False))
        self.assertEqual(effort.e1rm(0, 5), (None, False))

    def test_volume_per_hand_doubles(self):
        self.assertEqual(effort.set_volume(12, 10, per_hand=True), 240)
        self.assertEqual(effort.set_volume(12, 10), 120)
        self.assertEqual(effort.set_volume(12, 45, timed=True), 0)

    def test_volume_bodyweight_fraction(self):
        load = effort.set_load(0, 0.65, 80)
        self.assertEqual(load, 52)
        self.assertEqual(effort.set_volume(load, 15), 780)

    def test_assisted_load_is_bodyweight_minus_help(self):
        self.assertEqual(effort.set_load(30, 0.95, 80, "assisted"), 46)
        self.assertEqual(effort.set_load(90, 0.95, 80, "assisted"), 0)

    def test_lifting_met_by_rpe(self):
        self.assertEqual([effort.lifting_met(r) for r in (6.5, 7.5, 9, None)], [3.5, 5.0, 6.0, 5.0])
        self.assertEqual(effort.lifting_met(8.5), 5.0)

    def test_kcal_lift(self):
        self.assertEqual(effort.kcal(5, 80, 45), 300)

    def test_kcal_interval_bike(self):
        met = effort.cardio_met(effort.DEFAULT_METS["bike"], "interval", 30, 60)
        self.assertEqual(met, 5.6)
        self.assertEqual(effort.kcal(met, 80, 12), 89.6)

    def test_kcal_zone2_bike(self):
        met = effort.cardio_met(effort.DEFAULT_METS["bike"], "moderate")
        self.assertEqual(effort.kcal(met, 80, 35), 317.3)

    def test_kcal_unknown_protocol_interval(self):
        self.assertEqual(effort.cardio_met(None, "interval", machine="bike"), 5.92)

    def test_lift_minutes_clamped(self):
        self.assertEqual(effort.lift_minutes("2026-09-24T10:00:00", "2026-09-24T14:00:00", None), 120)
        self.assertEqual(effort.lift_minutes("2026-09-24T10:00:00", "2026-09-24T10:05:00", None), 15)
        self.assertEqual(effort.lift_minutes("2026-09-24T10:00:00", None, "2026-09-24T10:45:00", cardio_minutes=10), 35)

    def test_hard_ratio(self):
        self.assertAlmostEqual(effort.hard_ratio([8, 7, 9, None]), 2 / 3)
        self.assertEqual(effort.hard_ratio([None, None]), 0)

    def test_effort_on_par(self):
        r = effort.effort_score(1000, [900, 1000, 1100], 1.0, 400, 80)
        self.assertEqual(r["effort"], 83)
        self.assertEqual((r["parts"]["volume"], r["parts"]["hard_sets"], r["parts"]["calories"], r["parts"]["ref_volume"]),
                         (33.3, 30, 20, 1000))

    def test_effort_capped_at_100(self):
        self.assertEqual(effort.effort_score(2000, [1000] * 3, 1.0, 400, 80)["effort"], 100)

    def test_effort_no_rpe_part_b_zero(self):
        r = effort.effort_score(1000, [1000] * 3, effort.hard_ratio([None, None, None]), 400, 80)
        self.assertEqual(r["parts"]["hard_sets"], 0)
        self.assertEqual(r["effort"], 53)

    def test_effort_no_baseline(self):
        r = effort.effort_score(1000, [1000, 1000], 0.5, 0, 80)
        self.assertEqual(r["parts"]["volume"], 33.3)
        self.assertIsNone(r["parts"]["ref_volume"])

    def test_effort_cardio_only_interval(self):
        self.assertEqual(effort.cardio_effort(400, 80, ["interval"])["effort"], 100)
        self.assertEqual(effort.cardio_effort(400, 80, ["easy"])["effort"], 88)

    # ---- personal records

    def _prs(self, earlier, later):
        conn = fresh_conn()
        if earlier:
            w1 = add_workout(conn, TODAY - timedelta(days=7))
            add_sets(conn, w1, "barbell_bench_press", earlier)
        w2 = add_workout(conn, TODAY)
        add_sets(conn, w2, "barbell_bench_press", later)
        return effort.prs_for_workout(conn, w2, ft.get_settings(conn))

    def test_pr_e1rm(self):
        kinds = {p["kind"] for p in self._prs([(10, 40, 8)] * 3, [(10, 42.5, 8)] * 3)}
        self.assertEqual(kinds, {"e1rm", "weight"})

    def test_pr_reps_at_weight(self):
        prs = self._prs([(8, 40, 8)] * 3, [(10, 40, 8)])
        reps = [p for p in prs if p["kind"] == "reps"]
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0]["text"], "10 reps at 40 kg, previous best 8")

    def test_pr_none_on_first_exposure(self):
        self.assertEqual(self._prs([], [(10, 40, 8)] * 3), [])

    def test_pr_ignores_reps_over_12(self):
        self.assertEqual(self._prs([(10, 40, 8)], [(15, 30, 8)]), [])

    # ---- aggregates

    def test_strength_index_carry_forward(self):
        """Squat untrained in week 2 carries its week 1 value; the week is flagged."""
        conn = fresh_conn()
        w1 = add_workout(conn, MONDAY)
        add_sets(conn, w1, "barbell_bench_press", [(10, 40, 8)])
        add_sets(conn, w1, "back_squat", [(10, 60, 8)])
        w2 = add_workout(conn, MONDAY + timedelta(days=7))
        add_sets(conn, w2, "barbell_bench_press", [(10, 42.5, 8)])
        out = effort.strength_index(conn, [ex_id("barbell_bench_press"), ex_id("back_squat")], lambda d: 80.0, {ISO(MONDAY)})
        self.assertEqual(out[0], {"week": ISO(MONDAY), "index": 0.0, "carried": False})
        self.assertEqual(out[1]["week"], ISO(MONDAY + timedelta(days=7)))
        self.assertTrue(out[1]["carried"])
        gain = effort.e1rm(42.5, 10)[0] / effort.e1rm(40, 10)[0] - 1
        self.assertEqual(out[1]["index"], round(100 * gain / 2, 1))

    def test_weekly_e1rm_flags_low_confidence(self):
        conn = fresh_conn()
        w1 = add_workout(conn, MONDAY)
        add_sets(conn, w1, "barbell_bench_press", [(15, 30, 8)])
        w2 = add_workout(conn, MONDAY + timedelta(days=7))
        add_sets(conn, w2, "barbell_bench_press", [(10, 40, 8), (15, 30, 8)])
        out = effort.weekly_e1rm(conn, ex_id("barbell_bench_press"), lambda d: 80.0)
        self.assertEqual(out, [{"week": ISO(MONDAY), "e1rm": 45.0, "low_confidence": True},
                               {"week": ISO(MONDAY + timedelta(days=7)), "e1rm": 53.33, "low_confidence": False}])

    def test_weekly_sets_secondary_half_credit(self):
        conn = fresh_conn()
        w = add_workout(conn, TODAY)
        add_sets(conn, w, "barbell_bench_press", [(10, 40, 8)] * 3)
        out = effort.weekly_muscle_sets(conn, ISO(MONDAY), 80)
        self.assertEqual(out, [{"week": ISO(MONDAY), "muscles": {"chest": 3.0, "shoulders": 1.5, "triceps": 1.5}}])

    def test_monday_of_week_sql(self):
        conn = fresh_conn()
        q = "SELECT date(?, '-6 days', 'weekday 1')"
        self.assertEqual(conn.execute(q, ("2026-10-04",)).fetchone()[0], "2026-09-28")
        self.assertEqual(conn.execute(q, ("2026-09-28",)).fetchone()[0], "2026-09-28")
        self.assertEqual(conn.execute(q, ("2026-10-03",)).fetchone()[0], "2026-09-28")
        self.assertEqual(effort.monday_of(date(2026, 10, 4)), date(2026, 9, 28))

    # ---- the sync write path

    def test_recompute_after_late_sync_updates_kcal(self):
        """A set arriving after Finish turns a 0 kcal workout into 45 minutes of lifting."""
        conn = fresh_conn()
        s = ft.get_settings(conn)
        wcid = str(uuid.uuid4())
        res = sync(conn, s, [{"type": "workout", "client_id": wcid,
                              "payload": {"date": ISO(TODAY), "started_at": f"{ISO(TODAY)}T18:00:00", "ended_at": f"{ISO(TODAY)}T18:45:00"}}])
        self.assertEqual(res["rejected"], [])
        row = conn.execute("SELECT kcal_est, work_sets, volume FROM workouts WHERE client_id = ?", (wcid,)).fetchone()
        self.assertEqual(tuple(row), (0.0, 0, 0.0))
        res = sync(conn, s, [{"type": "set", "client_id": str(uuid.uuid4()),
                              "payload": {"workout_client_id": wcid, "exercise_id": ex_id("barbell_bench_press"), "reps": 10, "weight_kg": 40}}])
        self.assertEqual(res["rejected"], [])
        row = conn.execute("SELECT kcal_est, work_sets, volume, lift_minutes FROM workouts WHERE client_id = ?", (wcid,)).fetchone()
        self.assertEqual(tuple(row), (300.0, 1, 400.0, 45.0))

    def test_sync_cardio_row_gets_kcal(self):
        conn = fresh_conn()
        s = ft.get_settings(conn)
        wcid = str(uuid.uuid4())
        sync(conn, s, [{"type": "workout", "client_id": wcid,
                        "payload": {"date": ISO(TODAY), "started_at": f"{ISO(TODAY)}T18:00:00", "ended_at": f"{ISO(TODAY)}T18:15:00"}},
                       {"type": "cardio", "client_id": str(uuid.uuid4()),
                        "payload": {"workout_client_id": wcid, "exercise_id": ex_id("bike"), "minutes": 12, "intensity": "interval",
                                    "protocol": "fin_bike_30_60"}}])
        self.assertEqual(conn.execute("SELECT kcal_est FROM cardio_logs WHERE workout_client_id = ?", (wcid,)).fetchone()[0], 89.6)
        w = conn.execute("SELECT kcal_est, effort FROM workouts WHERE client_id = ?", (wcid,)).fetchone()
        self.assertEqual((w["kcal_est"], w["effort"]), (89.6, effort.cardio_effort(89.6, 80, ["interval"])["effort"]))

    def test_sync_set_before_workout_is_retried(self):
        conn = fresh_conn()
        res = sync(conn, ft.get_settings(conn), [{"type": "set", "client_id": "set-1",
                                                  "payload": {"workout_client_id": "missing", "exercise_id": ex_id("back_squat"), "reps": 5}}])
        self.assertEqual(res["applied"], [])
        self.assertTrue(res["rejected"][0]["retry"])

    def test_sync_workout_on_session_freezes_targets_and_marks_done(self):
        conn = fresh_conn()
        s = ft.get_settings(conn)
        s["programme_start"] = ISO(MONDAY)
        make_block(conn, s)
        thu = session_on(conn, TODAY)
        wcid = str(uuid.uuid4())
        sync(conn, s, [{"type": "workout", "client_id": wcid,
                        "payload": {"session_id": thu["id"], "date": ISO(TODAY), "started_at": f"{ISO(TODAY)}T18:00:00"}}])
        mains = [i for i in items(conn, thu["id"]) if i["section"] == "main"]
        self.assertEqual([(i["target_weight"], i["target_source"]) for i in mains], [(None, "first")] * 2)
        self.assertEqual(session_by_id(conn, thu["id"])["status"], "planned")
        sync(conn, s, [{"type": "workout", "client_id": wcid, "payload": {"ended_at": f"{ISO(TODAY)}T19:00:00"}}])
        self.assertEqual(session_by_id(conn, thu["id"])["status"], "done")


# ================================================================= food

class FoodTests(unittest.TestCase):
    """Search ranking, Open Food Facts mapping and logging in nutrition.py and the sync path."""

    def setUp(self):
        nutrition._off_cache.clear()

    def test_kj_to_kcal_fallback(self):
        c = nutrition.map_off_product({"code": "1", "product_name": "Test", "nutriments": {"energy_100g": 837}})
        self.assertEqual((c["kcal_100"], c["approx"]), (200.0, 0))

    def test_rank_and_pass(self):
        out = nutrition.rank_foods("chick bre", food_fixture())
        self.assertEqual(len(out), 2)
        for f in out:
            self.assertIn("chicken", f["name"].lower())
            self.assertIn("breast", f["name"].lower())

    def test_rank_or_fallback_when_and_empty(self):
        """With no AND match, foods rank by how many tokens they hit."""
        out = nutrition.rank_foods("chicken rice zzz", food_fixture())
        self.assertEqual(out[0]["name"], "Chicken and rice roll")
        names = {f["name"] for f in out}
        self.assertIn("Chicken, thigh, meat only, cooked, roasted", names)
        self.assertIn("Rice, brown, cooked", names)
        self.assertNotIn("Egg, whole, raw", names)

    def test_rank_nz_before_usda_same_tokens(self):
        """For "milk" the NZ Anchor rows come before the USDA generic row."""
        out = nutrition.rank_foods("milk", food_fixture())
        self.assertEqual(len(out), 3)
        self.assertEqual([f["source"] for f in out], ["nz", "nz", "usda"])

    def test_rank_starts_with_bonus(self):
        out = nutrition.rank_foods("egg", food_fixture())
        self.assertEqual([f["name"] for f in out], ["Egg, whole, raw", "Eggplant, raw"])

    def test_rank_times_used_breaks_ties(self):
        """Same source, same match: the food logged more often comes first."""
        out = nutrition.rank_foods("rice cooked", food_fixture())
        self.assertEqual([f["name"] for f in out], ["Rice, white, cooked", "Rice, brown, cooked"])

    def test_rank_matches_brand_tokens(self):
        out = nutrition.rank_foods("anchor", food_fixture())
        self.assertEqual({f["brand"] for f in out}, {"Anchor"})
        self.assertEqual(len(out), 2)

    def test_rank_short_query_returns_recent(self):
        foods = [food(f"Food {i}", last_used=ISO(TODAY - timedelta(days=i))) for i in range(25)]
        foods += [food("Never logged"), food("Also never")]
        out = nutrition.rank_foods("e", foods)
        self.assertEqual(len(out), 20)
        self.assertEqual([f["name"] for f in out[:3]], ["Food 0", "Food 1", "Food 2"])
        self.assertNotIn("Never logged", {f["name"] for f in out})

    def test_rank_max_30(self):
        foods = [food(f"Food {i}") for i in range(40)]
        self.assertEqual(len(nutrition.rank_foods("food", foods)), 30)
        self.assertEqual(len(nutrition.rank_foods("food", foods, limit=5)), 5)

    def test_rank_no_match_is_empty(self):
        self.assertEqual(nutrition.rank_foods("quinoa", food_fixture()), [])

    def test_off_mapping_kcal_present(self):
        c = nutrition.map_off_product(OFF_PRODUCT)
        self.assertEqual(c["name"], "Test bar EN")
        self.assertEqual(c["brand"], "Brandy")
        self.assertEqual((c["source"], c["source_id"], c["barcode"]), ("off", "9400000000001", "9400000000001"))
        self.assertEqual((c["kcal_100"], c["protein_100"], c["carb_100"], c["fat_100"], c["approx"]), (450, 10, 60, 18, 0))
        self.assertEqual(c["unit"], "g")
        self.assertEqual(len(c["portions"]), 1)
        self.assertTrue(c["portions"][0][0].startswith("1 serving"))
        self.assertEqual(c["portions"][0][1], 33.0)

    def test_off_mapping_kj_only(self):
        p = dict(OFF_PRODUCT, nutriments={"energy_100g": 1883, "proteins_100g": 10})
        c = nutrition.map_off_product(p)
        self.assertEqual(c["kcal_100"], round(1883 / 4.184, 1))
        self.assertEqual((c["approx"], c["carb_100"], c["fat_100"]), (0, 0, 0))

    def test_off_mapping_macros_only_marks_approx(self):
        p = dict(OFF_PRODUCT, nutriments={"proteins_100g": 10, "carbohydrates_100g": 20, "fat_100g": 5})
        c = nutrition.map_off_product(p)
        self.assertEqual((c["kcal_100"], c["approx"]), (165, 1))

    def test_off_mapping_unusable_products_skipped(self):
        self.assertIsNone(nutrition.map_off_product(dict(OFF_PRODUCT, nutriments={})))
        self.assertIsNone(nutrition.map_off_product(dict(OFF_PRODUCT, product_name="", product_name_en="")))
        self.assertIsNone(nutrition.map_off_product(None))

    def test_off_serving_size_parse(self):
        self.assertEqual([nutrition.parse_serving(s) for s in ("2 biscuits (33 g)", "30g", "1 cup")], [33, 30, None])
        self.assertEqual(nutrition.parse_serving("250 ml"), 250)
        self.assertEqual(nutrition.parse_serving("12,5 g"), 12.5)
        self.assertIsNone(nutrition.parse_serving(None))

    def test_off_cache_hit_within_20s(self):
        calls = []
        url = "https://world.openfoodfacts.org/api/v2/product/1.json?test=cache"
        opener = fake_opener({"status": 1, "product": OFF_PRODUCT}, calls)
        first = nutrition._off_get(url, "tester", opener)
        second = nutrition._off_get(url, "tester", opener)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first, second)

    def test_off_barcode_maps_product(self):
        calls = []
        c = nutrition.off_barcode("9400000000001", "tester", fake_opener({"status": 1, "product": OFF_PRODUCT}, calls))
        self.assertEqual(c["barcode"], "9400000000001")
        self.assertIn("world.openfoodfacts.org/api/v2/product/9400000000001.json", calls[0])
        self.assertIsNone(nutrition.off_barcode("9400000000002", "tester", fake_opener({"status": 0}, calls)))

    def test_off_rate_limit_raises(self):
        err = urllib.error.HTTPError("https://x", 429, "Too Many Requests", {}, None)
        with self.assertRaises(nutrition.OffRateLimited):
            nutrition._off_get("https://world.openfoodfacts.org/x?limit", "tester", fake_opener(err, []))

    def test_food_log_kcal_from_portion(self):
        v = nutrition.food_log_values({"kcal_100": 165, "protein_100": 31, "carb_100": 0, "fat_100": 3.6}, 140, 1.5)
        self.assertEqual((v["grams"], v["kcal"], v["protein"]), (210, 346.5, 65.1))

    def test_bundled_lists_seeded(self):
        conn = fresh_conn()
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM foods WHERE source = 'usda'").fetchone()[0], 7000)
        wb = conn.execute("SELECT * FROM foods WHERE name = 'Weet-Bix'").fetchone()
        self.assertEqual((wb["source"], wb["approx"], wb["brand"]), ("nz", 1, "Sanitarium"))
        portions = [tuple(r) for r in conn.execute("SELECT label, grams FROM food_portions WHERE food_id = ? ORDER BY id", (wb["id"],))]
        self.assertEqual(portions, [("1 biscuit", 15.0), ("2 biscuits", 30.0)])

    def _breakfast(self):
        conn = fresh_conn()
        s = ft.get_settings(conn)
        fid = add_food(conn)
        y = TODAY - timedelta(days=1)
        res = sync(conn, s, [food_log_op(fid, y, "breakfast", 50), food_log_op(fid, y, "breakfast", 100)])
        self.assertEqual(res["rejected"], [])
        return conn, s, fid, y

    def test_copy_yesterday_appends_stored_values(self):
        conn, s, fid, y = self._breakfast()
        ft.copy_slot(conn, s, {"to_date": ISO(TODAY), "slot": "breakfast", "from_date": ISO(y)})
        src = sorted(r[0] for r in conn.execute("SELECT kcal FROM food_logs WHERE date = ? AND deleted = 0", (ISO(y),)))
        dst = sorted(r[0] for r in conn.execute("SELECT kcal FROM food_logs WHERE date = ? AND deleted = 0", (ISO(TODAY),)))
        self.assertEqual(src, [190.0, 380.0])
        self.assertEqual(dst, src)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM food_logs").fetchone()[0], 4)
        with self.assertRaises(ft.BadRequest) as cm:
            ft.copy_slot(conn, s, {"to_date": ISO(TODAY), "slot": "dinner", "from_date": ISO(y)})
        self.assertEqual(cm.exception.code, 404)

    def test_times_used_increments_on_copy(self):
        conn, s, fid, y = self._breakfast()
        used = lambda: conn.execute("SELECT times_used, last_used FROM foods WHERE id = ?", (fid,)).fetchone()
        self.assertEqual(tuple(used()), (2, ISO(y)))
        ft.copy_slot(conn, s, {"to_date": ISO(TODAY), "slot": "breakfast", "from_date": ISO(y)})
        self.assertEqual(tuple(used()), (4, ISO(TODAY)))

    def test_add_meal_recomputes_from_current_food(self):
        conn = fresh_conn()
        s = ft.get_settings(conn)
        fid = add_food(conn, kcal=380)
        conn.commit()
        mid = ft.save_meal(conn, {"name": "Brekkie", "items": [{"food_id": fid, "grams": 100}]})
        conn.execute("UPDATE foods SET kcal_100 = 500 WHERE id = ?", (fid,))
        conn.commit()
        ft.add_meal(conn, s, {"meal_id": mid, "date": ISO(TODAY), "slot": "lunch"})
        row = conn.execute("SELECT kcal, slot, grams FROM food_logs WHERE date = ?", (ISO(TODAY),)).fetchone()
        self.assertEqual(tuple(row), (500.0, "lunch", 100.0))


# ================================================================= tools

class FoodDbToolTests(unittest.TestCase):
    """Pure label helpers in tools/build_food_db.py."""

    @classmethod
    def setUpClass(cls):
        cls.tool = load_food_db_tool()

    def test_portion_label_modifier_only(self):
        self.assertEqual(self.tool.portion_label(1, None, "", "cup, chopped or diced"), "1 cup, chopped or diced")

    def test_portion_label_with_unit(self):
        self.assertEqual(self.tool.portion_label(2, "tbsp", "", ""), "2 tbsp")

    def test_portion_label_half(self):
        self.assertEqual(self.tool.portion_label(0.5, "cup", "", ""), "0.5 cup")

    def test_shorten_description(self):
        self.assertEqual(self.tool.shorten_name("Chicken, broilers or fryers, breast, meat only, cooked, roasted"),
                         "Chicken, breast, meat only, cooked, roasted")
        self.assertEqual(self.tool.shorten_name("Egg, whole, raw"), "Egg, whole, raw")


if __name__ == "__main__":
    unittest.main()


class OffSearchFallbackTests(unittest.TestCase):
    """The newer search service is tried first; the classic endpoint only when it is down."""

    HIT = {"code": "9414942001123", "product_name": "Weet-Bix", "brands": ["Sanitarium"], "quantity": "750 g",
           "countries_tags": ["en:new-zealand"],
           "nutriments": {"energy-kcal_100g": 326.7, "proteins_100g": 12, "carbohydrates_100g": 67, "fat_100g": 1.3}}

    def make_opener(self, behaviour, calls):
        import io
        import urllib.error

        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout=None):
            calls.append(req.full_url)
            for prefix, result in behaviour:
                if req.full_url.startswith(prefix):
                    if isinstance(result, int):
                        raise urllib.error.HTTPError(req.full_url, result, "busy", {}, io.BytesIO(b""))
                    return Resp(result)
            raise AssertionError("unexpected url " + req.full_url)
        return opener

    def setUp(self):
        nutrition._off_cache.clear()
        self._sleep = nutrition.time.sleep
        nutrition.time.sleep = lambda s: None

    def tearDown(self):
        nutrition.time.sleep = self._sleep

    def test_new_service_first_with_list_brands(self):
        calls = []
        opener = self.make_opener([(nutrition.OFF_SEARCH, {"hits": [self.HIT, self.HIT, dict(self.HIT, code="1"), dict(self.HIT, code="2")]})], calls)
        out = nutrition.off_search("weet-bix", "tester", opener)
        self.assertEqual([c["source_id"] for c in out], ["9414942001123", "1", "2"])
        self.assertEqual(out[0]["brand"], "Sanitarium")
        self.assertEqual(len(calls), 1)
        self.assertIn("new-zealand", calls[0])

    def test_world_index_fills_in_when_nz_is_thin(self):
        calls = []
        opener = self.make_opener([(nutrition.OFF_SEARCH + "?q=milk%20countries", {"hits": [self.HIT]}),
                                   (nutrition.OFF_SEARCH, {"hits": [dict(self.HIT, code="2"), dict(self.HIT, code="3")]})], calls)
        out = nutrition.off_search("milk", "tester", opener)
        self.assertEqual([c["source_id"] for c in out], ["9414942001123", "2", "3"])
        self.assertEqual(len(calls), 2)

    def test_falls_back_to_legacy_when_new_service_is_down(self):
        calls = []
        opener = self.make_opener([(nutrition.OFF_SEARCH, 503), (nutrition.OFF_LEGACY, {"products": [self.HIT]})], calls)
        out = nutrition.off_search("weet-bix", "tester", opener)
        self.assertEqual(len(out), 1)
        self.assertTrue(any(c.startswith(nutrition.OFF_LEGACY) for c in calls))

    def test_busy_everywhere_is_a_plain_message(self):
        calls = []
        opener = self.make_opener([(nutrition.OFF_SEARCH, 503), (nutrition.OFF_LEGACY, 503)], calls)
        with self.assertRaises(nutrition.OffBusy) as cm:
            nutrition.off_search("weet-bix", "tester", opener)
        self.assertIn("busy", str(cm.exception).lower())
