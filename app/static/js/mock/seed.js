/* Kidney Diet Log — demo API: the sample person and KH.mock.start().

   Sample data for the demo: "Sam", CKD stage 4, type 1 diabetes, 70 kg, 170 cm. About 30
   days of renal-diet meals built from real foods in the database, a few higher days, two
   hypo treatments, three empty days, today partly eaten with dinner planned, three days
   ahead planned and three saved meals. Fixed seed: the same plan on every load. */
(() => {
  'use strict';
  const KH = window.KH;
  const { MEAL_KEYS } = KH.rules;
  const { todayStr, parseDate, addDays } = KH.util;
  const M = KH.mock;

  function seedSampleData(api, { hemodialysis = false } = {}) {
    let seed = 0x5eed2610;
    const rnd = () => { // mulberry32
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    const pick = (list) => list[Math.floor(rnd() * list.length)];
    // Foods by USDA FDC id, with a name fallback for the 24-food ?mock=1 list.
    const FOODS = {
      apple: [171688, /^apple, raw/i], blueberries: [171711, /^blueberries/i], strawberries: [167762, /^strawberries/i], grapes: [174683, /^grapes/i],
      applesauce: [171695, /^applesauce/i], pineapple: [169126, /^pineapple, canned/i], pears: [169936, /^pears, canned/i],
      rice: [168878, /^rice, white/i], bread: [174924, /^bread, white/i], pasta: [169737, /^pasta, cooked/i], creamOfWheat: [171657, /^cream of wheat/i],
      englishMuffin: [175063, /^english muffin, plain/i], riceCakes: [170250, /^rice cakes/i], riceMilk: [171942, /^rice milk/i],
      saltines: [172746, /^saltine/i], popcorn: [167959, /^popcorn, air/i], vanillaWafers: [174974, /^vanilla wafers/i], sugarCookies: [174971, /^cookies, sugar/i],
      chicken: [171477, /^chicken breast, roasted/i], turkey: [171496, /^turkey breast, roasted/i], cod: [171956, /^cod/i], eggWhite: [172183, /^egg white/i],
      greenBeans: [169141, /^green beans/i], cauliflower: [170397, /^cauliflower, boiled/i], cabbage: [169976, /^cabbage, boiled/i], cucumber: [168409, /^cucumber/i],
      lettuce: [169248, /^lettuce, iceberg/i], redPepper: [170108, /^bell pepper, red/i], onion: [170000, /^onion, raw/i], carrots: [170394, /^carrots, boiled/i],
      butter: [173430, /^butter, unsalted/i], creamCheese: [173418, /^cream cheese/i], oliveOil: [171413, /^olive oil/i], mayonnaise: [171009, /^mayonnaise/i],
      jam: [169641, /^jam/i], brownSugar: [168833, /^sugar, brown/i], salt: [173468, /^salt, table/i],
      coffee: [171890, /^coffee, brewed/i], water: [173647, /^water, tap/i], tea: [173227, /^tea, black/i],
      banana: [173944, /^banana/i], potato: [170093, /^potato, baked/i], deliTurkey: [172941, /^deli turkey/i], cola: [174852, /^cola, regular/i],
      orangeJuice: [169098, /^orange juice/i], cheeseburger: [170691, /^cheeseburger/i], fries: [170698, /^french fries, fast food/i], soup: [172909, /^soup, chicken noodle/i], pretzels: [167555, /^pretzels/i],
      glucose: [-10, /^glucose tablet/i],
    };
    const food = (key) => {
      const [fdc, re] = FOODS[key];
      return api._foods.find((f) => f.source === 'builtin' && f.fdc_id === fdc) || api._foods.find((f) => re.test(f.name)) || null;
    };
    const today = todayStr();
    const now = Date.now();
    const at = (date, hhmm) => { const d = parseDate(date); d.setHours(Math.floor(hhmm), Math.round((hhmm % 1) * 100), 0, 0); return d.getTime(); };
    const TIMES = { breakfast: 7.45, lunch: 12.3, dinner: 18.4, snack: 15.3 };
    const items = []; // [time, date, meal, key, servings, status, note]
    const add = (date, meal, list, { status = 'eaten', when = null, note = null } = {}) => {
      list.forEach(([key, servings, itemNote], i) => items.push([(when || at(date, TIMES[meal])) + i * 60000 + items.length, date, meal, key, servings, status, itemNote || (i === 0 ? note : null)]));
    };
    // A CKD stage 4 renal plate: small protein portions, white rice / pasta / bread, low-potassium
    // fruit and vegetables, unsalted butter and oil for energy, a pinch of salt when cooking.
    const BREAKFASTS = [
      [['eggWhite', 2], ['bread', 2], ['butter', 1], ['jam', 1], ['blueberries', 1], ['coffee', 1]],
      [['creamOfWheat', 1], ['riceMilk', 0.5], ['brownSugar', 1], ['strawberries', 1], ['coffee', 1]],
      [['englishMuffin', 1], ['creamCheese', 1], ['jam', 1], ['applesauce', 1], ['tea', 1]],
      [['eggWhite', 3], ['bread', 2], ['butter', 1], ['pears', 1], ['coffee', 1]],
    ];
    const LUNCHES = [
      [['chicken', 0.5], ['rice', 1], ['greenBeans', 1], ['oliveOil', 1], ['salt', 0.25], ['water', 1]],
      [['bread', 2], ['turkey', 0.5], ['mayonnaise', 1], ['lettuce', 0.5], ['cucumber', 1], ['apple', 1], ['water', 1]],
      [['pasta', 1], ['chicken', 0.5], ['redPepper', 1], ['onion', 0.5], ['oliveOil', 1], ['salt', 0.25], ['water', 1]],
    ];
    const DINNERS = [
      [['cod', 0.75], ['rice', 1], ['cauliflower', 2], ['butter', 1], ['salt', 0.5], ['water', 1]],
      [['chicken', 0.75], ['pasta', 1], ['cabbage', 1], ['oliveOil', 1], ['salt', 0.25], ['water', 1]],
      [['turkey', 0.75], ['rice', 1], ['greenBeans', 1], ['carrots', 1], ['butter', 1], ['salt', 0.25]],
      [['eggWhite', 3], ['bread', 1], ['cauliflower', 2], ['redPepper', 1], ['oliveOil', 1], ['salt', 0.5]],
    ];
    const SNACKS = [[['apple', 1]], [['riceCakes', 1], ['jam', 1]], [['grapes', 1]], [['pineapple', 1]], [['vanillaWafers', 1]],
      [['popcorn', 1]], [['sugarCookies', 1], ['coffee', 1]], [['saltines', 1], ['pears', 1]]];
    // Days (counted back from today) that differ from the usual plan.
    const EMPTY = new Set([9, 16, 23]);
    const SPECIAL = {
      2: { lunch: [['bread', 2], ['deliTurkey', 1.5], ['mayonnaise', 1], ['lettuce', 0.5], ['apple', 1], ['water', 1]],
        dinner: [['soup', 1], ['saltines', 1], ['chicken', 0.5], ['cucumber', 1], ['water', 1]] },
      4: { hypo: 'Hypo 3.5 mmol/L before dinner; 5.8 after 15 minutes' },
      5: { lunch: [['cheeseburger', 1], ['cola', 1, 'lunch out']] },
      7: { breakfast: [['banana', 1], ['creamOfWheat', 1], ['riceMilk', 0.5], ['coffee', 1]],
        dinner: [['chicken', 0.75], ['potato', 1], ['butter', 1], ['greenBeans', 1], ['water', 1]] },
      11: { dinner: [['cod', 0.75], ['potato', 1], ['butter', 1], ['cauliflower', 2], ['water', 1]] },
      13: { dinner: [['cheeseburger', 1], ['fries', 1], ['cola', 1, 'takeaway']], hypo: 'Hypo 3.7 mmol/L mid-morning; 5.4 after 15 minutes' },
      18: { lunch: [['bread', 2], ['deliTurkey', 1.5], ['mayonnaise', 1], ['lettuce', 0.5], ['water', 1]], snack: [['cola', 1], ['pretzels', 1]] },
      21: { breakfast: [['banana', 1], ['bread', 2], ['butter', 1], ['orangeJuice', 1], ['coffee', 1]],
        dinner: [['turkey', 0.75], ['potato', 1.5, 'big one'], ['butter', 1], ['cabbage', 1], ['water', 1]] },
      26: { lunch: [['cheeseburger', 1], ['water', 1]] },
      28: { lunch: [['bread', 2], ['deliTurkey', 1], ['mayonnaise', 1], ['cucumber', 1], ['water', 1]], snack: [['banana', 1]] },
    };
    for (let back = 30; back >= 1; back--) {
      const date = addDays(today, -back);
      const breakfast = pick(BREAKFASTS), lunch = pick(LUNCHES), dinner = pick(DINNERS);
      const snackCount = rnd() < 0.4 ? 2 : 1;
      const snacks = []; for (let i = 0; i < snackCount; i++) snacks.push(...pick(SNACKS));
      const extraWater = rnd() < 0.5;
      if (EMPTY.has(back)) continue;
      const sp = SPECIAL[back] || {};
      add(date, 'breakfast', sp.breakfast || breakfast);
      add(date, 'lunch', sp.lunch || lunch);
      add(date, 'dinner', sp.dinner || dinner);
      add(date, 'snack', sp.snack || snacks);
      if (extraWater) add(date, 'snack', [['water', 1]], { when: at(date, 20.15) });
      if (sp.hypo) add(date, 'snack', [['glucose', 4]], { when: at(date, back === 4 ? 17.5 : 10.4), note: sp.hypo });
    }
    // Today: breakfast and a bigger lunch eaten, an afternoon snack; dinner and an evening snack planned.
    add(today, 'breakfast', BREAKFASTS[0]);
    add(today, 'lunch', [['chicken', 1], ['rice', 1], ['greenBeans', 1], ['oliveOil', 1], ['water', 1]]);
    add(today, 'snack', [['apple', 1], ['water', 1]]);
    const planNight = at(addDays(today, -1), 20.3);
    add(today, 'dinner', [['cod', 0.75], ['rice', 1], ['cauliflower', 2], ['butter', 1], ['strawberries', 1], ['water', 1]], { status: 'planned', when: planNight });
    add(today, 'snack', [['riceCakes', 1, 'evening'], ['jam', 1]], { status: 'planned', when: planNight + 600000 });
    // Three days ahead, planned this morning.
    const planMorning = at(today, 7.15);
    const ahead = [
      { breakfast: BREAKFASTS[1], lunch: LUNCHES[0], dinner: DINNERS[2], snack: [['grapes', 1]] },
      { breakfast: BREAKFASTS[0], lunch: LUNCHES[1], dinner: DINNERS[1], snack: [['vanillaWafers', 1]] },
      { breakfast: BREAKFASTS[3], dinner: DINNERS[0] },
    ];
    ahead.forEach((plan, i) => {
      const date = addDays(today, i + 1);
      for (const meal of MEAL_KEYS) if (plan[meal]) add(date, meal, plan[meal], { status: 'planned', when: planMorning + (i * 4 + MEAL_KEYS.indexOf(meal)) * 120000 });
    });
    // Insert in time order (ids follow created_at, as on the server); nothing is stamped in the future.
    items.sort((a, b) => a[0] - b[0]);
    let last = 0;
    const cap = now - 5 * 60000;
    for (const [time, date, meal, key, servings, status, note] of items) {
      const f = food(key);
      if (!f) continue;
      const t = Math.max(Math.min(time, cap), last + 1);
      last = t;
      api._insertEntry({ date, meal, food: f, servings, grams: null, note, status, createdAt: api._stamp(new Date(t)) });
    }
    // Saved meals.
    const tplAt = api._stamp(new Date(at(addDays(today, -20), 21)));
    const tpl = (name, note, list) => {
      const its = list.map(([key, servings]) => { const f = food(key); return f ? { food_id: f.id, servings } : null; }).filter(Boolean);
      if (its.length) api._insertTemplate({ name, note, items: its, createdAt: tplAt });
    };
    tpl('Usual breakfast', 'Weekday default', BREAKFASTS[0]);
    tpl('Chicken & rice lunch', null, [['chicken', 0.5], ['rice', 1], ['greenBeans', 1], ['oliveOil', 1], ['water', 1]]);
    tpl('Hypo kit: glucose tablets', '4 tablets = 16 g fast carbohydrate with no potassium. Recheck in 15 minutes.', [['glucose', 4]]);
    // Profile: targets are what the suggestion gives for this person.
    const profile = hemodialysis
      ? { name: 'Sam', weight_kg: 70, height_cm: 170, ckd_stage: '5', dialysis: 'hemodialysis', diabetes: 'type1', warn_fraction: 0.8, dialysis_days: [0, 2, 4], week_start: 'monday' }
      : { name: 'Sam', weight_kg: 70, height_cm: 170, ckd_stage: '4', dialysis: 'none', diabetes: 'type1', warn_fraction: 0.8, dialysis_days: [], week_start: 'monday' };
    // "About you" (note 05 §4.2): sex is left unset so the demo shows the "add it" prompt.
    Object.assign(profile, { birth_month: '1971-03', activity: 'low_active' }, hemodialysis ? { urine_output_ml: 400 } : {});
    api._updateProfile(profile);
    // Lab results, as typed from the person's blood tests (some in SI units, to show the conversion).
    const labUser = api._currentUser().id;
    const lab = (daysAgo, analyte, value, unit, note = '') => {
      const date = addDays(today, -daysAgo);
      api._insertLab(labUser, KH.kidney.convert(analyte, value, unit), date, note, api._stamp(new Date(Math.min(at(date, 17.3), cap))));
    };
    if (hemodialysis) {
      lab(33, 'potassium', 5.1, 'mmol/L'); lab(33, 'phosphate', 6.2, 'mg/dL'); lab(33, 'albumin', 3.7, 'g/dL');
      lab(5, 'potassium', 5.7, 'mmol/L', 'Pre-dialysis, Monday'); lab(5, 'phosphate', 1.87, 'mmol/L'); lab(5, 'albumin', 36, 'g/L');
      lab(5, 'bicarbonate', 22, 'mmol/L'); lab(40, 'a1c', 7.3, '%');
    } else {
      lab(96, 'potassium', 5.3, 'mmol/L'); lab(96, 'creatinine', 2.3, 'mg/dL'); lab(96, 'egfr', 26, 'mL/min/1.73 m²');
      lab(41, 'albumin', 39, 'g/L'); lab(41, 'a1c', 58, 'mmol/mol');
      lab(12, 'potassium', 4.8, 'mmol/L', 'Clinic visit'); lab(12, 'phosphate', 1.58, 'mmol/L'); lab(12, 'bicarbonate', 21, 'mmol/L');
      lab(12, 'creatinine', 212, 'µmol/L'); lab(12, 'egfr', 25, 'mL/min/1.73 m²'); lab(12, 'uacr', 25, 'mg/mmol');
    }
    api._updateProfile({ targets: api._suggested().targets });
  }

  // The preview build embeds data/foods.json in a JSON script element with id "kdl-foods".
  // Read only in demo mode: the installed app never looks for it.
  function embeddedFoods() {
    const el = document.getElementById('kdl-foods');
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  // Build the demo API (main.js calls this only in demo mode) and expose the hooks the
  // verification scripts use; they are absent in the installed app.
  function start({ hemodialysis = false } = {}) {
    if (M.instance) return M.instance;
    const mock = new M.MockApi({ foodsData: embeddedFoods(), hemodialysis });
    M.instance = mock;
    window.__kdlMock = mock;
    window.__kdlEvaluateWarnings = KH.rules.evaluateWarnings;
    return mock;
  }

  Object.assign(M, { seedSampleData, embeddedFoods, start });
})();
