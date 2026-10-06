/* Kidney Diet Log — demo API: POST /api/foods/barcode (twin of app/barcode.py as seen from a demo server).

   The demo never contacts Open Food Facts or USDA. It answers like a server where Open Food Facts lookups are
   on (js/mock/settings.js locks OFF_ENABLED on, as an environment variable would) and USDA has no key, but its
   "Open Food Facts" knows only three products, recorded from Open Food Facts (ODbL, © Open Food Facts
   contributors; insubstantial single-product extracts, as tests/fixtures/off/README.md describes):

     Diet Coke 049000028911 (UPC-A) · Kraft Macaroni & Cheese 021000658831 (UPC-A) · Nutella 3017624010701 (EAN-13)

   Everything else follows the server: the body model (BarcodeLookup, unknown fields refused), normalising and
   classifying the code (js/engine/gtin.js; the same 400 reasons and texts), the person's own custom food with
   that barcode first, then a shared food they already scanned, the 60-an-hour limit, the person's consent
   (food.off_consent: 503 off_consent_required until they agree), one shared read-only `off` row per product
   linked to the person, attribution and quality notes. A product barcode the demo does not know answers 404
   like an Open Food Facts miss, with a demo sentence naming the three samples.

   DEMO_PRODUCTS are the rows the server stores for those fixtures (generated: tests/data/gen_barcode_vectors.py
   writes them into tests/data/barcode_vectors.json "demo_products"; tests/test_barcode_vectors.py keeps this
   block equal to it, and `node tests/js/run_vectors.mjs` rebuilds the server's answers from it). */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const G = KH.gtin;
  const { route, MockApi, Check, fail } = M;

  /* DEMO_PRODUCTS:BEGIN (generated; see above) */
  const DEMO_PRODUCTS = [
    {
      "fixture": "diet_coke_v3.4",
      "code": "049000028911",
      "format": "upc_a",
      "row": {
        "name": "Diet Coke Soft Drink",
        "brand": "Coke",
        "category": "Beverages",
        "source": "off",
        "serving_desc": "1 can (354.9 mL)",
        "serving_g": 354.9,
        "kidney_notes": "Contains phosphoric acid (E338), a phosphate additive. Contains potassium benzoate (E212): a small amount of potassium (no warning).",
        "gtin": "00049000028911",
        "source_url": "https://world.openfoodfacts.org/product/0049000028911",
        "source_license": "ODbL-1.0",
        "ingredients_text": "CARBONATED WATER, CARAMEL COLOR, ASPARTAME acts PHOSPHORIC ACID, POTASSIUM BENZOATE (TO PROTECT TASTE), NATURAL FLAVORS, CITRIC ACID, CAFFEINE",
        "nutrients": {
          "calories_kcal": 0.0,
          "protein_g": 0.0,
          "fat_g": 0.0,
          "sat_fat_g": null,
          "carbs_g": 0.0,
          "fiber_g": null,
          "sugar_g": null,
          "sodium_mg": 40.0,
          "potassium_mg": null,
          "phosphorus_mg": null,
          "calcium_mg": null,
          "fluid_ml": 355.0
        },
        "flags": [
          "phosphate_additive",
          "counts_as_fluid",
          "processed"
        ],
        "additives": [
          "e338"
        ],
        "quality": [
          "crowd_sourced",
          "ml_as_g",
          "potassium_unknown",
          "phosphorus_unknown"
        ]
      }
    },
    {
      "fixture": "kraft_mac_cheese_v3.4",
      "code": "021000658831",
      "format": "upc_a",
      "row": {
        "name": "mac & cheese",
        "brand": "Kraft",
        "category": "Grains & Breads",
        "source": "off",
        "serving_desc": "1 serving (70.874 g) (prepared)",
        "serving_g": 70.9,
        "kidney_notes": "Contains triphosphates (E451), a phosphate additive. Contains calcium phosphates (E341), a phosphate additive. Contains sodium phosphates (E339), a phosphate additive.",
        "gtin": "00021000658831",
        "source_url": "https://world.openfoodfacts.org/product/0021000658831",
        "source_license": "ODbL-1.0",
        "ingredients_text": "ENRICHED MACARONI (WHEAT FLOUR, DURUM FLOUR, NIACIN, FERROUS SULFATE [IRON], THIAMIN MONONITRATE [VITAMIN B1], RIBOFLAVIN [VITAMIN B2], FOLIC ACID), CHEESE SAUCE MIX (WHEY, MILKFAT, SALT, MILK PROTEIN CONCENTRATE, SODIUM TRIPHOSPHATE, TAPIOCA FLOUR, CITRIC ACID, CALCIUM PHOSPHATE, SODIUM PHOSPHATE, LACTIC ACID, PAPRIKA, TURMERIC, ANNATTO, CHEESE CULTURE, ENZYMES)",
        "nutrients": {
          "calories_kcal": 350.0,
          "protein_g": 10.0,
          "fat_g": 1.0,
          "sat_fat_g": 4.0,
          "carbs_g": 50.0,
          "fiber_g": 2.0,
          "sugar_g": 10.0,
          "sodium_mg": 710.0,
          "potassium_mg": 370.0,
          "phosphorus_mg": null,
          "calcium_mg": 130.0,
          "fluid_ml": 0.0
        },
        "flags": [
          "phosphate_additive",
          "processed"
        ],
        "additives": [
          "e451",
          "e341",
          "e339"
        ],
        "quality": [
          "crowd_sourced",
          "prepared_values",
          "energy_mismatch",
          "phosphorus_unknown"
        ]
      }
    },
    {
      "fixture": "nutella_v3.4",
      "code": "3017624010701",
      "format": "ean_13",
      "row": {
        "name": "Nutella",
        "brand": "Ferrero",
        "category": null,
        "source": "off",
        "serving_desc": "100 g",
        "serving_g": 100.0,
        "kidney_notes": null,
        "gtin": "03017624010701",
        "source_url": "https://world.openfoodfacts.org/product/3017624010701",
        "source_license": "ODbL-1.0",
        "ingredients_text": "sugar, palm oil, hazelnuts (13%), skimmed milk powder (8.7%), fat reduced cocoa (7.4%), emulsifier: lecithins (soya), vanillin",
        "nutrients": {
          "calories_kcal": 539.0,
          "protein_g": 6.3,
          "fat_g": 30.9,
          "sat_fat_g": 10.6,
          "carbs_g": 57.5,
          "fiber_g": null,
          "sugar_g": 56.3,
          "sodium_mg": 43.0,
          "potassium_mg": null,
          "phosphorus_mg": null,
          "calcium_mg": null,
          "fluid_ml": 0.0
        },
        "flags": [],
        "additives": [],
        "quality": [
          "crowd_sourced",
          "no_serving",
          "carbs_available",
          "sodium_from_salt",
          "potassium_unknown",
          "phosphorus_unknown"
        ]
      }
    }
  ];
  /* DEMO_PRODUCTS:END */

  const LOOKUPS_PER_HOUR = 60;
  const LIMIT_MESSAGE = 'Too many barcode lookups this hour. Try again later, or enter the food from its label.';
  const DEMO_NOT_FOUND = 'This demo knows only three sample products, recorded from Open Food Facts: Diet Coke (049000028911), '
    + 'Kraft Macaroni & Cheese (021000658831) and Nutella (3017624010701). Enter this food from its label; in the installed app '
    + 'the server asks Open Food Facts for any product barcode.';
  const LOOKUPS_OFF = 'Barcode lookups are switched off on this server. Enter the food from its label, or ask your admin to '
    + 'turn on Open Food Facts lookups in Settings.';
  const CONSENT_REQUIRED = 'To look this barcode up, turn on “Send barcodes I scan to Open Food Facts” in Settings → '
    + 'Food data. Or enter the food from its label.';
  const PY_TRUE = new Set(['1', 'on', 't', 'true', 'y', 'yes']);
  const PY_FALSE = new Set(['0', 'off', 'f', 'false', 'n', 'no']);
  const BY_GTIN = new Map(DEMO_PRODUCTS.map((p) => [p.row.gtin, p.row]));

  // BarcodeLookup: code (1–64 characters, not stripped), format, refresh (pydantic's lax bool); no other field.
  function lookupBody(body) {
    const c = new Check(body);
    if (!c.has('code')) c.err('code', 'Field required');
    else if (typeof body.code !== 'string') c.err('code', 'Input should be a valid string');
    else if (body.code.length < 1) c.err('code', 'String should have at least 1 character');
    else if (body.code.length > 64) c.err('code', 'String should have at most 64 characters');
    else c.out.code = body.code;
    c.choice('format', G.FORMATS, { def: 'unknown' });
    if (!c.has('refresh')) c.out.refresh = false;
    else {
      const v = body.refresh;
      if (typeof v === 'boolean') c.out.refresh = v;
      else if (typeof v === 'number' && (v === 0 || v === 1)) c.out.refresh = v === 1;
      else if (typeof v === 'string' && (PY_TRUE.has(v.toLowerCase()) || PY_FALSE.has(v.toLowerCase()))) c.out.refresh = PY_TRUE.has(v.toLowerCase());
      else c.err('refresh', typeof v === 'string' || (typeof v === 'number' && Number.isInteger(v))
        ? 'Input should be a valid boolean, unable to interpret input' : 'Input should be a valid boolean');
    }
    for (const k of Object.keys(c.body)) if (!['code', 'format', 'refresh'].includes(k)) c.err(k, 'Extra inputs are not permitted');
    return c.done();
  }

  Object.assign(MockApi.prototype, {
    // barcode._attributions_of_row
    _attributionsOfRow(row) {
      const license = row.source_license || '';
      const out = [];
      if (license.includes('CC0-1.0') && row.source === 'usda') out.push(KH.off.usdaAttribution());
      if (license.includes('ODbL-1.0') && row.gtin) out.push(KH.off.attribution(row.gtin));
      if (license.includes('CC0-1.0') && row.source !== 'usda') out.push(KH.off.usdaAttribution());
      return out;
    },
    _barcodeResult(row, gtin14, source, attributions) {
      const food = this._foodView(row);
      return { food, gtin: gtin14, source, attribution: attributions[0] || null, attributions, quality: food.quality };
    },
    // The person's own custom food with this barcode (newest first), else a shared food they already have.
    _barcodeLocal(gtin14) {
      const newest = (rows) => rows.sort((a, b) => (a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : b.id - a.id))[0] || null;
      const own = newest(this._foods.filter((f) => f.source === 'custom' && f.gtin === gtin14 && !f.hidden));
      if (own) return [own, 'local'];
      const linked = newest(this._foods.filter((f) => (f.source === 'off' || f.source === 'usda') && f.gtin === gtin14 && !f.hidden
        && this._foodLinks().has(f.id)));
      return linked ? [linked, linked.source] : [null, ''];
    },
    // The per-person limit (60 lookups an hour, sliding): 429 with retry_after.
    _takeBarcodeLookup() {
      const now = Date.now();
      const hits = (this._barcodeHits || []).filter((t) => now - t < 3600 * 1000);
      if (hits.length >= LOOKUPS_PER_HOUR) {
        const wait = Math.max(1, Math.ceil((hits[0] + 3600 * 1000 - now) / 1000));
        this._barcodeHits = hits;
        fail(429, LIMIT_MESSAGE, { retry_after: wait });
      }
      hits.push(now);
      this._barcodeHits = hits;
    },
    // barcode.store: the one shared `off` row for the barcode, updated in place; then linked to the person.
    _storeDemoProduct(product) {
      let row = this._foods.find((f) => f.source === 'off' && f.gtin === product.gtin) || null;
      const values = { name: product.name, brand: product.brand, category: product.category, serving_desc: product.serving_desc,
        serving_g: product.serving_g, nutrients: { ...product.nutrients }, flags: [...product.flags], kidney_notes: product.kidney_notes };
      const provenance = { gtin: product.gtin, source_url: product.source_url, source_license: product.source_license,
        ingredients_text: product.ingredients_text, additives: [...product.additives], quality: [...product.quality] };
      if (row) this._updateFood(row.id, { ...values, hidden: false, provenance });
      else row = this._food(this._insertFood({ source: 'off', ...values, ...provenance }));
      this._foodLinks().add(row.id);
      return row;
    },
  });

  route('POST', '/api/foods/barcode', function ({ body }) {
    const b = lookupBody(body);
    let gtin14;
    try { gtin14 = G.normalize(b.code, b.format); } catch (e) {
      if (!(e instanceof G.GtinError)) throw e;
      fail(400, e.message, { reason: e.reason });
    }
    const kind = G.classify(gtin14);
    if (kind !== 'retail') fail(400, G.CLASS_MESSAGES[kind], { reason: kind, gtin: gtin14 });

    const [row, source] = this._barcodeLocal(gtin14);
    if (row && (!b.refresh || source === 'local')) return this._barcodeResult(row, gtin14, source, this._attributionsOfRow(row));

    this._takeBarcodeLookup();
    const u = this._currentUser();
    const offEnabled = !!this._effectiveSetting('food.off_enabled', null).value;
    const consent = !!this._effectiveSetting('food.off_consent', u.id).value;
    const product = BY_GTIN.get(gtin14) || null;
    const offStatus = !offEnabled ? 'disabled' : !consent ? 'consent_required' : product ? 'found' : 'not_found';
    // USDA is needed when Open Food Facts missed or lacks potassium or sodium (the samples are US or EU labels);
    // the demo has no USDA key, so it is never usable.
    const usdaNeeded = offStatus !== 'found' || product.nutrients.potassium_mg == null || product.nutrients.sodium_mg == null;
    const usdaEnabled = !!this._effectiveSetting('food.usda_branded_barcode', null).value;
    const usda = !usdaNeeded ? 'skipped' : !usdaEnabled ? 'disabled' : 'not_configured';
    const checked = { off: offStatus, usda };
    if (offStatus === 'found') {
      const stored = this._storeDemoProduct(product);
      return this._barcodeResult(stored, gtin14, 'off', [KH.off.attribution(gtin14)]);
    }
    if (row) return this._barcodeResult(row, gtin14, source, this._attributionsOfRow(row)); // a refresh found nothing new
    if (offStatus === 'consent_required') fail(503, CONSENT_REQUIRED, { reason: 'off_consent_required', gtin: gtin14, checked });
    if (offStatus === 'disabled') fail(503, LOOKUPS_OFF, { reason: 'lookups_off', gtin: gtin14, checked });
    fail(404, DEMO_NOT_FOUND, { gtin: gtin14, name: null, checked, contribute_url: KH.off.CONTRIBUTE_URL + G.offCode(gtin14) });
    return null;
  });

  Object.assign(M, { DEMO_PRODUCTS, barcodeLookupBody: lookupBody });
})();
