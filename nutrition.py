"""Nutrition maths for Fitness Tracker.

Targets (BMR, maintenance, deficit, budget, macros), the weight trend and pace
line, the food search ranking, the Open Food Facts proxy, and readers for the
two bundled food lists. Standard library only.

Every function that depends on the calendar takes the date as a parameter so
the tests can pin it. Nothing here calls date.today().
"""

import csv
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

KCAL_PER_KG = 7700          # energy in a kilogram of body fat, the usual planning figure
KJ_PER_KCAL = 4.184

# Settings the targets need, with their defaults. The server merges these into
# the settings table on first run, so every key always exists.
DEFAULTS = {
    "sex": "m",
    "birth_date": None,
    "height_cm": None,
    "start_weight_kg": None,
    "target_weight_kg": None,
    "target_date": None,
    "goal_start_weight": None,
    "goal_start_date": None,
    "neat_factor": 1.3,
    "deficit_cap": 750,
    "surplus_cap": 300,
    "protein_g_per_kg": 2.0,
    "fat_g_per_kg": 0.8,
    "fat_floor_g_per_kg": 0.5,
    "carb_floor_g": 50,
    "kcal_floor": None,
    "water_target_ml": 2500,
    "sleep_target_h": 8,
    "steps_target": 8000,
}


# ----------------------------------------------------------------- dates

def to_date(value):
    """ISO string or date to date. None stays None."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def age_on(birth_date, d):
    birth = to_date(birth_date)
    if birth is None:
        return None
    return int(math.floor((d - birth).days / 365.25))


# ----------------------------------------------------------------- weight

def trend_weight(logs, d, start_weight=None):
    """The weight to use for a day.

    logs is a list of (date, weight_kg). Mean of the last seven calendar days
    when there is at least one log in the window; otherwise the latest log on
    or before the day, drawn dashed by the page; otherwise the starting weight
    from Settings. Returns (weight or None, source) with source one of
    trend, latest, start, none.
    """
    pairs = [(to_date(ld), float(w)) for ld, w in logs if w is not None]
    window = [w for ld, w in pairs if d - timedelta(days=6) <= ld <= d]
    if window:
        return round(sum(window) / len(window), 2), "trend"
    before = [(ld, w) for ld, w in pairs if ld <= d]
    if before:
        before.sort()
        return before[-1][1], "latest"
    if start_weight:
        return float(start_weight), "start"
    return None, "none"


def pace_weight(settings, d):
    """Where the straight line from the goal start to the target sits on a day."""
    gs = settings.get("goal_start_weight")
    gd = to_date(settings.get("goal_start_date"))
    tw = settings.get("target_weight_kg")
    td = to_date(settings.get("target_date"))
    if gs is None or gd is None or tw is None or td is None:
        return None
    total = (td - gd).days
    if total <= 0:
        return float(tw)
    frac = min(1.0, max(0.0, (d - gd).days / total))
    return round(float(gs) + (float(tw) - float(gs)) * frac, 2)


def weekly_pace(settings):
    """Planned change per week along the pace line, negative when losing."""
    gs = settings.get("goal_start_weight")
    gd = to_date(settings.get("goal_start_date"))
    tw = settings.get("target_weight_kg")
    td = to_date(settings.get("target_date"))
    if gs is None or gd is None or tw is None or td is None:
        return None
    total = (td - gd).days
    if total <= 0:
        return 0.0
    return round((float(tw) - float(gs)) * 7 / total, 2)


def pace_verdict(trend, pace, logs_last_14, goal_start_weight, target):
    """On pace, ahead or behind, as the Today page words it."""
    if trend is None or pace is None or goal_start_weight is None or target is None or logs_last_14 < 3:
        return {"code": "no_data", "text": "Log your weight a few times to see your pace"}
    sign = 1 if float(goal_start_weight) >= float(target) else -1   # losing: above the line is behind
    behind = (trend - pace) * sign
    if abs(behind) <= 0.5:
        return {"code": "on_pace", "text": "On pace", "kg": round(behind, 1)}
    if behind > 0:
        return {"code": "behind", "text": f"Behind by {behind:.1f} kg", "kg": round(behind, 1)}
    return {"code": "ahead", "text": f"Ahead by {-behind:.1f} kg", "kg": round(behind, 1)}


# ----------------------------------------------------------------- targets

def bmr(sex, weight_kg, height_cm, age):
    """Mifflin-St Jeor."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + (5 if sex == "m" else -161)


def profile_complete(settings):
    return all(settings.get(k) not in (None, "") for k in
               ("sex", "birth_date", "height_cm", "target_weight_kg", "target_date"))


def targets(settings, weight, d, exercise_kcal=0.0, eaten_kcal=0.0):
    """Everything the Today page shows about calories and macros.

    weight is the trend weight for the day. Returns a dict; when the profile
    is incomplete only complete=False is meaningful.
    """
    out = {"complete": False}
    if not profile_complete(settings) or weight is None:
        return out
    s = dict(DEFAULTS)
    s.update({k: v for k, v in settings.items() if v is not None})
    sex = "f" if str(s["sex"]).lower().startswith("f") else "m"
    age = age_on(s["birth_date"], d)
    b = bmr(sex, float(weight), float(s["height_cm"]), age)
    base = b * float(s["neat_factor"])

    target = float(s["target_weight_kg"])
    target_date = to_date(s["target_date"])
    days = (target_date - d).days
    gap = float(weight) - target
    cap = float(s["deficit_cap"])
    surplus_cap = float(s["surplus_cap"])
    deficit = 0.0
    mode = "maintaining"
    capped = False
    eta = None
    if abs(gap) >= 0.3:
        needed = math.inf if days < 1 else abs(gap) * KCAL_PER_KG / max(days, 1)
        if gap > 0:
            mode = "losing"
            deficit = min(needed, cap)
            capped = needed > cap
            if capped:
                eta = d + timedelta(days=math.ceil(gap * KCAL_PER_KG / cap))
        else:
            mode = "gaining"
            deficit = -min(needed, surplus_cap)
            capped = needed > surplus_cap
            if capped:
                eta = d + timedelta(days=math.ceil(-gap * KCAL_PER_KG / surplus_cap))

    floor = s.get("kcal_floor") or (1500 if sex == "m" else 1200)
    raw_budget = base - deficit + float(exercise_kcal or 0)
    budget = max(raw_budget, float(floor))
    floored = raw_budget < float(floor)

    protein = float(s["protein_g_per_kg"]) * float(weight)
    fat = float(s["fat_g_per_kg"]) * float(weight)
    carbs = (budget - 4 * protein - 9 * fat) / 4
    carb_floor = float(s["carb_floor_g"])
    if carbs < carb_floor:
        carbs = carb_floor
        fat = max(float(s["fat_floor_g_per_kg"]) * float(weight), (budget - 4 * protein - 4 * carb_floor) / 9)

    out.update({
        "complete": True,
        "sex": sex,
        "age": age,
        "weight": round(float(weight), 1),
        "bmr": round(b, 1),
        "base": round(base, 1),
        "mode": mode,
        "deficit": round(deficit, 1),
        "capped": capped,
        "eta": eta.isoformat() if eta else None,
        "target_passed": days < 0,
        "days_left": days,
        "exercise": round(float(exercise_kcal or 0), 1),
        "budget": round(budget, 1),
        "left": round(budget - float(eaten_kcal or 0), 1),
        "eaten": round(float(eaten_kcal or 0), 1),
        "floored": floored,
        "floor": float(floor),
        "protein": round(protein, 1),
        "fat": round(fat, 1),
        "carbs": round(carbs, 1),
        "weekly_pace": weekly_pace(s),
    })
    return out


# ----------------------------------------------------------------- food search

_token_re = re.compile(r"[^a-z0-9]+")


def tokens(text):
    return [t for t in _token_re.split(str(text or "").lower()) if t]


SOURCE_RANK = {"custom": 0, "nz": 0, "in": 0, "off": 1, "usda": 2}


def rank_foods(query, foods, limit=30):
    """Order foods for a search box.

    foods are dicts with name, brand, source, times_used, last_used and
    optionally search (extra text). Every query token must prefix-match a
    token of the food (AND); when nothing matches, fall back to OR scoring.
    Ties break on exact matches, then a start-of-name bonus, then how often
    the food has been logged, then source (NZ and custom above USDA), then a
    shorter name. A one-character query returns recently used foods.
    """
    q = tokens(query)
    if len(str(query or "").strip()) < 2 or not q:
        recent = [f for f in foods if f.get("last_used")]
        recent.sort(key=lambda f: (str(f.get("last_used") or ""), f.get("times_used") or 0), reverse=True)
        return recent[:20]

    def food_tokens(f):
        cached = f.get("_tokens")
        if cached is None:
            cached = tokens(" ".join([str(f.get("name") or ""), str(f.get("brand") or ""), str(f.get("search") or "")]))
            f["_tokens"] = cached
        return cached

    def score(f):
        ft = food_tokens(f)
        matched = 0
        exact = 0
        for t in q:
            if any(x.startswith(t) for x in ft):
                matched += 1
            if t in ft:
                exact += 1
        return matched, exact, ft

    scored = []
    for f in foods:
        matched, exact, ft = score(f)
        if matched == len(q):
            scored.append((f, matched, exact, ft))
    if not scored:
        for f in foods:
            matched, exact, ft = score(f)
            if matched:
                scored.append((f, matched, exact, ft))

    def key(item):
        f, matched, exact, ft = item
        starts = 1 if ft and ft[0].startswith(q[0]) else 0
        return (-matched, -exact, SOURCE_RANK.get(f.get("source"), 3), -starts,
                -(f.get("times_used") or 0), len(str(f.get("name") or "")))

    scored.sort(key=key)
    return [f for f, *_ in scored[:limit]]


# ----------------------------------------------------------------- Open Food Facts

class OffError(Exception):
    """Something went wrong talking to Open Food Facts. The message is user-facing."""


class OffRateLimited(OffError):
    pass


class OffBusy(OffError):
    """Open Food Facts answered with a 5xx. Their classic search does this often."""


OFF_FIELDS = "code,product_name,product_name_en,brands,quantity,serving_size,nutriments,countries_tags"
OFF_SEARCH = "https://search.openfoodfacts.org/search"          # the newer, faster search service
OFF_LEGACY = "https://world.openfoodfacts.org/cgi/search.pl"     # the classic one, often overloaded
OFF_PRODUCT = "https://world.openfoodfacts.org/api/v2/product/"
BUSY_MESSAGE = "Open Food Facts is busy right now. Try again in a minute, or add the food yourself with New food."
_off_cache = {}      # url -> (expires_at, payload)
OFF_CACHE_SECONDS = 20
OFF_TIMEOUT = 8


def _user_agent(contact):
    contact = (contact or "personal use").strip()
    return f"FitnessTracker/1.0 ({contact})"


def _off_get(url, contact, opener=None, retry_busy=False):
    """GET with a short cache so a double tap never costs a second request.

    A 5xx raises OffBusy so the caller can try another route; with retry_busy
    it first waits a moment and tries the same URL once more.
    """
    now = time.time()
    hit = _off_cache.get(url)
    if hit and hit[0] > now:
        return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": _user_agent(contact), "Accept": "application/json"})
    try:
        opener = opener or urllib.request.urlopen
        with opener(req, timeout=OFF_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise OffRateLimited("Open Food Facts is rate limiting us. Try again in half a minute.")
        if e.code == 404:
            payload = {"status": 0}
        elif e.code >= 500:
            if retry_busy:
                time.sleep(1.5)
                return _off_get(url, contact, opener, retry_busy=False)
            raise OffBusy(BUSY_MESSAGE)
        else:
            raise OffError(f"Open Food Facts answered {e.code}.")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise OffError("Could not reach Open Food Facts. Check the internet connection.")
    except ValueError:
        raise OffError("Open Food Facts sent something that was not JSON.")
    if len(_off_cache) > 100:
        for k in sorted(_off_cache, key=lambda k: _off_cache[k][0])[:50]:
            _off_cache.pop(k, None)
    _off_cache[url] = (now + OFF_CACHE_SECONDS, payload)
    return payload


def parse_serving(serving_size):
    """'2 biscuits (33 g)' gives 33.0; '30g' gives 30.0; '1 cup' gives None."""
    if not serving_size:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(g|ml)\b", str(serving_size), re.I)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def map_off_product(p):
    """An Open Food Facts product to a food candidate, or None when unusable."""
    if not p or not isinstance(p, dict):
        return None
    n = p.get("nutriments") or {}
    name = (p.get("product_name_en") or p.get("product_name") or "").strip()
    if not name:
        return None
    kcal = _num(n.get("energy-kcal_100g"))
    approx = 0
    protein = _num(n.get("proteins_100g")) or 0.0
    carb = _num(n.get("carbohydrates_100g")) or 0.0
    fat = _num(n.get("fat_100g")) or 0.0
    if kcal is None:
        kj = _num(n.get("energy_100g")) or _num(n.get("energy-kj_100g"))
        if kj is not None:
            kcal = kj / KJ_PER_KCAL
        elif any(k in n for k in ("proteins_100g", "carbohydrates_100g", "fat_100g")):
            kcal = 4 * protein + 4 * carb + 9 * fat
            approx = 1
        else:
            return None
    brands = p.get("brands") or ""
    if isinstance(brands, list):
        brand = (str(brands[0]).strip() if brands else "") or None
    else:
        brand = str(brands).split(",")[0].strip() or None
    serving = p.get("serving_size")
    grams = parse_serving(serving)
    portions = [[f"1 serving ({str(serving).strip()})", grams]] if grams else []
    unit = "ml" if re.search(r"\bml\b|\bl\b|litre|liter", str(p.get("quantity") or "") + " " + str(serving or ""), re.I) else "g"
    return {
        "name": name[:120],
        "brand": brand,
        "unit": unit,
        "source": "off",
        "source_id": str(p.get("code") or ""),
        "barcode": str(p.get("code") or "") or None,
        "kcal_100": round(kcal, 1),
        "protein_100": round(protein, 1),
        "carb_100": round(carb, 1),
        "fat_100": round(fat, 1),
        "approx": approx,
        "portions": portions,
        "quantity": p.get("quantity"),
    }


def off_search(query, contact=None, opener=None):
    """Text search.

    The newer search service answers in a second or two and takes a country
    filter, so New Zealand products come first and the world index fills in
    when that is thin. The classic endpoint is only used when the new one is
    down, because it is the one that keeps answering 503.
    """
    terms = str(query or "").strip()
    if not terms:
        return []
    results, seen = [], set()

    def add(products):
        for p in products or []:
            cand = map_off_product(p)
            if cand and cand["source_id"] not in seen:
                seen.add(cand["source_id"])
                results.append(cand)

    nz_query = urllib.parse.quote(terms + ' countries_tags:"en:new-zealand"')
    world_query = urllib.parse.quote(terms)
    try:
        add(_off_get(f"{OFF_SEARCH}?q={nz_query}&page_size=20&fields={OFF_FIELDS}", contact, opener).get("hits"))
        if len(results) < 3:
            add(_off_get(f"{OFF_SEARCH}?q={world_query}&page_size=20&fields={OFF_FIELDS}", contact, opener).get("hits"))
        return results
    except OffBusy:
        pass
    legacy = (f"{OFF_LEGACY}?search_terms={urllib.parse.quote_plus(terms)}&search_simple=1&action=process&json=1"
              f"&page_size=20&sort_by=unique_scans_n&fields={OFF_FIELDS}")
    add(_off_get(legacy, contact, opener, retry_busy=True).get("products"))
    return results


def off_barcode(code, contact=None, opener=None):
    """One product by barcode. A barcode is global, so only the world index is asked."""
    code = re.sub(r"\D", "", str(code or ""))
    if not code:
        raise OffError("That is not a barcode.")
    url = f"{OFF_PRODUCT}{code}.json?fields={OFF_FIELDS}"
    payload = _off_get(url, contact, opener, retry_busy=True)
    if payload.get("status") != 1 or not payload.get("product"):
        return None
    return map_off_product(payload["product"])


# ----------------------------------------------------------------- bundled lists

def iter_usda_foods(path):
    """Rows from data/foods_usda.json as dicts ready to insert."""
    with open(path, encoding="utf-8") as fh:
        blob = json.load(fh)
    fields = blob.get("fields") or ["id", "n", "k", "p", "c", "f", "cat", "por", "s"]
    for row in blob.get("foods", []):
        r = dict(zip(fields, row))
        yield {
            "name": r.get("n"),
            "brand": None,
            "unit": "g",
            "source": "usda",
            "source_id": str(r.get("id")),
            "barcode": None,
            "kcal_100": r.get("k") or 0,
            "protein_100": r.get("p") or 0,
            "carb_100": r.get("c") or 0,
            "fat_100": r.get("f") or 0,
            "approx": 0,
            "search": r.get("s"),
            "portions": [(lab, g) for lab, g in (r.get("por") or []) if lab and g],
        }


def iter_nz_foods(path, source="nz"):
    """Rows from a hand-written CSV (foods_nz.csv, foods_indian.csv) as dicts ready to insert."""
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            portions = []
            for i in (1, 2):
                lab = (r.get(f"portion{i}_label") or "").strip()
                g = _num(r.get(f"portion{i}_grams"))
                if lab and g:
                    portions.append((lab, g))
            yield {
                "name": (r.get("name") or "").strip(),
                "brand": (r.get("brand") or "").strip() or None,
                "unit": (r.get("unit") or "g").strip() or "g",
                "source": source,
                "source_id": (r.get("name") or "").strip().lower(),
                "barcode": (r.get("barcode") or "").strip() or None,
                "kcal_100": _num(r.get("kcal_100")) or 0,
                "protein_100": _num(r.get("protein_100")) or 0,
                "carb_100": _num(r.get("carb_100")) or 0,
                "fat_100": _num(r.get("fat_100")) or 0,
                "approx": 1,
                "search": (r.get("category") or "").replace("_", " "),
                "portions": portions,
            }


def food_log_values(food, grams, qty=1.0):
    """Calories and macros for an amount of a food."""
    g = float(grams) * float(qty or 1)
    factor = g / 100.0
    return {
        "grams": round(g, 1),
        "kcal": round(float(food["kcal_100"]) * factor, 2),
        "protein": round(float(food["protein_100"]) * factor, 2),
        "carb": round(float(food["carb_100"]) * factor, 2),
        "fat": round(float(food["fat_100"]) * factor, 2),
    }
