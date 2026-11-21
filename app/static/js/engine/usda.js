/* Kidney Diet Log — a USDA FoodData Central record to the food the server stores: the browser twin of
   app/foods.py map_usda_record and of one search hit of GET /api/foods/usda/search (foods.usda_search_item).

   In device mode (design note 38 §5.3) the page has no server: it gets FoodData Central's raw JSON through the
   app and must store exactly the row the server would. SR Legacy, Foundation and Branded records all go
   through mapRecord; app/foods.py explains each rule.

   Pure, no I/O. Needs KH.rules, KH.textclean, KH.gtin, KH.additives and KH.off (its Python helpers, KH.off.py),
   loaded before this file in index.html. Parity: tests/data/usda_vectors.json (tests/data/gen_usda_vectors.py),
   replayed by `node tests/js/run_vectors.mjs`. Exposes KH.usda = { mapRecord, row, searchItem, categoryStr,
   NUTRIENT_NUMBERS, CATEGORY_MAP, LABEL_NUTRIENTS }. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  const MAX_INGREDIENTS_CHARS = 4000;
  // USDA nutrient numbers (SR Legacy style) and nutrient ids (FDC style) to the app's key. Water (255/1051)
  // becomes fluid_ml only for foods that count as fluid.
  const NUTRIENT_NUMBERS = new Map([
    ['208', 'calories_kcal'], ['1008', 'calories_kcal'], ['203', 'protein_g'], ['1003', 'protein_g'],
    ['204', 'fat_g'], ['1004', 'fat_g'], ['606', 'sat_fat_g'], ['1258', 'sat_fat_g'], ['205', 'carbs_g'], ['1005', 'carbs_g'],
    ['291', 'fiber_g'], ['1079', 'fiber_g'], ['269', 'sugar_g'], ['2000', 'sugar_g'], ['307', 'sodium_mg'], ['1093', 'sodium_mg'],
    ['306', 'potassium_mg'], ['1092', 'potassium_mg'], ['305', 'phosphorus_mg'], ['1091', 'phosphorus_mg'],
    ['301', 'calcium_mg'], ['1087', 'calcium_mg'], ['255', 'fluid_ml'], ['1051', 'fluid_ml'],
  ]);
  // "Alcohol, ethyl", g per 100 g: from 0.4 g a record is flagged alcohol.
  const ALCOHOL_NUMBERS = new Set(['221', '1018']);
  const ALCOHOL_MIN_G_PER_100G = 0.4;
  // SR Legacy and Foundation food groups to the app's categories (other names are kept as they are).
  const CATEGORY_MAP = new Map([
    ['Fruits and Fruit Juices', 'Fruits'],
    ['Vegetables and Vegetable Products', 'Vegetables'],
    ['Cereal Grains and Pasta', 'Grains & Breads'],
    ['Baked Products', 'Grains & Breads'],
    ['Breakfast Cereals', 'Grains & Breads'],
    ['Dairy and Egg Products', 'Dairy & Alternatives'],
    ['Beef Products', 'Meat, Poultry & Eggs'],
    ['Pork Products', 'Meat, Poultry & Eggs'],
    ['Poultry Products', 'Meat, Poultry & Eggs'],
    ['Lamb, Veal, and Game Products', 'Meat, Poultry & Eggs'],
    ['Sausages and Luncheon Meats', 'Meat, Poultry & Eggs'],
    ['Finfish and Shellfish Products', 'Fish & Seafood'],
    ['Legumes and Legume Products', 'Legumes, Nuts & Seeds'],
    ['Nut and Seed Products', 'Legumes, Nuts & Seeds'],
    ['Beverages', 'Beverages'],
    ['Sweets', 'Sweets & Snacks'],
    ['Snacks', 'Sweets & Snacks'],
    ['Soups, Sauces, and Gravies', 'Condiments & Sauces'],
    ['Spices and Herbs', 'Condiments & Sauces'],
    ['Fats and Oils', 'Condiments & Sauces'],
    ['Fast Foods', 'Prepared & Fast Food'],
    ['Meals, Entrees, and Side Dishes', 'Prepared & Fast Food'],
    ['Restaurant Foods', 'Prepared & Fast Food'],
  ]);
  // labelNutrients (per serving, as printed on a branded label), in the server's order: the OpenAPI's
  // "postassium" spelling comes after "potassium", so it wins when both are there.
  const LABEL_NUTRIENTS = [
    ['calories', 'calories_kcal'], ['protein', 'protein_g'], ['fat', 'fat_g'], ['saturatedFat', 'sat_fat_g'],
    ['carbohydrates', 'carbs_g'], ['fiber', 'fiber_g'], ['sugars', 'sugar_g'], ['sodium', 'sodium_mg'],
    ['potassium', 'potassium_mg'], ['postassium', 'potassium_mg'], ['calcium', 'calcium_mg'],
  ];

  const py = () => KH.off.py;
  const label = (value, maxLen) => KH.textclean.cleanLabel(value, { maxLen });

  // foods._usda_category_str: a category given as text or as {description} / {name}.
  function categoryStr(value) {
    const { isMapping, get, or, str } = py();
    if (isMapping(value)) value = or(get(value, 'description'), get(value, 'name'));
    if (value == null) return null;
    return KH.textclean.pyStrip(str(value)) || null;
  }
  // foods._finite: a number that is finite and not negative, or null.
  function finite(value) {
    if (typeof value === 'boolean' || value == null) return null;
    let number;
    try { number = py().float(value); } catch (e) { if (e instanceof py().PyError) return null; throw e; }
    return Number.isFinite(number) && number >= 0 ? number : null;
  }
  function labelValue(item) { return py().isMapping(item) ? finite(py().get(item, 'value')) : finite(item); }
  // A nutrient amount: the API's "amount", else the web application's "value".
  function amountOf(item) { return Object.prototype.hasOwnProperty.call(item, 'amount') && item.amount !== undefined ? item.amount : py().get(item, 'value'); }

  // foods._usda_serving: [serving_g, serving_desc]: the first household portion, else the branded serving
  // size (g or mL), else 100 g.
  function servingOf(data) {
    const { isMapping, get, truthy, or, iter, str, float, PyError } = py();
    const G = KH.rules.pyG;
    for (const portion of iter(or(get(data, 'foodPortions'), []))) {
      if (!isMapping(portion)) continue;
      const grams = finite(get(portion, 'gramWeight'));
      if (!truthy(grams) || grams > 100000) continue;
      const amount = get(portion, 'amount');
      const measure = isMapping(get(portion, 'measureUnit')) ? portion.measureUnit : {};
      const unit = label(get(measure, 'name'), 40) || '';
      const modifier = label(get(portion, 'modifier'), 60) || '';
      const description = label(get(portion, 'portionDescription'), 80) || '';
      let parts = [];
      try {
        if (truthy(amount)) parts.push(G(float(amount)));
      } catch (e) {
        if (!(e instanceof PyError)) throw e;
      }
      if (unit && unit.toLowerCase() !== 'undetermined') parts.push(unit);
      if (modifier && modifier.toLowerCase() !== unit.toLowerCase()) parts.push(modifier);
      if (parts.length <= 1 && description && description.toLowerCase() !== 'quantity not specified') parts = [description];
      const text = KH.textclean.pyStrip(parts.join(' ')) || '1 serving';
      return [grams, `${text} (${G(grams)} g)`];
    }
    const servingSize = finite(get(data, 'servingSize'));
    const unit = str(or(get(data, 'servingSizeUnit'), '')).toLowerCase();
    if (truthy(servingSize) && servingSize > 0 && servingSize <= 100000 && ['g', 'grm', 'ml', 'mlt'].includes(unit)) {
      const shown = unit === 'ml' || unit === 'mlt' ? 'mL' : 'g'; // millilitres are counted as grams (1 mL ≈ 1 g)
      const household = label(get(data, 'householdServingFullText'), 40);
      return [servingSize, household ? `${household} (${G(servingSize)} ${shown})` : `${G(servingSize)} ${shown}`];
    }
    return [100, '100 g'];
  }

  // foods.map_usda_record: { kwargs: {name, brand, category, serving_desc, serving_g, nutrients, flags, kidney_notes},
  // gtin14, ingredients_text, additives, quality }, the server's UsdaMapped.
  function mapRecord(data, fdcId) {
    const { isMapping, get, truthy, or, iter, str } = py();
    const T = KH.textclean;
    const description = label(get(data, 'description'), 200) || `USDA food ${fdcId}`;
    const brand = label(or(get(data, 'brandOwner'), get(data, 'brandName')), 200);
    let usdaCategory = categoryStr(get(data, 'foodCategory')) || categoryStr(get(data, 'brandedFoodCategory'));
    usdaCategory = label(usdaCategory, 100);
    const category = CATEGORY_MAP.has(usdaCategory || '') ? CATEGORY_MAP.get(usdaCategory || '') : usdaCategory;

    const per100g = new Map();
    let alcohol100g = null;
    for (const item of iter(or(get(data, 'foodNutrients'), []))) {
      if (!isMapping(item)) continue;
      const nutrient = isMapping(get(item, 'nutrient')) ? item.nutrient : {};
      const candidates = [get(nutrient, 'number'), get(nutrient, 'id'), get(item, 'nutrientNumber'), get(item, 'nutrientId')]
        .map((v) => str(or(v, '')));
      if (alcohol100g == null && candidates.some((c) => ALCOHOL_NUMBERS.has(c))) {
        alcohol100g = finite(amountOf(item));
        continue;
      }
      const hit = candidates.find((c) => NUTRIENT_NUMBERS.has(c));
      const key = hit === undefined ? null : NUTRIENT_NUMBERS.get(hit);
      if (key == null || per100g.has(key)) continue;
      const amount = finite(amountOf(item));
      if (amount != null) per100g.set(key, amount);
    }

    const [servingG, servingDesc] = servingOf(data);
    const quality = [];
    if (servingDesc === '100 g' && !truthy(get(data, 'foodPortions')) && !truthy(get(data, 'servingSize'))) quality.push('no_serving');
    const unit = str(or(get(data, 'servingSizeUnit'), '')).toLowerCase();
    const isMl = (unit === 'ml' || unit === 'mlt') && !truthy(get(data, 'foodPortions'));
    if (isMl) quality.push('ml_as_g');
    const scale = servingG / 100;
    const nutrients = {};
    for (const key of KH.rules.NUTRIENT_KEYS) {
      if (key !== 'fluid_ml') nutrients[key] = per100g.has(key) ? per100g.get(key) * scale : null;
    }
    // Branded labels: the per-serving values printed on the package.
    const labels = get(data, 'labelNutrients');
    if (isMapping(labels) && truthy(get(data, 'servingSize')) && !truthy(get(data, 'foodPortions'))) {
      for (const [labelKey, key] of LABEL_NUTRIENTS) {
        const value = labelValue(get(labels, labelKey));
        if (value != null) nutrients[key] = value;
      }
    }

    const ingredients = T.cleanText(get(data, 'ingredients'), { maxLen: MAX_INGREDIENTS_CHARS, keepNewlines: true });
    const scan = KH.additives.scan([], ingredients, description);
    const flags = [...scan.flags];
    const isBeverage = isMl || category === 'Beverages' || !!(usdaCategory && usdaCategory.toLowerCase().includes('beverage'));
    if (isBeverage) {
      flags.push('counts_as_fluid');
      nutrients.fluid_ml = per100g.has('fluid_ml') ? per100g.get('fluid_ml') * scale : servingG;
    } else {
      nutrients.fluid_ml = 0;
    }
    if ((alcohol100g != null && alcohol100g >= ALCOHOL_MIN_G_PER_100G) || T.casefold(description).startsWith('alcoholic beverage')) {
      flags.push('alcohol');
    }

    const missing = ['potassium_mg', 'phosphorus_mg'].filter((k) => nutrients[k] == null).map((k) => KH.rules.NUT[k].label.toLowerCase());
    for (const k of ['potassium_mg', 'phosphorus_mg']) if (nutrients[k] == null) quality.push(`${k.split('_')[0]}_unknown`);
    const notes = [];
    if (scan.kidney_notes) notes.push(scan.kidney_notes);
    if (missing.length) notes.push(`USDA record does not report ${missing.join(' or ')}; treat it as unknown, not zero.`);
    if (!scan.kidney_notes) notes.push(...scan.notes);
    return {
      kwargs: {
        name: description,
        brand,
        category,
        serving_desc: servingDesc,
        serving_g: servingG,
        nutrients,
        flags,
        kidney_notes: T.cpSlice(notes.join(' '), 0, 1000) || null,
      },
      gtin14: KH.gtin.looseGtin14(get(data, 'gtinUpc')),
      ingredients_text: ingredients,
      additives: [...scan.additives],
      quality,
    };
  }

  // The food row the server stores for an imported record (foods.add_usda_food: the kwargs plus source, fdc_id and
  // foods.usda_provenance), before the stored rounding (the demo's _insertFood rounds as foods.stored_food_values
  // does). A barcode lookup stores the scanned barcode as `gtin` instead of the record's own.
  function row(mapped, fdcId) {
    const k = mapped.kwargs;
    return { name: k.name, brand: k.brand, category: k.category, serving_desc: k.serving_desc, serving_g: k.serving_g,
      nutrients: { ...k.nutrients }, flags: [...k.flags], kidney_notes: k.kidney_notes, source: 'usda', fdc_id: fdcId,
      gtin: mapped.gtin14, source_url: KH.off.USDA_HOME_URL, source_license: KH.off.USDA_LICENSE,
      ingredients_text: mapped.ingredients_text, additives: [...mapped.additives], quality: [...mapped.quality] };
  }

  // foods.usda_search_item: one hit of a FoodData Central text search as GET /api/foods/usda/search lists it, or
  // null when it has no id. Throws KH.off.py.PyError where the server would fail (an id that is not a number).
  function searchItem(item) {
    const { get, or, str, int } = py();
    const fdcId = get(item, 'fdcId');
    if (fdcId == null) return null;
    return {
      fdc_id: int(fdcId),
      description: KH.textclean.pyStrip(str(or(get(item, 'description'), ''))) || `USDA food ${str(fdcId)}`,
      data_type: get(item, 'dataType'),
      brand: or(or(get(item, 'brandOwner'), get(item, 'brandName')), null),
      category: categoryStr(get(item, 'foodCategory')),
    };
  }

  KH.usda = { mapRecord, row, searchItem, categoryStr, NUTRIENT_NUMBERS, CATEGORY_MAP, LABEL_NUTRIENTS };
})();
