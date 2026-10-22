# The online demo, and keeping your data in the browser

The **online demo** is the app running entirely in your browser, with no server: the GitHub Pages build
(`python scripts/build_preview.py --pages DIR`, published beside the handbook at `demo/`) answers every call from a
copy of the server that lives in the page, filled with a sample person, "Sam". It is for looking at the app. It has
no AI, no Open Food Facts or USDA lookups beyond a few recorded barcodes, no real sign-in (it is a signed-in demo
admin) and no installed-app features. **For real use, run your own server**: it keeps your data on a computer you
control, with sign-in, backups and the full app ([Deployment](deployment.md)).

Normally the demo keeps nothing: reloading starts over. This page is about the one exception, which you must choose.

## Keep my data in this browser

The demo's banner has a button, **Keep my data in this browser** (Settings → Your data has the same one). It opens a sheet that
says, in plain words:

* your data stays **only in this browser, on this device**, and **nothing is sent anywhere**;
* **clearing site data, private browsing, or the browser deciding to free up space can delete it**, so export it regularly;
* on a **shared device** other people who use this browser can see it (the demo has no real sign-in);
* for real use, run your own server.

Nothing is stored until you tick **I understand** and press the button. You choose what to start with: **an empty log of your
own** (the default: no sample person, no sample days) or **the sample data as it is now**. The page then asks the browser to
keep the data (`navigator.storage.persist()`) and the sheet tells you whether the browser agreed ("has agreed to keep this
data unless you clear the site data yourself", or "has not agreed to keep this data for good").

From then on the demo works like a small log with no server: every change that goes through is saved in the browser a moment
later (debounced, about 1.5 seconds, and when the page is hidden), and the saved copy is read back when you open the demo
again. The banner then reads "Your data is kept in this browser only: not on a server, and not backed up". Going offline
makes no difference while the mode is on (there is no server to reach).

### Export and import

* **Settings → Your data → Export my data (export.json)** (or **Export export.json** in the sheet) downloads the file the
  server's export holds, `export.json`: the same format (`kidney-health-export`, version 1), the same keys in the same order,
  with your log, own foods, saved meals, lab results, symptoms, food preferences ("Not for me", "More like this", "Less often"), profile and settings. It never holds a
  password, session or key. The AI sections are empty (the demo has no AI). The server's own export is a `.zip` with CSV
  files too; the demo gives the JSON only.
* **Settings → Your data → Import from a file** takes an `export.json` from this demo **or from a real server**, or the export `.zip` of a
  real server itself (the page opens it on the device, `js/engine/zip.js`; the demo's own export stays `export.json`), and works
  exactly like the server's import ([Privacy](privacy.md#moving-your-data-to-another-server)): it shows what the file would add
  before anything changes, refuses a file that is not an export in the server's words (an unknown field, a value out of range,
  a version it does not read, a file nested more than 32 levels), never imports the account, sessions, tokens, AI settings,
  AI providers or consents, and replaces your profile, targets and display settings only if you tick that. An account that
  already has data needs **Add to my existing data**, and importing the same file twice adds nothing.
* **To move to a real server**, export here and use **Import from a file** on the server. A log with the built-in glucose
  tablets, gel or shots (which carry a negative food number of their own) imports as well.

### Stop keeping data here

**Stop keeping data here** in the sheet asks in the page first ("Delete the copy of your data stored in this browser? The
demo then starts again with its sample data. This cannot be undone: export first if you want to keep it."), then deletes the
stored copy and starts the sample demo again.

### When it cannot work

* **Private browsing, blocked site data, or a frame without storage** (for example the demo inside another page): the sheet
  says "This browser does not let this page store data… The demo stays in memory: nothing is saved", and the button stays off.
* **The disk or the browser quota is full:** the sheet and the banner say so; the data is still in the page, and the next change
  tries again. Export it.
* **Two tabs of the demo:** the first to save wins. A second tab that finds the stored copy changed by another tab **stops
  saving and says so** instead of overwriting it; export what you need from it, then reload.
* **A copy saved by a newer version of the demo** is not loaded, never changed and never deleted by an older page; the banner and
  the sheet say why. Open the newer demo.
* **A copy that cannot be read** is treated the same.
* **A newer demo build does not update the built-in foods inside an old saved copy** (they are part of the copy). To get the newer
  list, export, **Stop keeping data here**, turn the mode on again with an empty log and import your file: the import finds
  each built-in food again by its FoodData Central number.

## What is stored

One record in the browser's IndexedDB (database `kdl-demo-local`, object store `state`, key `current`):
`{format: "kidney-health-demo-local", schema, rev, savedAt, foodsVersion, state}`. `state` is the demo API's own tables
(entries, foods, saved meals, labs, symptoms, profile, settings, the sample accounts); `schema` is its shape and `rev` counts
the saves. Nothing else is kept in the browser for this mode, and nothing is read from it unless you turned the mode on. It
exists only in the demo build: the installed app never opens this database, and neither does a development server's `?mock=1`
page (a test checks both).

A browser keeps IndexedDB **per web address (origin), not per page**: on GitHub Pages every project site of one account
shares `<account>.github.io`, so other pages published under the same address could read this database (the demo's own scripts
make no request, and its Content-Security-Policy applies only to the demo's page). If the Pages address is shared with pages
you do not control, do not keep real data there: run your own server instead.

## For people working on it

[ARCHITECTURE.md](../ARCHITECTURE.md#keep-my-data-in-this-browser-demo-only) has the contract. In short:
`app/static/js/mock/persist.js` (storage), `mock/export.js`, `mock/import.js` (the import's twin of `app/data_import.py`),
`views/demo_local.js` and `css/demo-local.css` (the banner button and sheet). Changing the **shape of the demo's state** in a
way an older saved copy cannot satisfy means bumping `SCHEMA` in `persist.js` and adding the step to `migrate()`; properties
the mock creates lazily need none. Changing the server's import (`app/data_import.py`) means regenerating
`tests/data/import_vectors.json` (`python3 tests/data/gen_import_vectors.py`) and making `mock/import.js` agree
(`node tests/js/run_vectors.mjs`). The browser walk is `python tools/e2e/demo_local.py`.
