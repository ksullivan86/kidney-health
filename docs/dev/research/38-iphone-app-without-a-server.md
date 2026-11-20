# 38 · The iPhone app without a server

| | |
|---|---|
| Status | Proposed 2026-11-20. Nothing built. Step 0 (§9) is a test on a real iPhone before anything else. |
| Owner's words | "I'd like to have it work locally if connection to the server is lost and sync later, maybe use the iOS AI if possible as well. I'd like to also have users not need a server to use the app." And: "can we also just include the option for a USDA API key to be added to app, it could have its own settings page for keys or APIs." (2026-11-20) |
| Builds on | [Note 15](15-native-ios-app.md) (the iPhone app, signing, TestFlight), [note 02](02-ios-pwa.md) (the Home Screen web app, the service worker on iOS), [note 12](12-phone-push-tokens.md) (device tokens), [note 14](14-reuse-map.md) (the JavaScript twins and their vectors), [`demo.md`](../../demo.md) ("Keep my data in this browser"), [note 36](36-lab-pdf-text.md) (lab text, local model only), [note 32](32-choose-local-or-cloud-ai.md) (local or cloud AI). |
| Scope | The iPhone app as a whole food log that works with no server. It keeps data on the phone, looks foods up with the person's own keys, uses Apple's on-device AI, and sends to a server when one is set up and reachable. |
| Out of scope | Android (later, the same plan). An App Store listing (§8, decision D6). Two-way sync of edits (§5.5, a later note). Any cloud AI from the phone. |

## 1. What it is for

Today the iPhone app does one job: it reads new weights and blood pressure readings from Apple Health and sends them to the
person's server. Food is logged in the web app, which needs the server.

The owner wants three things:

1. **Keep working when the server cannot be reached**, and send later.
2. **Work with no server at all**, so a person can use Kidney Health with only the app.
3. **Use the iPhone's own AI** where it helps.

They also want **a settings page for keys**, starting with a USDA FoodData Central key, so the app can look foods up by
itself.

## 2. What already exists

* **The whole app already runs without a server.** "Keep my data in this browser" ([`demo.md`](../../demo.md)) runs the web
  app with a copy of the server's rules written in JavaScript (`app/static/js/mock/`, about 7,000 lines). It saves the person's
  log, foods, labs, weights and settings on the device. The copies are checked against the server by the shared vectors in
  `tests/data/` (CLAUDE.md, "Parity").
* **Export and import already move data between the two.** The browser mode writes the server's `export.json`, and the server
  imports it. Importing the same file twice adds nothing.
* **The food list is small.** `data/foods.json` is the server's built-in list from USDA SR Legacy: 228 KB, or 33 KB compressed.
  It already ships with the browser mode.
* **The iPhone app already copes with a lost connection** for its one job. Readings stay in Apple Health, and the app moves its
  place forward only after the server took a round (note 15 §6, step 2). It sends the rest when the server is back.
* **The web app keeps entries made offline** and sends them later, when it is installed from an `https://` address (note 02).

So most of the work is already done. What is missing is a safe home for the data on the phone, food lookups beyond the
built-in list, the AI, and a way to send to a server.

## 3. Facts to rely on (re-check each when the build starts)

| # | Fact | Source |
|---|---|---|
| F1 | Apple's Foundation Models framework gives apps the on-device language model, about 3 billion parameters. It runs on the phone. Guided generation (`@Generable`) returns Swift values whose shape is guaranteed, and tool calling builds on it. | Apple, WWDC25 "Meet the Foundation Models framework" and "Deep dive"; Apple ML Research, 2025 updates |
| F2 | It runs only where Apple Intelligence runs: iPhone 15 Pro and 15 Pro Max, iPhone 16 and later, and iPhone Air (iOS 26 and iOS 27). The person must have turned Apple Intelligence on, and the device language must be supported. `SystemLanguageModel.default.availability` says whether it can be used and why not. | Apple Support 121115; Apple Newsroom June 2025; WWDC25 session 286 |
| F3 | Its context window is 4,096 tokens. Whether the Swift API takes images as input is not confirmed for our use: check the current documentation. | Apple Developer Forums (WWDC25 group lab summary); Apple ML Research |
| F4 | `WKWebsiteDataStore` keeps IndexedDB and local storage. An app can make a persistent store with its own identifier, which it gets back after a restart. Data is tied to the page's origin, so a changing origin loses it (WebKit bug 144875, with a random port). | Apple `WKWebsiteDataStore`; WebKit blog "Building Profiles with new WebKit API"; WebKit bugs 144875, 191294 |
| F5 | USDA FoodData Central data are public domain under CC0 1.0. USDA asks for credit and, if possible, a note of which product uses them. | fdc.nal.usda.gov (home page, licence) |
| F6 | The FoodData Central API needs a free key from api.data.gov. A key allows 1,000 requests an hour; more blocks it for an hour (HTTP 429). `DEMO_KEY` allows only 30 an hour and 50 a day. | fdc.nal.usda.gov API guide; api.data.gov developer manual |
| F7 | Open Food Facts reads need no key. Limits per IP address: 15 product reads a minute and 10 searches a minute, with no search-as-you-type. Apps must send a User-Agent like `AppName/Version (contact)`. Data are ODbL: credit, and share-alike for a combined database. | Open Food Facts API docs and FAQ |
| F8 | The Keychain stores secrets for one app. An item can be limited to this device (`…ThisDeviceOnly`). | Apple, Keychain services (as in note 15, I4) |

## 4. Options

| Option | What it is | Reuses | Verdict |
|---|---|---|---|
| **A. The web app inside the iPhone app, in device mode** | The app shows the web app's own files, packed inside it, running the browser mode's engine. Native Swift code does what a page must not: the network, the Keychain, Health, Face ID and the on-device AI. | Every screen, every rule and its vectors, export and import, the food list | **Recommended** |
| B. Native SwiftUI screens | A second app written in Swift | Only the vectors | No: a third copy of every rule (the server's and the JavaScript one already exist), and note 14's twin cost |
| C. The Home Screen web app alone | Install the web app from Safari, in the browser mode | Everything | No: Safari may delete a website's data when space runs low, it cannot read Health, and it has no on-device AI |

Option A is also what note 15 called option B (a `WKWebView` shell). Its worry then was that a web view cannot run the
service worker for a self-hosted domain (note 15, I5). That does not apply here. The files are inside the app, so there is
nothing to cache and no server to reach.

## 5. Design of option A

### 5.1 The shell

* A `WKWebView` loads the packed web app through the app's own URL scheme, `kidneyhealth-app://local/`, served by a
  `WKURLSchemeHandler`. This gives a fixed origin, so stored data survives restarts (F4), and avoids `file://` quirks.
* The web view uses a persistent data store with a fixed identifier (F4).
* **The page never touches the network.** Its Content Security Policy allows `connect-src` only to the app's own scheme.
  Every outside request goes through the native bridge (§5.3), which allows only a fixed list of hosts. This keeps CLAUDE.md's
  rules: no network from the browser, and nothing loaded from a CDN.
* The web app's files are packed at build time from `app/static/` by the same script that builds the online demo
  (`scripts/build_preview.py`), with a new `--device` target. No new copy of the code.
* The engine runs in a new **device mode**: the browser mode's persistence, with no sample person, no demo banner and no
  "Keep my data in this browser" sheet. Data is kept from the first start.

### 5.2 Where the data lives

* The log lives in the web view's IndexedDB (F4), as in the browser mode today.
* **A safety copy:** after each change, debounced like today, the app also writes `export.json` to the app's own folder on the
  phone. If the web view's store were ever lost, the app offers to import that copy. The person can see and copy it in the
  Files app (On My iPhone → Kidney Health).
* **Backups:** an iPhone backup to iCloud or to a computer includes app data unless the app opts out. Decision D3 says which.
* **Lock:** an optional Face ID or passcode lock (LocalAuthentication), off by default (D4). There is no sign-in, because the
  data never leaves the phone unless the person sends it.

### 5.3 Keys and services: the settings page the owner asked for

A native screen, **Settings → Keys and services**, lists each outside service with an on/off switch and, where needed, a key:

| Service | Needs | What it adds | Host |
|---|---|---|---|
| Built-in food list | nothing | the USDA SR Legacy list packed in the app (§2) | none |
| USDA FoodData Central | the person's free key (F6) | search all of USDA's foods, and branded barcodes | `api.nal.usda.gov` |
| Open Food Facts | nothing (F7) | barcode lookups for packaged foods | `world.openfoodfacts.org` |
| Your Kidney Health server | address and token | sending to your server (§5.5) | the person's server |

Rules for keys, the same as the server's (CLAUDE.md, "Secrets are write-only"):

* A key is pasted once, stored in the Keychain on this device only (F8), and **never shown again**. The screen says
  "A key is saved" and offers **Replace** and **Remove**.
* A **Test** button makes one request and says whether the key works. It sends nothing else.
* Keys are never written to the log, the export or the safety copy.
* Each service is off until the person turns it on. The screen says which host it talks to and what it sends: the food words
  typed, or the barcode, and never anything about the person.

The bridge enforces the limits: about 1,000 USDA requests an hour per key (F6), and 15 Open Food Facts reads and 10 searches a
minute, never as you type (F7). It sends the User-Agent Open Food Facts asks for. The contact part of that User-Agent is the
project's address, not the person's (CLAUDE.md: the person's email is never sent).

Foods found online are saved into the person's own foods, as the server's import does today, so a food looked up once works
offline afterwards. The credit lines USDA and Open Food Facts ask for (F5, F7) go on the About screen.

### 5.4 Apple Health

The app's existing Health reading (note 15) writes new weights and readings straight into the local log. With a server set
up, they are also sent there, as today.

### 5.5 Sending to a server

Three steps, from least to most work:

1. **By file (step 1 of §9).** Export on the phone, import on the server. Both exist today.
2. **One-way, automatic (step 4).** New entries made on the phone are sent to the server when it can be reached, and kept in
   a queue until then. This needs a server change: today's phone token may only add weights and blood pressure (note 12). A new
   token kind, "app", would be allowed to add log entries, foods, labs and symptoms, and nothing else: no reading, editing or
   deleting. Each row carries a client ID, so sending twice adds nothing, as import does today. Edits and deletes made on the
   phone after a row was sent are not sent in this step, and the screen says so.
3. **Two-way, with edits on both sides.** Real sync, with rules for which change wins. It is large, and it gets its own note
   only if the owner wants it after living with step 2.

### 5.6 The iPhone's own AI

Only when `SystemLanguageModel` is available (F2). On other phones these buttons do not appear, and everything else works.

* **Describe a meal:** "chicken and rice, half a cup of each" becomes a list of foods and amounts (guided generation, F1).
  Each is matched to the person's foods and the food list. The person checks every line before anything is saved, as Import a
  recipe does today.
* **Read a lab report's text:** the same rules as note 36. A value is kept only when it is written in the text, and the person
  checks each one. A photo is read with Apple's on-device text recognition (Vision) first. Image input to the model is not
  relied on (F3).
* **Meal ideas** within the person's targets, using the same checks as the server's AI ideas (`app/ai/guard.py` and its JavaScript twin `js/engine/aiguard.js`).

Safety rules that do not change (CLAUDE.md):

* The AI is never asked to dose insulin or medicine. The prompts never offer it, and replies are checked by the same guard.
* Nothing ever blocks or warns against treating a low.
* Prompts and replies are not stored.
* Everything runs on the phone, so the rule that lab reports and anything with a name or birth date go only to a local model
  is kept. The phone never calls a cloud AI.
* The 4,096-token window (F3) is small, so prompts send only what each task needs.

## 6. Safety and privacy review

| Concern | Answer |
|---|---|
| Data lost on the phone | The IndexedDB store plus the safety copy (§5.2), export at any time, and a reminder to export, as the server's backup reminder does. |
| A lost or shared phone | The optional lock (D4). The phone's own passcode protects the app's folder. Keys are Keychain, this device only. |
| A third company | Only the services the person turns on (§5.3), each named with its host. USDA and Open Food Facts are already used by the server, and the person's server is their own. Instacart, Withings and Whoop stay server features. |
| Keys leaking | Write-only, Keychain, never in exports or logs, a test sends nothing else (§5.3). |
| Wrong AI output | The person checks every line before it is saved. AI is never the only way to do anything. Lab values only from the text. |
| Dosing, lows | As §5.6. No new path can dose, and none can discourage treating a low. |
| Rules drifting | Device mode runs the same engine the vectors already check. New bridge code (keys, limits, queue) gets Swift tests on Linux like `KidneyHealthCore`. |

## 7. What changes, by part

* **Web app:** a device mode for the engine (§5.1), a bridge client for lookups, export snapshots, and hiding server-only
  screens: sign-in, admin, the Care team, Instacart, connected devices and cloud AI settings.
* **iPhone app:** the web view shell and URL scheme handler, the bridge, Keys and services, the safety copy, the lock, AI
  calls, and the send queue. It keeps the Health reading it has now.
* **Server:** nothing for steps 1 to 3. Step 4 needs the "app" token kind and its add-only routes, with tests in the isolation
  matrix (not-yours is 404).
* **Build:** `scripts/build_preview.py --device`, and the TestFlight workflow packs its output into the app.
* **Docs:** the handbook gets a page for using the app alone. `privacy.md` gets the phone's data and each service. ARCHITECTURE
  gets device mode and the bridge.

## 8. App Store and rules

TestFlight builds go only to testers, and that stays the route for family (note 15). An app anyone can download is a
different step (D6). It needs Apple's review, a privacy policy, Apple's rules for health data, and the regulatory question
already on the ROADMAP: is this a wellness app or clinical decision support? Building option A does not commit to that.

## 9. Plan and size

| Step | What | Rough size |
|---|---|---|
| 0 | **A test on a real iPhone.** A tiny build that writes to IndexedDB through the custom scheme, is force-quit and reopened, and survives "Offload app" and low-storage clean-up. If it fails, keep the data in a native SQLite file through the bridge instead. | small |
| 1 | The shell with device mode, the packed web app and food list, export and import through Files, and the safety copy | large |
| 2 | Keys and services: USDA and Open Food Facts through the bridge | medium |
| 3 | Health readings into the local log, and the optional lock | small |
| 4 | Sending to a server: the "app" token on the server, and the queue on the phone | medium to large |
| 5 | The on-device AI: describe a meal, lab text, meal ideas | medium |
| 6 | Two-way sync, only if wanted after step 4 (its own note) | large |

Each step is its own pull request with tests, and TestFlight builds let the owner try it between steps.

## 10. Decisions for the owner (defaults in bold)

* **D1. Two apps or one?** **One app, Kidney Health.** It works alone, and connecting a server is optional. (The other choice is
  a second app for the no-server use.)
* **D2. When a server is set up, where is the log kept?** **On the phone first, sent to the server** (§5.5). (Or: the app
  becomes a window onto the server's web app when a server is set up.)
* **D3. iPhone backups.** **Included in the phone's own backup** (iCloud or a computer, as the person has set up their phone).
  Or excluded, so the data never leaves the phone and the export file is the only backup.
* **D4. Lock.** **Optional Face ID or passcode lock, off by default.**
* **D5. Services on by default.** **None.** The built-in food list works with nothing turned on.
* **D6. The App Store.** **Not now.** TestFlight for family until the regulatory question is answered.

## 11. Sources

* Apple, [Meet the Foundation Models framework (WWDC25)](https://developer.apple.com/videos/play/wwdc2025/286/),
  [Deep dive into the Foundation Models framework](https://developer.apple.com/videos/play/wwdc2025/301/),
  [Updates to Apple's on-device and server foundation language models](https://machinelearning.apple.com/research/apple-foundation-models-2025-updates),
  [Apple Intelligence devices and languages](https://support.apple.com/en-us/121115),
  [Foundation Models forum thread on availability](https://developer.apple.com/forums/thread/805378).
* WebKit, [Building profiles with new WebKit API](https://webkit.org/blog/14423/building-profiles-with-new-webkit-api/),
  [bug 144875](https://bugs.webkit.org/show_bug.cgi?id=144875).
* USDA, [FoodData Central](https://fdc.nal.usda.gov/) (licence and citation), [API guide](https://fdc.nal.usda.gov/api-guide/),
  [api.data.gov developer manual](https://api.data.gov/docs/developer-manual/).
* Open Food Facts, [API introduction](https://openfoodfacts.github.io/openfoodfacts-server/api/),
  [FAQ](https://world.openfoodfacts.org/faq), [terms of use](https://world.openfoodfacts.org/terms-of-use).
