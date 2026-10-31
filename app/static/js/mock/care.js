/* Kidney Diet Log — demo API: the Care team (app/sharing.py, app/care_suggestions.py, design notes 19, 25 and 29).

   The demo has no other accounts, so it shows a sample Care team, kept in memory only (never saved by "Keep my data in this
   browser"):
   * your Care team: Jordan, who plans your meals and may suggest them (a Custom mix of switches), who planned two foods today
     and sent you one suggestion for tomorrow's dinner; an invite to "riley" waiting for an answer;
   * an invite for you from Lee (a Viewer of the food log), with Accept and Decline;
   * Ana, whose Care team you are on with every "Do" switch on: plan, log eaten food, use her saved meals and suggest. Her food
     log, her plan, her saved meal, her shopping list, with a few planned foods and one eaten.
   Ana's days are a second set of entries with her own profile (a copy of yours, named Ana) and one saved meal. Her routes run the
   demo's own log, foods, meals, shopping and planning twins with her entries swapped in, so the numbers are worked out the same
   way. A link cannot be made or used here: there is nobody to send it to. KH.mock.care holds the pure parts the parity vectors
   check (tests/data/care_vectors.json): the switches, the roles over them and the note check. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi, fail } = M;
  const { scaleNutrients, emptyTotals, addTotals, countUnknown, roundNutrients } = KH.rules;

  const AREAS = ['food', 'labs', 'body', 'symptoms', 'activity'];
  const ROLES = ['viewer', 'care_helper', 'caregiver'];
  const SWITCHES = ['may_plan', 'may_log', 'may_use_saved_meals', 'may_suggest'];
  const PRESETS = {
    viewer: { may_plan: false, may_log: false, may_use_saved_meals: false, may_suggest: false },
    care_helper: { may_plan: true, may_log: false, may_use_saved_meals: false, may_suggest: false },
    caregiver: { may_plan: true, may_log: true, may_use_saved_meals: false, may_suggest: false },
  };
  const NOT_SHARED = 'Not shared with you.';
  const LOW_TREATMENT = (name) => `Only ${name} can change or remove a low treatment.`;
  const NOT_YOUR_EATEN = 'You can change only the eaten food you added.';
  // app/care_suggestions.py
  const SUGGEST_DAYS = 14;
  const MAX_OPEN_PER_SHARE = 10;
  const MAX_PER_DAY = 20;
  const MAX_NOTE = 280;
  const MAX_ITEMS = 30;
  const NO_SUGGESTION = 'That suggestion is no longer open.';
  const NONE_LEFT = 'None of these foods is on your list any more, so nothing was added. You can say no thanks instead.';
  const NOTE_LOW = (name) => `Notes cannot be about lows. How to treat a low stays ${name}'s choice.`;
  const NOTE_WORD = (word) => `Please leave out "${word}". Notes are about food: never insulin, doses, medicines or lab results, and never call `
    + 'food "safe" or "bad".';
  const LOW_FOOD = (food, name) => `${food} is for treating a low. Suggestions leave those out: how to treat a low stays ${name}'s choice.`;
  const TOO_MANY_OPEN = (name) => `${name} already has ${MAX_OPEN_PER_SHARE} suggestions from you waiting for an answer. Wait for an answer first.`;
  const TOO_MANY_TODAY = `You have sent ${MAX_PER_DAY} suggestions in the last 24 hours, the most allowed. Try again tomorrow.`;
  // app/guidance/messages.py BANNED_PATTERN, word for word (tests/data/care_vectors.json compares the source).
  const BANNED_SOURCE = String.raw`\b(safe|bad|cheat|failed|unlimited|don't worry|insulin|bolus|basal|units?|ratios?|correction|doses?|dosing|`
    + String.raw`pump|binders?|sevelamer|lanthanum|calcium acetate|patiromer|zirconium|supplements?|diagnos\w*|lab results?|`
    + String.raw`as much as|no need to)\b`;
  const BANNED = new RegExp(BANNED_SOURCE, 'i');

  const DAY_MS = 86400000;
  const iso = (offsetDays) => new Date(Date.now() + offsetDays * DAY_MS).toISOString();
  const day = (offsetDays) => KH.util.addDays(KH.util.todayStr(), offsetDays);

  /** sharing.role_of: the preset these switches match, or "custom". */
  function roleOf(sw) {
    const want = Object.fromEntries(SWITCHES.map((k) => [k, !!(sw && sw[k])]));
    return ROLES.find((r) => SWITCHES.every((k) => PRESETS[r][k] === want[k])) || 'custom';
  }
  /** sharing._clean_areas: one each, in order; any "Do" switch adds the food log. */
  const clean = (areas, sw) => AREAS.filter((a) => (areas || []).includes(a) || (a === 'food' && SWITCHES.some((k) => sw && sw[k])));
  /** care_suggestions.note_problem: why a note cannot be sent, or null (the AI text checks). */
  function noteProblem(note, person) {
    if (!note) return null;
    if (KH.guidanceEngine.mentionsLow(note)) return NOTE_LOW(person);
    const found = BANNED.exec(KH.aiguard.fold(note));
    return found ? NOTE_WORD(found[0]) : null;
  }
  const withRole = (x) => ({ ...x, role: roleOf(x) });
  const switchesOf = (x) => Object.fromEntries(SWITCHES.map((k) => [k, !!x[k]]));

  Object.assign(MockApi.prototype, {
    _care() {
      if (this._careState) return this._careState;
      this._careState = {
        nextId: 100,
        mine: [{ id: 1, name: 'Jordan', username: 'jordan', areas: ['food', 'labs'], since: iso(-6), until: null, last_viewed_at: iso(0), active: true,
          ...PRESETS.care_helper, may_suggest: true, helper_changes: { day: iso(0).slice(0, 10), added: 2, changed: 0, removed: 0, logged: 0 } }],
        codes: [],
        invites: [{ id: 2, username: 'riley', areas: ['food'], ...PRESETS.viewer, days: null, created_at: iso(-1), expires_at: iso(6) }],
        people: [{ id: 3, name: 'Ana', username: 'ana', areas: ['food'], since: iso(-20), until: null, may_plan: true, may_log: true,
          may_use_saved_meals: true, may_suggest: true }],
        forMe: [{ id: 4, name: 'Lee', username: 'lee', areas: ['food'], ...PRESETS.viewer, days: 30, expires_at: iso(5) }],
        suggestions: null, // made on first use: the foods come from the demo's list
        worlds: {},
      };
      return this._careState;
    },
    // Suggestions to and from the demo person: one from Jordan to you, and what you send to Ana.
    _careSuggestions() {
      const s = this._care();
      if (s.suggestions) return s.suggestions;
      const pick = (word) => this._foods.find((f) => !f.hidden && f.name.toLowerCase().includes(word));
      const items = ['chicken', 'rice'].map(pick).filter(Boolean).map((f) => ({ food_id: f.id, servings: 1, name: f.name, serving_desc: f.serving_desc }));
      s.suggestions = items.length ? [{ id: 50, share_id: 1, to: 'me', from_name: 'Jordan', date: day(1), meal: 'dinner', items,
        note: 'Chicken and rice, like last week. The low-sodium broth is in the pantry.', created_at: iso(0), expires_at: iso(SUGGEST_DAYS),
        answer: null, answered_at: null }] : [];
      return s.suggestions;
    },
    // A sample person's own data: their entries, a profile (a copy of yours with their name) and one saved meal.
    _careWorld(person) {
      const s = this._care();
      if (s.worlds[person.id]) return s.worlds[person.id];
      const w = s.worlds[person.id] = { entries: [], profile: { ...JSON.parse(JSON.stringify(this._profile)), name: person.name }, templates: [] };
      if (person.username === 'ana') {
        this._asPerson(w, () => {
          const pick = (word) => this._foods.find((f) => !f.hidden && f.name.toLowerCase().includes(word));
          const plan = [[1, 'breakfast', 'apple'], [1, 'lunch', 'rice'], [1, 'dinner', 'chicken'], [2, 'breakfast', 'carrot']];
          for (const [offset, meal, word] of plan) {
            const food = pick(word);
            if (food) this._insertEntry({ date: day(offset), meal, food, servings: 1, status: 'planned', purpose: null });
          }
          const eaten = pick('banana');
          if (eaten) this._insertEntry({ date: day(0), meal: 'breakfast', food: eaten, servings: 1, status: 'eaten' });
          const lunch = ['rice', 'chicken'].map(pick).filter(Boolean);
          if (lunch.length) this.handle('POST', '/api/meals', { name: 'Rice and chicken', meal_hint: 'lunch', items: lunch.map((f) => ({ food_id: f.id, servings: 1 })) });
        });
      }
      return w;
    },
    _asPerson(world, fn) {
      const saved = [this._entries, this._profile, this._templates, this._inCareWorld];
      this._entries = world.entries; this._profile = world.profile; this._templates = world.templates; this._inCareWorld = true;
      try { return fn(); } finally { [this._entries, this._profile, this._templates, this._inCareWorld] = saved; }
    },
    // sharing._check_share: the share is yours, has the area and (for a write) one of the switches now; else the one 404.
    _careShare(id, area, anyOf = []) {
      this._currentUser();
      const p = this._care().people.find((x) => x.id === Number(id));
      if (!p || (area && !p.areas.includes(area)) || (anyOf.length && !anyOf.some((k) => p[k]))) fail(404, NOT_SHARED);
      return p;
    },
    _careAs(id, method, path, body, headers, anyOf = []) {
      const p = this._careShare(id, 'food', anyOf);
      return this._asPerson(this._careWorld(p), () => this.handle(method, path, body, headers));
    },
    _helperName() { const u = this._currentUser(); return (u.display_name || '').trim() || u.username; },
    // sharing.note_change: the count on your own share list is sample data; a helper's changes in Ana's world are not counted.
    // care_suggestions.fit_for: the suggestion added to that day's planned food, worked out by the demo's own day twin.
    _careFit(world, date, meal, items) {
      return this._asPerson(world, () => {
        const temp = [];
        for (const it of items) {
          const food = this._food(it.food_id);
          if (!food || !this._foodVisible(food)) continue;
          temp.push({ id: -1 - temp.length, date, meal, food_id: food.id, food_name: food.name, servings: Number(it.servings), grams: null, note: null,
            status: 'planned', nutrients: scaleNutrients(food.nutrients, Number(it.servings)), purpose: null, client_id: null,
            created_at: '9999-12-31T00:00:00.000000Z', updated_at: '9999-12-31T00:00:00.000000Z' });
        }
        this._entries.push(...temp);
        let summary;
        try { summary = this.handle('GET', `/api/log?date=${date}`); } finally {
          for (const row of temp) this._entries.splice(this._entries.indexOf(row), 1);
        }
        const totals = emptyTotals();
        const unknown = {};
        for (const row of temp) { addTotals(totals, row.nutrients); countUnknown(unknown, row.nutrients); }
        return { totals: roundNutrients(totals), unknown, day_status: summary.projected_status };
      });
    },
    _careItemViews(world, items) {
      return this._asPerson(world, () => items.map((it) => {
        const food = this._food(it.food_id);
        return { food_id: it.food_id, name: it.name, serving_desc: it.serving_desc ?? null, servings: Number(it.servings), available: !!(food && this._foodVisible(food)) };
      }));
    },
    _careExpire() {
      const now = new Date().toISOString();
      for (const sg of this._careSuggestions()) {
        if (sg.answer) continue;
        const share = sg.to === 'me' ? this._care().mine.find((x) => x.id === sg.share_id) : this._care().people.find((x) => x.id === sg.share_id);
        if (!share) { sg.answer = 'ended'; sg.answered_at = now; } else if (sg.expires_at <= now) { sg.answer = 'expired'; sg.answered_at = now; }
      }
    },
    _sentView(sg, world) {
      return { id: sg.id, date: sg.date, meal: sg.meal, items: this._careItemViews(world, sg.items), note: sg.note, created_at: sg.created_at,
        expires_at: sg.expires_at, answer: sg.answer || 'open', answered_at: sg.answered_at };
    },
    // account.export_data: the person's suggestions (care_suggestions.export_rows)
    _careExport() {
      return this._careSuggestions().filter((sg) => sg.to === 'me').map((sg) => ({ date: sg.date, meal: sg.meal, from: sg.from_name, note: sg.note,
        items: sg.items.map((it) => ({ name: it.name, servings: Number(it.servings) })), created_at: sg.created_at, answer: sg.answer || 'open',
        answered_at: sg.answered_at }));
    },
  });

  // ---- your Care team: /api/me/shares ----
  route('GET', '/api/me/shares', function () {
    this._currentUser();
    const s = this._care();
    return { enabled: true, areas: AREAS, roles: ROLES, max: 10, sharing: s.mine.map(withRole), codes: s.codes.map(withRole), invites: s.invites.map(withRole) };
  });
  route('POST', '/api/me/shares', function () {
    this._currentUser();
    fail(400, 'The demo has nobody to send a link to. On your own server, this makes a link.');
  });
  route('POST', '/api/me/shares/invite', function ({ body }) {
    const me = this._currentUser();
    const b = body || {};
    const name = String(b.username || '').trim().toLowerCase();
    if (!name) fail(400, 'Type the user name of the person you want to invite.');
    if (name === String(me.username).toLowerCase()) fail(400, 'That is your own user name. Type the user name of the person you want on your Care team.');
    if (b.role != null && !ROLES.includes(b.role)) fail(400, "role: Input should be 'viewer', 'care_helper' or 'caregiver'");
    const sw = PRESETS[b.role || 'viewer'];
    const areas = clean(b.areas, sw);
    if (!areas.length) fail(400, 'areas: List should have at least 1 item after validation, not 0');
    const s = this._care();
    s.invites = s.invites.filter((i) => i.username !== name);
    const inv = { id: s.nextId++, username: name, areas, ...sw, days: b.days || null, created_at: iso(0), expires_at: iso(7) };
    s.invites.push(inv);
    return withRole(inv);
  });
  route('DELETE', /^\/api\/me\/shares\/invites\/(\d+)$/, function ({ id }) {
    this._currentUser();
    const s = this._care();
    if (!s.invites.some((i) => i.id === Number(id))) fail(404, 'invite not found');
    s.invites = s.invites.filter((i) => i.id !== Number(id));
    return null;
  });
  route('PUT', /^\/api\/me\/shares\/(\d+)\/role$/, function ({ id, body }) {
    this._currentUser();
    const s = this._care().mine.find((x) => x.id === Number(id));
    if (!s) fail(404, 'share not found');
    if (!body || !ROLES.includes(body.role)) fail(400, "role: Input should be 'viewer', 'care_helper' or 'caregiver'");
    Object.assign(s, PRESETS[body.role]);
    s.areas = clean(s.areas, s);
    return withRole(s);
  });
  route('PUT', /^\/api\/me\/shares\/(\d+)\/switches$/, function ({ id, body }) {
    this._currentUser();
    const s = this._care().mine.find((x) => x.id === Number(id));
    if (!s) fail(404, 'share not found');
    const b = body && typeof body === 'object' ? body : {};
    const extra = Object.keys(b).filter((k) => k !== 'areas' && !SWITCHES.includes(k));
    if (extra.length) fail(400, `${extra[0]}: Extra inputs are not permitted`);
    for (const k of SWITCHES) if (k in b && b[k] !== null && typeof b[k] !== 'boolean') fail(400, `${k}: Input should be a valid boolean`);
    if ('areas' in b && b.areas !== null && (!Array.isArray(b.areas) || !b.areas.length || b.areas.some((a) => !AREAS.includes(a)))) {
      fail(400, 'areas: List should have at least 1 item after validation, not 0');
    }
    if ([...SWITCHES, 'areas'].some((k) => k in b && b[k] === null)) fail(400, 'Send true or false for each switch, and at least one area.');
    for (const k of SWITCHES) if (k in b) s[k] = b[k];
    s.areas = clean('areas' in b ? b.areas : s.areas, s);
    return withRole(s);
  });
  route('DELETE', /^\/api\/me\/shares\/(\d+)$/, function ({ id }) {
    this._currentUser();
    const s = this._care();
    if (!s.mine.some((x) => x.id === Number(id))) fail(404, 'share not found');
    s.mine = s.mine.filter((x) => x.id !== Number(id));
    return null;
  });

  // ---- the Care teams you are on: /api/shared ----
  route('GET', '/api/shared', function () {
    this._currentUser();
    const s = this._care();
    return { people: s.people.map(withRole), invites: s.forMe.map(withRole) };
  });
  route('POST', /^\/api\/shared\/invites\/(\d+)\/(accept|decline)$/, function ({ ids }) {
    this._currentUser();
    const s = this._care();
    const inv = s.forMe.find((i) => i.id === Number(ids[0]));
    if (!inv) fail(404, 'That invite is no longer open.');
    s.forMe = s.forMe.filter((i) => i !== inv);
    if (ids[1] === 'decline') return null;
    const person = { id: s.nextId++, name: inv.name, username: inv.username, areas: inv.areas, since: iso(0), until: inv.days ? iso(inv.days) : null, ...switchesOf(inv) };
    s.people.push(person);
    return withRole(person);
  });
  for (const p of ['/api/shared/info', '/api/shared/accept']) {
    route('POST', p, function () { this._currentUser(); fail(404, 'That link does not work. Ask for a new one.'); });
  }
  route('DELETE', /^\/api\/shared\/(\d+)$/, function ({ id }) {
    this._currentUser();
    const s = this._care();
    if (!s.people.some((x) => x.id === Number(id))) fail(404, 'share not found');
    s.people = s.people.filter((x) => x.id !== Number(id));
    return null;
  });

  // ---- what they share: the reads ----
  route('GET', /^\/api\/shared\/(\d+)\/profile$/, function ({ id }) {
    const p = this._careShare(id, null);
    const w = this._careWorld(p);
    const v = this._asPerson(w, () => this._profileView());
    return { name: p.name, ckd_stage: v.ckd_stage, dialysis: v.dialysis, diabetes: v.diabetes, dialysis_days: v.dialysis_days,
      week_start: v.week_start, weight_kg: null, targets: v.targets };
  });
  route('GET', /^\/api\/shared\/(\d+)\/(log|log\/range|log\/summary)$/, function ({ ids, query }) {
    return this._careAs(ids[0], 'GET', `/api/${ids[1]}?${query.toString()}`);
  });
  route('GET', /^\/api\/shared\/(\d+)\/(labs|symptoms|body\/summary|body\/weights|body\/blood-pressure)$/, function ({ ids }) {
    this._careShare(ids[0], ids[1].startsWith('body') ? 'body' : ids[1]); // the sample people share their food log only
    return fail(404, NOT_SHARED);
  });

  // ---- the helpers (sharing.care_helper, care_planner, care_food_search, care_saved_meals) ----
  const PLAN = ['may_plan'];
  const WRITE = ['may_plan', 'may_log'];
  const need = (p, k) => { if (!p[k]) fail(404, NOT_SHARED); };
  const switchFor = (status) => (status === 'eaten' ? 'may_log' : 'may_plan');
  route('GET', /^\/api\/shared\/(\d+)\/foods$/, function ({ ids, query }) {
    return this._careAs(ids[0], 'GET', `/api/foods?${query.toString()}`, undefined, undefined, ['may_plan', 'may_log', 'may_suggest']);
  });
  route('GET', /^\/api\/shared\/(\d+)\/plan\/shopping$/, function ({ ids, query }) {
    return this._careAs(ids[0], 'GET', `/api/plan/shopping?${query.toString()}`, undefined, undefined, PLAN);
  });
  const helperEntry = (b) => {
    if (b && typeof b === 'object' && b.status != null && !['planned', 'eaten'].includes(b.status)) fail(400, "status: Input should be 'planned' or 'eaten'");
    return { ...(b || {}), status: (b && b.status) || 'planned', client_id: null };
  };
  const markHelper = (row, who) => { if (row) { row.added_by = who; row.added_by_me = true; } };
  route('POST', /^\/api\/shared\/(\d+)\/log$/, function ({ ids, body }) {
    const who = this._helperName();
    const p = this._careShare(ids[0], 'food', WRITE);
    const b = helperEntry(body);
    need(p, switchFor(b.status));
    return this._asPerson(this._careWorld(p), () => {
      const e = this.handle('POST', '/api/log', b);
      const row = this._entry(e.id);
      markHelper(row, who);
      return this._entryView(row);
    });
  });
  route('POST', /^\/api\/shared\/(\d+)\/log\/batch$/, function ({ ids, body }) {
    const who = this._helperName();
    const p = this._careShare(ids[0], 'food', WRITE);
    const items = body && Array.isArray(body.entries) ? body.entries.map(helperEntry) : null;
    if (items) for (const it of items) need(p, switchFor(it.status));
    return this._asPerson(this._careWorld(p), () => {
      const res = this.handle('POST', '/api/log/batch', items ? { entries: items } : body);
      for (const e of res.entries) markHelper(this._entry(e.id), who);
      return { entries: res.entries.map((e) => this._entryView(this._entry(e.id))), results: res.results };
    });
  });
  route('POST', /^\/api\/shared\/(\d+)\/log\/clear-planned$/, function ({ ids, body }) {
    return this._careAs(ids[0], 'POST', '/api/log/clear-planned', body, undefined, PLAN);
  });
  route('POST', /^\/api\/shared\/(\d+)\/guidance\/plan-days$/, function ({ ids, body }) {
    const p = this._careShare(ids[0], 'food', PLAN);
    const useSaved = !!(body && body.use_saved_meals !== false) && !!p.may_use_saved_meals; // the server's default is true
    return this._careAs(ids[0], 'POST', '/api/guidance/plan-days', { ...(body || {}), use_saved_meals: useSaved }, undefined, PLAN);
  });
  route('*', /^\/api\/shared\/(\d+)\/log\/(\d+)$/, function ({ method, ids, body, header }) {
    if (method !== 'PUT' && method !== 'DELETE') fail(405, 'Method Not Allowed');
    const p = this._careShare(ids[0], 'food', WRITE);
    if (method === 'PUT') {
      const extra = Object.keys(body || {}).filter((k) => !['status', 'date', 'meal', 'servings', 'grams', 'note'].includes(k));
      if (extra.length) fail(400, `${extra[0]}: Extra inputs are not permitted`);
      if (body && body.status != null && body.status !== 'eaten') fail(400, "status: Input should be 'eaten'");
    }
    const eating = method === 'PUT' && body && body.status === 'eaten';
    return this._asPerson(this._careWorld(p), () => {
      const row = this._entry(ids[1]);
      // sharing._helper_entry: only the person's log; never a low treatment; planned food with its switch; eaten food only your own.
      if (!row) fail(404, `log entry ${ids[1]} not found`);
      if (row.purpose === 'hypo') fail(403, LOW_TREATMENT(p.name));
      if (row.status === 'planned') need(p, eating ? 'may_log' : 'may_plan');
      else if (!p.may_log) fail(404, `log entry ${ids[1]} not found`);
      else if (!row.added_by_me) fail(403, NOT_YOUR_EATEN);
      const ifMatch = header('If-Match');
      return this.handle(method, `/api/log/${ids[1]}`, body, ifMatch ? { 'If-Match': ifMatch } : undefined);
    });
  });
  route('GET', /^\/api\/shared\/(\d+)\/meals$/, function ({ ids }) {
    return this._careAs(ids[0], 'GET', '/api/meals', undefined, undefined, ['may_use_saved_meals']);
  });
  route('POST', /^\/api\/shared\/(\d+)\/meals\/(\d+)\/apply$/, function ({ ids, body }) {
    const who = this._helperName();
    const p = this._careShare(ids[0], 'food', ['may_use_saved_meals']);
    need(p, switchFor((body && body.status) || 'planned'));
    return this._asPerson(this._careWorld(p), () => {
      const res = this.handle('POST', `/api/meals/${ids[1]}/apply`, body);
      for (const e of res.entries) markHelper(this._entry(e.id), who);
      return { entries: res.entries.map((e) => this._entryView(this._entry(e.id))) };
    });
  });

  // ---- suggestions (app/care_suggestions.py) ----
  route('POST', /^\/api\/shared\/(\d+)\/suggestions$/, function ({ ids, body }) {
    const p = this._careShare(ids[0], 'food', ['may_suggest']);
    const b = body && typeof body === 'object' ? body : {};
    const extra = Object.keys(b).filter((k) => !['date', 'meal', 'items', 'note'].includes(k));
    if (extra.length) fail(400, `${extra[0]}: Extra inputs are not permitted`);
    const c = new M.Check(b);
    c.date('date'); c.choice('meal', KH.rules.MEAL_KEYS, { required: true });
    c.str('note', { max: MAX_NOTE, def: null });
    const v = c.done();
    if (!Array.isArray(b.items) || !b.items.length || b.items.length > MAX_ITEMS) fail(400, `items: List should have 1 to ${MAX_ITEMS} items`);
    b.items.forEach((it, i) => {
      if (!it || typeof it !== 'object' || !(Number(it.food_id) >= 1) || !(Number(it.servings) > 0 && Number(it.servings) <= 1000)) fail(400, `items.${i}: a food and servings above 0`);
    });
    const problem = noteProblem(v.note, p.name);
    if (problem) fail(400, problem);
    const w = this._careWorld(p);
    const items = this._asPerson(w, () => b.items.map((it, i) => {
      const food = this._food(it.food_id);
      if (!food || !this._foodVisible(food)) fail(404, `items[${i}]: food ${it.food_id} not found`);
      if ((food.flags || []).includes('hypo_treatment')) fail(400, LOW_FOOD(food.name, p.name));
      return { food_id: food.id, servings: Number(it.servings), name: food.name, serving_desc: food.serving_desc };
    }));
    const all = this._careSuggestions();
    this._careExpire();
    if (all.filter((sg) => sg.share_id === p.id && sg.to !== 'me' && !sg.answer).length >= MAX_OPEN_PER_SHARE) fail(409, TOO_MANY_OPEN(p.name));
    const since = new Date(Date.now() - DAY_MS).toISOString();
    if (all.filter((sg) => sg.to !== 'me' && sg.created_at > since).length >= MAX_PER_DAY) fail(429, TOO_MANY_TODAY);
    const sg = { id: this._care().nextId++, share_id: p.id, to: 'ana', date: v.date, meal: v.meal, items, note: v.note || null, created_at: iso(0),
      expires_at: iso(SUGGEST_DAYS), answer: null, answered_at: null };
    all.push(sg);
    return { ...this._sentView(sg, w), fit: this._careFit(w, sg.date, sg.meal, sg.items) };
  });
  route('GET', /^\/api\/shared\/(\d+)\/suggestions$/, function ({ ids }) {
    const p = this._careShare(ids[0], null);
    this._careExpire();
    const w = this._careWorld(p);
    return { suggestions: this._careSuggestions().filter((sg) => sg.share_id === p.id && sg.to !== 'me').slice().reverse().slice(0, 50).map((sg) => this._sentView(sg, w)) };
  });
  const mine = (api) => { api._careExpire(); return api._careSuggestions().filter((sg) => sg.to === 'me' && !sg.answer); };
  route('GET', '/api/me/suggestions', function () {
    this._currentUser();
    const me = { entries: this._entries, profile: this._profile, templates: this._templates };
    return { enabled: true, suggestions: mine(this).slice().sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.id - b.id)).map((sg) => ({
      ...this._sentView(sg, me), share_id: sg.share_id, from_name: sg.from_name, fit: this._careFit(me, sg.date, sg.meal, sg.items) })) };
  });
  route('POST', /^\/api\/me\/suggestions\/(\d+)\/(accept|decline)$/, function ({ ids }) {
    this._currentUser();
    const sg = mine(this).find((x) => x.id === Number(ids[0]));
    if (!sg) fail(404, NO_SUGGESTION);
    const now = new Date().toISOString();
    if (ids[1] === 'decline') { sg.answer = 'declined'; sg.answered_at = now; return null; }
    const rows = [];
    let skipped = 0;
    for (const it of sg.items) {
      const food = this._food(it.food_id);
      if (!food || !this._foodVisible(food)) { skipped += 1; continue; }
      rows.push(this._insertEntry({ date: sg.date, meal: sg.meal, food, servings: Number(it.servings), status: 'planned',
        purpose: (food.flags || []).includes('hypo_treatment') ? 'hypo' : null }));
    }
    if (!rows.length) fail(409, NONE_LEFT);
    sg.answer = 'accepted'; sg.answered_at = now;
    return { entries: rows.map((r) => this._entryView(r)), skipped };
  });

  M.care = { AREAS, ROLES, SWITCHES, PRESETS, SUGGEST_DAYS, MAX_OPEN_PER_SHARE, MAX_PER_DAY, MAX_NOTE, MAX_ITEMS, BANNED_SOURCE, roleOf, noteProblem,
    texts: { not_shared: NOT_SHARED, low_treatment: LOW_TREATMENT('Ana'), not_your_eaten: NOT_YOUR_EATEN, no_suggestion: NO_SUGGESTION,
      none_left: NONE_LEFT, too_many_open: TOO_MANY_OPEN('Ana'), too_many_today: TOO_MANY_TODAY, low_food: LOW_FOOD('Glucose tablets', 'Ana') } };
})();
