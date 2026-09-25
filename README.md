# Fitness Tracker

A private training and food tracker that lives on your phone. It plans your week, tells you what to lift, logs every set, counts calories and protein from a food list that includes New Zealand staples and Kerala and Indian dishes, and shows you getting stronger. Everything is stored on the phone. No account, no server, no cloud.

## Get it on your phone

There are two ways. Both keep your data on the phone, both work with no signal at the gym, and a backup file moves your data between them.

**The Android app.** On the phone, open the [latest release](https://github.com/Shah-Ron/fitness-tracker/releases/latest), download **Fitness-Tracker.apk** and open it. Android will ask you to allow installs from your browser for this file. When a newer release appears, download it and install it over the top; your data stays.

**The web app.** Open <https://shah-ron.github.io/fitness-tracker/> in Chrome on the phone, then choose **Add to Home screen** from Chrome's menu. It installs like an app and opens full screen.

Both come from this repository. GitHub builds the app file and publishes the web version every time the code changes.

## What it does

**Today** shows what is left to eat, protein, carbs and fat against target, this week's sessions, today's workout and quick buttons for weight, water, sleep and steps. A pace line tells you whether your weight trend is on track for the date you set.

**Workout** is built for one hand at the gym. Each exercise shows what you did last time and the weight to aim for, with big steppers for weight and reps, an RPE row for how hard the set felt, and a tick. The tick starts the rest timer, which buzzes when it is time. The finisher has an interval timer. Finish shows your volume, hard sets, calories and effort score, and takes the numbers from your watch if you have one.

**Plan** is the week. Pick a split in Settings: **Upper / Lower**, **Full body**, **Push / Pull / Legs** or a **Bro split**, and how many days you train. Main lifts stay for a four-week block so you can build on them, accessories and cardio finishers rotate every week, and week 4 is a deload. Shuffle a week, swap an exercise when a machine is busy, pull a session forward to today or mark a day as rest.

**Food** logs what you eat. Type a name and pick from the bundled list of about 7,500 foods: USDA generics, New Zealand brands and takeaways, and Kerala and Indian dishes from appam and puttu to beef fry, meen curry, thoran, avial, biryani and payasam. Choose a portion such as 1 appam or 1 cup, or type grams. Packaged products can be searched online or looked up by barcode through Open Food Facts, and once accepted they join your list. Save a meal to add it in one tap, or copy yesterday's.

**Progress** charts estimated one-rep max on the main lifts, the strength index against your first block, sets per muscle each week, effort per session, your weight trend against the pace line, calories eaten against burned, and how many planned sessions you did.

**History** lists workouts and food days with CSV exports. **Settings** holds your profile and goal, the split and training days, the exercise library, your own foods and meals, and backups.

## Backups

Everything is on the phone, so if the phone is lost or wiped, so is your data. **Settings, Backups, Export a backup** saves a JSON file (into Downloads in the Android app, or through the share sheet in the web app). Do it now and then and keep the file somewhere safe. **Restore a backup** puts it onto any phone or browser running this app.

## The numbers

- **Calories to eat** start from your basal metabolic rate (Mifflin-St Jeor) times a small factor for daily life. Training is not in that factor because each session's calories are added on the day. The gap between your weight and your target, spread over the days left, sets the daily deficit, capped at 750 kcal a day. If the date is too close, Today says when you would get there at the cap. Nothing is ever shown below a floor of 1,500 kcal.
- **Protein** is 2 g per kilogram of body weight, fat 0.8 g per kilogram, carbs fill the rest. Adjustable in Settings.
- **Calories burned** use MET tables: how hard the session felt sets the lifting figure, and each cardio bout uses its machine and intensity. Numbers from a watch replace the estimate.
- **Estimated one-rep max** uses the Epley formula. Sets over 12 reps show hollow because the estimate gets rough.
- **Progression** is double progression. When every set reaches the top of the rep range without a grind, the weight goes up next time: 2.5 kg for most lifts, 5 kg for squats and deadlifts, 1 kg for light dumbbells. Miss the bottom of the range and it comes down a step.
- **Effort** is a score out of 100 from volume against your usual for that session, the share of hard sets, and calories for your body size.
- **Weight trend** is the seven-day average, so one salty dinner does not read as a bad week.

Every one of these is an estimate, for steering rather than medical decisions. The Kerala, Indian and New Zealand food values are typical home-style figures and are marked approximate.

## What is in this repository

| Folder or file | What it is |
|---|---|
| `phone\` | The app: `index.html`, `app.js` (screens), `engine.js` (programme, effort and nutrition maths), `local-api.js` (the routes), `store.js` (storage), `sw.js`, the manifest, icons and `data\` |
| `android\` | The Android shell. A WebView around the same app, with the camera for barcodes and a Downloads folder for backups |
| `.github\workflows\` | `pages.yml` publishes `phone\` as the web app; `android.yml` builds and signs the app file and attaches it to a release |
| `data\` | The exercise library, the programme template with its splits, and the three food lists |
| `tools\build_phone.py` | Merges the food lists and stamps the service worker. Run it after changing anything in `data\` or `phone\` |
| `tools\build_food_db.py` | Rebuilds the USDA list from the public FoodData Central release |
| `tools\selftest.html` | Runs the whole engine end to end in a browser. It wipes that browser's data, so never open it on a phone you use |
| `phone\engine.test.js`, `tests.py` | Unit tests: `node --test phone/engine.test.js` and `python -m unittest tests` |
| `fitness_tracker.py`, `programme.py`, `effort.py`, `nutrition.py`, `app.html` | The original laptop edition: a Python server with a SQLite file and a phone link over home wifi. It still works, holds its own separate data, and is no longer the main way to use this. See `PLAN.md` |
| `PLAN.md` | The design this was built from |

## Developing

Edit the files in `phone\` or `data\`, run `python tools\build_phone.py`, and open `phone\index.html` through any local web server (for example `python -m http.server 8790 --directory phone`, then `http://127.0.0.1:8790/`). Push to `main` and GitHub publishes the web app and builds a new release with the app file. The Android build signs with a key kept in the repository's secrets; the same key must be used for every build or the phone will refuse the update.

## Privacy

The app makes no network calls except the food name or barcode you choose to look up on Open Food Facts. There is no account and nothing is uploaded. The web app is served from GitHub Pages, which only ever sends the app's files to the phone, never anything back.
