/* Kidney Diet Log — the parts of app/off.py (and the USDA provenance texts of app/foods.py) the browser
   needs: attribution texts and licences, the product-page URL built from a constant, the "Add it to Open
   Food Facts" link, and the quality-note sentences (note 03 R3, R11, §9 B4).

   It also holds the twins of off.trim_product and off.map_product (KH.off.trimProduct, mapProduct, row), so a
   page with no server (device mode, design note 38 §5.3) can turn the raw Open Food Facts answer into the row the
   server stores, and KH.off.py: Python's reading of JSON values, which js/engine/usda.js uses too. Needs KH.rules,
   KH.textclean, KH.gtin and KH.additives (loaded before this file in index.html).

   Pure, no I/O. js/scan.js shows the server's texts as they come; the demo API (js/mock/barcode.js,
   foods.js) builds the same answers with these. Parity: tests/data/barcode_vectors.json (quality_cases,
   demo_products, off_map_cases). Exposes KH.off. */
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

  // ---------------------------------------------------------------------------
  // Python's view of a JSON value. The server reads the same JSON with Python's rules (a missing key is
  // None; "", 0 and [] are false; float() takes "1_000" and " 12 "), so the twins below use these.
  // JSON.parse cannot tell 208 from 208.0: every whole number is read as a Python int here.
  // ---------------------------------------------------------------------------
  class PyError extends Error {} // float("x"), int([]) and the like: Python's ValueError or TypeError
  const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  function isMapping(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }
  // dict.get(key): null when the key is missing (or the value is not a dict at all).
  function get(o, k) { return isMapping(o) && hasOwn(o, k) && o[k] !== undefined ? o[k] : null; }
  function truthy(v) {
    if (v == null) return false;
    if (typeof v === 'boolean') return v;
    if (typeof v === 'number') return v !== 0;
    if (typeof v === 'string' || Array.isArray(v)) return v.length > 0;
    return Object.keys(v).length > 0;
  }
  // Python's `a or b`.
  function or(a, b) { return truthy(a) ? a : b; }
  // `for x in value`: a list as it is; a string or a dict gives items no caller can use; a number cannot be walked.
  function iter(v) {
    if (Array.isArray(v)) return v;
    if (!truthy(v) || typeof v === 'string' || isMapping(v)) return [];
    throw new PyError('not iterable');
  }

  // The first code point of each run of ten Unicode decimal digits (Python's unicodedata 15.1): float() and int()
  // read "١٢" as 12.
  const DIGIT_ZEROS = [0x30, 0x660, 0x6f0, 0x7c0, 0x966, 0x9e6, 0xa66, 0xae6, 0xb66, 0xbe6, 0xc66, 0xce6, 0xd66, 0xde6, 0xe50,
    0xed0, 0xf20, 0x1040, 0x1090, 0x17e0, 0x1810, 0x1946, 0x19d0, 0x1a80, 0x1a90, 0x1b50, 0x1bb0, 0x1c40, 0x1c50, 0xa620, 0xa8d0,
    0xa900, 0xa9d0, 0xa9f0, 0xaa50, 0xabf0, 0xff10, 0x104a0, 0x10d30, 0x11066, 0x110f0, 0x11136, 0x111d0, 0x112f0, 0x11450,
    0x114d0, 0x11650, 0x116c0, 0x11730, 0x118e0, 0x11950, 0x11c50, 0x11d50, 0x11da0, 0x11f50, 0x16a60, 0x16ac0, 0x16b50,
    0x1d7ce, 0x1d7d8, 0x1d7e2, 0x1d7ec, 0x1d7f6, 0x1e140, 0x1e2f0, 0x1e4f0, 0x1e950, 0x1fbf0];
  // What float() and int() do first: Unicode digits become ASCII ones, Unicode spaces a space, any other
  // non-ASCII character something no number can contain; then the ends are trimmed.
  function asciiNumberText(text) {
    let out = '';
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      if (cp < 127) { out += ch; continue; }
      if (KH.textclean.isPySpace(ch)) { out += ' '; continue; }
      const zero = DIGIT_ZEROS.find((z) => cp >= z && cp <= z + 9);
      out += zero === undefined ? '?' : String(cp - zero);
    }
    return out.replace(/^[ \t\n\v\f\r]+|[ \t\n\v\f\r]+$/g, ''); // Py_ISSPACE: ASCII spaces only
  }
  const DIGITS_PART = '[0-9](?:_?[0-9])*'; // Python allows one underscore between digits
  const FLOAT_TEXT = new RegExp(`^[+-]?(?:${DIGITS_PART}(?:\\.(?:${DIGITS_PART})?)?|\\.${DIGITS_PART})(?:[eE][+-]?${DIGITS_PART})?$`);
  const FLOAT_WORDS = /^([+-]?)(inf|infinity|nan)$/i;
  const INT_TEXT = new RegExp(`^[+-]?${DIGITS_PART}$`);
  // float(value), or throws PyError.
  function float(value) {
    if (typeof value === 'boolean') return value ? 1 : 0;
    if (typeof value === 'number') return value;
    if (typeof value !== 'string') throw new PyError('float() needs a number or text');
    const text = asciiNumberText(value);
    const word = FLOAT_WORDS.exec(text);
    if (word) return word[2].toLowerCase() === 'nan' ? NaN : (word[1] === '-' ? -Infinity : Infinity);
    if (!FLOAT_TEXT.test(text)) throw new PyError('could not convert text to a float');
    return Number(text.replace(/_/g, ''));
  }
  // int(value), or throws PyError (a whole number past 2^53 loses its last digits here).
  function int(value) {
    if (typeof value === 'boolean') return value ? 1 : 0;
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) throw new PyError('cannot convert to an integer');
      return Math.trunc(value) + 0; // + 0: Python has no -0 integer
    }
    if (typeof value !== 'string') throw new PyError('int() needs a number or text');
    const text = asciiNumberText(value);
    if (!INT_TEXT.test(text)) throw new PyError('invalid text for int()');
    return Number(text.replace(/_/g, '')) + 0;
  }
  // repr() of a str: Python's quotes and escapes.
  const UNPRINTABLE = /^[\p{C}\p{Z}]$/u;
  function strRepr(text) {
    const quote = text.includes("'") && !text.includes('"') ? '"' : "'";
    let out = quote;
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      if (ch === '\\' || ch === quote) out += `\\${ch}`;
      else if (ch === '\n') out += '\\n';
      else if (ch === '\r') out += '\\r';
      else if (ch === '\t') out += '\\t';
      else if (ch !== ' ' && UNPRINTABLE.test(ch)) {
        if (cp <= 0xff) out += `\\x${cp.toString(16).padStart(2, '0')}`;
        else if (cp <= 0xffff) out += `\\u${cp.toString(16).padStart(4, '0')}`;
        else out += `\\U${cp.toString(16).padStart(8, '0')}`;
      } else out += ch;
    }
    return out + quote;
  }
  function repr(v) {
    if (typeof v === 'string') return strRepr(v);
    if (Array.isArray(v)) return `[${v.map(repr).join(', ')}]`;
    if (isMapping(v)) return `{${Object.entries(v).map(([k, x]) => `${strRepr(k)}: ${repr(x)}`).join(', ')}}`;
    return str(v);
  }
  // str(value).
  function str(v) {
    if (v == null) return 'None';
    if (typeof v === 'boolean') return v ? 'True' : 'False';
    if (typeof v === 'string') return v;
    if (typeof v === 'number') return Number.isInteger(v) ? BigInt(v).toString() : KH.rules.pyRepr(v);
    return repr(v);
  }
  const py = { PyError, isMapping, get, truthy, or, iter, float, int, str, repr };

  // ---------------------------------------------------------------------------
  // off.trim_product and off.map_product: an Open Food Facts product (fresh or trimmed) to the food the server
  // stores (note 03 R3). Each helper twins the Python one of the same name; app/off.py explains the rules.
  // ---------------------------------------------------------------------------
  const MAX_NAME_CHARS = 200;
  const MAX_SERVING_DESC_CHARS = 60;
  const MAX_INGREDIENTS_CHARS = 4000;
  const MAX_TAGS = 200;
  const MAX_SERVING_G = 100000;
  const MAX_NUTRIENT_VALUE = 1000000;
  const NUTRIENT_MAP = [ // [app key, OFF nutrient, multiplier from OFF's unit]
    ['protein_g', 'proteins', 1], ['fat_g', 'fat', 1], ['sat_fat_g', 'saturated-fat', 1], ['fiber_g', 'fiber', 1],
    ['sugar_g', 'sugars', 1], ['potassium_mg', 'potassium', 1000], ['phosphorus_mg', 'phosphorus', 1000],
    ['calcium_mg', 'calcium', 1000],
  ];
  const KJ_PER_KCAL = 4.184;
  const SALT_PER_SODIUM = 2.5;
  const KEPT_NUTRIENTS = ['energy-kcal', 'energy-kj', 'energy', 'proteins', 'fat', 'saturated-fat', 'carbohydrates',
    'carbohydrates-total', 'fiber', 'sugars', 'sodium', 'salt', 'potassium', 'phosphorus', 'calcium'];
  const KEPT_SUFFIXES = ['', '_100g', '_serving', '_prepared', '_prepared_100g', '_prepared_serving', '_unit'];
  const CATEGORY_MAP = [
    [['en:beverages'], 'Beverages'],
    [['en:dairies'], 'Dairy & Alternatives'],
    [['en:meats', 'en:eggs'], 'Meat, Poultry & Eggs'],
    [['en:seafood', 'en:fishes'], 'Fish & Seafood'],
    [['en:breads', 'en:breakfast-cereals', 'en:pastas'], 'Grains & Breads'],
    [['en:legumes', 'en:nuts', 'en:seeds'], 'Legumes, Nuts & Seeds'],
    [['en:fruits'], 'Fruits'],
    [['en:vegetables'], 'Vegetables'],
    [['en:snacks', 'en:desserts', 'en:confectioneries'], 'Sweets & Snacks'],
    [['en:condiments', 'en:sauces'], 'Condiments & Sauces'],
    [['en:meals', 'en:pizzas'], 'Prepared & Fast Food'],
  ];
  const SWEETENED_BEVERAGE_TAG = 'en:sweetened-beverages';
  const HIGH_GI_MIN_SUGARS_PER_100 = 5;
  const ALCOHOLIC_BEVERAGES_TAG = 'en:alcoholic-beverages';
  const SALT_TAG = 'en:salts';
  const US_CA_TAGS = ['en:united-states', 'en:canada'];
  const DRY_TAGS = ['en:dried-products-to-be-rehydrated', 'en:dehydrated-beverages', 'en:instant-beverages'];
  const MAX_PER_100 = [ // judged per 100 g or 100 mL, in the server's order
    ['sodium_mg', 40000], ['potassium_mg', 60000], ['phosphorus_mg', 32000], ['calories_kcal', 950], ['protein_g', 100],
    ['fat_g', 100], ['sat_fat_g', 100], ['carbs_g', 100], ['fiber_g', 100], ['sugar_g', 100], ['calcium_mg', 40000],
  ];
  const ENERGY_MISMATCH_FRACTION = 0.25;
  const ENERGY_MISMATCH_MIN_KCAL = 40;
  // [multiply, divide] to grams.
  const UNIT_TO_GRAMS = new Map([['g', [1, 1]], ['mg', [1, 1000]], ['µg', [1, 1e6]], ['μg', [1, 1e6]], ['mcg', [1, 1e6]],
    ['ug', [1, 1e6]], ['kg', [1000, 1]]]);

  const label = (value, maxLen) => KH.textclean.cleanLabel(value, { maxLen });
  const fold = (text) => KH.textclean.casefold(text);

  function keptNutrimentKey(key) {
    for (const name of KEPT_NUTRIENTS) {
      if (key === name || key.startsWith(`${name}_`)) return KEPT_SUFFIXES.includes(key.slice(name.length));
    }
    return false;
  }
  // off._finite_number: a number, or text such as "12,5"; null for anything else, NaN and infinity.
  function finiteNumber(value) {
    let number;
    if (typeof value === 'boolean') return null;
    if (typeof value === 'number') number = value;
    else if (typeof value === 'string') {
      try { number = float(KH.textclean.pyStrip(value).replace(/,/g, '.')); } catch (e) { if (e instanceof PyError) return null; throw e; }
    } else return null;
    return Number.isFinite(number) ? number : null;
  }
  function stringList(value, limit = MAX_TAGS) {
    if (!Array.isArray(value)) return [];
    const out = [];
    for (const item of value.slice(0, limit)) {
      const cleaned = label(item, 100);
      if (cleaned) out.push(fold(cleaned));
    }
    return out;
  }
  function trimAggregated(value) {
    if (!isMapping(value)) return null;
    const nutrients = get(value, 'nutrients');
    if (!isMapping(nutrients)) return null;
    const kept = {};
    for (const name of KEPT_NUTRIENTS) {
      const item = get(nutrients, name);
      if (!isMapping(item)) continue;
      const number = finiteNumber(get(item, 'value'));
      const unit = label(get(item, 'unit'), 10);
      if (number != null && unit) kept[name] = { value: number, unit };
    }
    const out = { nutrients: kept };
    for (const key of ['per', 'preparation']) {
      const cleaned = label(get(value, key), 20);
      if (cleaned) out[key] = fold(cleaned);
    }
    return out;
  }
  // off.trim_product: the copy the server caches, and what map_product reads.
  function trimProduct(product) {
    const out = {};
    const put = (key, value) => { if (value) out[key] = value; };
    for (const key of ['code', 'lang']) put(key, label(get(product, key), 40));
    for (const key of ['product_name', 'product_name_en', 'generic_name', 'brands', 'quantity']) put(key, label(get(product, key), MAX_NAME_CHARS));
    put('serving_size', label(get(product, 'serving_size'), MAX_NAME_CHARS));
    for (const key of ['ingredients_text', 'ingredients_text_en']) {
      put(key, KH.textclean.cleanText(get(product, key), { maxLen: MAX_INGREDIENTS_CHARS, keepNewlines: true }));
    }
    for (const key of ['serving_quantity', 'nova_group', 'last_modified_t']) {
      const number = finiteNumber(get(product, key));
      if (number != null) out[key] = number;
    }
    for (const key of ['serving_quantity_unit', 'nutrition_data_per', 'nutrition_data_prepared_per', 'no_nutrition_data']) {
      const cleaned = label(get(product, key), 20);
      if (cleaned) out[key] = fold(cleaned);
    }
    for (const key of ['additives_tags', 'categories_tags', 'countries_tags']) {
      const tags = stringList(get(product, key));
      if (tags.length) out[key] = tags;
    }
    const nutriments = get(product, 'nutriments');
    const kept = {};
    if (isMapping(nutriments)) {
      for (const [key, value] of Object.entries(nutriments)) {
        if (!keptNutrimentKey(key)) continue;
        if (key.endsWith('_unit')) {
          const unit = label(value, 10);
          if (unit) kept[key] = unit;
          continue;
        }
        const number = finiteNumber(value);
        if (number != null) kept[key] = number;
      }
    }
    out.nutriments = kept;
    const nutrition = get(product, 'nutrition');
    if (isMapping(nutrition)) {
      const aggregated = trimAggregated(get(nutrition, 'aggregated_set'));
      if (aggregated) out.nutrition = { aggregated_set: aggregated };
    }
    return out;
  }

  // off.parse_nutrition_v35: flat `nutriments` from the API 3.5+ nutrition.aggregated_set.
  function parseNutritionV35(product) {
    const nutrition = get(product, 'nutrition');
    const aggregated = isMapping(nutrition) ? get(nutrition, 'aggregated_set') : null;
    if (!isMapping(aggregated) || !isMapping(get(aggregated, 'nutrients'))) return {};
    const per = str(or(get(aggregated, 'per'), '100g')).toLowerCase();
    const suffix = per === 'serving' ? '_serving' : '_100g';
    const infix = str(or(get(aggregated, 'preparation'), 'as_sold')).toLowerCase() === 'prepared' ? '_prepared' : '';
    const out = {};
    for (const [name, item] of Object.entries(aggregated.nutrients)) {
      if (!KEPT_NUTRIENTS.includes(name) || !isMapping(item)) continue;
      const value = finiteNumber(get(item, 'value'));
      const unit = KH.textclean.pyStrip(str(or(get(item, 'unit'), '')));
      if (value == null) continue;
      if (name.startsWith('energy')) {
        let key;
        if (unit.toLowerCase() === 'kcal') key = 'energy-kcal';
        else if (unit.toLowerCase() === 'kj') key = name !== 'energy' ? 'energy-kj' : 'energy';
        else continue;
        out[`${key}${infix}${suffix}`] = value;
        continue;
      }
      const factor = UNIT_TO_GRAMS.get(unit) || UNIT_TO_GRAMS.get(unit.toLowerCase());
      if (!factor) continue;
      out[`${name}${infix}${suffix}`] = value * factor[0] / factor[1];
    }
    return out;
  }

  function perValue(nutriments, name, infix, perServingLabel, servingG) {
    if (perServingLabel) {
      const direct = finiteNumber(get(nutriments, `${name}${infix}_serving`));
      if (direct != null) return direct;
    }
    const per100 = finiteNumber(get(nutriments, `${name}${infix}_100g`));
    return per100 == null ? null : per100 * servingG / 100;
  }
  function hasAny(nutriments, infix) {
    return KEPT_NUTRIENTS.some((name) => ['_100g', '_serving'].some((s) => finiteNumber(get(nutriments, `${name}${infix}${s}`)) != null));
  }
  function categoryOf(tags) {
    const set = new Set(tags);
    for (const [keys, category] of CATEGORY_MAP) if (keys.some((k) => set.has(k))) return category;
    return null;
  }
  function v35Per(product) {
    const nutrition = get(product, 'nutrition');
    const aggregated = isMapping(nutrition) ? get(nutrition, 'aggregated_set') : null;
    if (!isMapping(aggregated)) return null;
    return str(or(get(aggregated, 'per'), '100g')).toLowerCase();
  }
  // off.is_liquid: a serving in mL, a label per 100 mL, or a beverage that is not a powder.
  function isLiquid(product, categories) {
    const tags = new Set(categories);
    if (DRY_TAGS.some((t) => tags.has(t))) return false;
    const unit = fold(str(or(get(product, 'serving_quantity_unit'), '')));
    const per = fold(str(or(or(get(product, 'nutrition_data_per'), v35Per(product)), '')));
    return unit === 'ml' || per === '100ml' || tags.has('en:beverages');
  }
  // off._serving: [serving_g, serving_desc, quality codes].
  function servingOf(product, liquid) {
    const quality = [];
    const quantity = finiteNumber(get(product, 'serving_quantity'));
    const unit = fold(KH.textclean.pyStrip(str(or(get(product, 'serving_quantity_unit'), ''))));
    if (quantity != null && quantity > 0 && quantity <= MAX_SERVING_G && (unit === 'g' || unit === 'ml')) {
      if (unit === 'ml') quality.push('ml_as_g');
      const text = label(get(product, 'serving_size'), MAX_SERVING_DESC_CHARS);
      return [quantity, text || `${KH.rules.pyG(quantity)} ${unit === 'ml' ? 'mL' : 'g'}`, quality];
    }
    quality.push('no_serving');
    return [100, liquid ? '100 mL' : '100 g', quality];
  }

  // off.map_product: the fields of the server's `Mapped` (status, name, brand, category, serving_desc, serving_g,
  // nutrients, flags, kidney_notes, ingredients_text, additives, quality, us_label, country_known).
  function mapProduct(product, gtin14) {
    const T = KH.textclean;
    product = trimProduct(product);
    const code = KH.gtin.offCode(gtin14);
    const name = label(get(product, 'product_name'), MAX_NAME_CHARS) || label(get(product, 'product_name_en'), MAX_NAME_CHARS)
      || label(get(product, 'generic_name'), MAX_NAME_CHARS) || `Product ${code}`;
    const brands = or(get(product, 'brands'), '');
    const brand = typeof brands === 'string' ? label(brands.split(',')[0], MAX_NAME_CHARS) : null;
    const categories = or(get(product, 'categories_tags'), []);
    const countries = or(get(product, 'countries_tags'), []);
    const usLabel = US_CA_TAGS.some((t) => countries.includes(t));
    const ingredients = or(get(product, 'ingredients_text_en'), get(product, 'ingredients_text'));

    let nutriments = { ...or(get(product, 'nutriments'), {}) };
    let v35 = false;
    if (!hasAny(nutriments, '') && !hasAny(nutriments, '_prepared')) {
      nutriments = parseNutritionV35(product); // the API 3.5+ shape (empty `nutriments`)
      v35 = true;
    }
    const liquid = isLiquid(product, categories);
    const serving = servingOf(product, liquid);
    const servingG = serving[0];
    let servingDesc = serving[1];
    const quality = serving[2];

    let infix = '';
    if (!hasAny(nutriments, '') && hasAny(nutriments, '_prepared')) {
      infix = '_prepared';
      quality.push('prepared_values');
      const suffix = ' as sold, prepared';
      servingDesc = `${T.cpSlice(servingDesc, 0, MAX_SERVING_DESC_CHARS - suffix.length)}${suffix}`;
    }
    const perKey = infix ? 'nutrition_data_prepared_per' : 'nutrition_data_per';
    const perServingLabel = str(or(get(product, perKey), '')) === 'serving' || (v35 && v35Per(product) === 'serving');
    // Per-serving values without a serving weight cannot be used (review L6).
    const weightUnknown = perServingLabel && quality.includes('no_serving');
    const value = (n) => perValue(nutriments, n, infix, perServingLabel, servingG);

    const nutrients = {};
    let kcal = value('energy-kcal');
    if (kcal == null) {
      let kj = value('energy-kj');
      if (kj == null) kj = value('energy');
      kcal = kj == null ? null : kj / KJ_PER_KCAL;
    }
    nutrients.calories_kcal = kcal;
    const carbsTotal = value('carbohydrates-total');
    nutrients.carbs_g = carbsTotal != null ? carbsTotal : value('carbohydrates');
    if (carbsTotal == null && nutrients.carbs_g != null && !usLabel) quality.push('carbs_available');
    for (const [key, offName, factor] of NUTRIENT_MAP) {
      const raw = value(offName);
      nutrients[key] = raw == null ? null : raw * factor;
    }
    const sodium = value('sodium');
    const salt = value('salt');
    if (sodium != null) {
      nutrients.sodium_mg = sodium * 1000;
      if (!usLabel && salt != null && Math.abs(sodium * SALT_PER_SODIUM - salt) <= 0.01 * salt + 1e-9) quality.push('sodium_from_salt');
    } else {
      nutrients.sodium_mg = salt == null ? null : salt * 1000 / SALT_PER_SODIUM;
      if (salt != null) quality.push('sodium_from_salt');
    }

    // Plausibility (judged per 100 g or 100 mL), then the model bounds.
    const implausible = [];
    const isSalt = categories.includes(SALT_TAG);
    for (const [key, limit] of MAX_PER_100) {
      const v = nutrients[key];
      if (v == null) continue;
      const per100 = v * 100 / servingG;
      if (v < 0 || v > MAX_NUTRIENT_VALUE || (per100 > limit && !(key === 'sodium_mg' && isSalt))) {
        nutrients[key] = null;
        implausible.push(key);
      }
    }
    for (const key of implausible) quality.push(`implausible:${key}`);

    const noNutrition = weightUnknown || str(or(get(product, 'no_nutrition_data'), '')) === 'on'
      || ['calories_kcal', 'protein_g', 'fat_g', 'carbs_g'].every((k) => nutrients[k] == null);
    if (weightUnknown) quality.push('serving_weight_unknown');

    const parts = ['calories_kcal', 'carbs_g', 'protein_g', 'fat_g'].map((k) => nutrients[k]);
    if (parts.every((v) => v != null)) {
      const kcal100 = parts[0] * 100 / servingG;
      const computed100 = (4 * parts[1] + 4 * parts[2] + 9 * parts[3]) * 100 / servingG;
      const diff = Math.abs(kcal100 - computed100);
      if (diff > ENERGY_MISMATCH_FRACTION * kcal100 && diff > ENERGY_MISMATCH_MIN_KCAL) quality.push('energy_mismatch');
    }

    const scan = KH.additives.scan(get(product, 'additives_tags'), ingredients, name);
    const flags = [...scan.flags];
    if (liquid) { // the same test as the "100 mL" serving text (1 mL counted as 1 g)
      flags.push('counts_as_fluid');
      nutrients.fluid_ml = servingG;
    } else {
      nutrients.fluid_ml = 0;
    }
    if (get(product, 'nova_group') === 4) flags.push('processed');
    const sugars100 = nutrients.sugar_g == null ? null : nutrients.sugar_g * 100 / servingG;
    if (categories.includes(SWEETENED_BEVERAGE_TAG) && sugars100 != null && sugars100 >= HIGH_GI_MIN_SUGARS_PER_100) flags.push('high_gi');
    if (categories.includes(ALCOHOLIC_BEVERAGES_TAG)) flags.push('alcohol');

    for (const key of ['potassium_mg', 'phosphorus_mg']) if (nutrients[key] == null) quality.push(`${key.split('_')[0]}_unknown`);
    quality.unshift('crowd_sourced');
    if (noNutrition) quality.push('no_nutrition');

    return {
      status: noNutrition ? 'no_nutrition' : 'found',
      name,
      brand,
      category: categoryOf(categories),
      serving_desc: servingDesc,
      serving_g: servingG,
      nutrients,
      flags,
      kidney_notes: scan.kidney_notes || T.cpSlice(scan.notes.join(' '), 0, 1000) || null,
      ingredients_text: T.cleanText(ingredients, { maxLen: MAX_INGREDIENTS_CHARS, keepNewlines: true }),
      additives: [...scan.additives],
      quality: [...new Set(quality)],
      us_label: usLabel,
      country_known: truthy(countries),
    };
  }
  // Mapped.food_kwargs: what foods.insert_food takes.
  function foodKwargs(mapped) {
    const { name, brand, category, serving_desc, serving_g, nutrients, flags, kidney_notes } = mapped;
    return { name, brand, category, serving_desc, serving_g, nutrients: { ...nutrients }, flags: [...flags], kidney_notes };
  }
  // The food row the server stores when only Open Food Facts answered (barcode.assemble, then barcode.store): the
  // food_kwargs plus source and the provenance columns, before the stored rounding (the demo's _insertFood rounds
  // as foods.stored_food_values does). The server stores only a "found" product.
  function row(mapped, gtin14) {
    return { ...foodKwargs(mapped), source: 'off', gtin: gtin14, source_url: productPage(gtin14), source_license: LICENSE,
      ingredients_text: mapped.ingredients_text, additives: [...mapped.additives], quality: [...mapped.quality] };
  }

  KH.off = { LICENSE, ATTRIBUTION_TEXT, LICENSE_URL, HOME_URL, PRODUCT_PAGE_PREFIX, CONTRIBUTE_URL, USDA_LICENSE, USDA_HOME_URL,
    USDA_ATTRIBUTION_TEXT, METHOD_URL, QUALITY_MESSAGES, productPage, attribution, usdaAttribution, qualityItems, safeHttpsUrl,
    WEIGHT_UNKNOWN_CODES, WEIGHT_UNKNOWN_DETAIL, weightKnown, py, finiteNumber, trimProduct, parseNutritionV35, isLiquid,
    mapProduct, foodKwargs, row };
})();
