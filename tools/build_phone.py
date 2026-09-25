"""Assemble the phone edition.

Merges the three food lists into phone\\data\\foods.json, copies the exercise
library, the programme template and the icons into phone\\, stamps the service
worker with a version made from the app files, and writes phone\\version.json.
The phone\\ folder is then a complete static app: publish it with GitHub Pages,
serve it from any web server, or let the Android build copy it into the
package as assets.

Run from the project folder:  python tools\\build_phone.py
"""

import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PHONE = os.path.join(ROOT, "phone")
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, ROOT)
import nutrition  # noqa: E402

FIELDS = ["id", "name", "brand", "unit", "source", "kcal_100", "protein_100", "carb_100", "fat_100", "approx", "times_used", "last_used", "portions", "search", "barcode"]


def food_rows():
    rows = []
    for r in nutrition.iter_usda_foods(os.path.join(DATA, "foods_usda.json")):
        rows.append(["u:" + r["source_id"], r["name"], None, "g", "usda", r["kcal_100"], r["protein_100"], r["carb_100"], r["fat_100"], 0, 0, None,
                     [[lab, g] for lab, g in r["portions"]], r.get("search"), None])
    for source, name in (("nz", "foods_nz.csv"), ("in", "foods_indian.csv")):
        path = os.path.join(DATA, name)
        if not os.path.exists(path):
            continue
        for i, r in enumerate(nutrition.iter_nz_foods(path, source)):
            rows.append([f"{source}:{i}", r["name"], r["brand"], r["unit"], source, r["kcal_100"], r["protein_100"], r["carb_100"], r["fat_100"], 1, 0, None,
                         [[lab, g] for lab, g in r["portions"]], r.get("search"), r.get("barcode")])
    rows.sort(key=lambda r: (str(r[1]).casefold(), r[0]))
    return rows


def sha(paths):
    h = hashlib.sha1()
    for p in paths:
        with open(p, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:12]


def main():
    os.makedirs(os.path.join(PHONE, "data"), exist_ok=True)
    rows = food_rows()
    with open(os.path.join(PHONE, "data", "foods.json"), "w", encoding="utf-8") as fh:
        json.dump({"fields": FIELDS, "foods": rows}, fh, ensure_ascii=False, separators=(",", ":"))
    for name in ("exercises.json", "programme.json"):
        shutil.copy(os.path.join(DATA, name), os.path.join(PHONE, "data", name))
    for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png"):
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(PHONE, name))
    app_files = ["index.html", "app.js", "engine.js", "store.js", "local-api.js", "sw.src.js", "manifest.webmanifest",
                 os.path.join("data", "exercises.json"), os.path.join("data", "programme.json"), os.path.join("data", "foods.json")]
    version = sha([os.path.join(PHONE, f) for f in app_files if os.path.exists(os.path.join(PHONE, f))])
    with open(os.path.join(PHONE, "sw.src.js"), encoding="utf-8") as fh:
        sw = fh.read().replace("__BUILD__", version)
    with open(os.path.join(PHONE, "sw.js"), "w", encoding="utf-8") as fh:
        fh.write(sw)
    with open(os.path.join(PHONE, "version.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": version}, fh)
    print(f"phone edition built: {len(rows)} foods, version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
