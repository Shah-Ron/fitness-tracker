# Fitness Tracker

A private training and food tracker that runs on your own laptop. No account, no cloud. Your phone can join in over home wifi, log sets at the gym with no signal, and sync when you get home.

## Starting it

Double-click **Fitness Tracker.exe**. Your browser opens at `http://127.0.0.1:8778`. The app keeps running quietly in the background so your phone can sync whenever it is home. Stop it from **Settings, Server** or by double-clicking the .exe again and pressing Stop there. Double-click the .exe while it is running and it simply opens the page.

The first start after a build takes ten seconds or so while Windows unpacks and scans it. If Windows Defender ever quarantines it, restore it and add the folder as an exclusion; small home-built programs are a common false positive. Anything that goes wrong is written to `fitness_tracker.log` next to the .exe.

The first time it listens for your phone, Windows Firewall asks whether to allow it. Tick **Private networks** and choose **Allow**. If you cancel by mistake, the phone will time out silently; see Phone setup below for the fix.

### Without the .exe

**Start Fitness Tracker.bat** runs the same thing through Python with a console window you close to stop it. Or open PowerShell in this folder and run:

```powershell
python fitness_tracker.py
```

You need Python 3.8 or newer. Nothing else for the app itself. The tools that make certificates and the .exe install what they need the first time they run.

### Rebuilding the .exe

Only needed if the Python files, `app.html` or the data files change. Double-click **tools\build_exe.bat**. It stops a running copy, installs PyInstaller if it is missing, draws the icon and writes a fresh `Fitness Tracker.exe` here.

## What is in this folder

| File | What it is |
|---|---|
| `Fitness Tracker.exe` | The app, packaged. Double-click to start |
| `fitness.db` | **Your data.** A SQLite database, created on first run. `fitness.db-wal` and `fitness.db-shm` appear beside it while the app runs |
| `fitness_tracker.py` | The server: database, routes, sync, the phone listener |
| `programme.py`, `effort.py`, `nutrition.py` | The maths: the weekly plan, effort and calories, food targets |
| `app.html` | The page. The .exe carries a copy inside, but a copy here wins |
| `sw.js`, `manifest.webmanifest`, `icon-*.png` | What lets the phone install the page as an app and open it offline |
| `data\` | The exercise library, the programme template and the two food lists |
| `certs\` | Made by `tools\make_cert.bat`. The certificates your phone trusts. **Keep `ca-key.pem` private and out of OneDrive** |
| `tools\` | Build the .exe, draw the icon, make certificates, rebuild the food list, add to Startup |
| `tests.py` | `python -m unittest tests` checks the maths |
| `PLAN.md` | The design this was built from |
| `fitness_tracker.log`, `fitness_tracker.port` | Appear while running. What it did, and which ports it took |

## How it works

**Today** shows what is left to eat, your protein, carbs and fat against target, the week's sessions, today's workout and quick buttons for weight, water, sleep and steps. The pace line tells you whether your weight trend is on track for the date you set.

**Workout** is built for a phone in one hand. Each exercise shows what you did last time and the weight to aim for, with big steppers for weight and reps, an RPE row for how hard the set felt, and a tick. Ticking a set starts the rest timer, which buzzes when it is time. The finisher has an interval timer. Finish shows your volume, hard sets, calories and effort score, and asks for the numbers from your watch if you have them.

**Plan** is the week: four lifting days, a conditioning day and, if you train six days, an easy Zone 2 day. Main lifts stay for the block. Accessories and cardio finishers rotate every week so it does not get stale. Week 4 of each block is a deload. You can shuffle a week, swap an exercise when a machine is busy, pull a session forward to today or mark a day as rest.

**Food** logs what you eat. Type a name and pick from the bundled list, which works offline. Choose a portion such as 1 cup or 2 slices, or type grams. Packaged products can be searched online or looked up by barcode, and once accepted they are saved to your list. Save a slot as a meal to add it in one tap later, or copy yesterday's.

**Progress** charts estimated one-rep max for the main lifts, the strength index against your first block, weekly sets per muscle, effort per session, your weight trend against the pace line, calories eaten against burned, and how many planned sessions you did each week.

**History** lists every workout and food day, with CSV downloads. **Settings** holds your profile and goal, training days and kit, the exercise library, foods and meals, the phone link, backups and the server switch.

## Your phone

The phone talks to the laptop over home wifi, so it needs the laptop on and awake when it is home. At the gym it works on its own and syncs later. Set this up once:

1. On the laptop, run **tools\make_cert.bat**. It creates a private certificate authority and a server certificate for this laptop's wifi address. Re-run it if the address ever changes. Giving the laptop a fixed address in your router (a DHCP reservation) avoids that.
2. Start the app. Open **Settings, Phone**. It shows the link for the phone and the state of the certificate.
3. On the phone, open the `ca.crt` link shown there. Chrome warns that the connection is not private, because the phone does not trust the laptop yet. Choose Advanced, then Proceed, and the file downloads.
4. Install it: **Settings, Security and privacy, More security settings, Encryption and credentials, Install a certificate, CA certificate**, then pick the downloaded file. On Samsung phones it is under Other security settings, Install from device storage. Android shows a "network may be monitored" notice afterwards. That is expected for a certificate you installed yourself.
5. Close Chrome completely, open it again and open the pairing link from **Settings, Phone**. The page loads and the phone is paired.
6. In Chrome's menu choose **Add to Home screen**. The icon opens the app full screen, and it keeps working with no connection.

Everything you log with no connection is queued on the phone and sent when it can reach the laptop again. The chip at the top says how many changes are waiting.

If the phone times out even though the laptop is on, Windows Firewall is probably blocking it. Open Windows Defender Firewall, Advanced settings, Inbound Rules, and allow **Fitness Tracker** for private networks, or run this in an administrator PowerShell:

```powershell
netsh advfirewall firewall add rule name="Fitness Tracker" dir=in action=allow protocol=TCP localport=8779 profile=private program="C:\Personal\fitness-tracker\Fitness Tracker.exe"
```

Your home wifi must be set to **Private** in Windows network settings for that rule to apply. If you would like the server to be up whenever you sign in, run **tools\add_to_startup.bat**.

## The numbers

- **Calories to eat** start from your basal metabolic rate (Mifflin-St Jeor), multiplied by a small activity factor for daily life. Training is not in that factor because each session's calories are added on the day. The gap between your weight and your target, spread over the days left, sets the daily deficit, capped at 750 kcal a day for safety. If the date is too close, Today says when you would get there at the cap. Nothing is ever shown below a floor of 1,500 kcal.
- **Protein** is 2 g per kilogram of body weight, fat 0.8 g per kilogram, and carbs fill the rest. Both are adjustable in Settings.
- **Calories burned** use MET tables: how hard the session felt sets the lifting figure, and each cardio bout uses its machine and intensity. Numbers from a watch replace the estimate.
- **Estimated one-rep max** uses the Epley formula. Sets over 12 reps are shown hollow because the estimate gets rough there.
- **Progression** is double progression. When every set reaches the top of the rep range without a grind, the weight goes up next time: 2.5 kg for most lifts, 5 kg for squats and deadlifts, 1 kg for light dumbbells. Miss the bottom of the range and it comes down a step.
- **Effort** is a score out of 100 from three parts: your volume against your usual for that session, the share of hard sets, and calories against your body size.
- **Weight trend** is the seven-day average, so a salty dinner does not read as a bad week.

Every one of these is an estimate. They are for steering, not for medical decisions.

## The database

`fitness.db` is an ordinary SQLite file. Open it with [DB Browser for SQLite](https://sqlitebrowser.org/) or query it from Python. The tables are listed in `PLAN.md`. Every row your phone can create has a `client_id`, an `updated_at` and a `deleted` flag, which is how the sync stays safe to retry.

## Backups

**Settings, Your data** offers a JSON backup, a consistent copy of the database and CSV downloads of sets, food and body logs. Copying `fitness.db` by hand while the app runs can miss recent writes, so use the download or stop the app first. Keep this folder outside OneDrive, and never sync the `certs` folder.

To start completely fresh, close the app and delete `fitness.db`. It rebuilds with the exercise library and food lists next time you run it.

## Food data

The offline list is built from the USDA FoodData Central SR Legacy release, which is public data, compacted by `tools\build_food_db.py`, plus a hand-written set of New Zealand staples with typical label values. Those rows are marked approximate. Online lookups use [Open Food Facts](https://world.openfoodfacts.org/), a volunteer database, and are rate limited, so the online button is deliberate rather than search-as-you-type.

## Privacy

The laptop side listens on `127.0.0.1` only. The phone side listens on your wifi address over HTTPS with a certificate only your phone trusts, and every request from the phone carries a pairing code. Nothing is sent anywhere else, except the food name or barcode you choose to look up online.
