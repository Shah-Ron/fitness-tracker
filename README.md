# Fitness Tracker

A private training and food tracker that lives on your phone. It plans your week, tells you what to lift, logs every set, counts calories and protein from a food list that includes New Zealand staples and Kerala and Indian dishes, and shows you getting stronger. Everything is stored on the phone. No account, no server, no cloud.

## Get it on your phone

There are two ways. Both keep your data on the phone, both work with no signal at the gym, and a backup file moves your data between them.

**The Android app.** On the phone, open the [latest release](https://github.com/Shah-Ron/fitness-tracker/releases/latest), download **Fitness-Tracker.apk** and open it. Android will ask you to allow installs from your browser for this file. After that, **Settings, Updates, Check for updates** finds newer releases and installs them from inside the app; your data stays.

**The web app.** Open <https://shah-ron.github.io/fitness-tracker/> in Chrome on the phone, then choose **Add to Home screen** from Chrome's menu. It installs like an app and opens full screen.

**iPhone.** Apple does not allow installing an app file from a website, so on an iPhone the web app is the app. Open <https://shah-ron.github.io/fitness-tracker/> in Safari, tap **Share**, then **Add to Home Screen**. It opens full screen, works offline and keeps your data on the phone. **Settings, Updates, Check for updates** reloads it into the newest version. Two things the iPhone version cannot do: scan a barcode with the camera (type the number instead) and buzz when the screen is off (keep the screen on during a workout, which is the default).

Both come from this repository. GitHub builds the app file and publishes the web version every time the code changes.

## What it does

**Today** greets you by name and shows what is left to eat as a ring, with protein, carbs and fat against target, this week's sessions, today's workout and quick buttons for weight, water, sleep and steps. A pace line tells you whether your weight trend is on track for the date you set. A short note sits under it: a quote and a tip for the day, chosen by the date, with Another to move along. Settings, Look switches the notes off.

**Workout** is built for one hand at the gym. Each exercise shows what you did last time and the weight to aim for, with big steppers for weight and reps, an RPE row for how hard the set felt, and a tick. **How to do it** on any exercise opens a short description, the form cues and a YouTube tutorial from a well-known coaching channel; it stays closed until you ask for it. The weight stepper is drawn as a dumbbell, minus on one plate and plus on the other, and the plates swell as the load goes up; the reps stepper is a tally that fills towards the target. Each exercise asks only for what it needs: weight and reps for lifts, reps each side for one-sided moves, seconds with a hold timer for planks and carries (a Left and a Right button for side planks), and minutes, speed and how hard it felt for the treadmill, bike and rower, which get a countdown or interval timer instead of a set list. The tick starts the rest timer, which drains a bar as the rest runs out, shows a tip while you wait, buzzes when it is time and carries on where it was if you leave the app and come back. A line under the heading counts the session's sets, the next exercise is marked, finished exercises fold to one line (tap to open one again), and a set that beats your best on that exercise gets a PR flag the moment it is logged. Barbell weights, including squats, deadlifts, rows and hip thrusts, can be typed as the total on the bar or as the plates on each side, with the bar added for you; pick in Settings, where a one-time button converts anything you logged per side before. Treadmill, bike or rower work logged as sets in earlier versions is converted on the next start: the reps become minutes. Finish shows your volume, hard sets, calories and effort score, and takes the numbers from your watch if you have one.

**Plan** is the week. Pick a split in Settings: **Upper / Lower**, **Full body**, **Push / Pull / Legs**, a **Bro split**, **HIIT** or **Cardio first**, and how many days you train. Pick your experience level as well. **Beginner**, the default, is three sets, moderate reps, two reps in reserve and rests of one to two and a half minutes, about an hour a session. **Intermediate** adds a fourth set of five to eight on the first lift, tightens the rep ranges, lengthens the rests and the warm-up ramp, and leaves one rep in reserve, about 70 minutes. **Advanced** is four sets of four to six on the main lift, four sets on accessories, longer holds, a four-set warm-up ramp and a deload that halves the work, about 75 minutes. If your minutes per session are shorter than the level wants, the plan trims accessories to fit and Settings offers to allow the extra time. HIIT gives you interval sessions on the machines (Tabata, 30/30, 40/20), a dumbbell and bodyweight circuit with burpees, thrusters, swings and jump squats, and a mixed day, around two full-body lifting days. Cardio first gives you an intervals day (4 x 4 minutes or 8 x 2), a tempo session and a long steady 45 minutes, again with two lifting days so you keep your muscle. Cardio days rotate across the treadmill, bike and rower through the week. Main lifts stay for a four-week block so you can build on them, accessories and cardio finishers rotate every week, and week 4 is a deload. Shuffle a week, swap an exercise when a machine is busy, pull a session forward to today or mark a day as rest. A day can hold more than one session: pull a missed session into a day you have already trained and it joins as a second visit, and Settings has a sessions-a-day choice if you train twice a day as a rule.

**Food** logs what you eat. Type a name and pick from the bundled list of about 7,700 foods: USDA generics, New Zealand brands and takeaways, about 250 Kerala and Indian dishes from appam and puttu to beef fry, meen curry, thoran, avial, sadya, biryani and payasam, and a drinks list with New Zealand beers, ciders, wines, spirits, RTDs and cocktails. Choose a portion such as 1 appam, 1 cup or 1 pint, or type grams. Anything missing can be searched online: USDA FoodData Central answers for dishes and drinks (chicken curry, biryani, beer), Open Food Facts for packaged products by name or barcode. Whatever you pick joins your list and works offline from then on. Save a meal to add it in one tap, or copy yesterday's. The day's ring at the top shows what is left and how much protein is still to go, with a tip that reacts to where the day is.

**Progress** opens with sessions, kilograms lifted and average effort for the range, then charts estimated one-rep max on the main lifts, the strength index against your first block, sets per muscle each week, effort per session, your weight trend against the pace line, calories eaten against burned, and how many planned sessions you did.

**History** lists workouts and food days with CSV exports. **Settings** holds your profile (with a name for the greeting), your goal, the split, your experience level and training days, and the look: light, dark or the same as the device, a colour of your own from seven swatches or a picker, and the switch for the notes and tips. The colour runs through the buttons, tabs, chips, the week's dots and the shade of the page in both themes; the charts keep their own. The app icon follows the look too: the Android app swaps its launcher icon the moment you pick a colour or theme (some launchers then want it put back on the home screen, and a switch under Look keeps it green instead), the web app refreshes its icon the next time Chrome checks, and an iPhone keeps the icon it was added with. The exercise library, your foods and meals, the online search key, backups and updates stay folded until you open them.

On a phone the bar at the bottom holds Today, Workout, Food and Plan, and More opens Progress, History and Settings. On a wider screen the same sections are tabs across the top.

## Updates

The app checks GitHub for a new version when it opens, at most every six hours, and shows a banner with an Update button and a fold-out list of what is new. Later rests that version for three days. Android downloads the new package, shows the download as it happens and opens the installer; the web app fetches the new build through its service worker and reloads into it. The first open after an update shows what changed. Settings > Updates has the switch to turn the automatic check off, a Check now button, the time of the last check and the notes for the version you are on.

The notes come from `phone\whats-new.json`: add an entry at the top for each change. The build puts the newest entry into `phone\version.json`, and the release workflow puts it into the GitHub release so the Android app can read it before downloading.

## Backups

Everything is on the phone, so if the phone is lost or wiped, so is your data. **Settings, Backups, Export a backup** saves a JSON file (into Downloads in the Android app, or through the share sheet in the web app). Do it now and then and keep the file somewhere safe. **Restore a backup** puts it onto any phone or browser running this app.

## The numbers

- **Calories to eat** start from your basal metabolic rate (Mifflin-St Jeor) times a small factor for daily life. Training is not in that factor because each session's calories are added on the day. The gap between your weight and your target, spread over the days left, sets the daily deficit, capped at 750 kcal a day. If the date is too close, Today says when you would get there at the cap. Nothing is ever shown below a floor of 1,500 kcal.
- **Protein** is 2 g per kilogram of body weight, fat 0.8 g per kilogram, carbs fill the rest. Adjustable in Settings.
- **Calories burned** use MET tables: how hard the session felt sets the lifting figure, and each cardio bout uses its machine and intensity. Numbers from a watch replace the estimate.
- **Estimated one-rep max** uses the Epley formula. Sets over 12 reps show hollow because the estimate gets rough.
- **Experience level** sets the sets, rep ranges and rests of every scheme, the warm-up ramp on the first lift, how many reps to leave in reserve on a first exposure, and how hard the deload is. The three levels live in `data\programme.json` under `experience_levels` and `rep_schemes`.
- **Progression** is double progression. When every set reaches the top of the rep range without a grind, the weight goes up next time: 2.5 kg for most lifts, 5 kg for squats and deadlifts, 1 kg for light dumbbells. Miss the bottom of the range and it comes down a step.
- **Effort** is a score out of 100 from volume against your usual for that session, the share of hard sets, and calories for your body size.
- **Weight trend** is the seven-day average, so one salty dinner does not read as a bad week.

Every one of these is an estimate, for steering rather than medical decisions. The Kerala, Indian, New Zealand and drinks values are typical home-style or label figures and are marked approximate. Alcohol calories come from the strength on the label: 7 kcal per gram of alcohol plus the carbs.

## What is in this repository

| Folder or file | What it is |
|---|---|
| `phone\` | The app: `index.html`, `app.js` (screens), `engine.js` (programme, effort and nutrition maths), `local-api.js` (the routes), `store.js` (storage), `sw.js`, the manifest, icons, `data\` and `whats-new.json` (the release notes) |
| `android\` | The Android shell. A WebView around the same app, with the camera for barcodes and a Downloads folder for backups |
| `.github\workflows\` | `pages.yml` publishes `phone\` as the web app; `android.yml` builds and signs the app file and attaches it to a release |
| `data\` | The exercise library, the programme template with its splits, and the three food lists |
| `tools\build_phone.py` | Merges the food lists and stamps the service worker. Run it after changing anything in `data\` or `phone\` |
| `tools\make_icon.py` | Draws the icon in every look: the fourteen sets under `phone\icons`, their manifests and the Android launcher icons |
| `tools\build_food_db.py` | Rebuilds the USDA list from the public FoodData Central release |
| `tools\ui_sweep.js` | Renders the Workout card for every exercise in headless Edge and checks it asks for the right things |
| `tools\screenshot.js` | Screenshots any screen of the phone page in headless Edge at phone size, to check how it looks |
| `tools\selftest.html` | Runs the whole engine end to end in a browser. It wipes that browser's data, so never open it on a phone you use |
| `phone\engine.test.js`, `tests.py` | Unit tests: `node --test phone/engine.test.js` and `python -m unittest tests` |
| `fitness_tracker.py`, `programme.py`, `effort.py`, `nutrition.py`, `app.html` | The original laptop edition: a Python server with a SQLite file and a phone link over home wifi. It still works, holds its own separate data, and is no longer the main way to use this. See `PLAN.md` |
| `PLAN.md` | The design this was built from |

## Developing

Edit the files in `phone\` or `data\`, run `python tools\build_phone.py` (tests: `python -m unittest tests`, `node --test phone/engine.test.js`, `node tools/ui_sweep.js`), and open `phone\index.html` through any local web server (for example `python -m http.server 8790 --directory phone`, then `http://127.0.0.1:8790/`). Push to `main` and GitHub publishes the web app and builds a new release with the app file. The Android build signs with a key kept in the repository's secrets; the same key must be used for every build or the phone will refuse the update.

## Privacy

The app makes no network calls except the food name or barcode you choose to look up online, which goes to Open Food Facts and USDA FoodData Central. USDA shares one demo key between everyone, good for a few searches an hour; a free personal key from fdc.nal.usda.gov allows a thousand and is pasted into Settings. There is no account and nothing is uploaded. The web app is served from GitHub Pages, which only ever sends the app's files to the phone, never anything back.
