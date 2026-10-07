/* Kidney Diet Log — the parts of app/off.py (and the USDA provenance texts of app/foods.py) the browser
   needs: attribution texts and licences, the product-page URL built from a constant, the "Add it to Open
   Food Facts" link, and the quality-note sentences (note 03 R3, R11, §9 B4).

   Pure, no I/O. js/scan.js shows the server's texts as they come; the demo API (js/mock/barcode.js,
   foods.js) builds the same answers with these. Parity: tests/data/barcode_vectors.json (quality_cases,
   demo_products). Exposes KH.off. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  const LICENSE = 'ODbL-1.0';
  const ATTRIBUTION_TEXT = 'Product data © Open Food Facts contributors, ODbL';
  const LICENSE_URL = 'https://opendatacommons.org/licenses/odbl/1-0/';
  const HOME_URL = 'https://world.openfoodfacts.org';
  const PRODUCT_PAGE_PREFIX = 'https://world.openfoodfacts.org/product/';
  const CONTRIBUTE_URL = 'https://world.openfoodfacts.org/cgi/product.pl?type=search_or_add&action=display&code=';
  const USDA_LICENSE = 'CC0-1.0';
  const USDA_HOME_URL = 'https://fdc.nal.usda.gov/';
  const USDA_ATTRIBUTION_TEXT = 'Product data: USDA FoodData Central (public domain, CC0)';
  // The ODbL §4.6 method file: how this app changes Open Food Facts data (shown in Settings → About).
  const METHOD_URL = 'https://github.com/ksullivan86/kidney-health/blob/main/app/off.py';

  const QUALITY_MESSAGES = {
    crowd_sourced: 'Community data from Open Food Facts. Check it against the package.',
    potassium_unknown: 'Potassium is not listed for this product: treat it as unknown, not zero.',
    phosphorus_unknown: 'Phosphorus is not listed for this product: treat it as unknown, not zero.',
    sodium_from_salt: 'Sodium was worked out from the salt figure (salt ÷ 2.5).',
    carbs_available: 'This label is not a US or Canadian one: its carbohydrate usually excludes fiber.',
    prepared_values: 'Only the values for the prepared product are listed (as made by the package directions), and the '
      + 'serving weight is the product as sold, so it is logged in servings, not grams.',
    ml_as_g: 'The serving is in millilitres; it is counted as grams (1 mL ≈ 1 g).',
    no_serving: 'No serving size is listed, so the values are for 100 g (or 100 mL).',
    serving_weight_unknown: 'The label\'s values are per serving, but no serving weight is listed, so they cannot be '
      + 'used. Enter the food from the package label.',
    energy_mismatch: 'The calories do not match the protein, fat and carbohydrate listed. One of them may be wrong.',
    implausible: 'A value was impossible for a food and was left out',
    no_nutrition: 'This product has no nutrition facts in Open Food Facts.',
    filled_from_usda: 'Missing values were filled in from USDA FoodData Central',
    filled_from_off: 'Missing values were filled in from Open Food Facts',
  };

  // off.off_code via KH.gtin when loaded (js/engine/gtin.js comes first in index.html).
  function productPage(gtin14) { return PRODUCT_PAGE_PREFIX + KH.gtin.offCode(gtin14); }
  function attribution(gtin14) { return { text: ATTRIBUTION_TEXT, url: productPage(gtin14), license: LICENSE }; }
  function usdaAttribution() { return { text: USDA_ATTRIBUTION_TEXT, url: USDA_HOME_URL, license: USDA_LICENSE }; }

  // off.quality_items: [{code, message}] in the stored order; a code may name a nutrient after a colon.
  function qualityItems(codes) {
    const NUT = KH.rules ? KH.rules.NUT : {};
    const out = [];
    for (const stored of codes || []) {
      const text = String(stored);
      const at = text.indexOf(':');
      const code = at < 0 ? text : text.slice(0, at);
      const key = at < 0 ? '' : text.slice(at + 1);
      let message = Object.prototype.hasOwnProperty.call(QUALITY_MESSAGES, code) ? QUALITY_MESSAGES[code] : null;
      if (message == null) continue; // a code from a newer version this one does not know
      if (key) message = `${message}: ${NUT[key] ? NUT[key].label.toLowerCase() : key}.`;
      else if (code === 'implausible' || code === 'filled_from_usda' || code === 'filled_from_off') message = `${message}.`;
      out.push({ code, message });
    }
    return out;
  }
  // An https: URL from the server, or null: the UI sets an href only when this says yes (§9 B4).
  function safeHttpsUrl(value) {
    try { const u = new URL(String(value)); return u.protocol === 'https:' ? u.href : null; } catch (e) { return null; }
  }

  // foods.weight_known / WEIGHT_UNKNOWN_CODES / WEIGHT_UNKNOWN_DETAIL: a product with only prepared values has
  // nutrients per serving as prepared but a serving weight as sold (Kraft macaroni: 70.9 g dry makes a 198 g cup),
  // so it is logged in servings only; the log refuses grams for it with this text. `quality` holds stored codes
  // ("implausible:sodium_mg") on a demo food row or {code, message} items on a Food answer.
  const WEIGHT_UNKNOWN_CODES = ['prepared_values', 'serving_weight_unknown'];
  const WEIGHT_UNKNOWN_DETAIL = "grams: this product's values are for it as prepared, but its serving weight is the product "
    + 'as sold, so log it in servings, not grams';
  function weightKnown(food) {
    const items = (food && food.quality) || [];
    return !items.some((q) => WEIGHT_UNKNOWN_CODES.includes(String(q && typeof q === 'object' ? q.code : q).split(':')[0]));
  }

  KH.off = { LICENSE, ATTRIBUTION_TEXT, LICENSE_URL, HOME_URL, PRODUCT_PAGE_PREFIX, CONTRIBUTE_URL, USDA_LICENSE, USDA_HOME_URL,
    USDA_ATTRIBUTION_TEXT, METHOD_URL, QUALITY_MESSAGES, productPage, attribution, usdaAttribution, qualityItems, safeHttpsUrl,
    WEIGHT_UNKNOWN_CODES, WEIGHT_UNKNOWN_DETAIL, weightKnown };
})();
