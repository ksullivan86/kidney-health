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

Every way ends the same: only the digits go to your server. A 12-, 13- or 8-digit code, a short UPC-E
code and a 14-digit case code of the same product all find the same food.

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
   12-, 13- and 14-digit forms of the barcode and accepts only an exact match.
5. **Both found**: for a US product the numbers come from USDA (they come from the maker) and gaps are
   filled from Open Food Facts; otherwise the other way round. Every filled value is named in the notes.
   Flags from both ingredient lists are combined.

The product is stored once on the server, read-only, and appears in your food search from then on.
To change it, make an editable copy of it; the copy keeps the barcode (and the attribution) and is what
you get next time.

### What you see, and how far to trust it

* **"Potassium: not listed"** and **"Phosphorus: not listed"** instead of 0. Most packaged foods do not
  list them (US labels have had potassium only since 2020; EU labels need neither). Unknown is not zero:
  your day's total will be too low.
* **Quality notes**, for example "Community data from Open Food Facts. Check it against the package",
  "Sodium was worked out from the salt figure (salt ÷ 2.5)", "Only the values for the prepared product
  are listed", "No serving size is listed, so the values are for 100 g", "The calories do not match the
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
* **Attribution** under the name: "Product data © Open Food Facts contributors, ODbL" with a link to the
  product page, or the USDA FoodData Central citation.

### When nothing is found

The answer offers **Enter from the label**: Quick add opens with the barcode (and the product name, when
Open Food Facts knows the product without its nutrition facts). Type the numbers per serving and paste the
**ingredients**: the server reads them on save, so "sodium phosphate" sets the phosphate flag. The new food
keeps the barcode, so the next scan finds it at once.

You can also add the product to Open Food Facts for everyone: the answer carries the link
`https://world.openfoodfacts.org/cgi/product.pl?type=search_or_add&action=display&code=<barcode>`.

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
* `scripts/check_off_live.py` checks the mapping against the live service (staging by default); the
  weekly workflow `.github/workflows/off-live-check.yml` runs it and only warns. Open Food Facts API 3.5+
  empties the classic `nutriments` object; the app pins 3.4 and keeps `parse_nutrition_v35` ready
  ([`ROADMAP.md`](ROADMAP.md)).

## Photos

*This section belongs to the optional photo features (a photo of a nutrition label read by AI, a photo
of a plate) built with the AI layer (note 03 R8–R9, note 04). Their owner documents here what a photo
does, what leaves the device and which provider sees it.* Until then: the barcode **photo** above is read
on your device and never uploaded.
