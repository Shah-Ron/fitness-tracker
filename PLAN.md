# Fitness Tracker: implementation plan

## Phase 2, decided 26 September 2026: the phone holds the data

The user chose a phone-only app: no laptop server, no sync, no certificates. The brains move into the page.

**Shape.** A static progressive web app in `phone\`, published through GitHub Pages (the user's choice for the one-off install) and installable with Add to Home screen. Everything runs on the phone and all data stays on the phone in IndexedDB. The same page opened on the laptop keeps its own separate data; a JSON backup moves data between devices.

```
phone\
  index.html        styles and skeleton (from app.html), scripts loaded from files
  app.js            the screens (from app.html), calling a local dispatcher instead of a server
  engine.js         programme, effort and nutrition maths ported from the Python modules, same rules and thresholds
  local-api.js      the same routes the Python server had (/api/state, /api/today, /api/sync ...) implemented on the store
  store.js          IndexedDB persistence, in-memory model, ids, backup and restore
  sw.js             precache of every file, cache-first, version stamp
  manifest.webmanifest, icon-192.png, icon-512.png, icon-maskable-512.png
  data\exercises.json, data\programme.json, data\foods.json (USDA + NZ + Indian merged)
tools\build_phone.py  merges the food lists, copies icons and data, stamps sw.js, writes docs\ for GitHub Pages
```

**What changes for the user.** Open Food Facts lookups go straight from the phone (their API allows it). Backups are a file the app exports (share sheet on the phone) and imports. The laptop app in `fitness_tracker.py` stays as it was for anyone who wants it, but it is no longer the plan for this user.

**What stays.** Every rule in the Engines section, the data model (as collections instead of tables, hard deletes instead of soft), the screens, the seed content and the unit-test expectations, which become a Node test file for `engine.js`.

**Also added on 26 September 2026.** An Android package (`android\`, a WebView shell with camera, Downloads and a native Open Food Facts call) built and signed by `.github\workflows\android.yml` and attached to GitHub Releases, so the phone installs it from the Releases page; four training splits in `data\programme.json` (`splits`) chosen in Settings; 130 Kerala and Indian dishes in `data\foods_indian.csv`; online food search moved to Open Food Facts' newer service with the classic endpoint as fallback.

**Verified.** Browser self-test of the on-device engine (51 checks, `tools\selftest.html`), every screen rendered headlessly with data, Python suite green, web app live at https://shah-ron.github.io/fitness-tracker/, release v1.3 with a signed APK. Not yet verified on a physical phone: installing the APK, camera barcode scanning inside the WebView, and the Downloads-folder backup.

## Status, 24 September 2026

Built and smoke-tested from this plan in one session. Everything below was implemented with these deliberate differences:

- The pairing link in Settings > Phone is shown as text with a Copy button rather than a QR code, to keep the page free of a large embedded encoder. Typing the link once on the phone is a one-off.
- The page supports hash deep links (`/#plan`, `/#food` and so on), added so each tab could be rendered headlessly during testing.
- `GET /api/food/day?date=` was added so the Food tab can show and edit past days.
- The finance tracker was not consulted; the design language is the app's own.

Verified: API smoke test (plan generation, workout start with frozen targets, set logging through sync, idempotent replays, effort and calories, next-week progression, food logging, meals, body and daily logs, progress, history, exports, backups, shuffle and swap), TLS 1.3 handshake on the phone listener, every tab rendered in headless Edge with no console errors, PyInstaller build and a run of the .exe including the second-launch guard and Stop. Not yet verified on the phone itself: CA install, Add to Home screen, aeroplane-mode logging and the sync on return.

## Context

The author already had a personal money tracker built the same way: a Python standard-library server, one self-contained `app.html`, a SQLite file, packaged as a Windows .exe with PyInstaller, fully local. This is a sibling app in the same spirit, for training and nutrition:

- log every set (weight, reps, RPE) and see strength improve week over week
- estimate effort and calories burned per session, and accept wearable figures
- log food by name with calories and macros looked up automatically
- set a target weight and date and be paced towards it
- get a weekly workout plan that rotates so it does not get boring
- log sets on an Android phone at the gym, syncing to the laptop at home

## Decisions taken with the user (24 September 2026)

| Area | Decision |
|---|---|
| Goal | Recomposition: lose fat and gain strength. Slight deficit, high protein |
| Target | Target weight and target date entered in Settings; app derives the daily deficit and weekly pace |
| Training | Full gym, 5 to 6 days a week, about 60 min, beginner, app picks the split |
| Cardio | 8 to 12 min finisher after each lifting day plus one dedicated conditioning day. Treadmill, bike, rower |
| Effort | Volume and estimated 1RM, RPE per set, MET-based calorie estimate, wearable calories/HR typed in |
| Food lookup | Bundled offline food list first, Open Food Facts online fallback, accepted results saved locally |
| Nutrients | Calories, protein, carbs, fat |
| Food entry | Servings (1 cup, 1 slice, 1 egg), grams/ml, saved meals, barcode (typed or camera on Android) |
| Food targets | Daily calorie and protein target with a live "left today" counter. No meal suggestions |
| Extras | Body weight, body measurements, water, sleep hours and steps |
| Workout screen | Last time's numbers to beat, rest timer, form cues, warm-up and cool-down |
| Stack | Same as finance tracker plus reachable from the phone on home wifi |
| Phone link | Self-signed HTTPS on the LAN with a one-off CA install on the phone, so the page installs as an app, works offline at the gym and syncs at home |
| Phone | Android (Chrome): camera barcode scanning and home-screen install both work |
| Units | Metric (kg, cm, km). Personal stats (age, sex, height, weight) are entered in Settings on first run, not in this plan |

## Environment checked on this laptop

- Python 3.12.0, OpenSSL 3.0.11 in the `ssl` module (`ssl._ssl._test_decode_cert` present), SQLite 3.42 (UPSERT with `excluded` and `WHERE`, `RETURNING`, `VACUUM INTO` all available)
- PyInstaller 6.22.3 and Pillow 11 installed. `cryptography` not installed (the cert tool will pip install it on demand, same pattern as PyInstaller in `build_exe.bat`). It must never be imported by the server
- The laptop's hostname and wifi address are read at runtime; both `socket.getaddrinfo(gethostname())` and the UDP-connect trick return the address
- Open Food Facts read API: `GET /api/v2/product/{barcode}.json`, text search `GET /cgi/search.pl?search_terms=...&json=1`, limits 15 product reads and 10 searches per minute per IP, custom User-Agent required. So online search is a button, never search-as-you-type
- USDA FoodData Central SR Legacy CSV: `https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip`, 6.7 MB, public data, no key. About 7,800 generic foods with household portions

## Reuse map: what comes across from the finance tracker

Source: the earlier money tracker (not part of this repository). Line numbers refer to its files.

**Server patterns copied as they are**
- Path block and `html_path()` (34-38, 54-56): `FROZEN`, `HERE` beside the exe, `BUNDLE` from `_MEIPASS`, a local `app.html` wins over the packed copy. Generalised into `static_path(name)` for `sw.js`, the manifest, icons and `data\*`.
- `already_running()` (1226-1255): reads the `.port` file, probes `/api/ping` and checks `{"app": APP_ID}` before trusting a busy port; second click opens the browser and exits. New `APP_ID = "fitness-tracker"`.
- Port walk-up `for ... else` loop (1284-1293), delayed `webbrowser.open` (1306), `log()` that prints when a console exists and appends to the log file when frozen (59-71), `alert()` Win32 message box when frozen (1258-1267), top-level crash guard (1341-1348).
- `Handler` shape (1076-1220): `_send()` as the only place headers are set with `Cache-Control: no-store` and `nosniff`, `_json()`, `_body()` reading exactly `Content-Length`, `_id_from()`, `BadRequest` to 400 and the two-clause `except` tail, `log_message` silenced, `urlparse(self.path).path` before matching.
- Database: `connect()` with `row_factory = sqlite3.Row` and foreign keys on (246-250), one connection per request, `SCHEMA` as one `executescript` string (153-237), `ensure_column()` for additive migrations (253-257), settings-flag guard for one-shot data migrations (306-317), JSON-encoded `get_settings` / `set_setting` (327-341), seed only when `COUNT(*) == 0`, upserts with `ON CONFLICT(name)`, soft delete returning `{"ok": True, "hidden": ...}` (971, 1026).
- `parse_date()` (346-355) and the shape of `money()` (741-750) as `number(v, name, lo, hi)` for weights, reps, grams and RPE.
- One fat `GET /api/state` with the page re-fetching after each write (411). Kept for the laptop; the phone adds the offline queue on top.
- Watchdog thread plus 20-second page ping (1311-1325, app.html 1978), retimed as described under Idle behaviour.
- `tools\build_exe.bat` in full (self-installs PyInstaller, `--distpath .`, build junk in `%TEMP%`), and `tools\make_icon.py`'s pure-stdlib .ico writer (`frame`, `bmp_entry`, `ICONDIR` packing) with a new drawing and one colour constant.
- `Start Finance Tracker.bat` with the names changed.

**Server things fixed rather than inherited** (flagged by the exploration)
- `PRAGMA journal_mode=WAL`, `synchronous=NORMAL` and `sqlite3.connect(DB_PATH, timeout=5)`: two listeners and threads will write concurrently.
- Progress aggregates in SQL, not Python loops over every row (`build_state()` is O(accounts x entries) at 507-513).
- Validate fully before any insert; `s.get(key, default)` for settings rather than bare indexing.
- Guard the bare `print()` calls in `init_db` the way `log()` does.

**Page pieces copied verbatim** (app.html)
- Token block and both dark overrides (17-70), base, buttons, inputs, `[hidden]`, shared `:focus-visible` (73-124).
- `.tile` nav CSS (159-169) with `switchTab()` (1897-1904) and the delegated `[data-go]` handler (1905-1909).
- `.card`, `.grid` `.g2-.g4`, `.stat`, `.pill`, `.meter`, `.callout`, `.empty`, table rules (172-210).
- Morph form shell CSS (259-280) and the `setKind` + `data-for` mode mechanism (1204-1216); `.kinds`/`.kind` segmented control and `.chips`/`.chip` (282-305).
- `.tooltip` with `showTip`/`hideTip` (402-413, 866-877); `.toast` with `toast(msg, undo)` (416-422, 848-864) and the delete pattern in `wireLedger` (`.leaving`, 260 ms, request, undo closure that posts the inverse, 1134-1151).
- Theme switch CSS, markup, `applyTheme` and its init (147-156, 469-474, 1963-1975).
- Entrance animations with the `--i` stagger and the reduced-motion block (440-456).
- `api` / `load` / `pushSettings` (819-845), the boot error card (1980-1984), `esc`, the date helpers `D`, `isoOf`, `addDays`, `fmtLong`, `fmtShort`, `fmtDay` (779-784), `plural` (792).
- SVG chart scaffolding from `drawHistory` (1668-1695): margins object, `X`/`Y` closures, 5-step gridline and tick loop, transparent full-height hit rect per slot, dashed reference line. The `drawDebt` crosshair (1787-1796) for the weight-trend and e1RM line charts. The `.days` CSS bar strip (225-241) becomes a 7-column week strip.

**Page pieces dropped**: everything about people, shares, splits, accounts, envelope categories, payday, loans, INR and the fortnight period helpers.

**Page changes for the phone** (from the exploration's audit)
- Control height 44-48 px on the Workout and Food screens; chips about 12 px 18 px; no `button.link` without padding; no `prompt()` dialogs, inline fields instead.
- Fixed bottom bar under 640 px carrying Today, Workout, Food and More, with `env(safe-area-inset-bottom)` padding, and the toast lifted above it.
- Set logging is a full-width bottom sheet on small screens, not the desktop morph; focus the first field immediately, no 320 ms delay.
- Every hover-only detail (tooltips on bars and points) gets a tap-to-pin equivalent or inline numbers.
- One full-width field per row in forms, `inputmode="decimal"` on weights and `inputmode="numeric"` on reps.
- Lists use the `.lg-row` pattern, never the 8-column tables, on narrow screens.

## Project layout

```
C:\Personal\fitness-tracker\
  PLAN.md                     this plan, copied in as step 0
  fitness_tracker.py          entry point: servers, routes, auth, database, sync, TLS
  programme.py                weekly plan generation, rotation, progression, deload
  effort.py                   volume, e1RM, MET calories, effort score, PR detection
  nutrition.py                BMR/targets maths, food search ranking, Open Food Facts proxy
  tests.py                    unittest, standard library only
  app.html                    the page (CSS + HTML + JS, no external assets)
  sw.js                       service worker: offline shell, cached plan and food list, background flush
  manifest.webmanifest        PWA manifest so Android installs it to the home screen
  icon-192.png, icon-512.png, icon-maskable-512.png   written by tools\make_icon.py
  data\exercises.json         ~90 gym exercises: pattern, muscles, equipment, MET, cues
  data\programme.json         split templates, slot pools, rep schemes, cardio protocols
  data\foods_usda.json        compact USDA SR Legacy (generated by tools\build_food_db.py, committed)
  data\foods_nz.csv           ~120 NZ staples with typical values, flagged approximate
  certs\                      generated, never committed or synced: ca.pem, ca-key.pem, ca.crt, server.pem, server-key.pem, server.json
  tools\build_exe.bat         PyInstaller build, installs PyInstaller if missing
  tools\make_icon.py          draws icon.ico plus the PWA PNGs
  tools\make_cert.bat / .py   creates the CA once and a server cert for the current IPs
  tools\build_food_db.py      downloads USDA zip, writes data\foods_usda.json
  tools\add_to_startup.bat    optional: shortcut in the Startup folder so the server is up when the phone syncs
  Start Fitness Tracker.bat   runs the source through Python
  README.md                   same voice and sections as the finance tracker README
  fitness.db (+ -wal, -shm)   runtime, created on first start
  fitness_tracker.log / .port runtime
```

The server is split into four modules rather than one file because the programme and nutrition logic is larger than the finance maths. PyInstaller follows plain imports; no hidden-import flags.

## Server (fitness_tracker.py)

**Constants.** `HOST = "127.0.0.1"`, `HTTP_PORT = 8778`, HTTP fallback ports 8800-8819 (the finance walk-up of `port + 1` would land on the HTTPS port), `LAN_HOST = "0.0.0.0"`, `HTTPS_PORT = 8779` fixed (the phone's installed app and the QR encode it; no fallback), `CERT_DIR = HERE\certs`, a module `STOP = threading.Event()`.

**Two listeners, one handler.** `class AppServer(ThreadingHTTPServer)` with `allow_reuse_address = False` (on Windows `SO_REUSEADDR` lets a second process bind a listening port, so a clash would never raise) and `handle_error()` overridden to log one line instead of a stderr traceback (stderr is `None` under `--noconsole`).
- HTTP on loopback for the laptop. Loopback is a secure context, so the service worker and camera work there without a certificate.
- HTTPS on the LAN: `make_tls_context()` builds `ssl.SSLContext(PROTOCOL_TLS_SERVER)`, `minimum_version = TLSv1_2`, `load_cert_chain(server.pem, server-key.pem)`, kept in a module global so `POST /api/phone/reload-cert` (loopback only) can reload after `make_cert.bat` without a restart. `bind_https()` returns the server or a reason string: certs missing ("Run tools\make_cert.bat, then restart"), key does not match, or port 8779 in use. The reason is stored for `/api/phone` and Settings; the laptop side keeps working.
- Wrap the listening socket with `do_handshake_on_connect=False` and run the handshake in `Handler.setup()` with `self.request.settimeout(10)`. Otherwise a client that connects and sends nothing blocks the accept loop forever. Per-connection `timeout = 30`. Keep HTTP/1.0, one request per connection.
- Quiet, useful errors in `handle_error`: `TLSV1_ALERT_UNKNOWN_CA` / `CERTIFICATE_UNKNOWN` / `BAD_CERTIFICATE` logs "Phone at 192.168.1.50 does not trust the certificate yet. Install /ca.crt on it."; `HTTP_REQUEST` / `WRONG_VERSION_NUMBER` logs "Plain http request on the https port, use https://"; EOF, reset, broken pipe and timeouts are silent unless `--verbose`. `_send()` wraps the write in `try/except (ConnectionResetError, BrokenPipeError)`.

**main()**: `already_running()` (probes the HTTP loopback port only; `/api/ping` returns `{"ok", "app", "https": bool, "build"}`) then open the browser and exit if found; `init_db()`, `ensure_pair_key()`, `BUILD_STAMP = build_stamp()`; bind both; `check_cert()`; write `.port` as JSON `{"http": 8778, "https": 8779}`; start each `serve_forever` in a daemon thread; start the watchdog; delayed browser open; wait with `while not STOP.wait(1.0)` (a bare wait is not interruptible by Ctrl+C on Windows); `finally` shut both servers down, remove `.port`, log "Stopped".

**Dispatch and authorisation.** `do_GET/POST/PUT/DELETE` all call `_dispatch(verb)`: bump `LAST_SEEN`, parse the path, `_authorise()`, route, shared `except BadRequest / Unauthorised / Exception`. `_authorise()`:
- peer `127.0.0.1` or `::1`: allowed.
- public allowlist without a key: `/api/ping`, `/ca.crt`.
- key accepted from `?key=`, cookie `fit_pair`, header `X-Pair-Key`, compared with `hmac.compare_digest`. A valid `?key=` on a navigation answers `302 Location: /` with `Set-Cookie: fit_pair=...; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=34560000`, refreshed on every authenticated navigation (Chrome caps cookies at 400 days). The cookie is required, not optional: the manifest fetch, `sw.js`, the service worker's precache and every navigation are browser-made requests with no custom header, and all of them carry same-origin cookies. `SameSite=Strict` would break the first visit from the camera app.
- missing or wrong: navigations get `PAIR_HTML` (title, one paragraph, a plain `GET /` form with an `<input name="key">`), API calls get `401 {"error": "pair"}`. Both through `_send()`.
- `pair_key` = `secrets.token_urlsafe(9)` stored in settings; Settings > Phone has "New code" to rotate it.

**Routes** (JSON unless noted, all under `/api/`):
- Static via `static_path()` and a `STATIC` map: `/`, `/app.html`, `/sw.js` (with `__BUILD__` replaced by the stamp), `/manifest.webmanifest` (`application/manifest+json`), the three icons, `/ca.crt` (DER via `ssl.PEM_cert_to_DER_cert`, `application/x-x509-ca-cert`, attachment `fitness-tracker-ca.crt`)
- `GET ping`; `GET state` (everything Today needs: profile, targets, today's totals, session, streak, pace, queue-free); `GET/PUT settings`; `GET/PUT profile`
- `GET exercises`, `POST exercises` (custom), `PUT exercises/{id}`
- `GET plan/week?date=`, `POST plan/shuffle {week_id}` (new seed for that week's untouched sessions, later weeks cascade), `POST plan/regenerate` (rebuild planned sessions after a training-settings change, seeds preserved), `POST plan/swap` (409 if the item already has a logged set), `POST plan/move` (do this session today: exchanges dates with today's session, sets `moved_from` on both)
- `GET today`: not one session but `{date, sessions: [seven days from today], last: {exercise_id: last-time sets}, targets}` so a phone whose cache is a day old still finds its day
- `POST sync` (the phone and laptop write path, see Phone section); the legacy direct routes `POST workouts`, `POST sets`, `POST cardio`, `POST food_logs`, `POST body`, `POST daily` are thin wrappers that build a one-op sync batch, so there is exactly one write path
- `GET foods/list` compact array for client-side search (cached by the service worker); `GET foods/online?q=` (nz then world) and `GET foods/barcode/{code}` (world only, a barcode is global) proxies; `POST foods` (upsert on source + source_id); `GET meals`, `POST meals {name, from_date, slot}`; `POST food_logs/meal {meal_id, date, slot}`; `POST food_logs/copy {to_date, slot, from_date?}`
- `GET progress?range=`; `GET history?...`; `GET export.csv?what=sets|food|body`; `GET backup.json`; `GET backup.db` (consistent copy via `VACUUM INTO`); `POST restore`
- `GET phone` (loopback only, 403 otherwise): `{https, reason, lan_ip, url, key, cert: {ips, dns, not_after, covers_lan}, build}`; `POST phone/reload-cert`; `POST phone/new-key`
- `POST stop`: respond `{"ok": true}` then `threading.Timer(0.3, STOP.set)`

**Certificate check at startup.** `cert_info()` tries `ssl._ssl._test_decode_cert(path)` (SAN pairs look like `("IP Address", "192.168.x.x")`, note the space; `notAfter` via `ssl.cert_time_to_seconds`), then falls back to `certs\server.json` written by the cert tool, else skips quietly. `check_cert()` logs: LAN IP not covered ("...covers 192.168.1.42. The phone will refuse to connect. Run tools\make_cert.bat, then press Reload certificate in Settings > Phone"), expired or within 30 days, or "Not on a network yet; skipped the certificate address check".

**Idle behaviour.** Setting `stay_running` default on. The watchdog thread always runs and reads the setting each 5-second tick; when off, stop after 12 hours idle (phone syncs bump `LAST_SEEN` too). Drop the finance "no page within ten minutes" clause because the Startup shortcut runs with `--no-browser`. Keep `--idle N` for tests. The 20-second `/api/ping` heartbeat in the page stays; it bypasses the service worker.

**Database.** `connect()` as finance plus `timeout=5`; `init_db()` sets WAL and `synchronous=NORMAL` once; a module `SEED_LOCK` around the first-run seed loader. Seeds load from `data\*` on first run, keyed by a `seed_version` setting so later seed updates can add rows without touching edits. Ordinary routes need no Python lock. The sync batch and any read-modify-write (`next set_no`, `times_used`) use `BEGIN IMMEDIATE`. Progress queries aggregate in SQL: week bucket `date(d, '-6 days', 'weekday 1')` (the Monday on or before), e1RM `MAX(load * (1 + reps / 30.0)) FILTER (WHERE reps <= 12)`, hard-set counts per exercise per week joined to `exercises.primary_muscle` and `secondary_muscles`, adherence `SUM(status = 'done') / COUNT(*)` per plan week, all with `deleted = 0`. `GET foods/list` is served gzip-compressed when the client accepts it (about 1.2 MB raw, under 300 KB compressed), cached per `seed_version`.

## Data model

```sql
settings      (key, value)   -- profile, goal (target_weight_kg, target_date, goal_start_weight, goal_start_date
                             -- snapshotted when the goal is saved), training (train_days, session_minutes,
                             -- cardio_kit, programme_start), pair_key, seed_version, stay_running, theme
exercises     (id, key UNIQUE, name, pattern, primary_muscle, secondary_muscles, equipment, per_hand, timed,
               unilateral, bodyweight_fraction, increment_kg, min_load_kg, variation_of, carry, mets, cues,
               is_custom, active)
               -- key: slug referenced by programme.json; custom rows get custom_{id}
               -- pattern: squat, hinge, lunge, horizontal_push, vertical_push, horizontal_pull,
               --          vertical_pull, shoulder_iso, triceps, biceps, rear_delt, quad_iso, ham_iso,
               --          glute, calf, core, cardio_treadmill, cardio_bike, cardio_rower, mobility
               -- equipment: barbell, trap_bar, dumbbell, cable, machine, assisted (load inverts),
               --            bodyweight, band, treadmill, bike, rower, none
               -- mets: JSON {easy, moderate, vigorous} on cardio rows only
               -- variation_of + carry: incline bench is a variation of flat bench with carry 0.8,
               --            used only for the first-exposure "guess"
blocks        (id, block_no, start_date, weeks, split, seed, notes)       -- 4-week blocks
plan_weeks    (id, block_id, week_no, start_date, seed, is_deload)
plan_sessions (id, week_id, day_offset, date, kind, title, status, moved_from, note)
               -- kind: upper_a, lower_a, upper_b, lower_b, conditioning, zone2, rest
               -- status: planned, done, skipped, void (dates before programme_start)
plan_items    (id, session_id, ord, section, slot_key, exercise_id, sets, rep_low, rep_high, target_weight,
               target_source, rest_sec, minutes, protocol, optional, note)
               -- section: warmup, main, accessory, core, finisher, cooldown
               -- target_weight is NULL until the session starts, then frozen with its source label
workouts      (id, client_id UNIQUE, session_id, date, started_at, ended_at, session_rpe, work_sets, hard_sets,
               volume, lift_minutes, kcal_est, kcal_wearable, hr_avg, effort, effort_parts, notes,
               updated_at, deleted)
set_logs      (id, client_id UNIQUE, workout_client_id, plan_item_id, exercise_id, set_no, reps, weight_kg,
               rpe, is_warmup, done_at, updated_at, deleted)      -- reps hold seconds for timed moves
cardio_logs   (id, client_id UNIQUE, workout_client_id, plan_item_id, exercise_id, minutes, distance_km,
               intensity, protocol, kcal_est, updated_at, deleted)
foods         (id, client_id UNIQUE, name, brand, unit, source, source_id, barcode, kcal_100, protein_100,
               carb_100, fat_100, approx, times_used, last_used, active)   -- source: usda, nz, off, custom
               -- UNIQUE (source, source_id) so accepting the same online product twice does not duplicate
food_portions (id, food_id, label, grams, is_default)
meals         (id, name, active)
meal_items    (id, meal_id, food_id, grams, portion_label, qty)
food_logs     (id, client_id UNIQUE, date, slot, food_id, food_client_id, grams, portion_label, qty,
               kcal, protein, carb, fat, updated_at, deleted)   -- slot: breakfast, lunch, dinner, snack
body_logs     (id, client_id UNIQUE, date, weight_kg, waist_cm, chest_cm, arm_cm, hip_cm, thigh_cm, note,
               updated_at, deleted)             -- client_id = "body-" + date
daily_logs    (id, client_id UNIQUE, date, water_ml, sleep_h, steps, updated_at, deleted)   -- "daily-" + date
```

Every row the phone can create carries a browser-made UUID `client_id` (unique index), `updated_at` and a soft-delete flag, so retries are idempotent and sync is last-write-wins. Child rows reference their parent by `workout_client_id` so a set logged before its workout has synced still resolves. Plan tables, seeded exercises and foods are server-owned and never pushed by the phone.

## Engines

Shared definitions. A **working set** is `is_warmup = 0 AND deleted = 0` in a workout with `deleted = 0`. A **finished workout** has `ended_at IS NOT NULL AND deleted = 0`. `round_load(x, equipment)` rounds half-up to 2.5 kg, or to 1 kg for dumbbells under 10 kg (never Python's banker's `round()`). Every engine function takes `today` as a parameter.

### Targets (nutrition.py)

Settings: `sex` (m or f), `birth_date`, `height_cm`, `start_weight_kg`, `target_weight_kg`, `target_date`, `goal_start_weight` and `goal_start_date` (snapshotted whenever the target weight or date is saved), `neat_factor` 1.2, 1.3 or 1.4 (default 1.3; exercise is not in the factor because each session's calories are logged), `deficit_cap` 750, `surplus_cap` 300, `protein_g_per_kg` 2.0, `fat_g_per_kg` 0.8, `fat_floor_g_per_kg` 0.5, `carb_floor_g` 50, `kcal_floor` (default 1,500 for men, 1,200 for women).

```
W    = trend_weight(d)                      # one function, see Weight trend
age  = floor((d - birth_date).days / 365.25)
bmr  = 10W + 6.25H - 5 age + (5 if male else -161)          # Mifflin-St Jeor
base = bmr x neat_factor
gap  = W - target;  days = (target_date - d).days
|gap| < 0.3           -> deficit 0, verdict "maintaining"
gap > 0 (lose)        -> needed = gap x 7700 / max(days, 1), or inf if the date has passed
                         deficit = min(needed, deficit_cap); if capped, eta = d + ceil(gap x 7700 / cap)
gap < 0 (gain)        -> same with surplus_cap, deficit negative
exercise = sum(coalesce(kcal_wearable, kcal_est)) over finished workouts on d
budget   = max(base - deficit + exercise, kcal_floor);  left = budget - eaten(d)
protein  = protein_g_per_kg x W;  fat = fat_g_per_kg x W;  carbs = (budget - 4 protein - 9 fat) / 4
carbs < carb_floor    -> carbs = carb_floor; fat = max(fat_floor x W, (budget - 4 protein - 4 carbs) / 9)
```
Round at display only. Worked example (man, 80 kg, 180 cm, 30): BMR 1780, base 2314; 72 kg in 100 days gives deficit 616, budget 1698, or 2048 after a 350 kcal session; protein 160 g, fat 64 g, carbs 120.5 g.

What Today shows: profile incomplete, a "Finish your profile" card and no numbers; no weight logged, numbers from `start_weight_kg` plus a "Log your weight" pill; capped, "At 750 kcal a day you would reach 72 kg on {eta}"; target date passed, the capped figures plus "Set a new date"; target above current, a surplus of at most 300 with the verdict wording flipped; floor hit, "Held at the 1,500 kcal floor"; no or unfinished workout, burned 0 until Finish.

**Weight trend and pace.** `trend_weight(d)` = mean of `body_logs.weight_kg` dated `d-6` to `d` (one or more logs); empty window, the latest log on or before `d` drawn dashed; none, `start_weight_kg`. This one function is "current weight" everywhere, including calorie maths. `pace(d)` is the straight line from (`goal_start_weight`, `goal_start_date`) to (target, target date), clamped to that interval. Verdict needs three or more logs in the last 14 days, else "log your weight to see pace": `behind = (trend - pace) x sign(goal_start_weight - target)`; within 0.5 kg "on pace", above "behind by x.x kg", below "ahead by x.x kg".

### Programme (programme.py)

**Inputs** (settings): `train_days` sorted ISO weekdays, 5 or 6 of them, default Mon-Fri; `session_minutes` 60; `experience` beginner; `cardio_kit` non-empty subset of treadmill, bike, rower; `main1_swap_every_blocks` 2; `programme_start` written on first block creation.

**Blocks and weeks.** The first block starts on the Monday of the current week; sessions dated before `programme_start` get status `void` (grey, excluded from adherence, never auto-skipped, but "Do this today" may pull them forward). All four weeks of `plan_weeks`, `plan_sessions` and `plan_items` are generated at block creation with `target_weight = NULL`; targets are computed live for the Plan and Today views and frozen into `plan_items.target_weight` and `target_source` when the session starts. `ensure_plan_through(conn, d)` at the top of `GET state`, `GET today` and `GET plan/week` creates the next block when `d` passes the last planned week, never more than one block ahead. `plan_weeks.seed = f"{block.seed}:{week_no}"`, week 4 is the deload, `block_no` counts blocks by start date. Seven sessions per week: `template_5 = [upper_a, lower_a, conditioning, upper_b, lower_b]`, `template_6` adds `zone2`, mapped onto `train_days` in order, other weekdays `rest`; built in date order so finisher no-repeat works within a week.

**Lifting session items** (ord ascending): warm-up cardio on the finisher machine, protocol `warm_easy_5`, 5 min; dynamic warm-up pseudo-exercise, 2 min; `main1` 3 x 6-10, rest 150 s; `main2` 3 x 8-12, rest 90 s; `acc1`, `acc2`, `acc3` 3 x 10-15, rest 60 s; `acc4` marked `optional`; `core1` on lower days 3 x 10-15 (seconds when `timed`), rest 45 s; `finisher` protocol from the user's kit; cool-down pseudo-exercise, 3 min. Ramp-up sets are not plan items: the Workout screen shows two warm-up rows under Main 1 at `round_load(0.5 x target) x 8` and `round_load(0.75 x target) x 4`.

**Selection.** Main 1 `idx = ((block_no - 1) // main1_swap_every_blocks) % len(pool)`; Main 2 `idx = (block_no - 1) % len(pool)`; every other slot rotates with `pick()`:
```
def pick(pool, week_seed, slot_id, previous):
    if len(pool) == 1: return pool[0]
    candidates = [k for k in pool if k != previous] or pool
    h = zlib.crc32(f"{week_seed}|{slot_id}".encode())     # never hash(): salted per process
    return candidates[h % len(candidates)]
```
`previous` is the same slot in the previous week; for the finisher it is the protocol of the most recent earlier lifting session. A pool of two alternates strictly. **Shuffle** (`POST plan/shuffle {week_id}`) writes a new `secrets.token_hex(4)` week seed, rebuilds that week's sessions that are still `planned` with no workout row, then cascade-rebuilds later untouched weeks of the block with their existing seeds. **Swap** (`POST plan/swap {item_id, exercise_key?}`): without a key, the first pool member by hash order that is neither current nor previous; with a key, it must be in the slot pool or any active exercise of the same pattern; 409 if the item already has a live set; `note = "swapped"`. Swaps do not persist; deactivating an exercise in Settings is the permanent mechanism (an emptied pool falls back to its first member with a warning).

**Deload (week 4).** Main, accessory and core items get `sets = max(1, sets - 1)`; cardio items use their `rounds_min` or `minutes_min`; targets are `round_load(0.9 x normal)` with `target_source = "deload"`; rep ranges unchanged. Deload workouts are never used as progression references.

**Time budget.** `est_min(item) = minutes if set else sets x (rest_sec + 40) / 60`, plus 2 min on Main 1. Defaults sum to 58.0 min for upper days and 62.25 for lower days. While the sum exceeds `session_minutes`, apply in order and re-check after each: drop `optional` items; finisher to its minimum; accessories from 3 to 2 sets, `acc3` then `acc2` then `acc1`; core to 2 sets; drop `acc3`; drop the finisher with `note = "trimmed for time"`. Warm-up, Main 1, Main 2 and cool-down are never trimmed. Changing `session_minutes` re-trims planned sessions from today; changing `train_days` rebuilds from next week (`POST plan/regenerate`).

**Block transitions** (`variation_of` and `carry` on the exercise rows):

| Slot | Blocks 1-2 | Blocks 3-4 | carry |
|---|---|---|---|
| Upper A Main 1 | barbell bench press | incline barbell bench press | 0.80 |
| Lower A Main 1 | back squat | front squat | 0.80 |
| Upper B Main 1 | barbell overhead press | seated DB shoulder press (per hand) | 0.40 |
| Lower B Main 1 | trap bar deadlift | barbell deadlift | 0.90 |
| Main 2 (odd / even blocks) | lat pulldown / seated cable row; chest-supported row / assisted pull-up; Romanian deadlift / DB Romanian deadlift; leg press / hack squat | | |

Main 1 swaps every two blocks because the strength index is defined on the block-1 lifts and a beginner needs eight weeks on them. Rep schemes do not change between blocks for a beginner.

**Target for an exercise** (`target_for`): a reference workout exists, apply the progression rule; none, but the exercise is a variation of one that has, `round_load(carry x e1RM_old / (1 + rep_low / 30))` labelled `guess`; neither, `NULL` labelled `first` with the text "Find a weight you can do for {rep_low + 2} with two reps in reserve". A reference older than 28 days gives the hold rule labelled `stale`.

**Progression (double progression).** Reference = the most recent finished, non-deleted, non-deload workout with a working set of this exercise, other than the current one. Over its working sets: `w = max(weight)`, `top_sets` = sets at `w`, `planned_sets` from the reference plan item (else the current item, else 3), `mean_rpe` over logged RPEs (8.0 if none), `n_hi = count(rpe >= 9.5)`, `hit_all_high = len(top_sets) >= planned_sets and all reps >= rep_high`, `any_low = any reps < rep_low`, `partial = fewer sets than planned`. First match wins:
- `any_low or n_hi >= 2`: `max(min_load, min(round_load(0.95 w), w - step))`, labelled `decrease_reps` or `decrease_rpe`
- `partial`: `w`, `hold_partial`
- `hit_all_high and mean_rpe <= 8.5`: `round_load(w + inc)`, `increase`
- `hit_all_high`: `w`, `hold_rpe`
- otherwise `w`, `hold_reps`
`inc = increment_kg` when set on the exercise, else 5 kg for squat and hinge patterns on barbell, trap bar or machine, else 1 kg for dumbbells under 10 kg, else 2.5 kg. `min_load = min_load_kg` when set, else 20 kg for a barbell, else one step. No cap on consecutive increases: needing every set at `rep_high` with mean RPE at or under 8.5 is the brake. Special load types: `assisted` (weight is assistance, directions invert, load = `bodyweight_fraction x bw - weight`); `timed` (reps are seconds, range 30-60 s, no weight, "+5 s" when every set reaches the top); pure bodyweight (rep-based only); `per_hand` (weight is one dumbbell). The Workout screen shows "Last: 3 x 10 at 40 kg, RPE 7" and "Target: 3 x 6-10 at 42.5 kg".

**Missed sessions, move, adherence.** `sweep_missed(conn, today)` runs with `ensure_plan_through`: planned non-rest sessions dated before today with no live workout become `skipped`; a started but unfinished workout stays `planned` and Today offers Finish (sets `ended_at` to the last set) or Discard. Finishing marks the session `done`; soft-deleting a finished workout returns it to `planned`. **Do this today** (`POST plan/move`): the source must be planned, skipped or void and within 14 days; today's session must have no live workout (409); the two exchange dates, both get `moved_from`, the source becomes `planned`, then sweep. Starting a workout on a non-today session applies the same exchange. **Mark rest** sets `skipped` with `note = "rest"`. Adherence per week = done / planned over the four lifting kinds plus conditioning, excluding `void`; `zone2` and `rest` count on neither side.

**Conditioning and Zone 2.** Conditioning: warm-up 5 min on machine M; main interval protocol for M from the `conditioning` group, rotating with no repeat versus last week; three core circuit items from disjoint pools, rest 30 s; mobility pseudo-exercise 10 min. M rotates weekly over `cardio_kit` with no repeat. Zone 2: one item, machine from the kit avoiding M, protocol `zone2_steady`, 35 min, logged as `moderate`. Cardio is logged through `POST cardio {client_id, workout_client_id, plan_item_id?, exercise_id, minutes, distance_km?, intensity, protocol?}` with intensity in easy, moderate, vigorous or interval.

**`data\exercises.json`** `{"version": 1, "exercises": [...]}`, each with `key` (slug, referenced by programme.json; custom rows get `custom_{id}`), `name`, `pattern`, `primary_muscle` (chest, shoulders, back, biceps, triceps, quads, hamstrings, glutes, calves, core), `secondary_muscles`, `equipment` (barbell, trap_bar, dumbbell, cable, machine, assisted, bodyweight, band, treadmill, bike, rower, none), `cues` (2-3 strings), `unilateral`, `per_hand`, `timed`, `bodyweight_fraction` (0.65 push-up, 0.95 pull-up and dip, 0.45 inverted row), `increment_kg`, `min_load_kg`, `variation_of`, `carry`, and `mets {easy, moderate, vigorous}` on cardio rows only.

**`data\programme.json`**: `set_overhead_sec` 40; `rest_sec` per section; `rep_schemes.beginner` for main1, main2, accessory, core; `deload {week_no 4, set_delta -1, load_factor 0.9}`; `template_5`, `template_6`; `sessions.{kind}` with `title`, `warmup`, `cooldown` and `slots [{key, section, scheme, select (fixed | rotate | block_alternate), optional, pool}]`; `protocols [{id, group (warmup | finisher | conditioning | zone2), machine, minutes + minutes_min or work_sec + rest_sec + rounds + rounds_min, intensity, text}]`; `warmup_moves` and `cooldown_stretches` for upper and lower. Startup validation fails loudly if a pool key is missing from exercises.json or has the wrong pattern, or a protocol names an unknown machine.

Finisher protocols: treadmill incline walk 10 min (min 8, "incline 8-12 per cent, 5.5-6 km/h"); treadmill run/walk 60 s / 60 s x 6 (min 4); bike 30 s / 60 s x 8 (min 6); rower 60 s / 60 s x 5 (min 4). Conditioning: bike 30/60 x 15 (min 10); rower 1/1 x 10 (min 8); treadmill run/walk x 10 (min 7); treadmill hill 20 min (min 15). Zone 2 steady 35 min (min 30).

**Disjoint pools** (58 members; swap alternates and the cardio, warm-up and mobility pseudo-exercises bring the library to about 90):

| Day | Slot | Pool |
|---|---|---|
| Upper A | main1 | barbell_bench_press, incline_barbell_bench_press |
| | main2 | lat_pulldown, seated_cable_row |
| | acc1 shoulder_iso | db_lateral_raise, cable_lateral_raise, machine_lateral_raise |
| | acc2 triceps | cable_pushdown, overhead_cable_extension, assisted_dip |
| | acc3 rear_delt | face_pull, reverse_fly_machine |
| | acc4 biceps (optional) | cable_curl, hammer_curl |
| Upper B | main1 | barbell_overhead_press, seated_db_shoulder_press |
| | main2 | chest_supported_row, assisted_pull_up |
| | acc1 horizontal_push | incline_db_press, machine_chest_press, cable_fly |
| | acc2 horizontal_pull | single_arm_db_row, straight_arm_pulldown |
| | acc3 biceps | db_curl, ez_bar_curl, incline_db_curl |
| | acc4 triceps (optional) | skull_crusher, db_overhead_extension |
| Lower A | main1 | back_squat, front_squat |
| | main2 | romanian_deadlift, dumbbell_romanian_deadlift |
| | acc1 lunge | bulgarian_split_squat, walking_lunge, reverse_lunge |
| | acc2 ham_iso | lying_leg_curl, seated_leg_curl |
| | acc3 calf | standing_calf_raise, single_leg_calf_raise |
| | core1 | plank, dead_bug, cable_crunch |
| Lower B | main1 | trap_bar_deadlift, barbell_deadlift |
| | main2 | leg_press, hack_squat |
| | acc1 glute | hip_thrust, cable_pull_through, glute_kickback |
| | acc2 quad_iso | leg_extension, step_up |
| | acc3 calf | seated_calf_raise, leg_press_calf_raise |
| | core1 | hanging_knee_raise, pallof_press, ab_wheel |
| Conditioning | circ1, circ2, circ3 | (plank, side_plank), (dead_bug, bird_dog), (mountain_climber, bicycle_crunch) |

### Effort and calories (effort.py)

**Per set.** `load = weight + bodyweight_fraction x bw(date)` (assisted: `max(0, bodyweight_fraction x bw - weight)`), where `bw` is `trend_weight`. `volume = load x reps x (2 if per_hand else 1)`, zero for timed and cardio. `e1RM = load x (1 + reps / 30)` for 1 to 12 reps on loaded, non-timed exercises; above 12 reps it is computed but flagged `low_confidence` (drawn hollow, excluded from PRs and the index). Hard set = RPE >= 8; `hard_ratio = hard_sets / sets_with_rpe`, 0 when none logged. `lift_minutes = clamp(elapsed - cardio_minutes, 15, 120)` where elapsed runs from `started_at` to `ended_at` or the last set.

**Calories.** Lifting MET 3.5 when mean RPE < 7, 5.0 up to 8.5 (and when no RPE), 6.0 above; `kcal_lift = MET x bw x lift_minutes / 60`. Cardio per row `kcal = MET_eff x bw x minutes / 60` stored in `cardio_logs.kcal_est`, from the table (easy / moderate / vigorous): treadmill 3.5 / 5.5 / 9.0, bike 4.0 / 6.8 / 8.8, rower 4.8 / 7.0 / 10.0; intervals `MET_eff = f x vigorous + (1 - f) x easy` with `f = work / (work + rest)` from the protocol, 0.4 if unknown. At 80 kg: bike 30/60 for 12 min gives 89.6 kcal, Zone 2 bike 35 min gives 317 kcal. `workouts.kcal_est = kcal_lift + sum(cardio)`; `kcal_used = coalesce(kcal_wearable, kcal_est)`.

**Effort score.** Lifting sessions:
```
ref    = median volume of finished workouts of the same session kind in the previous 28 days
partA  = 50 x min(volume / ref, 1.5) / 1.5     if at least 3 references, else 33.3
partB  = 30 x hard_ratio
partC  = 20 x min(kcal_used / (5 x bw), 1)
effort = round(partA + partB + partC)
```
Cardio-only sessions: `round(70 x min(kcal_used / (5 x bw), 1) + 30 x (1.0 if any vigorous or interval else 0.6))`. `effort_parts` stores the parts and `ref` so stored scores never drift.

**PRs, strength index, relative strength.** PRs are computed on read for exercises with an earlier finished workout: `e1rm` (best this workout, reps <= 12, above the previous best), `weight` (heaviest load), `reps` (more reps at a weight used before); `GET today` carries each exercise's `best_e1rm`, `best_weight` and reps at the five heaviest weights so the phone detects PRs offline. Strength index over the four block-1 Main 1 lifts: `baseline(E)` = best e1RM in weeks 1-3 of block 1; `idx(E, W) = best e1RM in week W / baseline - 1`; an untrained week carries the last value forward as a dashed segment; the index is the mean of the four, as a percentage. Variations are separate lines and never feed the index. Relative strength = best e1RM in the last 28 days / `bw(today)` per Main 1 lift.

**Write versus read.** `recompute_workout(conn, workout_id)` runs at finish and after any later set or cardio write, including inside the sync transaction, and stores `volume`, `work_sets`, `hard_sets`, `lift_minutes`, `kcal_est`, `effort`, `effort_parts` and the cardio `kcal_est`. Computed on read: e1RM per set, PRs, strength index, relative strength, weekly muscle sets, trend, adherence. The weekly muscle chart counts hard sets, not kilograms: primary muscle 1.0, each secondary 0.5, distributed in Python from a SQL group by `date(w.date, '-6 days', 'weekday 1')` (the Monday on or before) and exercise.

### Food (nutrition.py plus app.html)

**Offline list.** USDA SR Legacy compacted by `tools\build_food_db.py` (details in the USDA subsection below) plus the NZ overlay. NZ rows load with `source = nz`, `approx = 1` and show a small marker.

**NZ overlay `data\foods_nz.csv`.** Columns `name, brand, unit, kcal_100, protein_100, carb_100, fat_100, portion1_label, portion1_grams, portion2_label, portion2_grams, category, barcode, note`; `unit` is `g` or `ml` (1 ml treated as 1 g). About 120 rows with typical label values filled in by hand, in seven groups:
- Breads and cereals (22): Weet-Bix, Vogel's Original and Soy and Linseed, Tip Top Supersoft and Wholemeal, Molenberg, Burgen, Nature's Fresh, Pams White Sandwich, Freya's Dark Rye, Ploughman's, English muffin, bagel, crumpet, Harraways oats, Hubbards muesli, Light 'n' Tasty, Skippy Cornflakes, Uncle Toby's Plus, Nutri-Grain, cooked brown rice, cooked pasta.
- Dairy and eggs (20): Anchor Blue, Light Blue, Trim, Calci+, Zero Lacto, Meadow Fresh, oat milk, Anchor Greek yoghurt, Puhoi Valley, Fresh'n Fruity, Yoplait, Mainland Edam, Tasty and Colby, cottage cheese, Philadelphia, Anchor butter, Buttersoft, whipping cream, size 7 egg.
- Meats and fish (18): beef mince 5 and 15 per cent raw and cooked, chicken breast, thigh and drumstick, lamb loin chop and leg, pork loin chop, Hellers sausages, bacon and ham, Tegel tenders, Sealord tuna in springwater and oil, fish fingers, salmon fillet, green-lipped mussels.
- Takeaways (22): mince and cheese pie, steak and cheese pie, sausage roll, battered fish, chips by the scoop, Hell and Domino's and Pizza Hut slices, BurgerFuel Bastard, Big Mac, Kiwiburger, medium fries, KFC Original piece and Zinger, Subway 6-inch Chicken Teriyaki, sushi roll, butter chicken with rice, pad Thai, lamb kebab, cheese scone, custard square, lamington.
- Cafe and cold drinks (18): flat white standard and trim, latte, cappuccino, mocha, hot chocolate, long black, chai latte, Primo iced coffee, Tank smoothie, L&P, Coca-Cola, Coke Zero, V, Just Juice, Charlie's, Phoenix lemonade, Speight's.
- Snacks and sweets (18): Whittaker's Creamy Milk, Dark Ghana and Peanut Slab, Cadbury Dairy Milk, Cookie Time, Super Wine, Toffee Pop, Gingernut, Tim Tam, Bluebird Ready Salted, Eta Ripples, Proper Crisps, Pams roasted nuts, Bumper Bar, One Square Meal, Nice and Natural bar, Pineapple Lumps, Hokey Pokey ice cream.
- Sauces and spreads (16): Marmite, Vegemite, Pic's and Sanitarium peanut butter, Nutella, Craig's jam, Airborne honey, Olivani, Meadowlea, Wattie's tomato sauce, baked beans and spaghetti, Best Foods and Eta Lite mayo, Kiwi onion dip, Lisa's hummus.
- Plus kūmara (baked) and pavlova, because the USDA names ("sweet potato", "meringue") are not what a New Zealander types.

**Search.** Client-side over the cached list, `rank_foods(q)`: tokenise on non-letters, every query token must prefix-match a name or brand token (AND), falling back to OR scoring when AND finds nothing; score = tokens matched, then a bonus for an exact or starts-with name match, then source rank (custom, nz, off above usda for the same tokens, so "milk" shows Anchor first), then `times_used`, then shorter name. A one-character query returns the 20 most recently used. Maximum 30 results. `times_used` and `last_used` update on every `food_logs` insert including copies and saved-meal adds.

**Portions.** Each food's own portions (1 cup, 1 slice, 1 large egg), plus 100 g and free grams/ml with a quantity multiplier. `grams = portion_grams x qty`; free grams set `portion_label = NULL, qty = 1`. `food_logs.kcal = kcal_100 x grams / 100` stored as REAL; display rounds kcal to whole numbers and macros to 1 g.

**Open Food Facts proxy.** `User-Agent: FitnessTracker/1.0 (personal use; <email from Settings>)`, 8-second timeout, upstream 429 becomes `503 {"retry_after": 30}`. Search: `nz.openfoodfacts.org/cgi/search.pl?search_terms={q}&search_simple=1&action=process&json=1&page_size=20&sort_by=unique_scans_n&fields=code,product_name,product_name_en,brands,quantity,serving_size,nutriments,countries_tags`; if fewer than three products come back, repeat against `world` and merge, nz first, deduplicated by `code`. Barcode: `world.openfoodfacts.org/api/v2/product/{code}.json?fields=...`, `status != 1` becomes 404. Mapping to a candidate: `kcal_100` from `energy-kcal_100g`, else `energy_100g / 4.184`, else `4p + 4c + 9f` with `approx = 1`, else skip; macros from `proteins_100g`, `carbohydrates_100g`, `fat_100g` defaulting to 0; `name` from `product_name_en` or `product_name`; `brand` the first of `brands`; `source = off`, `source_id = barcode = code`; one default portion "1 serving (33 g)" when `serving_size` matches `(\d+(?:[.,]\d+)?)\s*(g|ml)`. Module cache `{url: (expires_at, status, body)}` with a 20-second TTL pruned to 100 entries, so a double-tap or re-scan never hits the rate limit. Nothing is saved until the user accepts and `POST foods` upserts on `(source, source_id)`.

**Camera scan.** Android Chrome `BarcodeDetector` over a `getUserMedia` video element, EAN-13 and EAN-8, needs the secure context the HTTPS listener provides. Falls back to typing the number.

**Saved meals and copying.** "Save this slot as a meal" copies the slot's live rows into `meal_items`. "Add meal" writes one `food_logs` row per item with a fresh `client_id`, recomputing kcal and macros from the food's current per-100 values so an edited food carries through. "Copy yesterday" (`from_date` defaults to the day before) copies the stored values as logged, appends rather than merges, and returns 404 "nothing to copy" on an empty source slot.

**USDA compaction (`tools\build_food_db.py`).** Files from the SR Legacy zip: `food.csv` (`fdc_id`, `description`), `food_nutrient.csv` (`fdc_id`, `nutrient_id`, `amount`; ids 1008 kcal, 1003 protein, 1005 carbohydrate by difference, 1004 total lipid), `food_portion.csv` (`fdc_id`, `amount`, `measure_unit_id`, `portion_description`, `modifier`, `gram_weight`), `measure_unit.csv` (`id`, `name`). Portion label = `amount` formatted (`0.5`, `1`, `2`) plus the unit name when the unit is not "undetermined", plus `, modifier` when present: "1 cup, chopped or diced", "2 tbsp", "0.5 cup". Descriptions are shortened for display by dropping filler clauses such as "broilers or fryers" while keeping the full text as search tokens. Drop baby foods, infant formula and restaurant-chain rows. Output `data\foods_usda.json` as an array of `[name, kcal, protein, carb, fat, [[label, grams], ...]]` rows, about 7,800 foods and roughly 1.5 MB, committed to the repo.

## The page (app.html)

Same skeleton as the finance page: header with title and theme toggle, hero, tiles nav, panels, toast, footer note. Seven tiles: **Today**, **Workout**, **Plan**, **Food**, **Progress**, **History**, **Settings**. Under 640 px the tiles collapse into a fixed bottom bar with Today, Workout, Food and More.

**Today.** Hero: calories left today, with eaten and burned beside it and the three macro bars underneath. Countdown to the target date with the pace verdict. Today's session card (title, first three exercises, estimated minutes, Start). Quick pills: weight, water +250 ml, sleep and steps. Week strip of seven dots: done, planned, skipped, rest. A small "3 changes waiting to sync" chip while the offline queue is not empty.

**Workout (Gym mode).** Phone-first. One exercise card at a time with the list collapsed above. Each set row: ghosted last-time numbers, target, big weight and reps steppers (2.5 kg and 1 rep, long-press to repeat), RPE chips 6 to 10, tick. Ticking a set starts the rest timer in a sticky bottom bar with vibration when done (`navigator.vibrate`). Cues expand under the exercise name. Swap and skip buttons. Warm-up and cool-down are collapsible sections at each end. Finisher shows the protocol with an interval timer. Finish opens the summary: volume, hard sets, PRs, effort score with its parts, estimated kcal, fields for wearable kcal and average HR, notes. The in-progress workout is mirrored to localStorage on every tick so a killed tab resumes where it was.

**Plan.** The week as seven columns (stack on phone), each session with its items. Buttons: Shuffle week, Swap item, Do this today, Mark rest. Block header: "Block 2, week 3 of 4, deload next week".

**Food.** Date picker with today default. Four slots with items and slot totals. Search box at the top with offline results as you type, then "Search online" and barcode buttons. Portion sheet on select. Totals bar against targets. Saved meals row.

**Progress.** Strength by lift (e1RM per week, four Main lifts, hollow low-confidence points), strength index line, weekly volume by muscle group (stacked bars), effort per session, weight trend against the pace line, measurements table, calories in against out by week, adherence heatmap.

**History.** Sessions and food days, filters by range and kind, search. Click a session for its sets. CSV downloads.

**Settings.** Profile (sex, birth date, height, starting weight), goal (target weight, target date, deficit cap, protein and fat per kg, NEAT factor), training (available weekdays, session minutes, experience, cardio kit, rest default), exercise library editor, food list (custom foods, portions, hide), saved meals, Phone (QR code from an embedded MIT-licensed JS encoder with the URL as text fallback, CA download, step list for stock Android and Samsung, cert status and "Reload certificate", "New code", "Offline ready: yes, version abc123", last sync errors), data (JSON backup and restore, `.db` copy, CSV), server (stay running, Stop), theme.

**Design tokens.** Keep the finance neutrals, shadows, radii, Bahnschrift display face, dark-mode block and entrance animations. Primary accent moves from ultramarine to a deep Le Corbusier green (`--accent: #3E6B48`, dark `#86BE94`) so the two apps read as siblings but are told apart at a glance. Charts keep the finance pairing: ultramarine for calories eaten, burnt sienna for calories burned and effort, green for strength. Blue and sienna were already checked for colour-vision safety in the finance app; green is only ever drawn alone.

## Phone: HTTPS, install, offline, sync

**1. Certificates (`tools\make_cert.py`).** `make_cert.bat` pip-installs `cryptography>=42` if missing, runs the script, then best-effort `curl -X POST http://127.0.0.1:8778/api/phone/reload-cert`. The script:
- `lan_ipv4s()`: union of `socket.getaddrinfo(socket.gethostname(), None, AF_INET)` and the UDP-connect trick, minus `127.*` and `169.254.*`.
- `load_or_make_ca()`: once, ECDSA P-256, `CN=Fitness Tracker CA (hostname)`, valid 10 years, `BasicConstraints(ca=True, path_length=0)` critical (Android refuses to install a file without it), `KeyUsage(key_cert_sign, crl_sign, digital_signature)` critical, `SubjectKeyIdentifier`. Writes `ca.pem`, `ca-key.pem` (PKCS8, unencrypted) and `ca.crt` (DER).
- `make_server_cert()`: fresh P-256 key, `CN=hostname`, 2 years, SAN = `DNSName` the hostname, hostname.local, localhost plus `IPAddress` 127.0.0.1 and every LAN IP (Chrome matches SANs only, never the CN), `BasicConstraints(ca=False)`, `ExtendedKeyUsage([SERVER_AUTH])`, `AuthorityKeyIdentifier`, SHA-256. Writes `server.pem`, `server-key.pem` and the sidecar `server.json` `{ips, dns, not_after, made}`. Timezone-aware datetimes throughout.
- Chrome's 398-day leaf limit applies only to chains ending in a publicly trusted root, so the 2-year leaf and 10-year CA are accepted for a user-installed root. `ca-key.pem` stays in `certs\`, outside OneDrive; `certs\` goes in `.gitignore`.
- Re-run when the LAN IP changes; the phone keeps trusting the CA. README recommends a DHCP reservation for the laptop in the router.

**2. Install on the phone (once).** Settings > Phone and the README list: open `https://192.168.x.x:8779/ca.crt` on the phone (Chrome shows the "not private" interstitial once; Advanced, Proceed), then stock Android 13/14: Settings > Security and privacy > More security and privacy > Encryption and credentials > Install a certificate > CA certificate > Install anyway > pick `fitness-tracker-ca.crt`; Samsung One UI: Settings > Security and privacy > Other security settings > Install from device storage > CA certificate. Android shows a persistent "Network may be monitored" notice, expected for any user CA. Fully close Chrome afterwards because it caches the failed verification for the session. Then scan the QR from the laptop's Settings > Phone; the `?key=` redirect sets the cookie and the address bar ends at `/`. Chrome menu > Add to Home screen installs it full screen.

**3. Manifest and static files.** `manifest.webmanifest`: `id "/"`, `name "Fitness Tracker"`, `short_name "Fitness"`, `start_url "/?source=pwa"`, `scope "/"`, `display standalone`, `theme_color #3E6B48`, the three icons with `purpose maskable` on one. Root-relative URLs mean the same bytes install separately on `127.0.0.1:8778` and `192.168.x.x:8779`. `app.html` gets `<link rel="manifest">` and `<meta name="theme-color">`. All static files go through `_send()` with `no-store`; the Cache API ignores HTTP caching headers, so precaching and `no-store` coexist.

**4. Service worker (`sw.js`).** `build_stamp()` on the server = first 12 hex of SHA-1 over `app.html`, `sw.js` and the manifest, recomputed when `app.html`'s mtime changes, substituted for `__BUILD__` when `sw.js` is served, so any page edit rolls the worker. Handlers: `install` precaches `/`, the manifest and icons into `shell-VERSION` then `skipWaiting()`; `activate` deletes stale `shell-*`, keeps `api`, `clients.claim()`; `fetch` router: non-GET pass through; navigations and the shell cache-first (`ignoreSearch`); `/api/today`, `/api/state`, `/api/exercises`, `/api/foods/list`, `/api/plan/week` network-first with a 3-second `AbortController` timeout, cache only `ok` responses (a cached 401 would be sticky), fall back to cache or `503 {"error": "offline"}`; everything else pass through. `sync` event runs a trimmed flush; `message` answers `{type: "version"}`. Page side: register, `reg.update()` on visibility, on `controllerchange` after the first install show a persistent "Updated. Tap to reload" toast, never auto-reload mid-workout; call `navigator.storage.persist()` once.

**5. Offline write queue (app.html).** Op = `{client_id, type, payload, at}` with `type` in `workout, set, cardio, food_log, food, body, daily`; a delete is the same op with `payload.deleted = 1`. IndexedDB database `fitness`, store `queue` keyed by `client_id`, so a second edit or a delete of the same row replaces the earlier op (last-write-wins, small queue). IndexedDB rather than localStorage because the service worker's `sync` event cannot read localStorage. `mutate(op)`: stamp `updated_at` and `at`, `applyLocal(op)` updates state and re-renders, `qPut(op)`, `flush()` in the background, refresh the waiting chip. Settings, regenerate and swap call `api()` directly. `flush()`: single in-flight guard, ops sorted by `at`, chunks of 200 to `POST /api/sync` with a 4-second timeout, delete applied ids, keep ops rejected as retryable ("workout not synced yet"), toast and store real rejections in `ft-sync-errors` (last 20) for Settings. Triggers: load, `online`, visibility, after each mutate, a 30-second interval while the queue is non-empty, and `reg.sync.register("flush")` where supported. Background Sync is a bonus; the README says the flush that usually succeeds is the one on the next open at home. localStorage mirrors: `ft-key`, `ft-theme`, `ft-live-workout` (the in-progress overlay `{client_id, session_id, date, started_at, sets}`), `ft-sync-errors`. The foods list lives only in the worker's `api` cache.

**6. `POST /api/sync` (server).** Request `{device, ops}`; response `{applied: [...], rejected: [{client_id, error}], ids: {client_id: server_id}, server_time}`. `apply_sync()`: order by dependency (`workout`, `food`, then `set`, `cardio`, `food_log`, then `body`, `daily`) and `at`; one connection, `BEGIN IMMEDIATE`, a `SAVEPOINT` per op rolled back on `BadRequest`, `COMMIT`; per-type column allowlist and validators (reps 0-100, weight 0-1000, RPE 5-10 or null, ISO dates), never SQL built from payload keys; generic `upsert_by_client_id()`:
```sql
INSERT INTO set_logs (client_id, ..., updated_at, deleted) VALUES (?, ..., ?, ?)
ON CONFLICT(client_id) DO UPDATE SET ..., updated_at = excluded.updated_at, deleted = excluded.deleted
WHERE excluded.updated_at > set_logs.updated_at
```
A `food_log` carrying `food_client_id` resolves to the food created earlier in the batch. After the batch, recompute `kcal_est` and `effort` for every touched workout. The laptop page uses the same `mutate()` path so every user-created row has a `client_id`.

**7. Rendering offline.** Workout screen = cached `/api/today` (seven days plus last-time numbers) chosen by the phone's local date, plus the `ft-live-workout` overlay. Cache older than a week: "Plan not available offline; connect to home wifi", with freestyle logging against the cached exercise list still allowed. Last-time numbers exclude an unsynced session until the next flush; the README says so.

**8. Firewall and power.** Windows Firewall prompts once when the exe first listens on the LAN; tick Private networks and Allow. If cancelled, Windows writes a block rule and the phone times out silently: fix via `wf.msc` or `netsh advfirewall firewall add rule name="Fitness Tracker" dir=in action=allow protocol=TCP localport=8779 profile=private program="C:\Personal\fitness-tracker\Fitness Tracker.exe"`. The rule is keyed on the exe path, so the fixed name and folder keep it across rebuilds; running from source is a separate rule for `python.exe`. Home wifi must be marked Private in Windows. Suggest sleep "Never" on mains if sync-at-home should be hands-off.

## Build and tools

- `tools\build_exe.bat`: as the finance build, plus `curl -X POST http://127.0.0.1:8778/api/stop` and a 2-second wait first so a running copy does not hold the exe open; `python tools\make_icon.py`; then `--onefile --noconsole --name "Fitness Tracker" --icon tools\icon.ico` with `--add-data` for `app.html`, `sw.js`, `manifest.webmanifest`, the three PNGs and `data;data`, `--distpath .`, work and spec paths in `%TEMP%\fitness-tracker-build`. `ssl`, `sqlite3`, `hashlib`, `hmac`, `secrets` are stdlib and PyInstaller bundles the OpenSSL DLLs itself. `certs\` is read from `HERE` only and never bundled.
- `tools\make_icon.py`: the finance stdlib .ico writer with a kettlebell drawing in the green accent, plus Pillow for the three PWA PNGs written to the project root.
- `tools\build_food_db.py`: downloads the USDA SR Legacy CSV zip to the scratch folder, joins `food.csv`, `food_nutrient.csv` (nutrient ids 1008 kcal, 1003 protein, 1005 carbohydrate, 1004 fat), `food_portion.csv` and `measure_unit.csv`, writes `data\foods_usda.json` (about 7,800 foods, roughly 1.5 MB). Committed so runtime never downloads.
- `tools\add_to_startup.bat`: creates a shortcut to the exe with `--no-browser` in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`. Optional.
- `Start Fitness Tracker.bat` and README in the finance voice, with new sections for the phone setup, the food sources, the maths, the `-wal` and `-shm` side files and the `.db` backup route.

## Seed content to author

- `data\exercises.json`: about 90 exercises across the patterns above, each with equipment, primary and secondary muscles, MET, `bodyweight_fraction` where relevant and two or three lines of form cues.
- `data\programme.json`: the templates, slot pools, rep schemes per experience level, block swap table, cardio protocols (bike 8 x 30 s on / 60 s off; rower 5 x 1 min on / 1 min off; treadmill 10 min incline walk 8-12 per cent at 5.5-6 km/h; treadmill 1 min run / 1 min walk x 6; conditioning-day 20-25 min versions), warm-up moves and cool-down stretches.
- `data\foods_nz.csv`: about 120 rows with typical label values, marked approximate.

## Implementation order

0. **Save this plan** into the project as `C:\Personal\fitness-tracker\PLAN.md` so it travels with the code, and tick items off there as they land.
1. **Scaffold.** Copy the server patterns, schema, settings, seed loader, page shell (tiles, theme, toast, fetch wrapper, heartbeat). Settings profile and goal form. Today hero showing targets from `nutrition.py`. Runs from `Start Fitness Tracker.bat`.
2. **Training.** Exercise library, `programme.py`, Plan tab, Workout screen on the laptop with set logging through `mutate()` and `/api/sync`, last-time and targets, rest timer, cues, warm-up and cool-down, finish summary with `effort.py`. Cardio logging and the conditioning day.
3. **Food.** `build_food_db.py`, NZ overlay, client search, portions, Food tab with slots and totals, saved meals, Open Food Facts proxy and barcode by number.
4. **Progress and History.** Charts in the finance style, CSV export, JSON and `.db` backup, restore.
5. **Phone.** `make_cert.py`, HTTPS listener, pairing key and cookie, Phone settings panel with QR, manifest, service worker, IndexedDB queue, phone layout pass on Gym mode, camera barcode.
6. **Ship.** Icon, `build_exe.bat`, README, startup shortcut. Build and run the exe end to end.

## Verification

- **Maths.** `python -m unittest tests.py`, the full list in the appendix. Engine functions take `today` as a parameter, never call `date.today()`, and row-based tests use `sqlite3.connect(":memory:")` with the real `SCHEMA`.
- **Programme.** Generate 12 weeks for a 5-day and a 6-day setup and inspect: every lifting day fits 60 minutes, no accessory repeats two weeks running, block 2 shows the swapped mains, weeks 4 and 8 are deloads.
- **Server from source.** Start with the .bat, log a profile, a body weight, a workout with three exercises and a finisher, a day of food including one Open Food Facts lookup and one barcode. Check Today's budget and left figure by hand against the formulas.
- **Sync and idempotency.** `curl` the same batch to `/api/sync` twice: one row per `client_id`. A `deleted: 1` op with an older `updated_at` than the stored row leaves the row live. A batch with a set whose workout is missing returns it as retryable.
- **Two writers.** Phone logging sets while the laptop refreshes Progress in a loop: no "database is locked" in the log, `PRAGMA journal_mode` returns `wal`.
- **TLS and pairing.** From the laptop `curl --cacert certs\ca.pem https://192.168.x.x:8779/api/ping`. Hold a raw socket open for 60 s against 8779 and confirm the phone still loads. Open the URL on the phone before installing the CA and confirm the log shows the "does not trust the certificate yet" line, not a traceback. Rename `server.pem` and restart: the laptop still works and Settings shows the reason. Edit `server.json` to a wrong IP: the warning text appears. After scanning the QR the address bar ends at `/`; in Chrome remote DevTools (`chrome://inspect/#devices`) the `fit_pair` cookie exists and the manifest and `sw.js` return 200. Clear site data and reopen the installed app: the in-page pairing card appears.
- **Service worker and offline.** Settings > Phone shows "Offline ready: yes" with the version; remote DevTools shows the worker activated. Two offline scenarios: (a) aeroplane mode, reopen the home-screen app, log three sets, finish; (b) phone on wifi but the laptop server stopped, which exercises the 3-second timeout path. In both, the queue chip counts up and the Workout screen renders from cache. Reconnect: the chip drains and the sets appear on the laptop. Change one character in `app.html` and confirm the "Updated. Tap to reload" toast appears on the phone within two opens.
- **Instances, ports, stop, idle.** Double-click the exe twice: the second opens the browser and exits. Hold 8779 with `python -m http.server 8779` and start the app: the log and Settings say the port is in use, the laptop side works. Settings > Stop exits within a second and removes `.port`. Start with `--idle 15` and `stay_running` off: it stops 15 s after the last ping, and never while `stay_running` is on. Ctrl+C from the .bat closes both listeners within a second.
- **Firewall.** Cancel the prompt once on purpose, confirm the phone times out, apply the README fix, confirm it connects. Rebuild the exe and confirm no new prompt.
- **Charts and dark mode.** Progress tab in light and dark, at 1080 px and 390 px wide.
- **Build.** `tools\build_exe.bat`, double-click the exe, repeat the phone checks against it. `fitness_tracker.log` shows both listeners, the build stamp and the cert SAN check.

## Risks and notes

- **IP changes** break the HTTPS address until `make_cert.bat` is re-run. Mitigated by the DHCP reservation, the startup warning and "Reload certificate".
- **Laptop asleep** while the phone is at the gym is fine: everything queues. It only needs to be on when the phone is back on home wifi. `stay_running` and the optional startup shortcut cover it.
- **Open Food Facts** coverage for NZ products is patchy and rate-limited; the offline list and custom foods carry the daily load. USDA values are US generics and the NZ overlay is typical values, both editable.
- **Health formulas** are estimates. The README will say so in the same tone as the finance README's note on visa figures.
- **OneDrive and SQLite** caveat carries over from the finance README; this project lives in C:\Personal, outside OneDrive, and `certs\` must stay out of any synced folder.

## Appendix: tests.py

Fixtures: an 80 kg, 180 cm, 30-year-old man unless stated; `today` fixed; in-memory SQLite with the real schema where rows are needed.

**Nutrition**

| Test | Expected |
|---|---|
| `test_bmr_male` (80 kg, 180 cm, 30 y) | 1780 |
| `test_bmr_female` (60 kg, 165 cm, 28 y) | 1330.25 |
| `test_maintenance_neat` (1780 x 1.3) | 2314 |
| `test_deficit_within_cap` (80 to 72 kg, 100 days) | 616 |
| `test_deficit_clamped_and_eta` (80 to 72, 50 days) | deficit 750, eta today + 83 days |
| `test_deficit_target_date_passed` | deficit 750, `target_passed` true |
| `test_surplus_capped` (70 to 76, 30 days) | deficit -300, eta today + 154 days |
| `test_at_target_band` (gap 0.2 kg) | deficit 0, verdict `maintaining` |
| `test_budget_no_workout` | 1698 |
| `test_budget_with_workout_350` | 2048 |
| `test_budget_wearable_overrides_estimate` (est 350, wearable 420) | 2118 |
| `test_budget_floor_male` (base - deficit = 1400) | 1500, `floored` true |
| `test_macros_default` (80 kg, budget 1698) | protein 160, fat 64, carbs 120.5 |
| `test_macros_carb_floor_reduces_fat` (100 kg, budget 1500) | protein 200, carbs 50, fat 55.6 |
| `test_current_weight_falls_back_to_start` (no logs) | `goal_start_weight` |
| `test_trend_seven_day_mean` (80, 81, 79) | 80.0 |
| `test_trend_carries_forward_when_window_empty` | latest log, `dashed` true |
| `test_pace_line_midpoint` (80 to 72 over 100 days, day 50) | 76.0 |
| `test_verdict_on_pace` (trend 80.0, pace 79.5) | `on pace` |
| `test_verdict_behind` (trend 80.6, pace 79.5) | `behind by 1.1 kg` |
| `test_verdict_ahead_for_gain_goal` | `ahead` |
| `test_verdict_needs_three_logs` | `no verdict` |

**Programme**

| Test | Expected |
|---|---|
| `test_round_load_half_up` (41.25 barbell) | 42.5 |
| `test_round_load_dumbbell_under_10` (7.6) | 8.0 |
| `test_progression_increase_upper` (3 x 10 at 40, RPE 7, 7, 8) | 42.5, `increase` |
| `test_progression_increase_lower` (squat 3 x 10 at 60, RPE 8) | 65 |
| `test_progression_hold_reps` (3 x 8 at 40, scheme 6-10) | 40, `hold_reps` |
| `test_progression_hold_rpe` (3 x 10 at 40, RPE 9, 9, 9) | 40, `hold_rpe` |
| `test_progression_decrease_below_low` (10, 8, 5 at 40) | 37.5, `decrease_reps` |
| `test_progression_decrease_two_high_rpe` (RPE 9.5, 10, 8) | 37.5, `decrease_rpe` |
| `test_progression_decrease_at_least_one_step` (cable 10 kg fail) | 7.5 |
| `test_progression_barbell_floor` (20 kg fail) | 20 |
| `test_progression_partial_sets_hold` (2 of 3 at rep_high) | 40, `hold_partial` |
| `test_progression_missing_rpe_neutral` (3 x 10, no RPE) | 42.5 |
| `test_progression_dumbbell_steps` (8 kg success; 10 kg success) | 9.0; 12.5 |
| `test_progression_assisted_inverts` (assist 30 kg success) | 27.5 |
| `test_progression_skips_deload_reference` | uses week 3, not week 4 |
| `test_progression_first_exposure_blank` | None, `first` |
| `test_progression_guess_from_variation` (flat bench e1RM 100, incline carry 0.8, rep_low 6) | 67.5, `guess` |
| `test_progression_stale_reference_holds` (reference 40 days old) | `stale` |
| `test_deload_target` (normal 42.5) | 37.5, `deload` |
| `test_pick_deterministic` | same seed and slot give the same key |
| `test_pick_no_repeat` | never equals `previous` when pool > 1 |
| `test_pick_pool_two_alternates` | A, B, A, B |
| `test_pick_pool_one_constant` | always pool[0] |
| `test_block_alternate_main1_every_two_blocks` | blocks 1-2 index 0, blocks 3-4 index 1 |
| `test_block_alternate_main2_every_block` | odd 0, even 1 |
| `test_week_five_days_layout` (Mon-Fri) | Mon upper_a, Tue lower_a, Wed conditioning, Thu upper_b, Fri lower_b, weekend rest |
| `test_week_six_days_zone2_last` | Sat zone2 |
| `test_first_block_starts_monday_void_before_today` (today Wednesday) | Mon and Tue `void` |
| `test_deload_week_sets` | Main 1 sets 2 in week 4 |
| `test_lifting_day_fits_budget` (12 weeks, both layouts) | every lifting session estimate <= 60 |
| `test_trim_drops_optional_first` | optional accessory absent, others keep 3 sets, finisher 10 |
| `test_trim_finisher_then_sets` (budget 50) | finisher at minimum before any accessory loses a set |
| `test_no_accessory_repeats_consecutive_weeks` (12 weeks) | no slot repeats week to week |
| `test_finisher_varies_within_week` | no two consecutive lifting sessions share a protocol |
| `test_shuffle_changes_only_untouched_sessions` | done session unchanged, later weeks cascade |
| `test_swap_rejects_item_with_logged_set` | 409 |
| `test_sweep_marks_past_planned_skipped` | `skipped`; started but unfinished stays `planned` |
| `test_move_exchanges_dates_and_sets_moved_from` | dates swapped, both `moved_from` set |
| `test_adherence_excludes_zone2_and_void` (5 planned, 4 done, zone2 skipped) | 0.8 |
| `test_seed_validation_pool_keys_exist` | every pool key exists in exercises.json with the matching pattern |

**Effort**

| Test | Expected |
|---|---|
| `test_e1rm_epley` (100 x 5) | 116.67 |
| `test_e1rm_low_confidence_over_12` (60 x 15) | 90.0, `low_confidence` |
| `test_volume_per_hand_doubles` (12 kg x 10, dumbbell) | 240 |
| `test_volume_bodyweight_fraction` (push-up 0.65, bw 80, 15 reps) | 780 |
| `test_lifting_met_by_rpe` | 6.5 gives 3.5; 7.5 gives 5.0; 9 gives 6.0; none gives 5.0 |
| `test_kcal_lift` (80 kg, 45 min, MET 5) | 300 |
| `test_kcal_interval_bike` (30 s on / 60 s off, 12 min, 80 kg) | 89.6 |
| `test_kcal_zone2_bike` (35 min, 80 kg) | 317.3 |
| `test_kcal_unknown_protocol_interval` (work fraction 0.4) | bike MET 5.92 |
| `test_lift_minutes_clamped` (workout left open 4 hours) | 120 |
| `test_effort_on_par` (volume = median, all RPE 8, kcal >= 5 x bw) | 83 |
| `test_effort_capped_at_100` (volume 2 x median) | 100 |
| `test_effort_no_rpe_part_b_zero` | part B 0 |
| `test_effort_no_baseline` (fewer than 3 references) | part A 33.3 |
| `test_effort_cardio_only_interval` (kcal >= reference) | 100 |
| `test_pr_e1rm`, `test_pr_reps_at_weight` | detected |
| `test_pr_none_on_first_exposure`, `test_pr_ignores_reps_over_12` | none |
| `test_strength_index_carry_forward` | untrained week equals previous, `carried` true |
| `test_weekly_sets_secondary_half_credit` (bench 3 sets) | chest 3.0, triceps 1.5, shoulders 1.5 |
| `test_monday_of_week_sql` (Sunday 2026-10-04) | 2026-09-28 |
| `test_recompute_after_late_sync_updates_kcal` | `kcal_est` changes when a set arrives after finish |

**Food**

| Test | Expected |
|---|---|
| `test_portion_label_modifier_only` | "1 cup, chopped or diced" |
| `test_portion_label_with_unit` | "2 tbsp" |
| `test_portion_label_half` | "0.5 cup" |
| `test_shorten_description` ("Chicken, broilers or fryers, breast, meat only, cooked, roasted") | "Chicken, breast, meat only, cooked, roasted" |
| `test_kj_to_kcal_fallback` (837 kJ) | 200 |
| `test_rank_and_pass` ("chick bre") | chicken breast rows only |
| `test_rank_or_fallback_when_and_empty` | score = tokens matched |
| `test_rank_nz_before_usda_same_tokens` ("milk") | Anchor rows first |
| `test_rank_starts_with_bonus` ("egg") | exact "Egg" beats "Eggplant" |
| `test_rank_short_query_returns_recent` ("e") | top 20 by `last_used` |
| `test_rank_max_30` | length <= 30 |
| `test_off_mapping_kcal_present`, `test_off_mapping_kj_only`, `test_off_mapping_macros_only_marks_approx` | fields populated; kcal = kJ / 4.184; approx 1 |
| `test_off_serving_size_parse` ("2 biscuits (33 g)", "30g", "1 cup") | 33, 30, None |
| `test_off_cache_hit_within_20s` | upstream called once |
| `test_food_log_kcal_from_portion` (kcal_100 165, 1 cup 140 g, qty 1.5) | 346.5 |
| `test_copy_yesterday_appends_stored_values` | rows doubled, values equal |
| `test_add_meal_recomputes_from_current_food` | uses edited `kcal_100` |
| `test_times_used_increments_on_copy` | +1 per row |
