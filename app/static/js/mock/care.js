/* Kidney Diet Log — demo API: the Care team (app/sharing.py, design notes 19 and 25).

   The demo has no other accounts, so it shows a sample Care team, kept in memory only (never saved by "Keep my data in this
   browser"):
   * your Care team: Jordan, a Care helper, who planned two foods today; an invite to "riley" waiting for an answer;
   * an invite for you from Lee (a Viewer of the food log), with Accept and Decline;
   * Ana, whose Care helper you are: her food log, her plan and her shopping list, with a few planned foods.
   Ana's days are a second set of entries with her own profile (a copy of yours, named Ana) and no saved meals. Her routes run the
   demo's own log, foods, shopping and planning twins with her entries swapped in, so the numbers are worked out the same way.
   A link cannot be made or used here: there is nobody to send it to. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi, fail } = M;

  const AREAS = ['food', 'labs', 'body', 'symptoms', 'activity'];
  const ROLES = ['viewer', 'care_helper'];
  const NOT_SHARED = 'Not shared with you.';
  const DAY_MS = 86400000;
  const iso = (offsetDays) => new Date(Date.now() + offsetDays * DAY_MS).toISOString();
  const day = (offsetDays) => KH.util.addDays(KH.util.todayStr(), offsetDays);
  const clean = (areas, role) => AREAS.filter((a) => (areas || []).includes(a) || (a === 'food' && role === 'care_helper'));

  Object.assign(MockApi.prototype, {
    _care() {
      if (this._careState) return this._careState;
      this._careState = {
        nextId: 100,
        mine: [{ id: 1, name: 'Jordan', username: 'jordan', areas: ['food', 'labs'], since: iso(-6), until: null, last_viewed_at: iso(0), active: true,
          role: 'care_helper', helper_changes: { day: iso(0).slice(0, 10), added: 2, changed: 0, removed: 0 } }],
        codes: [],
        invites: [{ id: 2, username: 'riley', areas: ['food'], role: 'viewer', days: null, created_at: iso(-1), expires_at: iso(6) }],
        people: [{ id: 3, name: 'Ana', username: 'ana', areas: ['food'], since: iso(-20), until: null, role: 'care_helper' }],
        forMe: [{ id: 4, name: 'Lee', username: 'lee', areas: ['food'], role: 'viewer', days: 30, expires_at: iso(5) }],
        worlds: {},
      };
      return this._careState;
    },
    // A sample person's own data: their entries, a profile (a copy of yours with their name) and no saved meals.
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
        });
      }
      return w;
    },
    _asPerson(world, fn) {
      const saved = [this._entries, this._profile, this._templates, this._inCareWorld];
      this._entries = world.entries; this._profile = world.profile; this._templates = world.templates; this._inCareWorld = true;
      try { return fn(); } finally { [this._entries, this._profile, this._templates, this._inCareWorld] = saved; }
    },
    // sharing._check_share: the share is yours, has the area and (for a write) the role; else the one 404.
    _careShare(id, area, role = null) {
      this._currentUser();
      const p = this._care().people.find((x) => x.id === Number(id));
      if (!p || (area && !p.areas.includes(area)) || (role && p.role !== role)) fail(404, NOT_SHARED);
      return p;
    },
    _careAs(id, method, path, body, headers, { area = 'food', role = null } = {}) {
      const p = this._careShare(id, area, role);
      return this._asPerson(this._careWorld(p), () => this.handle(method, path, body, headers));
    },
    _helperName() { const u = this._currentUser(); return (u.display_name || '').trim() || u.username; },
  });

  // ---- your Care team: /api/me/shares ----
  route('GET', '/api/me/shares', function () {
    this._currentUser();
    const s = this._care();
    return { enabled: true, areas: AREAS, roles: ROLES, max: 10, sharing: s.mine, codes: s.codes, invites: s.invites };
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
    const role = ROLES.includes(b.role) ? b.role : 'viewer';
    const areas = clean(b.areas, role);
    if (!areas.length) fail(400, 'areas: List should have at least 1 item after validation, not 0');
    const s = this._care();
    s.invites = s.invites.filter((i) => i.username !== name);
    const inv = { id: s.nextId++, username: name, areas, role, days: b.days || null, created_at: iso(0), expires_at: iso(7) };
    s.invites.push(inv);
    return inv;
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
    if (!body || !ROLES.includes(body.role)) fail(400, "role: Input should be 'viewer' or 'care_helper'");
    s.role = body.role;
    s.areas = clean(s.areas, s.role);
    return s;
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
    return { people: s.people, invites: s.forMe };
  });
  route('POST', /^\/api\/shared\/invites\/(\d+)\/(accept|decline)$/, function ({ ids }) {
    this._currentUser();
    const s = this._care();
    const inv = s.forMe.find((i) => i.id === Number(ids[0]));
    if (!inv) fail(404, 'That invite is no longer open.');
    s.forMe = s.forMe.filter((i) => i !== inv);
    if (ids[1] === 'decline') return null;
    const person = { id: s.nextId++, name: inv.name, username: inv.username, areas: inv.areas, since: iso(0), until: inv.days ? iso(inv.days) : null, role: inv.role };
    s.people.push(person);
    return person;
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

  // ---- the Care helper (sharing.care_helper) ----
  const HELPER = { role: 'care_helper' };
  route('GET', /^\/api\/shared\/(\d+)\/foods$/, function ({ ids, query }) { return this._careAs(ids[0], 'GET', `/api/foods?${query.toString()}`, undefined, undefined, HELPER); });
  route('GET', /^\/api\/shared\/(\d+)\/plan\/shopping$/, function ({ ids, query }) {
    return this._careAs(ids[0], 'GET', `/api/plan/shopping?${query.toString()}`, undefined, undefined, HELPER);
  });
  const planned = (b) => {
    if (b && typeof b === 'object' && b.status != null && b.status !== 'planned') fail(400, "status: Input should be 'planned'");
    return { ...(b || {}), status: 'planned', client_id: null };
  };
  route('POST', /^\/api\/shared\/(\d+)\/log$/, function ({ ids, body }) {
    const who = this._helperName();
    const p = this._careShare(ids[0], 'food', 'care_helper');
    const w = this._careWorld(p);
    return this._asPerson(w, () => {
      const e = this.handle('POST', '/api/log', planned(body));
      const row = this._entry(e.id);
      row.added_by = who;
      return this._entryView(row);
    });
  });
  route('POST', /^\/api\/shared\/(\d+)\/log\/batch$/, function ({ ids, body }) {
    const who = this._helperName();
    const p = this._careShare(ids[0], 'food', 'care_helper');
    const items = body && Array.isArray(body.entries) ? body.entries.map(planned) : body;
    return this._asPerson(this._careWorld(p), () => {
      const res = this.handle('POST', '/api/log/batch', Array.isArray(items) ? { entries: items } : items);
      for (const e of res.entries) { const row = this._entry(e.id); if (row) row.added_by = who; }
      return { entries: res.entries.map((e) => this._entryView(this._entry(e.id))), results: res.results };
    });
  });
  route('POST', /^\/api\/shared\/(\d+)\/log\/clear-planned$/, function ({ ids, body }) {
    return this._careAs(ids[0], 'POST', '/api/log/clear-planned', body, undefined, HELPER);
  });
  route('POST', /^\/api\/shared\/(\d+)\/guidance\/plan-days$/, function ({ ids, body }) {
    return this._careAs(ids[0], 'POST', '/api/guidance/plan-days', { ...(body || {}), use_saved_meals: false }, undefined, HELPER);
  });
  route('*', /^\/api\/shared\/(\d+)\/log\/(\d+)$/, function ({ method, ids, body, header }) {
    if (method !== 'PUT' && method !== 'DELETE') fail(405, 'Method Not Allowed');
    const p = this._careShare(ids[0], 'food', 'care_helper');
    return this._asPerson(this._careWorld(p), () => {
      const row = this._entry(ids[1]);
      // A helper never changes eaten food or a low treatment, and only reaches the person's own entries.
      if (!row || row.status !== 'planned' || row.purpose === 'hypo') fail(404, `log entry ${ids[1]} not found`);
      if (method === 'PUT') {
        const extra = Object.keys(body || {}).filter((k) => !['date', 'meal', 'servings', 'grams', 'note'].includes(k));
        if (extra.length) fail(400, `${extra[0]}: Extra inputs are not permitted`);
      }
      const ifMatch = header('If-Match');
      return this.handle(method, `/api/log/${ids[1]}`, body, ifMatch ? { 'If-Match': ifMatch } : undefined);
    });
  });
})();
