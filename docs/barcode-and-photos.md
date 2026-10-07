# Barcodes and photos

How the app turns a packaged food's barcode into a food you can log, what leaves your device, where the
numbers come from and how far to trust them. The design behind this page is
[`docs/dev/research/03-barcode-and-photo.md`](dev/research/03-barcode-and-photo.md) (note 03, with its
§9 security review); the API is in [`ARCHITECTURE.md`](../ARCHITECTURE.md) ("M2 API: barcode"). The
patient-facing version of this page is the handbook's
[Barcodes and label photos](../handbook/docs/app/barcode-and-photo.md).

## Barcodes

### What leaves your device

* **Only the digits.** Your phone or computer reads the barcode itself (camera, a photo of the barcode,
  a typed number or a USB/Bluetooth scanner that types) and sends the number to **your** server. The
  photo never leaves the device.
* **Your server** then asks Open Food Facts and/or USDA FoodData Central **only if** the product is not
  already known to you, and only the providers that are switched on for you (below). They receive the
  barcode number and the server's identifying User-Agent (`KidneyHealth/<version> (<contact>)`), nothing
  about you.
* **Nothing at all** leaves the server for barcodes until an admin turns a provider on: Open Food Facts
  is **off by default**, and USDA needs a key.

### Three ways to enter a barcode

* **Live scanning** with the camera needs **HTTPS** (or `localhost`): browsers give camera access only to
  secure pages. See [`https.md`](https.md) to set it up.
* **A photo of the barcode** works over plain HTTP too: the phone's camera app takes the picture and the
  page reads the code from it on the device.
* **Typing the digits** under the bars always works, also with a USB or Bluetooth scanner that types, and
  with a screen reader.

Every way ends the same: only the digits go to your server. A US 12-digit code, the same number read as
13 digits (with a leading 0), its 14-digit form and the short 8-digit UPC-E code all find the same food.

In the app: **Add → Scan** opens the three ways in one sheet.

* **Camera**: point it at the barcode inside the frame and hold still; the app takes a code only after
  reading the **same digits twice**, then stops the camera. The camera also stops when you close the
  sheet, switch apps or leave the page. If the camera sends no picture for 4 seconds, the sheet says so
  and offers the photo and typing instead. On a plain-HTTP address the camera button is replaced by why
  (camera access needs HTTPS) and the photo route.
* **Photo of a barcode**: the phone's own decoder reads it when the browser has one (Chrome on Android,
  for example); otherwise the app's built-in reader (about 1 MB, part of the app, downloaded from your
  server the first time it is needed and kept for offline use). Either way the photo stays on the device.
* **Type the barcode**: the check digit is checked as you submit; a wrong digit or an in-store code is
  explained under the field before anything is sent.

A found product opens the usual "Add food" sheet with where its data came from under the name: the
attribution (a link to the product page), the barcode, the quality notes, the additives found and the
ingredient list. Review the amount and log it.

### Turning lookups on

| Who | What | Where |
|---|---|---|
| Admin | Open Food Facts for the server: `food.off_enabled` | Settings → Admin → Server settings, the first-run setup checkbox, or `OFF_ENABLED=true` |
| Each person | "Send barcodes I scan to Open Food Facts": `food.off_consent` | Settings → Food data (it is personal: the admin's choice does not make it for you) |
| Admin or person | A USDA FoodData Central key (shared or your own) | Settings → Food data / Admin → Shared keys, or `USDA_API_KEY_FILE` |
| Admin | USDA branded barcode lookups: `food.usda_branded_barcode` (on) | Server settings or `USDA_BRANDED_BARCODE` |

If nothing is on for you, a scan answers "Barcode lookups are switched off on this server" (or asks you
to agree in Settings) and offers **Enter from the label**. Your own foods with a barcode are always found.

### How a lookup works

1. The number is checked first: the GS1 check digit, then the kind of code. **In-store codes** for
   weighed deli, meat and produce (prefixes 020–029, 040–049, 200–299) are refused, because they are only
   unique inside one shop and a lookup would return a stranger's product. Books (ISBN), magazines (ISSN),
   coupons and receipts are refused too. Nothing is sent anywhere for a refused code.
2. **Your own data**: a food you created with this barcode (Quick add, a new food, or a copy of a scanned
   one), then a shared product you scanned before. Your own copy always wins.
3. **Open Food Facts** (if on and agreed): the server's shared cache first. Found products are kept until
   someone taps refresh (at most once a day per product); "not found" is remembered for 24 hours.
4. **USDA FoodData Central, Branded Foods** (with a USDA key), when Open Food Facts does not know the
   product, has no nutrition facts for it, or lacks potassium or sodium for a US product. The app tries the
   12-, 13- and 14-digit forms of the barcode and accepts only an exact match. When USDA does not know a
   product and Open Food Facts is on but you have not agreed to it yet, the app asks whether to look it
   up there (it never says "not found" for a database it did not ask; a "not found" names the databases
   that were asked).
5. **Both found**: for a US product the numbers come from USDA (they come from the maker) and gaps are
   filled from Open Food Facts; otherwise the other way round. Every filled value is named in the notes.
   Flags from both ingredient lists are combined.

How the numbers are read (`app/off.py`; `ARCHITECTURE.md` "Open Food Facts client"):

* A label **per serving** is used as it is; a label **per 100 g or 100 mL** is scaled to the serving weight.
  A label per serving **without** a serving weight ("1 bar") cannot be scaled, so nothing is stored and the
  answer says why: enter the food from the package label.
* A product with **only "as prepared" values** (a boxed macaroni: made with milk and butter) keeps them per
  serving, but its serving weight is the product **as sold** (70.9 g of dry pasta makes a 198 g cup). The
  serving text ends "as sold, prepared" and the food is logged **in servings only**: the entry sheet has no
  grams box for it, and the server refuses grams (`400 grams: … log it in servings, not grams`), so 198 g
  can never count as 2.8 servings.
* A **drink** (a serving in millilitres, a label per 100 mL, or the beverages category; not a drink powder)
  counts toward a fluid limit: its fluid is the serving.
* **Impossible values are left out** and named in the notes: per 100 g, potassium above 60 g or phosphorus
  above 32 g (more than a food-grade salt can hold, so a salt substitute or cream of tartar keeps its
  number), sodium above 40 g (except salts), any macronutrient above 100 g, energy above 950 kcal.
* The **ingredient scan** flags named phosphate compounds and E-numbers; the bare word "phosphorus" (as in
  "a source of phosphorus") is not an additive.

The product is stored once on the server, read-only, and appears in your food search from then on.
To change it, make an editable copy of it; the copy keeps the barcode (and the attribution) and is what
you get next time.

### What you see, and how far to trust it

* **"Potassium: not listed"** and **"Phosphorus: not listed"** instead of 0. Most packaged foods do not
  list them (US labels have had potassium only since 2020; EU labels need neither). Unknown is not zero:
  your day's total will be too low.
* **Quality notes**, for example "Community data from Open Food Facts. Check it against the package",
  "Sodium was worked out from the salt figure (salt ÷ 2.5)", "Only the values for the prepared product
  are listed …, so it is logged in servings, not grams", "No serving size is listed, so the values are for 100 g", "The calories do not match the
  protein, fat and carbohydrate listed", and "A value was impossible for a food and was left out".
* **Additive flags** from the additive codes and the ingredient list (also in German, Dutch, French,
  Spanish, Italian and Portuguese):

  | Found | For example | Effect |
  |---|---|---|
  | A phosphate additive | phosphoric acid (E338), sodium phosphate, E450–E452 | phosphorus is **high** whatever the number says |
  | A potassium additive, **potassium not listed** | potassium chloride (E508), potassium lactate (E326) | a **medium** warning: "Contains a potassium additive; potassium not listed" |
  | A potassium additive, potassium listed | the same | the normal potassium thresholds |
  | A salt substitute | potassium chloride as the first ingredient, "NoSalt", "lite salt" | **avoid** with kidney disease |
  | A trace additive | potassium sorbate, acesulfame K, starch phosphates | a note, no warning |

  Products listing a potassium additive measured 750–1,100 mg potassium per 100 g, and additive potassium
  is about 90 % absorbed ([`docs/research/fact-check.md`](research/fact-check.md) §5). A missing additive
  is **not** proof there is none: 8 of 25 enhanced meat products in one study did not list theirs. The
  medium level is waiting for a renal dietitian's review ([`ROADMAP.md`](ROADMAP.md)).
* **Alcoholic drinks** (Open Food Facts category `en:alcoholic-beverages`; USDA records with at least 0.4 g
  ethanol per 100 g, about 0.5 % by volume, or named "Alcoholic beverage, …") get the `alcohol` flag: no
  warning, but meal guidance never suggests them, because with insulin alcohol can cause lows hours later
  ([`guidance.md`](guidance.md) "What guidance never does").
* **Attribution** under the name: "Product data © Open Food Facts contributors, ODbL" with a link to the
  product page, or the USDA FoodData Central citation.

### When nothing is found

The answer offers **Enter from the label**: Quick add opens with the barcode (and the product name, when
Open Food Facts knows the product without its nutrition facts). Type the numbers per serving and paste the
**ingredients**: the server reads them on save, so "sodium phosphate" sets the phosphate flag. The new food
keeps the barcode, so the next scan finds it at once.

You can also add the product to Open Food Facts for everyone: the answer carries the link
`https://world.openfoodfacts.org/cgi/product.pl?type=search_or_add&action=display&code=<barcode>`.

**Quick add with a photo of the label.** Quick add has *Use a photo of the label*: the photo is shown
beside the form on a wide screen (above it on a phone) with 1×, 2× and 3× zoom, so you can copy the
numbers. It stays on your device (the page shows it from memory and forgets it when you close Quick add).
Only if your admin set up AI with a vision model is there also **Read the label for me (AI)**, which sends
a resized copy (see [Photos](#photos)) and fills the fields, each marked "from photo" until you change it.
Under the **Ingredients** box the app says what saving will mark, as you type ("Saving marks this food:
Phosphate additives", "Potassium additives", or "Avoid with CKD" for a salt substitute): the same rules
the server applies when you save.

**Without a connection** a barcode cannot be looked up (the lookup runs on your server), but products you
scanned or opened before are in the offline food search, and what you log waits on the device until the
server can be reached ([`install-on-your-phone.md`](install-on-your-phone.md#offline)).

**In the demo** (`?mock=1` and the preview) Open Food Facts is "on" with three recorded products: Diet Coke
`049000028911`, Kraft macaroni & cheese `021000658831` and Nutella `3017624010701`. It still asks for your
agreement first, and any other barcode says it is not one of the three. The preview has no built-in
barcode reader and no camera: type the digits.

### Limits

* **60 lookups an hour per person** (products you already have do not count).
* **Open Food Facts allows 15 product lookups a minute from one address**, so the whole server shares a
  budget of `food.off_rate_per_minute` (10). When it is used up the answer is "Try again in N seconds"
  (HTTP 429 with `Retry-After`); nothing is queued in the background. If Open Food Facts itself says "slow
  down", the server pauses for a minute.
* A busy Open Food Facts (HTTP 503) is retried once after 2 seconds; then the answer is "could not be
  reached".

### Privacy

* The server stores the product data it fetched in a shared cache (`barcode_cache`) and the product
  itself as a shared food row. **Which products you scanned** is stored only as your link to that row; it
  is deleted with your account and is in your export.
* You never get another person's own foods, and you only get a cached product if you could have looked it
  up yourself at that moment (the provider is on for you), so the answer never tells you what someone else
  on the server scanned. A found product is always the same answer (HTTP 200) whether it came from the
  cache or not. A cache hit is faster than a real lookup; that timing difference remains and is accepted.

### Licences

* **Open Food Facts**: database under the [Open Database License](https://opendatacommons.org/licenses/odbl/1-0/)
  (ODbL), contents under the Database Contents License, images CC BY-SA (the app shows no images). Every
  Open Food Facts food carries its attribution and product link (the API returns them with the food),
  Settings shows the licence notice, the export archive's README says "rows marked ODbL-1.0 contain
  information from Open Food Facts …", and every CSV export has
  `source` and `source_license` columns (`ODbL-1.0`, `CC0-1.0`, or `CC0-1.0 AND ODbL-1.0` for a USDA
  product completed with Open Food Facts data). How the app changes the data (ODbL §4.6) is public:
  [`app/off.py`](../app/off.py) and [`app/additives.py`](../app/additives.py). A server that only you
  and your household use is not "public use" under the ODbL; one that strangers use is.
* **USDA FoodData Central**: public domain (CC0 1.0); citation: U.S. Department of Agriculture,
  Agricultural Research Service. FoodData Central. fdc.nal.usda.gov.
* The repository and the image contain no Open Food Facts data except a few single-product test fixtures
  (`tests/fixtures/off/README.md`).

### For operators

| Setting (env lock) | Default | Purpose |
|---|---|---|
| `food.off_enabled` (`OFF_ENABLED`) | `false` | Barcode lookups may contact Open Food Facts |
| `food.off_contact` (`OFF_CONTACT`) | `https://github.com/ksullivan86/kidney-health` | Contact in the User-Agent, as Open Food Facts asks; an admin email address is better |
| `food.off_rate_per_minute` (`OFF_RATE_PER_MINUTE`) | `10` (1–15) | Server-wide Open Food Facts budget |
| `food.barcode_negative_ttl_hours` (`BARCODE_NEGATIVE_TTL_HOURS`) | `24` (1–720) | How long "not found" is remembered |
| `food.usda_branded_barcode` (`USDA_BRANDED_BARCODE`) | `true` | USDA branded lookups by barcode (needs a key) |
| `food.off_consent` (personal) | `false` | Each person's agreement to send scans to Open Food Facts |
| `OFF_BASE_URL` (**env only**) | `https://world.openfoodfacts.org` | Staging (`https://world.openfoodfacts.net`) or your own Product Opener; `https://` only (plain `http://` only for localhost), no path |

* **Network**: allow `world.openfoodfacts.org:443` (and `api.nal.usda.gov:443` for USDA) — see
  [`network-allowlist.md`](network-allowlist.md). `images.openfoodfacts.org` is not needed.
* **SSRF protection**: every outbound call goes through `app/egress.py`, which resolves the host on each
  request, refuses private, link-local, metadata and reserved addresses (a custom `OFF_BASE_URL` host may
  be private: you chose it), connects to the checked address with the original host name for TLS, and
  never follows redirects. Answers are capped at 1 MiB (Open Food Facts) and 2 MiB (USDA) after
  decompression. If your server must use an HTTP proxy, set the standard `HTTPS_PROXY`/`NO_PROXY`
  variables; the proxy then resolves names and enforcing the allowlist is its job.
* **Several workers**: the per-minute budget and the hourly per-person limit are kept in memory per
  process. The image runs one process; if you run several, divide `food.off_rate_per_minute` by their
  number.
* **Maintenance**: `python -m app.admin remap-barcodes` re-applies a newer mapping to every cached product
  without the network (run it after an upgrade whose notes say so);
  `python -m app.admin purge-barcode-cache` removes expired "not found" entries now (the server does it
  daily).

### For developers

* Code: `app/gtin.py` (normalise, classify), `app/additives.py` (E-number tiers, ingredient scan),
  `app/textclean.py` (NFKC, invisible and control characters out, before anything is stored or scanned),
  `app/off.py` (client, pacing, trimming, mapping, quality, the API 3.5+ parser), `app/egress.py`
  (SSRF-checked transport), USDA branded in `app/foods.py`, the route in `app/barcode.py`, schema step
  `app/migrations/m007_barcode.py`. The warning rule is in `app/nutrients.py` with its browser twin in
  `app/static/js/engine/rules.js` (parity: `tests/data/rules_vectors.json`).
* Fixtures are real recorded answers (`scripts/record_barcode_fixtures.py off|usda`); tests replay them
  and never touch the network (`tests/test_off_mapping.py`, `test_usda_branded.py`, `test_barcode_api.py`).
* Browser: `app/static/js/scan.js` (`KH.scan`: decoder choice, camera, photo, typed digits, the answers'
  panels, provenance, Quick add's label photo), `css/device.css`, and the twins `js/engine/gtin.js`,
  `textclean.js`, `additives.js`, `off.js` (parity: `tests/data/barcode_vectors.json`, generator
  `tests/data/gen_barcode_vectors.py`, run by `node tests/js/run_vectors.mjs`). The demo route is
  `js/mock/barcode.js`; `tools/e2e/parity.py` section 13 compares it with the server.
* The built-in reader is vendored, never loaded from a CDN: `barcode-detector` 3.2.2 (`ponyfill.iife.js`)
  and `zxing-wasm` 3.1.3 (`zxing_reader.wasm`), MIT, built on ZXing-C++ (Apache-2.0), in
  `app/static/vendor/` with SHA-256 pins and licences in `app/static/vendor/README.md`.
  `python scripts/vendor_barcode.py` fetches them from the npm registry (checking npm's SHA-512 integrity
  and the pins); `--check` verifies the files offline (`tests/test_vendor.py`), `--check-latest` reports new
  releases (weekly in `.github/workflows/vendor-check.yml`, warning only). The page's CSP allows
  `'wasm-unsafe-eval'` for it.
* Browser checks: `tools/e2e/device.py` decodes a generated EAN-13 photo with the built-in reader and
  through the native-detector branch, scans with Chromium's fake camera on `http://localhost`, and checks
  the label photo upload (≤ 1600 px, no EXIF) against a fake OpenAI-compatible server.
* `scripts/check_off_live.py` checks the mapping against the live service (staging by default); the
  weekly workflow `.github/workflows/off-live-check.yml` runs it and only warns. Open Food Facts API 3.5+
  empties the classic `nutriments` object; the app pins 3.4 and keeps `parse_nutrition_v35` ready
  ([`ROADMAP.md`](ROADMAP.md)).

## Photos

Two optional photo features use the AI layer ([`ai.md`](ai.md)): **Read a label** turns a photo of a
nutrition label into a draft custom food, and **Plate photo** names the foods on a plate. Both are off
unless your admin set up an AI provider with a vision model; plate photos are also off by default
(`ai.vision_plate_enabled`). The barcode **photo** above is different: it is read on your device and
never uploaded.

### What leaves your device and the server

* **On your device** the app redraws the photo as a JPEG at most 1600 pixels on its long side, which
  removes the location and camera data (EXIF) and turns HEIC photos into JPEG.
* **The server does not trust that step** (any signed-in person could send a file directly). It accepts
  only a raw `image/jpeg` body of at most `MAX_IMAGE_BYTES` (4 MiB), checks the JPEG structure without
  decoding the picture (one frame, 8-bit, 16–2048 pixels per side, at most 4:1 and 4 megapixels),
  **removes every metadata segment (EXIF, XMP, ICC, comments) and anything after the end of the
  picture**, and forwards only those rewritten bytes (`app/imagecheck.py`). Oversized or malformed
  pictures are refused before anything is sent: a 52800×44 picture crashed a popular local model server
  in a public proof of concept, and a 4 MiB JPEG can declare 65535×65535 pixels.
* **The AI provider** receives the photo as a `data:image/jpeg;base64,…` part of one request, with the
  task text; never a link to it. Which provider and host: the consent sheet for **photos** says, and you
  agree to photos separately from meal ideas.
* **Nothing is kept**: photos are never written to disk, stored or logged. Your AI activity keeps the
  photo's SHA-256 fingerprint, size and dimensions only.
* A Hermes agent receives photos only if the admin allowed it (`AI_VISION_ALLOW_AGENT`) **and** its tool
  check passes right before each photo (text printed on a package could try to instruct an agent).

### Read a label

1. In **Add**, choose **Read a label (AI)** and take or pick a photo of the Nutrition Facts panel (and
   the ingredient list, if it fits).
2. The AI copies the printed values only (`null` for anything not printed). The server then:
   * scales a per-100 g or per-100 ml label to one serving when the serving weight is printed (or keeps
     it per 100 g and says so);
   * works out sodium from salt (salt ÷ 2.5) and, on US labels, potassium, phosphorus, sodium or calcium
     from the % Daily Value (FDA daily values 4700, 1250, 2300 and 1300 mg) — **marked "estimated"**;
   * checks plausibility: the calories against fat, carbohydrate and protein (within 20 % + 20 kcal),
     grams that add up to more than the serving, mineral values that are implausible for one serving
     (often mg read as g);
   * scans the ingredient text with the app's own rules (not the AI) and tells you what it found;
   * says "Potassium is not on this label; it is saved as unknown, not zero" when it is missing.
3. You get a **draft** with every value the AI read marked "from photo". **Check each one against the
   label.** Nothing is saved until you tap **Save**; saving is the ordinary "add a custom food", which
   scans the ingredient text **you confirmed** for phosphate and potassium additives.

### Plate photo

* The AI names the foods it sees and guesses a weight and how sure it is. It **never** gives nutrient
  numbers: each name is matched to foods in **your** food list (three at most), and the servings are
  worked out from the guessed weight.
* A fixed banner says: *"AI estimate from a photo. In studies, portion estimates were off by about a
  third and too small for big plates. Weigh or measure when it matters, and do not dose insulin from
  this alone."* (Fridolfsson et al. 2025, mean absolute error about 36 % for weight; note 03 F8.)
* Items the AI is unsure about start unticked. Nothing is logged until you tap **Add**; entries are
  added as **planned** by default.

### How far to trust it

AI can misread a label (350 mg as 35 mg, a missing potassium line); the plausibility checks catch some
of that, not all. Studies found large language models unreliable at estimating renal nutrients
themselves, which is why the app lets AI copy and name, never estimate (note 04 F7). For carbohydrate
counting with insulin, weigh or measure.

### For operators

`AI_VISION_MODEL` (empty = photos off), `ai.vision_plate_enabled` (`AI_VISION_PLATE_ENABLED`, off),
`ai.vision_allow_agent` (`AI_VISION_ALLOW_AGENT`, off), `AI_VISION_TIMEOUT_S` (120 s), `MAX_IMAGE_BYTES`
(4 MiB). Photos count toward the shared daily AI limit. Suggested local models: `qwen3-vl:8b` (6.1 GB) or
`qwen3-vl:4b` (3.3 GB) on Ollama, `gemma4:12b-it-qat` as an alternative (all Apache-2.0); not
`llama3.2-vision` as a default (its licence excludes the EU for the multimodal models). The API is
`POST /api/vision/label` and `POST /api/vision/plate` ([`ARCHITECTURE.md`](../ARCHITECTURE.md), "M2 API:
AI and photos"); tests are `tests/test_vision_api.py` and `tests/test_imagecheck.py`.
