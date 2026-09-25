"""Build the compact USDA food list for the fitness tracker.

What it does
------------
Downloads the USDA FoodData Central "SR Legacy" CSV zip (about 6 MB), reads
the CSVs straight out of the zip and writes a compact JSON food list to
data\\foods_usda.json. Nothing is extracted into the project folder. The zip
is kept in a scratch folder so a second run does not download it again.

For every food we keep:
  - the fdc_id, so a row can be traced back to USDA
  - a shortened display name (filler such as ", broilers or fryers" removed)
  - the original description when it differs, so search still sees it
  - kcal, protein, carbohydrate and fat per 100 g
  - the USDA food category id
  - up to four household portions with their gram weights

Baby foods, infant formula, American Indian/Alaska Native foods and
restaurant rows are dropped. Foods with no energy value are dropped.

How to run
----------
From the project folder:

    python tools\\build_food_db.py

To reuse a zip you already have instead of downloading:

    python tools\\build_food_db.py --zip C:\\path\\to\\FoodData_Central_sr_legacy_food_csv_2018-04.zip

Standard library only. Python 3.12.

Output shape
------------
{"v": 1, "src": "usda_sr_legacy_2018-04",
 "fields": ["id", "n", "k", "p", "c", "f", "cat", "por", "s"],
 "foods": [[fdc_id, name, kcal, protein, carb, fat, category_id,
            [[portion_label, grams], ...], original_description_or_null], ...]}
"""

import csv
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

# Where things live.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(PROJECT_DIR, "data", "foods_usda.json")
SCRATCH_DIR = (
    r"C:\Users\shahr\AppData\Local\Temp\claude\C--Personal-fitness-tracker"
    r"\8fb1c3dd-5348-4fc6-8f50-a1f8c0b31f74\scratchpad"
)
ZIP_NAME = "FoodData_Central_sr_legacy_food_csv_2018-04.zip"
ZIP_URL = "https://fdc.nal.usda.gov/fdc-datasets/" + ZIP_NAME
DOWNLOAD_PAGE = "https://fdc.nal.usda.gov/download-datasets/"
USER_AGENT = "FitnessTracker/1.0 (personal use; build_food_db.py)"

SOURCE_TAG = "usda_sr_legacy_2018-04"

# Nutrient ids in food_nutrient.csv.
NUTRIENT_KCAL = "1008"
NUTRIENT_KJ = "1062"
NUTRIENT_PROTEIN = "1003"
NUTRIENT_CARB = "1005"
NUTRIENT_FAT = "1004"
WANTED_NUTRIENTS = {NUTRIENT_KCAL, NUTRIENT_KJ, NUTRIENT_PROTEIN, NUTRIENT_CARB, NUTRIENT_FAT}

# Categories to drop, matched by name in food_category.csv. The ids differ
# between USDA releases (24 in the 2018-04 zip, 35 elsewhere), so we look
# them up by name and fall back to the known ids if the names are not found.
DROP_CATEGORY_NAMES = {"Baby Foods", "American Indian/Alaska Native Foods"}
DROP_CATEGORY_IDS_FALLBACK = {"3", "24", "35"}

# Description filters. Prefixes are case-sensitive, the substring is not.
DROP_PREFIXES = ("Babyfood", "Infant formula")
DROP_SUBSTRING = "restaurant"

# Filler fragments removed from the display name, in this order.
# Each includes its leading comma and space. Case-sensitive.
NAME_FRAGMENTS = [
    ", broilers or fryers",
    ', trimmed to 0" fat',
    ', trimmed to 1/8" fat',
    ", all grades",
    ", choice",
    ", select",
    ", NFS",
    ", USDA Commodity",
    ", composite of trimmed retail cuts",
    ", year round average",
    ", without salt",
    ", unprepared",
]

UNDETERMINED_UNIT = "9999"
MAX_PORTIONS = 4

# Set by load_zip(). read_table() streams members from it.
ZIP = None


def download(dest_path):
    """Fetch the SR Legacy zip into dest_path unless it is already there.

    Tries the fixed dataset URL first. If that fails, scrapes the FoodData
    Central download page for the current SR Legacy CSV link. Returns the
    URL that worked, or None when the file was already present.
    """
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        print(f"Reusing zip already in scratch: {dest_path}")
        return None

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    candidates = [ZIP_URL]
    last_error = None
    for url in candidates:
        try:
            print(f"Downloading {url}")
            _fetch_to_file(url, dest_path)
            return url
        except Exception as exc:  # noqa: BLE001 - we want to try the fallback
            last_error = exc
            print(f"  failed: {exc}")

    # Fallback: find the current SR Legacy CSV link on the download page.
    print(f"Looking for the current SR Legacy CSV link on {DOWNLOAD_PAGE}")
    try:
        page = _fetch_text(DOWNLOAD_PAGE)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Could not download the zip ({last_error}) or the download page ({exc})"
        ) from exc

    links = re.findall(r'href="([^"]*sr_legacy[^"]*csv[^"]*\.zip)"', page, flags=re.I)
    if not links:
        raise RuntimeError(
            f"Could not download the zip ({last_error}) and found no SR Legacy CSV link on the download page"
        )
    for link in links:
        url = link if link.startswith("http") else "https://fdc.nal.usda.gov" + link
        try:
            print(f"Downloading {url}")
            _fetch_to_file(url, dest_path)
            return url
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"  failed: {exc}")
    raise RuntimeError(f"Every download attempt failed. Last error: {last_error}")


def _fetch_to_file(url, dest_path):
    """Stream a URL to disk. Writes to a temp name first so a half download is never mistaken for a good file."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp_path = dest_path + ".part"
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_path, "wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
    os.replace(tmp_path, dest_path)
    print(f"  saved {os.path.getsize(dest_path):,} bytes")


def _fetch_text(url):
    """Fetch a URL and return its body as text."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_zip(zip_path):
    """Open the zip and remember it for read_table(). Checks the files we need are inside."""
    global ZIP
    ZIP = zipfile.ZipFile(zip_path)
    needed = ["food.csv", "food_nutrient.csv", "food_portion.csv", "measure_unit.csv"]
    missing = [name for name in needed if _find_member(name) is None]
    if missing:
        raise RuntimeError(f"Zip is missing {missing}. Is this the SR Legacy CSV zip?")
    return ZIP


def _find_member(name):
    """Find a member by base name. Members may sit inside a folder in the zip."""
    for member in ZIP.namelist():
        if member == name or member.endswith("/" + name):
            return member
    return None


def read_table(name):
    """Stream one CSV from the zip as dicts, one row at a time.

    Streaming matters for food_nutrient.csv, which is about 36 MB.
    """
    member = _find_member(name)
    if member is None:
        raise RuntimeError(f"{name} not found in zip")
    with ZIP.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        for row in csv.DictReader(text):
            yield row


def fmt_amount(value):
    """Format a portion amount: 1.0 -> "1", 0.5 -> "0.5", 2.0 -> "2"."""
    if value == int(value):
        return str(int(value))
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text


def fmt_grams(value):
    """Round grams to one decimal, or to a whole number when whole."""
    rounded = round(value, 1)
    if rounded == int(rounded):
        return int(rounded)
    return rounded


def portion_label(amount, unit_name, portion_description, modifier):
    """Build the portion label from the parts that are present.

    Examples: (1, None, "", "cup, chopped or diced") -> "1 cup, chopped or diced"
              (2, "tbsp", "", "") -> "2 tbsp"
    """
    parts = [fmt_amount(amount), unit_name or "", portion_description or "", modifier or ""]
    label = " ".join(part.strip() for part in parts if part and part.strip())
    return re.sub(r"\s{2,}", " ", label).strip()


def shorten_name(description):
    """Remove filler fragments to make a shorter display name.

    Collapses ", ," left behind and strips trailing commas. Returns the
    description unchanged when no fragment matches.
    """
    name = description
    for fragment in NAME_FRAGMENTS:
        name = name.replace(fragment, "")
    # Tidy anything the removals left behind.
    name = re.sub(r",(\s*,)+", ",", name)
    name = re.sub(r"\s{2,}", " ", name)
    name = name.strip().rstrip(",").strip()
    return name or description


def to_float(text):
    """Parse a CSV number, returning None when it is blank or not a number."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def build():
    """Read the tables and return (payload, stats)."""
    stats = {
        "foods_total": 0,
        "kept": 0,
        "dropped_category": 0,
        "dropped_description": 0,
        "dropped_no_energy": 0,
        "portions_total": 0,
        "portions_skipped_zero_weight": 0,
    }

    # Categories to drop, found by name with a fallback to known ids.
    drop_categories = set()
    try:
        for row in read_table("food_category.csv"):
            if row.get("description", "").strip() in DROP_CATEGORY_NAMES:
                drop_categories.add(row["id"].strip())
    except RuntimeError:
        pass
    if len(drop_categories) < len(DROP_CATEGORY_NAMES):
        drop_categories |= DROP_CATEGORY_IDS_FALLBACK
    print(f"Dropping category ids: {sorted(drop_categories, key=int)}")

    # Pass 1: foods, filtered by category and description.
    foods = {}
    for row in read_table("food.csv"):
        stats["foods_total"] += 1
        fdc_id = row["fdc_id"].strip()
        # A few USDA descriptions carry double spaces. Collapse them here so
        # the stored original and the display name differ only when a
        # fragment was really removed.
        description = " ".join(row["description"].split())
        category = row.get("food_category_id", "").strip()

        if category in drop_categories:
            stats["dropped_category"] += 1
            continue
        if description.startswith(DROP_PREFIXES) or DROP_SUBSTRING in description.lower():
            stats["dropped_description"] += 1
            continue
        foods[fdc_id] = {"description": description, "category": category}

    # Pass 2: nutrients, streamed. Only the five ids we care about are kept.
    nutrients = {}
    for row in read_table("food_nutrient.csv"):
        nutrient_id = row["nutrient_id"].strip()
        if nutrient_id not in WANTED_NUTRIENTS:
            continue
        fdc_id = row["fdc_id"].strip()
        if fdc_id not in foods:
            continue
        amount = to_float(row["amount"])
        if amount is None:
            continue
        nutrients.setdefault(fdc_id, {})[nutrient_id] = amount

    # Pass 3: measure units, then portions.
    units = {}
    for row in read_table("measure_unit.csv"):
        units[row["id"].strip()] = row["name"].strip()

    portions = {}
    for row in read_table("food_portion.csv"):
        fdc_id = row["fdc_id"].strip()
        if fdc_id not in foods:
            continue
        grams = to_float(row["gram_weight"])
        if grams is None or grams <= 0:
            stats["portions_skipped_zero_weight"] += 1
            continue
        amount = to_float(row["amount"])
        if amount is None or amount <= 0:
            # A portion of "0 cups" is not usable.
            stats["portions_skipped_zero_weight"] += 1
            continue
        unit_id = row["measure_unit_id"].strip()
        unit_name = units.get(unit_id, "") if unit_id != UNDETERMINED_UNIT else ""
        label = portion_label(amount, unit_name, row.get("portion_description", ""), row.get("modifier", ""))
        if not label:
            continue
        seq = to_float(row.get("seq_num")) or 0
        portions.setdefault(fdc_id, []).append((seq, label, grams))

    # Assemble the rows.
    rows = []
    for fdc_id, food in foods.items():
        nut = nutrients.get(fdc_id, {})
        kcal = nut.get(NUTRIENT_KCAL)
        if kcal is None and nut.get(NUTRIENT_KJ) is not None:
            kcal = nut[NUTRIENT_KJ] / 4.184
        if kcal is None:
            stats["dropped_no_energy"] += 1
            continue

        protein = round(nut.get(NUTRIENT_PROTEIN, 0.0), 1)
        carb = round(nut.get(NUTRIENT_CARB, 0.0), 1)
        fat = round(nut.get(NUTRIENT_FAT, 0.0), 1)

        # Portions: by seq_num, deduplicated by label, at most four.
        por = []
        seen_labels = set()
        for _seq, label, grams in sorted(portions.get(fdc_id, []), key=lambda p: p[0]):
            if label in seen_labels:
                continue
            seen_labels.add(label)
            por.append([label, fmt_grams(grams)])
            if len(por) >= MAX_PORTIONS:
                break
        stats["portions_total"] += len(por)

        description = food["description"]
        name = shorten_name(description)
        original = description if description != name else None
        category = int(food["category"]) if food["category"].isdigit() else None

        rows.append([int(fdc_id), name, int(round(kcal)), protein, carb, fat, category, por, original])
        stats["kept"] += 1

    # Sort by display name. Case-folded so "McDONALD'S" sits with the other Ms.
    rows.sort(key=lambda r: (r[1].casefold(), r[0]))

    payload = {
        "v": 1,
        "src": SOURCE_TAG,
        "fields": ["id", "n", "k", "p", "c", "f", "cat", "por", "s"],
        "foods": rows,
    }
    return payload, stats


def parse_args(argv):
    """Tiny argument parser: --zip PATH and --help."""
    zip_path = None
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif arg == "--zip":
            if not args:
                sys.exit("--zip needs a path")
            zip_path = args.pop(0)
        elif arg.startswith("--zip="):
            zip_path = arg.split("=", 1)[1]
        else:
            sys.exit(f"Unknown argument: {arg}. Use --zip PATH or --help.")
    return zip_path


def main(argv=None):
    zip_path = parse_args(sys.argv[1:] if argv is None else argv)

    if zip_path:
        if not os.path.exists(zip_path):
            sys.exit(f"Zip not found: {zip_path}")
        print(f"Using zip: {zip_path}")
    else:
        zip_path = os.path.join(SCRATCH_DIR, ZIP_NAME)
        used_url = download(zip_path)
        if used_url:
            print(f"Downloaded from: {used_url}")

    load_zip(zip_path)
    payload, stats = build()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out:
        json.dump(payload, out, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUTPUT_PATH)

    print()
    print(f"Foods in source:        {stats['foods_total']:,}")
    print(f"Foods kept:             {stats['kept']:,}")
    print(f"Dropped, category:      {stats['dropped_category']:,}")
    print(f"Dropped, description:   {stats['dropped_description']:,}")
    print(f"Dropped, no energy:     {stats['dropped_no_energy']:,}")
    print(f"Portions total:         {stats['portions_total']:,}")
    print(f"Portions skipped (zero weight or amount): {stats['portions_skipped_zero_weight']:,}")
    print(f"Output:                 {OUTPUT_PATH}")
    print(f"Output size:            {size:,} bytes ({size / 1024 / 1024:.2f} MB)")
    print()
    print("Sample rows:")
    for row in payload["foods"][:3]:
        print("  " + json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
