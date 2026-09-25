"""Effort and calories for Fitness Tracker.

Per-set load, volume and estimated one-rep max; MET-based calorie estimates
for lifting and cardio; the effort score; personal records; the strength
index; weekly muscle sets. Standard library only.

The pure functions take plain numbers so tests can pin them. The functions
that take a connection read the tables described in PLAN.md and store the
results on the workout row.
"""

import json
import math
import statistics
from datetime import date, timedelta

from nutrition import trend_weight, to_date

# Lifting MET by how hard the session felt (mean RPE of the working sets).
LIFT_MET_EASY, LIFT_MET_MODERATE, LIFT_MET_HARD = 3.5, 5.0, 6.0

# Fallback cardio METs by machine when the exercise row has none.
DEFAULT_METS = {
    "treadmill": {"easy": 3.5, "moderate": 5.5, "vigorous": 9.0},
    "bike": {"easy": 4.0, "moderate": 6.8, "vigorous": 8.8},
    "rower": {"easy": 4.8, "moderate": 7.0, "vigorous": 10.0},
}
INTERVAL_DEFAULT_WORK_FRACTION = 0.4
KCAL_REF_PER_KG = 5.0        # a "full" session burns about 5 kcal per kg of body weight


# ----------------------------------------------------------------- per set

def round_load(x, equipment="barbell"):
    """Round a load half-up to the plates on the floor: 2.5 kg, or 1 kg for light dumbbells."""
    if x is None:
        return None
    step = 1.0 if equipment == "dumbbell" and x < 10 else 2.5
    return math.floor(x / step + 0.5) * step


def set_load(weight_kg, bodyweight_fraction=0.0, bodyweight=None, equipment=None):
    """The load actually moved in a set.

    Assisted machines log the assistance, so the load is body weight minus
    help. Bodyweight moves add the fraction of body weight they carry.
    """
    w = float(weight_kg or 0)
    frac = float(bodyweight_fraction or 0)
    bw = float(bodyweight or 0)
    if equipment == "assisted":
        return max(0.0, frac * bw - w)
    return w + frac * bw


def set_volume(load, reps, per_hand=False, timed=False):
    if timed:
        return 0.0
    return float(load) * float(reps or 0) * (2 if per_hand else 1)


def e1rm(load, reps):
    """Epley estimate. Returns (value, low_confidence) or (None, False)."""
    reps = int(reps or 0)
    if reps < 1 or not load or load <= 0:
        return None, False
    value = float(load) * (1 + reps / 30.0)
    return round(value, 2), reps > 12


def hard_ratio(rpes):
    logged = [r for r in rpes if r is not None]
    if not logged:
        return 0.0
    return sum(1 for r in logged if r >= 8) / len(logged)


# ----------------------------------------------------------------- calories

def lifting_met(mean_rpe):
    if mean_rpe is None:
        return LIFT_MET_MODERATE
    if mean_rpe < 7:
        return LIFT_MET_EASY
    if mean_rpe <= 8.5:
        return LIFT_MET_MODERATE
    return LIFT_MET_HARD


def cardio_met(mets, intensity, work_sec=None, rest_sec=None, machine=None):
    """MET for a cardio bout. Intervals blend the vigorous and easy figures by the work fraction."""
    table = mets or DEFAULT_METS.get(machine or "", DEFAULT_METS["bike"])
    intensity = (intensity or "moderate").lower()
    if intensity == "interval":
        if work_sec and rest_sec is not None and (work_sec + rest_sec) > 0:
            f = work_sec / (work_sec + rest_sec)
        else:
            f = INTERVAL_DEFAULT_WORK_FRACTION
        return round(f * table["vigorous"] + (1 - f) * table["easy"], 3)
    return float(table.get(intensity, table["moderate"]))


def kcal(met, bodyweight, minutes):
    return round(float(met) * float(bodyweight) * float(minutes) / 60.0, 1)


def lift_minutes(started_at, ended_at, last_set_at, cardio_minutes=0.0, planned_minutes=None):
    """Minutes spent lifting, clamped to 15 to 120 so a forgotten tab does not inflate the burn."""
    start = _ts(started_at)
    end = _ts(ended_at) or _ts(last_set_at)
    if start is None or end is None or end <= start:
        if planned_minutes:
            return float(min(120, max(15, planned_minutes)))
        return 45.0
    elapsed = (end - start).total_seconds() / 60.0 - float(cardio_minutes or 0)
    return float(min(120, max(15, elapsed)))


def _ts(value):
    from datetime import datetime
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


# ----------------------------------------------------------------- effort score

def effort_score(volume, reference_volumes, hard, kcal_used, bodyweight):
    """0 to 100 for a lifting session, with its three parts kept for display."""
    refs = [v for v in reference_volumes if v]
    if len(refs) >= 3:
        ref = statistics.median(refs)
        ratio = (volume / ref) if ref else 1.0
        part_a = 50 * min(ratio, 1.5) / 1.5
    else:
        ref = None
        part_a = 33.3
    part_b = 30 * float(hard or 0)
    kcal_ref = KCAL_REF_PER_KG * float(bodyweight or 80)
    part_c = 20 * min(float(kcal_used or 0) / kcal_ref, 1.0) if kcal_ref else 0
    return {
        "effort": int(round(part_a + part_b + part_c)),
        "parts": {"volume": round(part_a, 1), "hard_sets": round(part_b, 1), "calories": round(part_c, 1),
                  "ref_volume": round(ref, 1) if ref else None, "kcal_ref": round(kcal_ref, 1)},
    }


def cardio_effort(kcal_used, bodyweight, intensities):
    """0 to 100 for a session with no working sets."""
    kcal_ref = KCAL_REF_PER_KG * float(bodyweight or 80)
    part_a = 70 * min(float(kcal_used or 0) / kcal_ref, 1.0) if kcal_ref else 0
    hard = any((i or "").lower() in ("vigorous", "interval") for i in intensities)
    part_b = 30 * (1.0 if hard else 0.6)
    return {"effort": int(round(part_a + part_b)),
            "parts": {"calories": round(part_a, 1), "intensity": round(part_b, 1), "kcal_ref": round(kcal_ref, 1)}}


# ----------------------------------------------------------------- database

def body_logs(conn):
    return [(r["date"], r["weight_kg"]) for r in conn.execute(
        "SELECT date, weight_kg FROM body_logs WHERE deleted = 0 AND weight_kg IS NOT NULL")]


def bodyweight_on(conn, d, settings):
    w, _ = trend_weight(body_logs(conn), to_date(d), settings.get("start_weight_kg"))
    return w or 80.0


def working_sets(conn, workout_client_id):
    """Working sets of a workout joined to what the engine needs from the exercise."""
    return [dict(r) for r in conn.execute("""
        SELECT s.*, e.per_hand, e.timed, e.bodyweight_fraction, e.equipment, e.pattern, e.key AS exercise_key,
               e.name AS exercise_name, e.primary_muscle, e.secondary_muscles
        FROM set_logs s JOIN exercises e ON e.id = s.exercise_id
        WHERE s.workout_client_id = ? AND s.deleted = 0 AND s.is_warmup = 0
        ORDER BY s.exercise_id, s.set_no, s.done_at""", (workout_client_id,))]


def protocol_lookup(programme):
    return {p["id"]: p for p in (programme or {}).get("protocols", [])}


def recompute_workout(conn, workout_client_id, settings, programme):
    """Store volume, hard sets, minutes, calories and effort on a workout row."""
    w = conn.execute("SELECT * FROM workouts WHERE client_id = ?", (workout_client_id,)).fetchone()
    if not w:
        return None
    w = dict(w)
    bw = bodyweight_on(conn, w["date"], settings)
    sets = working_sets(conn, workout_client_id)
    volume = 0.0
    rpes = []
    last_set_at = None
    for s in sets:
        load = set_load(s["weight_kg"], s["bodyweight_fraction"], bw, s["equipment"])
        volume += set_volume(load, s["reps"], bool(s["per_hand"]), bool(s["timed"]))
        rpes.append(s["rpe"])
        if s["done_at"] and (last_set_at is None or s["done_at"] > last_set_at):
            last_set_at = s["done_at"]
    logged = [r for r in rpes if r is not None]
    mean_rpe = sum(logged) / len(logged) if logged else None

    protocols = protocol_lookup(programme)
    cardio = [dict(r) for r in conn.execute("""
        SELECT c.*, e.mets, e.equipment AS machine FROM cardio_logs c
        LEFT JOIN exercises e ON e.id = c.exercise_id
        WHERE c.workout_client_id = ? AND c.deleted = 0""", (workout_client_id,))]
    cardio_kcal = 0.0
    cardio_minutes = 0.0
    intensities = []
    for c in cardio:
        proto = protocols.get(c.get("protocol") or "", {})
        mets = json.loads(c["mets"]) if c.get("mets") else None
        met = cardio_met(mets, c.get("intensity"), proto.get("work_sec"), proto.get("rest_sec"), c.get("machine"))
        k = kcal(met, bw, c.get("minutes") or 0)
        conn.execute("UPDATE cardio_logs SET kcal_est = ? WHERE id = ?", (k, c["id"]))
        cardio_kcal += k
        cardio_minutes += float(c.get("minutes") or 0)
        intensities.append(c.get("intensity"))

    minutes = 0.0
    kcal_lift = 0.0
    if sets:
        minutes = lift_minutes(w.get("started_at"), w.get("ended_at"), last_set_at, cardio_minutes)
        kcal_lift = kcal(lifting_met(mean_rpe), bw, minutes)
    kcal_est = round(kcal_lift + cardio_kcal, 1)
    kcal_used = w.get("kcal_wearable") if w.get("kcal_wearable") not in (None, "", 0) else kcal_est

    hard = hard_ratio(rpes)
    hard_sets = sum(1 for r in rpes if r is not None and r >= 8)
    if sets:
        kind = conn.execute("SELECT kind FROM plan_sessions WHERE id = ?", (w.get("session_id"),)).fetchone()
        kind = kind["kind"] if kind else "adhoc"
        since = (to_date(w["date"]) - timedelta(days=28)).isoformat()
        if kind == "adhoc":
            refs = [r["volume"] for r in conn.execute("""
                SELECT volume FROM workouts WHERE deleted = 0 AND ended_at IS NOT NULL AND session_id IS NULL
                AND date >= ? AND date < ? AND client_id != ?""", (since, w["date"], workout_client_id))]
        else:
            refs = [r["volume"] for r in conn.execute("""
                SELECT wk.volume FROM workouts wk JOIN plan_sessions ps ON ps.id = wk.session_id
                WHERE wk.deleted = 0 AND wk.ended_at IS NOT NULL AND ps.kind = ?
                AND wk.date >= ? AND wk.date < ? AND wk.client_id != ?""", (kind, since, w["date"], workout_client_id))]
        score = effort_score(volume, refs, hard, kcal_used, bw)
    else:
        score = cardio_effort(kcal_used, bw, intensities)

    conn.execute("""UPDATE workouts SET volume = ?, work_sets = ?, hard_sets = ?, lift_minutes = ?, kcal_est = ?,
                    effort = ?, effort_parts = ? WHERE client_id = ?""",
                 (round(volume, 1), len(sets), hard_sets, round(minutes, 1), kcal_est,
                  score["effort"], json.dumps(score["parts"]), workout_client_id))
    return {"volume": round(volume, 1), "work_sets": len(sets), "hard_sets": hard_sets, "lift_minutes": round(minutes, 1),
            "kcal_est": kcal_est, "kcal_used": kcal_used, "effort": score["effort"], "effort_parts": score["parts"]}


def history_for_exercise(conn, exercise_id, before_client_id=None, until_date=None):
    """Working sets of an exercise from earlier finished workouts, newest first."""
    rows = conn.execute("""
        SELECT s.reps, s.weight_kg, s.rpe, w.date, w.client_id AS workout_client_id, w.ended_at
        FROM set_logs s JOIN workouts w ON w.client_id = s.workout_client_id
        WHERE s.exercise_id = ? AND s.deleted = 0 AND s.is_warmup = 0 AND w.deleted = 0 AND w.ended_at IS NOT NULL
        AND (? IS NULL OR w.client_id != ?) AND (? IS NULL OR w.date <= ?)
        ORDER BY w.date DESC, w.ended_at DESC, s.set_no""",
        (exercise_id, before_client_id, before_client_id, until_date, until_date))
    return [dict(r) for r in rows]


def bests_for_exercise(conn, exercise_id, exercise, bw, before_client_id=None):
    """Best e1RM, heaviest load and reps at the five heaviest weights, from earlier workouts."""
    hist = history_for_exercise(conn, exercise_id, before_client_id)
    best_e1rm = None
    best_weight = None
    reps_at = {}
    for s in hist:
        load = set_load(s["weight_kg"], exercise.get("bodyweight_fraction"), bw, exercise.get("equipment"))
        if exercise.get("timed"):
            continue
        val, low = e1rm(load, s["reps"])
        if val and not low and not exercise.get("bodyweight_fraction"):
            best_e1rm = max(best_e1rm or 0, val)
        if load > 0:
            best_weight = max(best_weight or 0, load)
            key = round(load, 2)
            reps_at[key] = max(reps_at.get(key, 0), int(s["reps"] or 0))
    top = sorted(reps_at.items(), key=lambda kv: -kv[0])[:5]
    return {"best_e1rm": best_e1rm, "best_weight": best_weight, "reps_at_weight": {str(k): v for k, v in top},
            "has_history": bool(hist)}


def prs_for_workout(conn, workout_client_id, settings):
    """Personal records set in a workout, judged against everything before it."""
    w = conn.execute("SELECT date FROM workouts WHERE client_id = ?", (workout_client_id,)).fetchone()
    if not w:
        return []
    bw = bodyweight_on(conn, w["date"], settings)
    out = []
    by_ex = {}
    for s in working_sets(conn, workout_client_id):
        by_ex.setdefault(s["exercise_id"], []).append(s)
    for ex_id, sets in by_ex.items():
        ex = sets[0]
        bests = bests_for_exercise(conn, ex_id, ex, bw, before_client_id=workout_client_id)
        if not bests["has_history"]:
            continue
        name = ex["exercise_name"]
        top_e1rm, top_weight = None, None
        for s in sets:
            load = set_load(s["weight_kg"], ex["bodyweight_fraction"], bw, ex["equipment"])
            if ex["timed"]:
                continue
            val, low = e1rm(load, s["reps"])
            if val and not low and not ex["bodyweight_fraction"]:
                top_e1rm = max(top_e1rm or 0, val)
            top_weight = max(top_weight or 0, load)
            prev_reps = bests["reps_at_weight"].get(str(round(load, 2)))
            if prev_reps is not None and int(s["reps"] or 0) > prev_reps:
                out.append({"exercise": name, "kind": "reps", "text": f"{int(s['reps'])} reps at {load:g} kg, previous best {prev_reps}"})
        if top_e1rm and bests["best_e1rm"] and top_e1rm > bests["best_e1rm"]:
            out.append({"exercise": name, "kind": "e1rm", "text": f"Estimated 1RM {top_e1rm:.1f} kg, up from {bests['best_e1rm']:.1f}"})
        if top_weight and bests["best_weight"] and top_weight > bests["best_weight"]:
            out.append({"exercise": name, "kind": "weight", "text": f"Heaviest set {top_weight:g} kg, previous {bests['best_weight']:g}"})
    seen = set()
    unique = []
    for p in out:
        k = (p["exercise"], p["kind"])
        if k not in seen:
            seen.add(k)
            unique.append(p)
    return unique


def monday_of(d):
    d = to_date(d)
    return d - timedelta(days=d.weekday())


def weekly_muscle_sets(conn, from_date, bw):
    """Hard-set counts per muscle per week: primary 1.0, each secondary 0.5."""
    rows = conn.execute("""
        SELECT date(w.date, '-6 days', 'weekday 1') AS week_start, e.primary_muscle, e.secondary_muscles,
               COUNT(*) AS sets
        FROM set_logs s JOIN workouts w ON w.client_id = s.workout_client_id JOIN exercises e ON e.id = s.exercise_id
        WHERE s.deleted = 0 AND s.is_warmup = 0 AND w.deleted = 0 AND w.ended_at IS NOT NULL AND w.date >= ?
        GROUP BY week_start, e.id""", (from_date,))
    out = {}
    for r in rows:
        wk = out.setdefault(r["week_start"], {})
        wk[r["primary_muscle"]] = wk.get(r["primary_muscle"], 0) + r["sets"]
        try:
            secs = json.loads(r["secondary_muscles"] or "[]")
        except ValueError:
            secs = []
        for m in secs:
            wk[m] = wk.get(m, 0) + r["sets"] * 0.5
    return [{"week": k, "muscles": {m: round(v, 1) for m, v in sorted(v.items())}} for k, v in sorted(out.items())]


def weekly_e1rm(conn, exercise_id, bw_by_date):
    """Best e1RM per week for one exercise, with low-confidence weeks flagged."""
    rows = conn.execute("""
        SELECT date(w.date, '-6 days', 'weekday 1') AS week_start, s.reps, s.weight_kg, w.date,
               e.bodyweight_fraction, e.equipment
        FROM set_logs s JOIN workouts w ON w.client_id = s.workout_client_id JOIN exercises e ON e.id = s.exercise_id
        WHERE s.exercise_id = ? AND s.deleted = 0 AND s.is_warmup = 0 AND w.deleted = 0 AND w.ended_at IS NOT NULL
        ORDER BY week_start""", (exercise_id,))
    weeks = {}
    for r in rows:
        bw = bw_by_date(r["date"])
        load = set_load(r["weight_kg"], r["bodyweight_fraction"], bw, r["equipment"])
        val, low = e1rm(load, r["reps"])
        if not val:
            continue
        cur = weeks.get(r["week_start"])
        if cur is None or val > cur["e1rm"] or (cur["low"] and not low and val >= cur["e1rm"] * 0.9):
            weeks[r["week_start"]] = {"e1rm": val, "low": low}
    return [{"week": k, "e1rm": v["e1rm"], "low_confidence": v["low"]} for k, v in sorted(weeks.items())]


def strength_index(conn, main_exercise_ids, bw_by_date, baseline_weeks):
    """Mean percentage gain over the block-1 main lifts, week by week, carried forward when untrained."""
    series = {}
    all_weeks = set()
    for ex_id in main_exercise_ids:
        pts = [p for p in weekly_e1rm(conn, ex_id, bw_by_date) if not p["low_confidence"]]
        if not pts:
            continue
        base_pts = [p["e1rm"] for p in pts if p["week"] in baseline_weeks] or [pts[0]["e1rm"]]
        baseline = max(base_pts)
        series[ex_id] = ({p["week"]: p["e1rm"] / baseline - 1 for p in pts}, baseline)
        all_weeks.update(p["week"] for p in pts)
    out = []
    last = {ex_id: None for ex_id in series}
    for wk in sorted(all_weeks):
        vals = []
        carried = False
        for ex_id, (byweek, _) in series.items():
            if wk in byweek:
                last[ex_id] = byweek[wk]
            elif last[ex_id] is not None:
                carried = True
            if last[ex_id] is not None:
                vals.append(last[ex_id])
        if vals:
            out.append({"week": wk, "index": round(100 * sum(vals) / len(vals), 1), "carried": carried})
    return out
