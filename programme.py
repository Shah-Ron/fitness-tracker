"""Programme engine for Fitness Tracker.

Builds four-week blocks of sessions from data/programme.json, rotates the
accessories week by week, trims each session to the time available, marks
the deload week, works out the target weight for every exercise from what
happened last time, and handles missed, moved and swapped sessions.

Standard library only. Functions that depend on the calendar take today as
a parameter so tests can pin it.
"""

import json
import math
import secrets
import zlib
from datetime import date, timedelta

from effort import round_load, set_load, e1rm, bodyweight_on
from nutrition import to_date

LIFTING_KINDS = ("upper_a", "lower_a", "upper_b", "lower_b")
ADHERENCE_KINDS = LIFTING_KINDS + ("conditioning",)
STALE_DAYS = 28

TRAIN_DEFAULTS = {
    "train_days": [1, 2, 3, 4, 5],
    "session_minutes": 60,
    "experience": "beginner",
    "cardio_kit": ["treadmill", "bike", "rower"],
    "main1_swap_every_blocks": 2,
    "programme_start": None,
    "split": "upper_lower",
}


class PlanError(Exception):
    """User-facing error from the programme engine."""

    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


# ----------------------------------------------------------------- seed

def load_programme(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def validate_seed(prog, exercises_by_key):
    """Every pool key must exist with the right shape. Returns a list of problems."""
    problems = []
    for kind, sess in prog.get("sessions", {}).items():
        for key in (sess.get("warmup"), sess.get("cooldown")):
            if key and key not in exercises_by_key:
                problems.append(f"{kind}: {key} is not in exercises.json")
        for slot in sess.get("slots", []):
            for key in slot.get("pool", []):
                if key not in exercises_by_key:
                    problems.append(f"{kind}/{slot['key']}: {key} is not in exercises.json")
    for proto in prog.get("protocols", []):
        m = proto.get("machine")
        if m and m != "any" and m not in exercises_by_key:
            problems.append(f"protocol {proto['id']}: machine {m} is not in exercises.json")
        has_minutes = "minutes" in proto
        has_interval = "work_sec" in proto
        if has_minutes == has_interval:
            problems.append(f"protocol {proto['id']}: needs minutes or work_sec/rest_sec/rounds, not both")
    return problems


def protocols_by_id(prog):
    return {p["id"]: p for p in prog.get("protocols", [])}


def protocol_minutes(proto, minimum=False):
    """Minutes a protocol takes, at its normal or minimum length."""
    if "minutes" in proto:
        return float(proto["minutes_min"] if minimum and proto.get("minutes_min") else proto["minutes"])
    rounds = proto.get("rounds_min") if minimum and proto.get("rounds_min") else proto.get("rounds", 1)
    return round(rounds * (proto.get("work_sec", 0) + proto.get("rest_sec", 0)) / 60.0, 2)


def protocol_rounds(proto, minimum=False):
    if "minutes" in proto:
        return None
    return proto.get("rounds_min") if minimum and proto.get("rounds_min") else proto.get("rounds")


# ----------------------------------------------------------------- helpers

def monday_of(d):
    d = to_date(d)
    return d - timedelta(days=d.weekday())


def train_settings(settings):
    s = dict(TRAIN_DEFAULTS)
    for k, v in settings.items():
        if k in s and v not in (None, ""):
            s[k] = v
    days = sorted(set(int(x) for x in s["train_days"]))
    s["train_days"] = [d for d in days if 1 <= d <= 7]
    kit = [m for m in s["cardio_kit"] if m in ("treadmill", "bike", "rower")]
    s["cardio_kit"] = kit or ["bike"]
    return s


def pick(pool, week_seed, slot_id, previous=None):
    """Deterministic choice from a pool that never repeats last week's pick."""
    pool = list(pool)
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]
    candidates = [k for k in pool if k != previous] or pool
    h = zlib.crc32(f"{week_seed}|{slot_id}".encode("utf-8"))
    return candidates[h % len(candidates)]


def exercises_by_key(conn, include_inactive=True):
    rows = conn.execute("SELECT * FROM exercises" + ("" if include_inactive else " WHERE active = 1"))
    return {r["key"]: dict(r) for r in rows}


def exercises_by_id(conn):
    return {r["id"]: dict(r) for r in conn.execute("SELECT * FROM exercises")}


def _active_pool(pool, ex_by_key):
    live = [k for k in pool if ex_by_key.get(k, {}).get("active", 1)]
    return live or list(pool[:1])


def est_minutes(item, overhead_sec=40):
    """How long an item takes on the floor."""
    if item.get("minutes"):
        return float(item["minutes"])
    sets = item.get("sets") or 0
    rest = item.get("rest_sec") or 0
    mins = sets * (rest + overhead_sec) / 60.0
    if item.get("slot_key") == "main1":
        mins += 2.0
    return mins


def session_minutes(items, overhead_sec=40):
    return round(sum(est_minutes(i, overhead_sec) for i in items), 2)


# ----------------------------------------------------------------- building

def previous_week_picks(conn, week_id, kind):
    """slot_key -> exercise key and protocol, from the same kind of session last week."""
    if not week_id:
        return {}
    rows = conn.execute("""
        SELECT pi.slot_key, e.key AS exercise_key, pi.protocol
        FROM plan_items pi JOIN plan_sessions ps ON ps.id = pi.session_id
        LEFT JOIN exercises e ON e.id = pi.exercise_id
        WHERE ps.week_id = ? AND ps.kind = ?""", (week_id, kind))
    return {r["slot_key"]: {"exercise": r["exercise_key"], "protocol": r["protocol"]} for r in rows}


def _scheme(prog, ts, name):
    schemes = prog["rep_schemes"].get(ts["experience"]) or prog["rep_schemes"]["beginner"]
    return schemes.get(name) or schemes["accessory"]


def build_lifting_items(conn, kind, block_no, week_seed, is_deload, prev_picks, prev_finisher, ts, prog, ex_by_key):
    sess = prog["sessions"][kind]
    protos = protocols_by_id(prog)
    kit = ts["cardio_kit"]
    swap_every = int(ts.get("main1_swap_every_blocks") or 2)
    items = []
    ordn = 0

    def add(**kw):
        nonlocal ordn
        ordn += 1
        base = {"ord": ordn, "section": None, "slot_key": None, "exercise_key": None, "sets": None, "rep_low": None,
                "rep_high": None, "rest_sec": None, "minutes": None, "protocol": None, "rounds": None,
                "optional": 0, "note": None}
        base.update(kw)
        items.append(base)

    # Finisher first, so the warm-up knows which machine to use.
    fin_pool = [p["id"] for p in prog["protocols"] if p.get("group") == "finisher" and p.get("machine") in kit]
    fin_id = pick(fin_pool, week_seed, f"{kind}:finisher", prev_finisher) if fin_pool else None
    fin = protos.get(fin_id) if fin_id else None
    machine = fin["machine"] if fin else kit[0]

    wu = prog.get("warmup_cardio") or {"key": "wu_cardio", "protocol": "warm_easy_5"}
    wu_proto = protos.get(wu["protocol"], {"minutes": 5})
    add(section="warmup", slot_key=wu["key"], exercise_key=machine, protocol=wu["protocol"],
        minutes=protocol_minutes(wu_proto))
    if sess.get("warmup"):
        add(section="warmup", slot_key="wu_dynamic", exercise_key=sess["warmup"], minutes=2.0)

    for slot in sess["slots"]:
        pool = _active_pool(slot["pool"], ex_by_key)
        select = slot.get("select", "rotate")
        if select == "block_alternate":
            every = swap_every if slot["key"] == "main1" else 1
            idx = ((block_no - 1) // every) % len(pool)
            key = pool[idx]
        elif select == "fixed":
            key = pool[0]
        else:
            prev = (prev_picks.get(slot["key"]) or {}).get("exercise")
            key = pick(pool, week_seed, f"{kind}:{slot['key']}", prev)
        ex = ex_by_key[key]
        scheme = _scheme(prog, ts, slot.get("scheme") or slot["section"])
        rest = prog["rest_sec"].get(slot.get("scheme") or slot["section"], 60)
        sets = scheme["sets"]
        lo, hi = scheme["rep_low"], scheme["rep_high"]
        if ex.get("timed"):
            lo, hi = prog.get("timed_scheme", {}).get("rep_low", 30), prog.get("timed_scheme", {}).get("rep_high", 60)
        if is_deload and slot["section"] in ("main", "accessory", "core"):
            sets = max(1, sets + int(prog["deload"].get("set_delta", -1)))
        add(section=slot["section"], slot_key=slot["key"], exercise_key=key, sets=sets, rep_low=lo, rep_high=hi,
            rest_sec=rest, optional=1 if slot.get("optional") else 0)

    if fin:
        add(section="finisher", slot_key="finisher", exercise_key=machine, protocol=fin_id,
            minutes=protocol_minutes(fin, minimum=is_deload), rounds=protocol_rounds(fin, minimum=is_deload))
    if sess.get("cooldown"):
        add(section="cooldown", slot_key="cooldown", exercise_key=sess["cooldown"], minutes=3.0)
    return items


def build_conditioning_items(conn, block_no, week_seed, is_deload, prev_picks, prev_machine, ts, prog, ex_by_key):
    sess = prog["sessions"]["conditioning"]
    protos = protocols_by_id(prog)
    kit = ts["cardio_kit"]
    machine = pick(kit, week_seed, "conditioning:machine", prev_machine)
    items = []
    ordn = 0

    def add(**kw):
        nonlocal ordn
        ordn += 1
        base = {"ord": ordn, "section": None, "slot_key": None, "exercise_key": None, "sets": None, "rep_low": None,
                "rep_high": None, "rest_sec": None, "minutes": None, "protocol": None, "rounds": None,
                "optional": 0, "note": None}
        base.update(kw)
        items.append(base)

    wu = prog.get("warmup_cardio") or {"key": "wu_cardio", "protocol": "warm_easy_5"}
    add(section="warmup", slot_key=wu["key"], exercise_key=machine, protocol=wu["protocol"],
        minutes=protocol_minutes(protos.get(wu["protocol"], {"minutes": 5})))
    for slot in sess["slots"]:
        if slot.get("protocol_group"):
            pool = [p["id"] for p in prog["protocols"] if p.get("group") == slot["protocol_group"] and p.get("machine") in (machine, "any")]
            prev = (prev_picks.get(slot["key"]) or {}).get("protocol")
            pid = pick(pool, week_seed, f"conditioning:{slot['key']}", prev)
            proto = protos[pid]
            add(section=slot["section"], slot_key=slot["key"], exercise_key=machine, protocol=pid,
                minutes=protocol_minutes(proto, minimum=is_deload), rounds=protocol_rounds(proto, minimum=is_deload))
        else:
            pool = _active_pool(slot["pool"], ex_by_key)
            prev = (prev_picks.get(slot["key"]) or {}).get("exercise")
            key = pick(pool, week_seed, f"conditioning:{slot['key']}", prev)
            ex = ex_by_key[key]
            scheme = _scheme(prog, ts, slot.get("scheme") or "circuit")
            lo, hi = scheme["rep_low"], scheme["rep_high"]
            if ex.get("timed"):
                lo, hi = prog.get("timed_scheme", {}).get("rep_low", 30), prog.get("timed_scheme", {}).get("rep_high", 60)
            sets = scheme["sets"]
            if is_deload:
                sets = max(1, sets + int(prog["deload"].get("set_delta", -1)))
            add(section=slot["section"], slot_key=slot["key"], exercise_key=key, sets=sets, rep_low=lo, rep_high=hi,
                rest_sec=prog["rest_sec"].get("circuit", 30))
    if sess.get("cooldown"):
        add(section="cooldown", slot_key="mobility", exercise_key=sess["cooldown"], minutes=10.0)
    return items, machine


def build_zone2_items(week_seed, conditioning_machine, is_deload, ts, prog):
    protos = protocols_by_id(prog)
    kit = [m for m in ts["cardio_kit"] if m != conditioning_machine] or ts["cardio_kit"]
    machine = pick(kit, week_seed, "zone2:machine")
    proto = protos.get("zone2_steady") or next(p for p in prog["protocols"] if p.get("group") == "zone2")
    return [{"ord": 1, "section": "main", "slot_key": "zone2", "exercise_key": machine, "sets": None, "rep_low": None,
             "rep_high": None, "rest_sec": None, "minutes": protocol_minutes(proto, minimum=is_deload),
             "protocol": proto["id"], "rounds": None, "optional": 0, "note": None}]


def trim_to_budget(items, budget, prog):
    """Shorten a lifting session until it fits, in the order the plan describes."""
    protos = protocols_by_id(prog)
    overhead = prog.get("set_overhead_sec", 40)
    if session_minutes(items, overhead) <= budget:
        return items
    # 1. drop optional items
    items = [i for i in items if not i.get("optional")]
    if session_minutes(items, overhead) <= budget:
        return items
    # 2. finisher to its minimum
    for i in items:
        if i["section"] == "finisher" and i.get("protocol") in protos:
            i["minutes"] = protocol_minutes(protos[i["protocol"]], minimum=True)
            i["rounds"] = protocol_rounds(protos[i["protocol"]], minimum=True)
    if session_minutes(items, overhead) <= budget:
        return items
    # 3. accessories from 3 to 2 sets, last slot first
    for key in ("acc3", "acc2", "acc1"):
        for i in items:
            if i["slot_key"] == key and (i.get("sets") or 0) > 2:
                i["sets"] = 2
        if session_minutes(items, overhead) <= budget:
            return items
    # 4. core to 2 sets
    for i in items:
        if i["section"] == "core" and (i.get("sets") or 0) > 2:
            i["sets"] = 2
    if session_minutes(items, overhead) <= budget:
        return items
    # 5. drop acc3
    items = [i for i in items if i["slot_key"] != "acc3"]
    if session_minutes(items, overhead) <= budget:
        return items
    # 6. drop the finisher
    items = [i for i in items if i["section"] != "finisher"]
    for i in items:
        if i["section"] == "main" and i["slot_key"] == "main1":
            i["note"] = "trimmed for time"
    return items


def insert_items(conn, session_id, items, ex_by_key):
    for n, it in enumerate(items, start=1):
        ex = ex_by_key.get(it["exercise_key"]) if it.get("exercise_key") else None
        conn.execute("""INSERT INTO plan_items (session_id, ord, section, slot_key, exercise_id, sets, rep_low, rep_high,
                        target_weight, target_source, rest_sec, minutes, protocol, rounds, optional, note)
                        VALUES (?,?,?,?,?,?,?,?,NULL,NULL,?,?,?,?,?,?)""",
                     (session_id, n, it["section"], it["slot_key"], ex["id"] if ex else None, it.get("sets"),
                      it.get("rep_low"), it.get("rep_high"), it.get("rest_sec"), it.get("minutes"), it.get("protocol"),
                      it.get("rounds"), it.get("optional", 0), it.get("note")))


def build_session_items(conn, session, week, block, ts, prog, ex_by_key, week_context):
    """Create the plan_items for one session row. week_context carries per-week rotation state."""
    kind = session["kind"]
    if kind == "rest":
        return
    prev_week_id = week_context.get("prev_week_id")
    prev_picks = previous_week_picks(conn, prev_week_id, kind)
    if is_lifting(kind, prog):
        items = build_lifting_items(conn, kind, block["block_no"], week["seed"], bool(week["is_deload"]), prev_picks,
                                    week_context.get("last_finisher"), ts, prog, ex_by_key)
        items = trim_to_budget(items, float(ts["session_minutes"]), prog)
        for i in items:
            if i["section"] == "finisher":
                week_context["last_finisher"] = i["protocol"]
    elif kind == "conditioning":
        prev_machine = (prev_picks.get("wu_cardio") or {}).get("exercise")
        items, machine = build_conditioning_items(conn, block["block_no"], week["seed"], bool(week["is_deload"]),
                                                  prev_picks, prev_machine, ts, prog, ex_by_key)
        week_context["conditioning_machine"] = machine
    elif kind == "zone2":
        items = build_zone2_items(week["seed"], week_context.get("conditioning_machine"), bool(week["is_deload"]), ts, prog)
    else:
        return
    insert_items(conn, session["id"], items, ex_by_key)


def is_lifting(kind, prog):
    return kind in prog.get("sessions", {}) and kind not in ("conditioning", "zone2")


def counts_for_adherence(kind):
    return kind not in ("rest", "zone2")


def template_for(ts, prog):
    """The weekly template for the chosen split and number of training days."""
    n = len(ts["train_days"])
    split = prog.get("splits", {}).get(ts.get("split") or "upper_lower")
    if split and split.get("templates"):
        keys = sorted(int(k) for k in split["templates"])
        fit = [k for k in keys if k <= n]
        return split["templates"][str(fit[-1] if fit else keys[0])]
    return prog["template_6"] if n >= 6 else prog["template_5"]


def week_kinds(ts, prog):
    days = ts["train_days"]
    template = template_for(ts, prog)
    kinds = {}
    for i, wd in enumerate(days[:len(template)]):
        kinds[wd] = template[i]
    return kinds


def titles(prog):
    t = {k: v.get("title", k) for k, v in prog["sessions"].items()}
    t["rest"] = "Rest"
    return t


def create_week(conn, block, week_no, start, settings, prog, ex_by_key, prev_week_id):
    ts = train_settings(settings)
    seed = f"{block['seed']}:{week_no}"
    is_deload = 1 if week_no == int(prog["deload"].get("week_no", 4)) else 0
    cur = conn.execute("INSERT INTO plan_weeks (block_id, week_no, start_date, seed, is_deload) VALUES (?,?,?,?,?)",
                       (block["id"], week_no, start.isoformat(), seed, is_deload))
    week = {"id": cur.lastrowid, "block_id": block["id"], "week_no": week_no, "start_date": start.isoformat(),
            "seed": seed, "is_deload": is_deload}
    programme_start = to_date(settings.get("programme_start")) or start
    kinds = week_kinds(ts, prog)
    names = titles(prog)
    ctx = {"prev_week_id": prev_week_id}
    # conditioning before zone2 within the week so zone2 can avoid its machine
    for wd in range(1, 8):
        kind = kinds.get(wd, "rest")
        d = start + timedelta(days=wd - 1)
        status = "void" if (d < programme_start and kind != "rest") else "planned"
        cur = conn.execute("""INSERT INTO plan_sessions (week_id, day_offset, date, kind, title, status, moved_from, note)
                              VALUES (?,?,?,?,?,?,NULL,NULL)""", (week["id"], wd - 1, d.isoformat(), kind, names.get(kind, kind), status))
        session = {"id": cur.lastrowid, "kind": kind, "date": d.isoformat()}
        build_session_items(conn, session, week, block, ts, prog, ex_by_key, ctx)
    return week


def create_block(conn, start, settings, prog, ex_by_key):
    start = monday_of(start)
    block_no = conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] + 1
    seed = secrets.token_hex(4)
    cur = conn.execute("INSERT INTO blocks (block_no, start_date, weeks, split, seed, notes) VALUES (?,?,?,?,?,NULL)",
                       (block_no, start.isoformat(), 4, "upper_lower", seed))
    block = {"id": cur.lastrowid, "block_no": block_no, "start_date": start.isoformat(), "seed": seed}
    prev = conn.execute("SELECT id FROM plan_weeks ORDER BY start_date DESC LIMIT 1").fetchone()
    prev_week_id = prev["id"] if prev else None
    for week_no in range(1, 5):
        week = create_week(conn, block, week_no, start + timedelta(days=7 * (week_no - 1)), settings, prog, ex_by_key, prev_week_id)
        prev_week_id = week["id"]
    return block


def ensure_plan_through(conn, d, settings, prog, ex_by_key, set_setting):
    """Make sure a plan exists that covers the given day. Creates at most the block that contains it."""
    d = to_date(d)
    last = conn.execute("SELECT start_date FROM plan_weeks ORDER BY start_date DESC LIMIT 1").fetchone()
    if not last:
        if not settings.get("programme_start"):
            settings["programme_start"] = d.isoformat()
            set_setting("programme_start", d.isoformat())
        create_block(conn, d, settings, prog, ex_by_key)
        last = conn.execute("SELECT start_date FROM plan_weeks ORDER BY start_date DESC LIMIT 1").fetchone()
    guard = 0
    while d > to_date(last["start_date"]) + timedelta(days=6) and guard < 60:
        create_block(conn, to_date(last["start_date"]) + timedelta(days=7), settings, prog, ex_by_key)
        last = conn.execute("SELECT start_date FROM plan_weeks ORDER BY start_date DESC LIMIT 1").fetchone()
        guard += 1


def sweep_missed(conn, today):
    """Planned sessions that are now in the past with no workout become skipped."""
    conn.execute("""UPDATE plan_sessions SET status = 'skipped'
                    WHERE status = 'planned' AND date < ? AND kind != 'rest'
                    AND id NOT IN (SELECT session_id FROM workouts WHERE deleted = 0 AND session_id IS NOT NULL)""",
                 (to_date(today).isoformat(),))


# ----------------------------------------------------------------- rebuilding

def _live_session_ids(conn, week_id):
    return {r["session_id"] for r in conn.execute(
        """SELECT w.session_id FROM workouts w JOIN plan_sessions ps ON ps.id = w.session_id
           WHERE ps.week_id = ? AND w.deleted = 0""", (week_id,))}


def rebuild_week(conn, week_id, settings, prog, ex_by_key, from_date=None):
    """Regenerate the untouched sessions of a week with its current seed and today's settings."""
    week = dict(conn.execute("SELECT * FROM plan_weeks WHERE id = ?", (week_id,)).fetchone())
    block = dict(conn.execute("SELECT * FROM blocks WHERE id = ?", (week["block_id"],)).fetchone())
    prev = conn.execute("SELECT id FROM plan_weeks WHERE start_date < ? ORDER BY start_date DESC LIMIT 1",
                        (week["start_date"],)).fetchone()
    ts = train_settings(settings)
    kinds = week_kinds(ts, prog)
    names = titles(prog)
    live = _live_session_ids(conn, week_id)
    start = to_date(week["start_date"])
    programme_start = to_date(settings.get("programme_start")) or start
    ctx = {"prev_week_id": prev["id"] if prev else None}
    for wd in range(1, 8):
        d = start + timedelta(days=wd - 1)
        row = conn.execute("SELECT * FROM plan_sessions WHERE week_id = ? AND day_offset = ?", (week_id, wd - 1)).fetchone()
        untouched = row is None or (row["id"] not in live and row["status"] in ("planned", "void", "skipped")
                                    and (from_date is None or d >= to_date(from_date)))
        if row and not untouched:
            # keep it, but remember its finisher and machine so later days rotate correctly
            for it in conn.execute("SELECT slot_key, protocol, exercise_id FROM plan_items WHERE session_id = ?", (row["id"],)):
                if it["slot_key"] == "finisher":
                    ctx["last_finisher"] = it["protocol"]
                if row["kind"] == "conditioning" and it["slot_key"] == "wu_cardio":
                    ex = conn.execute("SELECT key FROM exercises WHERE id = ?", (it["exercise_id"],)).fetchone()
                    ctx["conditioning_machine"] = ex["key"] if ex else None
            continue
        kind = kinds.get(wd, "rest")
        status = "void" if (d < programme_start and kind != "rest") else ("planned" if d >= date.today() or row is None else (row["status"] if row["status"] != "void" else "planned"))
        if row:
            conn.execute("DELETE FROM plan_items WHERE session_id = ?", (row["id"],))
            conn.execute("UPDATE plan_sessions SET kind = ?, title = ?, status = ?, note = NULL WHERE id = ?",
                         (kind, names.get(kind, kind), status if row["status"] != "skipped" or d >= date.today() else "skipped", row["id"]))
            sid = row["id"]
        else:
            cur = conn.execute("""INSERT INTO plan_sessions (week_id, day_offset, date, kind, title, status, moved_from, note)
                                  VALUES (?,?,?,?,?,?,NULL,NULL)""", (week_id, wd - 1, d.isoformat(), kind, names.get(kind, kind), status))
            sid = cur.lastrowid
        build_session_items(conn, {"id": sid, "kind": kind, "date": d.isoformat()}, week, block, ts, prog, ex_by_key, ctx)


def shuffle_week(conn, week_id, settings, prog, ex_by_key):
    """New seed for one week, then cascade through the later weeks of its block."""
    week = conn.execute("SELECT * FROM plan_weeks WHERE id = ?", (week_id,)).fetchone()
    if not week:
        raise PlanError("That week does not exist.", 404)
    conn.execute("UPDATE plan_weeks SET seed = ? WHERE id = ?", (secrets.token_hex(4), week_id))
    rebuild_week(conn, week_id, settings, prog, ex_by_key)
    later = conn.execute("SELECT id FROM plan_weeks WHERE block_id = ? AND start_date > ? ORDER BY start_date",
                         (week["block_id"], week["start_date"])).fetchall()
    for r in later:
        rebuild_week(conn, r["id"], settings, prog, ex_by_key)


def regenerate_from(conn, from_date, settings, prog, ex_by_key):
    """After a training-settings change: rebuild every untouched session from a date, seeds kept."""
    weeks = conn.execute("SELECT id, start_date FROM plan_weeks WHERE date(start_date, '+6 days') >= ? ORDER BY start_date",
                         (to_date(from_date).isoformat(),)).fetchall()
    for w in weeks:
        rebuild_week(conn, w["id"], settings, prog, ex_by_key, from_date=from_date)


def swap_item(conn, item_id, exercise_key, prog, ex_by_key):
    item = conn.execute("""SELECT pi.*, ps.kind, ps.week_id FROM plan_items pi JOIN plan_sessions ps ON ps.id = pi.session_id
                           WHERE pi.id = ?""", (item_id,)).fetchone()
    if not item:
        raise PlanError("That item does not exist.", 404)
    used = conn.execute("SELECT COUNT(*) FROM set_logs WHERE plan_item_id = ? AND deleted = 0", (item_id,)).fetchone()[0]
    if used:
        raise PlanError("You have already logged a set on this exercise today. Finish it or delete the set first.", 409)
    current = conn.execute("SELECT key, pattern FROM exercises WHERE id = ?", (item["exercise_id"],)).fetchone()
    slot = next((s for s in prog["sessions"].get(item["kind"], {}).get("slots", []) if s["key"] == item["slot_key"]), None)
    pool = _active_pool(slot["pool"], ex_by_key) if slot else []
    if exercise_key:
        ex = ex_by_key.get(exercise_key)
        if not ex or not ex.get("active", 1):
            raise PlanError("That exercise is not in the library.", 404)
        if exercise_key not in pool and current and ex["pattern"] != current["pattern"]:
            raise PlanError("Pick an exercise with the same movement pattern.", 400)
    else:
        prev = conn.execute("""SELECT e.key FROM plan_items pi JOIN plan_sessions ps ON ps.id = pi.session_id
                               JOIN exercises e ON e.id = pi.exercise_id
                               WHERE ps.kind = ? AND pi.slot_key = ? AND ps.week_id = (SELECT id FROM plan_weeks WHERE start_date < (SELECT start_date FROM plan_weeks WHERE id = ?) ORDER BY start_date DESC LIMIT 1)""",
                            (item["kind"], item["slot_key"], item["week_id"])).fetchone()
        prev_key = prev["key"] if prev else None
        options = [k for k in pool if k != (current["key"] if current else None) and k != prev_key] or \
                  [k for k in pool if k != (current["key"] if current else None)]
        if not options:
            same = [k for k, e in ex_by_key.items() if current and e["pattern"] == current["pattern"] and e.get("active", 1) and k != current["key"]]
            options = sorted(same)
        if not options:
            raise PlanError("There is nothing to swap this for.", 400)
        exercise_key = options[zlib.crc32(f"{item_id}|{len(options)}".encode()) % len(options)]
    ex = ex_by_key[exercise_key]
    lo, hi = item["rep_low"], item["rep_high"]
    if ex.get("timed"):
        lo, hi = prog.get("timed_scheme", {}).get("rep_low", 30), prog.get("timed_scheme", {}).get("rep_high", 60)
    elif current and conn.execute("SELECT timed FROM exercises WHERE id = ?", (item["exercise_id"],)).fetchone()["timed"]:
        scheme = _scheme(prog, train_settings({}), item["slot_key"] if item["slot_key"] in ("main1", "main2") else item["section"])
        lo, hi = scheme["rep_low"], scheme["rep_high"]
    conn.execute("UPDATE plan_items SET exercise_id = ?, rep_low = ?, rep_high = ?, target_weight = NULL, target_source = NULL, note = 'swapped' WHERE id = ?",
                 (ex["id"], lo, hi, item_id))
    return ex


def move_session(conn, session_id, today):
    """Do a planned, skipped or void session today by exchanging dates with today's session."""
    today = to_date(today)
    s = conn.execute("SELECT * FROM plan_sessions WHERE id = ?", (session_id,)).fetchone()
    if not s:
        raise PlanError("That session does not exist.", 404)
    if s["status"] not in ("planned", "skipped", "void"):
        raise PlanError("That session is already done.", 409)
    if abs((to_date(s["date"]) - today).days) > 14:
        raise PlanError("Only sessions within two weeks can be moved.", 400)
    if s["date"] == today.isoformat():
        return
    t = conn.execute("SELECT * FROM plan_sessions WHERE date = ?", (today.isoformat(),)).fetchone()
    if t is None:
        raise PlanError("Today is not in the plan yet.", 409)
    live = conn.execute("SELECT COUNT(*) FROM workouts WHERE session_id = ? AND deleted = 0", (t["id"],)).fetchone()[0]
    if live:
        raise PlanError("You have already started today's session.", 409)
    conn.execute("UPDATE plan_sessions SET date = ?, day_offset = ?, week_id = ?, moved_from = ?, status = 'planned' WHERE id = ?",
                 (today.isoformat(), t["day_offset"], t["week_id"], s["date"], s["id"]))
    old = to_date(s["date"])
    conn.execute("UPDATE plan_sessions SET date = ?, day_offset = ?, week_id = ?, moved_from = ?, status = CASE WHEN status = 'void' THEN 'void' ELSE 'planned' END WHERE id = ?",
                 (old.isoformat(), s["day_offset"], s["week_id"], today.isoformat(), t["id"]))
    sweep_missed(conn, today)


def mark_rest(conn, session_id):
    s = conn.execute("SELECT status FROM plan_sessions WHERE id = ?", (session_id,)).fetchone()
    if not s:
        raise PlanError("That session does not exist.", 404)
    if s["status"] == "done":
        raise PlanError("That session is already done.", 409)
    conn.execute("UPDATE plan_sessions SET status = 'skipped', note = 'rest' WHERE id = ?", (session_id,))


# ----------------------------------------------------------------- progression

def _step(ex, w):
    return 1.0 if ex.get("equipment") == "dumbbell" and (w or 0) < 10 else 2.5


def _increment(ex, w):
    if ex.get("increment_kg"):
        return float(ex["increment_kg"])
    if ex.get("pattern") in ("squat", "hinge") and ex.get("equipment") in ("barbell", "trap_bar", "machine"):
        return 5.0
    if ex.get("equipment") == "dumbbell":
        return 1.0 if (w or 0) < 10 else 2.5
    return 2.5


def _min_load(ex, w):
    if ex.get("min_load_kg") is not None:
        return float(ex["min_load_kg"])
    if ex.get("equipment") == "barbell":
        return 20.0
    return _step(ex, w)


def reference_workout(conn, exercise_id, exclude_client_id=None):
    row = conn.execute("""
        SELECT w.client_id, w.date FROM workouts w
        JOIN set_logs s ON s.workout_client_id = w.client_id
        LEFT JOIN plan_sessions ps ON ps.id = w.session_id
        LEFT JOIN plan_weeks pw ON pw.id = ps.week_id
        WHERE s.exercise_id = ? AND s.is_warmup = 0 AND s.deleted = 0
          AND w.ended_at IS NOT NULL AND w.deleted = 0
          AND COALESCE(pw.is_deload, 0) = 0 AND (? IS NULL OR w.client_id != ?)
        ORDER BY w.date DESC, w.ended_at DESC LIMIT 1""", (exercise_id, exclude_client_id, exclude_client_id)).fetchone()
    return dict(row) if row else None


def reference_sets(conn, workout_client_id, exercise_id):
    rows = conn.execute("""SELECT s.reps, s.weight_kg, s.rpe, s.set_no, pi.sets AS planned_sets
                           FROM set_logs s LEFT JOIN plan_items pi ON pi.id = s.plan_item_id
                           WHERE s.workout_client_id = ? AND s.exercise_id = ? AND s.is_warmup = 0 AND s.deleted = 0
                           ORDER BY s.set_no""", (workout_client_id, exercise_id))
    return [dict(r) for r in rows]


def progression(ex, sets, rep_low, rep_high, planned_sets):
    """The double-progression rule on one exercise's sets from the reference workout.

    Returns (weight or None, label). For timed moves the weight is None and the
    label says whether to add seconds.
    """
    if not sets:
        return None, "first"
    assisted = ex.get("equipment") == "assisted"
    weights = [float(s["weight_kg"] or 0) for s in sets]
    w = min(weights) if assisted else max(weights)
    top = [s for s in sets if float(s["weight_kg"] or 0) == w]
    rpes = [float(s["rpe"]) for s in sets if s.get("rpe") is not None]
    mean_rpe = sum(rpes) / len(rpes) if rpes else 8.0
    n_hi = sum(1 for r in rpes if r >= 9.5)
    planned = planned_sets or 3
    reps = lambda s: int(s.get("reps") or 0)
    hit_all_high = len(top) >= planned and all(reps(s) >= rep_high for s in top)
    any_low = any(reps(s) < rep_low for s in sets)
    partial = len(sets) < planned

    if ex.get("timed"):
        if any_low or n_hi >= 2:
            return None, "hold_time"
        if hit_all_high:
            return None, "add_time"
        return None, "hold_time"
    if ex.get("bodyweight_fraction") and ex.get("equipment") == "bodyweight":
        return None, "add_reps" if hit_all_high else "hold_reps"

    step = _step(ex, w)
    inc = _increment(ex, w)
    if assisted:
        if any_low or n_hi >= 2:
            return round_load(w + step, ex.get("equipment")), "decrease_reps" if any_low else "decrease_rpe"
        if partial:
            return w, "hold_partial"
        if hit_all_high and mean_rpe <= 8.5:
            return max(0.0, round_load(w - inc, ex.get("equipment"))), "increase"
        return w, "hold_rpe" if hit_all_high else "hold_reps"

    if any_low or n_hi >= 2:
        target = max(_min_load(ex, w), min(round_load(0.95 * w, ex.get("equipment")), w - step))
        return target, "decrease_reps" if any_low else "decrease_rpe"
    if partial:
        return w, "hold_partial"
    if hit_all_high and mean_rpe <= 8.5:
        return round_load(w + inc, ex.get("equipment")), "increase"
    if hit_all_high:
        return w, "hold_rpe"
    return w, "hold_reps"


def target_for(conn, ex, item, today, is_deload=False, exclude_client_id=None, ex_by_key=None, bw=None):
    """Target weight and its explanation for one plan item.

    Returns {weight, source, last: {date, sets}, text}.
    """
    today = to_date(today)
    rep_low = item.get("rep_low") or 8
    rep_high = item.get("rep_high") or 12
    ref = reference_workout(conn, ex["id"], exclude_client_id)
    last = None
    if ref:
        sets = reference_sets(conn, ref["client_id"], ex["id"])
        planned = next((s["planned_sets"] for s in sets if s.get("planned_sets")), None) or item.get("sets") or 3
        weight, label = progression(ex, sets, rep_low, rep_high, planned)
        last = {"date": ref["date"], "sets": [{"reps": s["reps"], "weight": s["weight_kg"], "rpe": s["rpe"]} for s in sets]}
        if (today - to_date(ref["date"])).days > STALE_DAYS and weight is not None:
            weights = [float(s["weight_kg"] or 0) for s in sets]
            weight = min(weights) if ex.get("equipment") == "assisted" else max(weights)
            label = "stale"
    else:
        weight, label = None, "first"
        if ex.get("variation_of") and ex_by_key and ex.get("carry"):
            old = ex_by_key.get(ex["variation_of"])
            if old:
                old_ref = reference_workout(conn, old["id"])
                if old_ref:
                    old_sets = reference_sets(conn, old_ref["client_id"], old["id"])
                    best = 0.0
                    for s in old_sets:
                        load = set_load(s["weight_kg"], old.get("bodyweight_fraction"), bw or 80, old.get("equipment"))
                        val, low = e1rm(load, s["reps"])
                        if val and not low:
                            best = max(best, val)
                    if best:
                        weight = round_load(float(ex["carry"]) * best / (1 + rep_low / 30.0), ex.get("equipment"))
                        label = "guess"
    if is_deload and weight is not None and label not in ("first",):
        weight = round_load(weight * 0.9, ex.get("equipment"))
        label = "deload"
    return {"weight": weight, "source": label, "last": last, "text": target_text(ex, weight, label, rep_low, rep_high)}


def target_text(ex, weight, label, rep_low, rep_high):
    unit = "s" if ex.get("timed") else "reps"
    texts = {
        "first": f"First time. Find a weight you can do for {rep_low + 2} {unit} with two in reserve.",
        "guess": "A starting guess from a related lift. Adjust freely.",
        "increase": "You hit every set last time. Go up.",
        "hold_reps": "Same weight. Try for more reps.",
        "hold_rpe": "You hit the reps but it was hard. Same weight, make it smoother.",
        "hold_partial": "You did not get every set in last time. Same weight, all sets.",
        "decrease_reps": "Reps fell short last time. A little lighter, own it.",
        "decrease_rpe": "Last time was a grind. A little lighter.",
        "stale": "It has been a while. Repeat your last weight.",
        "deload": "Deload week. Lighter on purpose, keep the reps crisp.",
        "add_time": "Add five seconds to each hold.",
        "hold_time": f"Hold {rep_low} to {rep_high} seconds.",
        "add_reps": "Add a rep or two each set.",
    }
    return texts.get(label, "")


def freeze_targets(conn, session_id, today, settings, ex_map, ex_by_key, prog):
    """Write the live targets onto a session's items the moment the workout starts."""
    week = conn.execute("""SELECT pw.is_deload FROM plan_sessions ps JOIN plan_weeks pw ON pw.id = ps.week_id
                           WHERE ps.id = ?""", (session_id,)).fetchone()
    is_deload = bool(week and week["is_deload"])
    bw = bodyweight_on(conn, today, settings)
    for it in conn.execute("SELECT * FROM plan_items WHERE session_id = ? AND target_source IS NULL", (session_id,)).fetchall():
        it = dict(it)
        if it["section"] not in ("main", "accessory", "core") or not it.get("exercise_id"):
            continue
        ex = ex_map.get(it["exercise_id"])
        if not ex:
            continue
        t = target_for(conn, ex, it, today, is_deload, ex_by_key=ex_by_key, bw=bw)
        conn.execute("UPDATE plan_items SET target_weight = ?, target_source = ? WHERE id = ?", (t["weight"], t["source"], it["id"]))


# ----------------------------------------------------------------- views

def week_for_date(conn, d):
    return conn.execute("""SELECT pw.*, b.block_no, b.seed AS block_seed FROM plan_weeks pw JOIN blocks b ON b.id = pw.block_id
                           WHERE pw.start_date <= ? AND date(pw.start_date, '+6 days') >= ? ORDER BY pw.start_date DESC LIMIT 1""",
                        (to_date(d).isoformat(), to_date(d).isoformat())).fetchone()


def session_view(conn, session, today, settings, prog, ex_map, ex_by_key, bw, with_targets=True, exclude_client_id=None):
    """One session with its items, exercises, targets and last-time numbers."""
    session = dict(session)
    week = conn.execute("SELECT is_deload, week_no FROM plan_weeks WHERE id = ?", (session["week_id"],)).fetchone()
    is_deload = bool(week and week["is_deload"])
    protos = protocols_by_id(prog)
    items = []
    total = 0.0
    for it in conn.execute("SELECT * FROM plan_items WHERE session_id = ? ORDER BY ord", (session["id"],)).fetchall():
        it = dict(it)
        ex = ex_map.get(it["exercise_id"]) if it.get("exercise_id") else None
        it["exercise"] = _exercise_public(ex) if ex else None
        it["est_minutes"] = round(est_minutes(it, prog.get("set_overhead_sec", 40)), 1)
        total += it["est_minutes"]
        if it.get("protocol") and it["protocol"] in protos:
            it["protocol_text"] = protos[it["protocol"]].get("text")
            it["protocol_detail"] = {k: protos[it["protocol"]].get(k) for k in ("work_sec", "rest_sec", "intensity", "machine")}
        if with_targets and ex and it["section"] in ("main", "accessory", "core"):
            if it.get("target_source"):
                t = target_for(conn, ex, it, today, is_deload, exclude_client_id=exclude_client_id, ex_by_key=ex_by_key, bw=bw)
                it["target"] = {"weight": it["target_weight"], "source": it["target_source"], "last": t["last"],
                                "text": target_text(ex, it["target_weight"], it["target_source"], it["rep_low"] or 8, it["rep_high"] or 12)}
            else:
                it["target"] = target_for(conn, ex, it, today, is_deload, exclude_client_id=exclude_client_id, ex_by_key=ex_by_key, bw=bw)
        items.append(it)
    session["items"] = items
    session["est_minutes"] = round(total, 1)
    session["is_deload"] = is_deload
    session["week_no"] = week["week_no"] if week else None
    w = conn.execute("SELECT client_id, started_at, ended_at, effort, kcal_est, kcal_wearable, volume, work_sets FROM workouts WHERE session_id = ? AND deleted = 0 ORDER BY started_at DESC LIMIT 1",
                     (session["id"],)).fetchone()
    session["workout"] = dict(w) if w else None
    return session


def _exercise_public(ex):
    out = dict(ex)
    for k in ("cues", "secondary_muscles", "mets"):
        if isinstance(out.get(k), str):
            try:
                out[k] = json.loads(out[k])
            except ValueError:
                pass
    return out


def week_view(conn, d, today, settings, prog, ex_map, ex_by_key):
    week = week_for_date(conn, d)
    if not week:
        return None
    bw = bodyweight_on(conn, today, settings)
    sessions = [session_view(conn, s, today, settings, prog, ex_map, ex_by_key, bw)
                for s in conn.execute("SELECT * FROM plan_sessions WHERE week_id = ? ORDER BY date", (week["id"],)).fetchall()]
    planned = [s for s in sessions if counts_for_adherence(s["kind"]) and s["status"] != "void"]
    done = [s for s in planned if s["status"] == "done"]
    weeks_in_block = conn.execute("SELECT COUNT(*) FROM plan_weeks WHERE block_id = ?", (week["block_id"],)).fetchone()[0]
    ts = train_settings(settings)
    split_def = prog.get("splits", {}).get(ts.get("split") or "upper_lower")
    return {"week": dict(week), "sessions": sessions, "weeks_in_block": weeks_in_block, "split": ts.get("split"),
            "split_name": split_def["name"] if split_def else "Upper / Lower",
            "adherence": {"done": len(done), "planned": len(planned)}}


def adherence_by_week(conn):
    rows = conn.execute("""SELECT pw.start_date AS week, b.block_no, pw.week_no,
                           SUM(CASE WHEN ps.status = 'done' THEN 1 ELSE 0 END) AS done,
                           COUNT(*) AS planned
                           FROM plan_sessions ps JOIN plan_weeks pw ON pw.id = ps.week_id JOIN blocks b ON b.id = pw.block_id
                           WHERE ps.kind NOT IN ('rest', 'zone2') AND ps.status != 'void'
                           GROUP BY pw.id ORDER BY pw.start_date""")
    return [dict(r) for r in rows]
