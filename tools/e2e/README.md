# End-to-end harnesses

Browser harnesses that check the app the way a person uses it. They are slower than the
test suite (minutes, not seconds), need a Chromium, and are run by hand before a release or after a
change to the frontend, the demo API or the server's routes. `python -m pytest` only checks that they
still compile and can read the server's setup code (`tests/test_e2e_tools.py`).

| File | What it checks | Server | Time |
|---|---|---|---|
| `parity.py` | The demo API in the preview build (`window.__kdlMock`) answers exactly like the real server: ~6,200 comparisons over foods, warnings, targets, logging, planning, saved meals, summaries, validation errors, custom foods, the shape of the accounts routes, (section 11) the v0.3 profile fields, lab results and personalised suggestions, (section 12) meal guidance, `POST /api/log/batch`, the log's `purpose` / `client_id` and saved meals' `meal_hint`, and (section 13) barcodes: foods with a `gtin` and an ingredient list (the additive scan) and `POST /api/foods/barcode` with its 400/422 reasons (Open Food Facts and USDA off on both sides). (section 14) the optional AI while it is off (`GET /api/me/ai`'s shape, every `/api/ai/*` and `/api/vision/*` route 404 on both sides). `--sections 0,12` runs a subset | real, signed in as the first admin | ~2 min |
| `sandbox.py` | The preview fragment inside an emulated claude.ai Artifact host (strict CSP, sandboxed iframe, no storage): every view (Lab results included), What fits now, a recorded barcode after the Open Food Facts agreement, Plan the rest of my day and Treating a low, the explained suggestion, Settings, sign out/in with the demo account, at phone and desktop sizes in four light/dark combinations; console errors, CSP violations, network requests, overflow, contrast, tap targets | none (static) | ~5 min |
| `regress.py` | The installed app against a real server at 375×812 and 1280×800, light and dark: first-run setup in the page with the logged code, then Profile (suggested targets, about-you fields), Lab results (conversion echo, what it changed, potassium banner, delete), Today, Add, quick add, USDA message, Plan, saved meals, Trends, CSV, What fits now, a typed barcode of the person's own food (additive warning), Treating a low, delete confirmations, plus probes (embedded data ignored, live warnings equal the server's) | real, fresh per config | ~4 min |
| `learn.py` | The patient handbook at `/learn` (a built site, `--site`), served by the real app: start page, a stage page, the potassium page, unit tabs, the palette switch, search, the 404 page, "Back to the food log", sign-in, the header's Learn entry, a warning's handbook link and Settings → About, at 375×812 and 1280×800; WCAG 2.2 AA text contrast (1.4.3) of every visible text run on five pages in the light and dark schemes. Fails on any contrast below AA, any CSP or Trusted Types violation, page or console error, failed request, request to another origin or unexpected HTTP error. CI runs it in the `handbook` job | real, signed in as the first admin | ~1 min |
| `guidance_perf.py` | The browser twin of the meal guidance engine (the demo answers `/api/guidance/*` in the page) in headless Chromium with the CPU slowed down 4× (`--rate`): cold, p50, p95 and max of every guidance route for the demo as shipped and for the benchmark size of note 06 §4.12 (1,975 foods, 60 days, 100 saved meals); fails when a route does not answer `ok` or a p95 is above `--max-p95` (200 ms, the note's request budget) | none (static) | ~1 min |
| `device.py` | Barcodes, label photos, AI cards and the offline outbox (note 03 R7–R9, R11; note 02 R5, R7) in Chromium on `http://localhost` (a secure context): a generated EAN-13 photo decoded by the vendored WebAssembly reader and by the native-detector branch, live scanning with Chromium's fake camera (a generated `.y4m`) and its no-frame watchdog, the plain-HTTP note; the outbox with `context.set_offline` (log offline, reload offline from the service worker, reconnect synced exactly once, a lost batch answer resent without a second row, a refused item's Retry/Discard, the sign-out sheet); Settings → This device on three fresh profiles opened at `#settings` while the first visit's service worker takes control (drawn once: one "Works offline" row, one Clear button, no duplicate ids); the iPhone Home Screen tip (an iPhone user agent sees it on the third visit only, a desktop never); AI meal ideas and "Read the label for me" against a fake OpenAI-compatible server it runs itself (the upload is a JPEG ≤ 1600 px without EXIF), the guidance AI buttons' "What will be sent?" and dropped picks, AI activity (the provider's raw answer captioned and masked), a personal key that never comes back (the server's outbound proxy points nowhere, so nothing leaves the machine); the demo's recorded products and outbox; the new screens at 375×812 and 1280×800, light and dark. `--only photo,native,live,outbox,firstvisit,iostip,ai,demo,shots` runs a subset | real, signed in as the first admin, AI on (env provider → the fake server) | ~1 min |
| `journey.py` | The whole v0.3 story on one real server, two people, in Chromium: first-run setup with Open Food Facts ticked, the admin switching AI on and opting in, Profile with the personal inputs and Suggest targets, two lab results that change the suggestion ("What this result changed", the change list with the rule's reason, "Why this number?"), a day logged with a barcode USDA knows, a barcode only Open Food Facts knows (the agreement panel first), a label photo read by AI (consent, fields "from photo"), What fits now, Not for me, a swap and "Plan the rest of my day"; two entries logged offline and synced exactly once; Trends insights; the Learn links; a second person who sees none of the first person's labs, guidance choices, AI activity or waiting offline entries; the export zip; account deletion (every row gone); then every new screen at 375×812 and 1280×800, light and dark. Needs a built handbook (`--site`) | real (`replay_app:app`), fake AI on `--ai-port`, fake Open Food Facts on `--off-port` | ~3 min |
| `upgrade.py` | Upgrades a populated **v0.2** database (commit `8b8d4ec`) and a populated **schema v3** (M1, `9ef9151`) one to this checkout's schema: both old versions are unpacked with `git archive` (the checkout is untouched), filled through their own API, then served by this version on a copy; entries, totals, profile, saved meals, custom foods and CSV rows must be identical, the new columns empty, the step 4–7 tables present, `integrity_check` and `foreign_key_check` clean, and labs, suggestions, guidance, `POST /api/log/batch` and the export must work on the old data (v0.2: the `APP_PASSWORD` import, `kidney.db.pre-v3.bak` 0600; v3: two people, a USDA key that still opens). Needs a full clone (not shallow) | old and new real servers on `--port` and the next one | ~1 min |
| `replay_app.py` | Not a harness: `uvicorn replay_app:app` is the real app with USDA FoodData Central answered from `tests/fixtures/usda` (it has no base-URL setting); `journey.py` runs it through `khserver.Server(app_spec=...)` | | |
| `khserver.py` | Shared helpers (not a harness): start `uvicorn app.main:app` with a fresh `DATA_DIR` and the image's flags, read the `FIRST-RUN SETUP` code from the log, a JSON client that sends the CSRF headers and keeps the session cookie, `first_admin()`, `invite_user()` | | |

## Requirements

* The development requirements (`pip install --require-hashes --no-deps -r requirements-dev.lock`) and Playwright for Python
  (`pip install -r requirements-tools.txt`; CI installs the same version hash-locked from
  `tools/e2e/requirements.lock`, generated by `scripts/lock.sh`).
* A Chromium for Playwright. The harnesses use, in order: `PLAYWRIGHT_CHROMIUM` (path to a `chrome`
  binary), a browser under `PLAYWRIGHT_BROWSERS_PATH` or `/opt/pw-browsers`, else Playwright's own
  download (`python -m playwright install chromium`).
* Node is not needed (the JS parity vectors are `node tests/js/run_vectors.mjs`, run by CI).

No network access is needed: the server runs with no USDA key and Open Food Facts off, except in `journey.py`,
whose server talks only to its own local fakes (AI and Open Food Facts) and to the recorded USDA answers, with
its outbound proxy pointing nowhere, so nothing can leave the machine.

## Running

Run from the repository root (or anywhere: the harnesses find the repository from their own path).

```bash
python tools/e2e/parity.py                     # exit 0 when every comparison matched
python tools/e2e/regress.py --no-pytest        # add --only 375-light for one configuration
python tools/e2e/sandbox.py --workers 4        # add --only top-phone-light-none for one walk
python tools/e2e/guidance_perf.py              # add --rate 6 for a slower phone
python tools/e2e/device.py                     # add --only outbox,live for some sections
python tools/e2e/journey.py --site handbook/site   # after building the handbook; --only setup,profile,labs,...
python tools/e2e/upgrade.py                    # add --only v0.2 or --only v3
(cd handbook && mkdocs build) && python tools/e2e/learn.py --site handbook/site
```

Options shared by the harnesses:

* `--out DIR` — work directory for the server's data, logs, the built preview, screenshots and the
  report. Default: `<system temp dir>/kidney-health-e2e/<harness>/`. **`parity.py` wipes it first**;
  never point it at a directory you care about (it refuses paths inside `app/`, `data/` or `tests/`).
* `--port N` — `parity.py` runs the server on 8061 and the preview site on 8062 (`--static-port`);
  `regress.py` uses 8063, `learn.py` 8064, `guidance_perf.py` 8065, `device.py` 8066 (and 8067 for its fake
  AI server, `--ai-port`), `journey.py` 8068 (fake AI 8069, fake Open Food Facts 8070), `upgrade.py` 8071 and 8072; `sandbox.py` picks a free port unless given one. A harness stops if its
  port is already taken, so two can run at once with different ports.
* `parity.py --server-python PATH` runs the server on another interpreter (for example the
  image's Python) while the harness itself stays on yours.

Every server, static server and browser a harness starts is stopped when it ends, also on errors.

## Accounts (v0.3)

Every `/api` route needs a signed-in person, and before first-run setup the server answers `503
setup_required`. So:

* `parity.py` and the probes in `regress.py` finish setup through `POST /api/auth/setup` with the
  code from the server log (user `parity` / `regress`, password `khserver.DEFAULT_PASSWORD`), and
  send `X-Requested-With: kidney-health` and a same-origin `Origin` on every write.
* `regress.py` finishes setup **in the page** for each configuration (setup screen → Today), then
  opens a second session for its own direct API reads.
* The preview needs no sign-in: the demo person is a signed-in demo admin.

## Reading the results

* `parity.py` prints a table per section and every mismatch with a severity (`high` for numbers,
  levels, ratings and list lengths, `medium` for texts). The report is `<out>/report.json`. One
  difference is by design and compared by status only: USDA search answers 503 on both sides, but
  the demo has no server, so its words differ (the UI shows "needs the installed app").
* `regress.py` prints `PASS` / `FAIL` / `INFO` lines; `<out>/report.json` and `<out>/shots/`.
* `sandbox.py` groups issues by severity; `<out>/results.json` and `<out>/shots/`.
* `guidance_perf.py` prints a table per data set and `FAIL` lines; `<out>/report.json`.
* `device.py` prints `PASS` / `FAIL` lines per section; `<out>/report.json` and `<out>/shots/` (a screenshot of
  the page is kept for a section that stops on an error). What it cannot show: a real phone camera, iOS
  Safari, a real native `BarcodeDetector` (Linux Chromium has none, so a stand-in exercises that branch) and a
  live AI provider.
* `journey.py` prints `PASS` / `FAIL` lines per step of the story; `<out>/report.json` and `<out>/shots/` (numbered
  by step; `error-<section>.png` when a section stops). Sections run in story order and build on each other, so
  `--only` is for re-running a prefix (`--only setup,profile,labs`). What it cannot show: a live AI provider, the
  live Open Food Facts and USDA services, a real phone.
* `upgrade.py` prints `PASS` / `FAIL` lines per starting point; `<out>/report.json`; the old versions' sources,
  data directories and server logs stay in `<out>` for a look after a failure.

When you write or change a harness: Playwright's route handlers (the fake camera, the recorded answers) run
only while Python is inside a Playwright call, so wait with `page.wait_for_timeout` or `wait_js`, never
`time.sleep`, while a route must answer. Under heavy parallel load (several harnesses and Chromium workers on
four cores) a 20-second wait can still run out; re-run the one section with `--only` before suspecting the app.

When a parity check fails after a server change, fix the twin in `app/static/js/engine/*` or
`app/static/js/mock/*` (and the vectors in `tests/data/` when an engine changed), not the harness.
