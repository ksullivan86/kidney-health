/* Kidney Diet Log — demo API: your own list app and recipe import (twin of app/list_sync/api.py and app/recipe_import/api.py,
   design note 30).

   The demo has no server and never leaves the page:
   * List sync answers like a server with it on and a sample Grocy at http://grocy.example already set up (key set, list
     "Groceries" chosen). Test, preview and Send work against a fake list app in the page, which keeps what was sent in memory
     (`_listsState().sent`). Nothing is saved by "Keep my data in this browser".
   * Recipe import answers like a server with web pages on: any link gives the built-in sample recipe page below (its schema.org
     Recipe data), read with the same parser and matched with the demo's own food search, as the server does. Pasted ingredients
     work as on a server.
   * Instacart (app/instacart.py, design note 33) answers like a server with it on. Preview shows the same lines as list sync;
     Send answers a placeholder link (#instacart-demo) that does not leave the page, and nothing is sent.
   The words of each list line and the parser are pinned to the server by tests/data/lists_recipes_vectors.json.

   DEVICE MODE (the iPhone app, design note 39 §7, plan step 9): none of the demo's stand-ins. Recipe pages, Instacart and the list
   app are the person's own server's, through its gateway (js/mock/server_api.js), and only with a token both ways and the service
   on there; the server reads the page through its checked transport and uses its own keys, and no key comes to the phone. With no
   such server, or while it cannot be reached, they are off, as on a server with them off: the recipe sheet offers pasting only
   (pasted ingredients are read here, offline too), and Plan shows no Instacart or list app button. A recipe page's lines are
   matched again with this phone's own foods, the ones the recipe is saved with. The list app is set up in the server's web app.
   The server makes its lists from its own Plan, which holds the phone's plans once they are sent; its lines name its own food ids,
   so they are shown with this phone's ids (by the food's name, so "ticked on this phone" works) and sent back with the server's. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi, fail, Check } = M;
  const R = KH.recipeImport;

  const APPS = [
    { id: 'grocy', name: 'Grocy', key_name: 'API key', key_help: 'In Grocy, open Settings (the wrench), then Manage API keys, then Add.' },
    { id: 'kitchenowl', name: 'KitchenOwl', key_name: 'Long-lived token', key_help: 'In KitchenOwl, open Settings, then your profile, then Sessions, and add a long-lived token.' },
    { id: 'mealie', name: 'Mealie', key_name: 'API token', key_help: 'In Mealie, open your profile, then API Tokens, and generate one.' },
  ];
  const APP_IDS = APPS.map((a) => a.id);
  const FAKE_LISTS = [{ id: '1', name: 'Groceries' }];
  const KEY_AGAIN = 'Enter the key again: it is needed for a new address or a different app.';
  const NO_LIST = 'Choose a list first: press Test in Settings → Shopping list app.';
  const MAX_ITEMS = 200;

  // The words a list line is sent with (app/list_sync/api.py list_item; the same as Plan's "Share list").
  function listItem(row) {
    const amount = KH.rules.fmtServings(row.servings) + (row.serving_desc ? ` of ${row.serving_desc}` : '');
    return { food_id: row.food_id, name: row.food_name, amount, text: `${row.food_name}: ${amount}` };
  }
  // app/list_sync/apps.py check_base_url (the demo allows home addresses, as a server with LIST_SYNC_ALLOWED_HOSTS does).
  function checkBaseUrl(raw) {
    const text = String(raw || '').trim();
    if (!text || text.length > 500 || /\s/.test(text)) return [null, 'Enter the address of your list app, such as https://grocy.example.com.'];
    let u;
    try { u = new URL(text); } catch { return [null, 'That address cannot be read. Enter it as https://your-server or http://192.168.1.20:9283.']; }
    if (!['http:', 'https:'].includes(u.protocol) || !u.hostname || u.port === '0' || !/^https?:\/\//i.test(text)) return [null, 'The address must start with http:// or https:// and name a server.'];
    if (u.username || u.password) return [null, 'Leave the user name and password out of the address. The key goes in its own box.'];
    if (u.search || u.hash || /[?#]/.test(text)) return [null, 'Leave anything after ? or # out of the address.'];
    return [`${u.protocol}//${u.host}${u.pathname.replace(/\/+$/, '')}`, null];
  }

  // ---- device mode: the server's services through the gateway ----
  const DEVICE = !!(KH.flags && KH.flags.DEVICE === true);
  const UNREACHABLE = 'Your server cannot be reached right now. Try again when this iPhone is online.';
  const isDict = (v) => v != null && typeof v === 'object' && !Array.isArray(v);
  const idMaps = new Map(); // "<what>|<start>|<end>" → Map(the id shown on this phone → the server's id); in memory only
  // What the server says of a service (its GET), or `off` when it is not offered both ways, is off there, or cannot be reached.
  async function serverStatus(what, path, off) {
    const S = M.serverApi;
    if (!S || !(await S.offers(what))) return off;
    const res = await S.call('GET', path);
    return res.status === 200 && isDict(res.json) ? res.json : off;
  }
  // One request to the server's route: its answer, or its error as the page's own.
  async function viaServer(what, method, path, body) {
    const S = M.serverApi;
    if (!S || !(await S.offers(what))) fail(404, 'Not Found');
    const res = await S.call(method, path, { body });
    if (res.offline || res.error) fail(503, UNREACHABLE);
    if (res.status >= 400 || !isDict(res.json)) S.failWith(res);
    return res.json;
  }
  // The server's lines with this phone's food ids, remembered for the send that follows.
  function shownHere(api, what, b, json) {
    const here = new Map();
    try { for (const it of api._shopping(b.start, b.end).items) if (!here.has(it.food_name)) here.set(it.food_name, it.food_id); } catch (e) { /* the server checked the range */ }
    const map = new Map();
    json.items = (Array.isArray(json.items) ? json.items : []).map((it, i) => {
      let id = here.get(it.name);
      if (id == null || map.has(id)) id = -(i + 1); // not planned on this phone: an id no food has
      map.set(id, it.food_id);
      return { ...it, food_id: id };
    });
    idMaps.set(`${what}|${b.start}|${b.end}`, map);
    return json;
  }
  function toServer(what, body) {
    const b = isDict(body) ? body : {};
    const map = idMaps.get(`${what}|${b.start}|${b.end}`);
    return Array.isArray(b.food_ids) ? { ...b, food_ids: b.food_ids.map((id) => (map && map.has(id) ? map.get(id) : id)) } : b;
  }
  const rangeOf = (body) => (isDict(body) ? { start: body.start, end: body.end } : {});

  Object.assign(MockApi.prototype, {
    _listsState() {
      if (!this._listSync && this._sample !== true) this._listSync = { sent: [], connection: null }; // no sample list app
      if (!this._listSync) {
        this._listSync = { sent: [], connection: { app: 'grocy', base_url: 'http://grocy.example', list_id: '1', list_name: 'Groceries',
          key_set: true, last_test_at: null, last_test_error: null, last_sent_at: null, last_sent_count: null } };
      }
      return this._listSync;
    },
    _listConnection() { const c = this._listsState().connection; if (!c) fail(404, 'Not Found'); return c; },
    _listItems(body) {
      const c = new Check(body);
      c.str('start', { required: true, nullable: false }); c.str('end', { required: true, nullable: false });
      const b = c.done();
      return this._shopping(b.start, b.end).items.map(listItem);
    },
    _importDraft(recipe, sourceUrl) {
      const lines = [];
      for (const text of recipe.lines) {
        const parsed = R.parseLine(text);
        if (!parsed.text) continue;
        let matches = [];
        for (const q of R.searchTerms(parsed.food_text)) {
          const foods = this._searchFoods(q, null, null, 3);
          if (foods.length) {
            matches = foods.map((f) => ({ food: Object.fromEntries(FOOD_KEYS.map((k) => [k, f[k] === undefined ? null : f[k]])),
              servings: R.recipeServings(parsed.amount, parsed.unit, f.serving_desc, f.serving_g) }));
            break;
          }
        }
        lines.push({ ...parsed, matches });
      }
      if (!lines.length) fail(422, 'No ingredient lines were found. Paste one ingredient on each line.', { code: 'no_lines' });
      return { name: recipe.name || null, servings_made: recipe.servings_made ?? null, steps: recipe.steps || [], steps_cut: !!recipe.steps_cut,
        lines_cut: !!recipe.lines_cut, source_url: sourceUrl, lines, notice: CHECK_TEXT, estimate: ESTIMATE_TEXT };
    },
  });
  const FOOD_KEYS = ['id', 'name', 'brand', 'category', 'source', 'serving_desc', 'serving_g', 'nutrients', 'flags', 'warnings', 'kidney_rating', 'hidden'];
  const CHECK_TEXT = 'Check each food the app chose, and fix it if it is wrong. Nothing is saved until you press Save.';
  const ESTIMATE_TEXT = 'These numbers are estimates. Recipe sites rarely list potassium or phosphorus, so the app works them out from its '
    + 'own food list. Cooking, soaking and draining change what ends up on the plate, and the app does not count that.';

  // ---- list sync ----
  route('GET', '/api/list-sync', function () {
    this._currentUser();
    if (DEVICE) return serverStatus('listSync', '/api/list-sync', { enabled: false, can_use: false, private_hosts: false, apps: APPS.map((a) => ({ ...a })), connection: null });
    return { enabled: true, can_use: true, private_hosts: true, apps: APPS.map((a) => ({ ...a })), connection: this._listsState().connection ? { ...this._listsState().connection } : null };
  });
  route('PUT', '/api/list-sync', function ({ body }) {
    this._currentUser();
    if (DEVICE) fail(404, 'Not Found'); // set up in the server's web app
    const c = new Check(body);
    c.choice('app', APP_IDS, { required: true, nullable: false });
    c.str('base_url', { required: true, min: 1, max: 500, nullable: false });
    c.str('key', { min: 1, max: 4096, def: null });
    c.str('list_id', { max: 64, def: null });
    c.str('list_name', { max: 200, def: null });
    const b = c.done();
    const [baseUrl, problem] = checkBaseUrl(b.base_url);
    if (problem) fail(400, problem);
    const st = this._listsState();
    const row = st.connection;
    const same = !!row && row.app === b.app && row.base_url === baseUrl;
    if (b.key == null && !(same && row.key_set)) fail(400, KEY_AGAIN);
    const listId = b.list_id || null;
    if (listId != null && !(b.app === 'mealie' ? /^[A-Za-z0-9-]{1,64}$/.test(listId) : /^[0-9]{1,18}$/.test(listId))) {
      fail(400, 'That list cannot be used. Press Test and choose one of your lists.');
    }
    let [id, name] = [listId, listId ? (b.list_name || null) : null];
    if (listId == null && same && !('list_id' in (body || {}))) [id, name] = [row.list_id, row.list_name];
    const keepTest = same && b.key == null;
    const keepSend = keepTest && id === row.list_id;
    st.connection = { app: b.app, base_url: baseUrl, list_id: id, list_name: name, key_set: true,
      last_test_at: keepTest ? row.last_test_at : null, last_test_error: keepTest ? row.last_test_error : null,
      last_sent_at: keepSend ? row.last_sent_at : null, last_sent_count: keepSend ? row.last_sent_count : null };
    return { ...st.connection };
  });
  route('DELETE', '/api/list-sync', function () {
    this._currentUser();
    if (DEVICE) fail(404, 'Not Found');
    this._listConnection();
    this._listsState().connection = null;
    return null;
  });
  route('POST', '/api/list-sync/test', function () {
    this._currentUser();
    if (DEVICE) fail(404, 'Not Found');
    const conn = this._listConnection();
    conn.last_test_at = new Date().toISOString();
    conn.last_test_error = null;
    const chosen = FAKE_LISTS.find((x) => x.id === conn.list_id);
    if (chosen) conn.list_name = chosen.name;
    else if (FAKE_LISTS.length === 1) { conn.list_id = FAKE_LISTS[0].id; conn.list_name = FAKE_LISTS[0].name; }
    return { ok: true, error: null, message: null, lists: FAKE_LISTS.map((x) => ({ ...x })), connection: { ...conn } };
  });
  route('POST', '/api/list-sync/preview', function ({ body }) {
    this._currentUser();
    if (DEVICE) return viaServer('listSync', 'POST', '/api/list-sync/preview', rangeOf(body)).then((json) => shownHere(this, 'list', rangeOf(body), json));
    const conn = this._listConnection();
    const items = this._listItems(body);
    const app = APPS.find((a) => a.id === conn.app);
    return { app: conn.app, app_name: app ? app.name : conn.app, list_name: conn.list_name, ready: !!conn.list_id, items,
      last_sent_at: conn.last_sent_at, last_sent_count: conn.last_sent_count };
  });
  route('POST', '/api/list-sync/send', function ({ body }) {
    this._currentUser();
    if (DEVICE) return viaServer('listSync', 'POST', '/api/list-sync/send', toServer('list', body));
    const conn = this._listConnection();
    const ids = body && Array.isArray(body.food_ids) ? body.food_ids : null;
    if (!ids || !ids.length || ids.length > MAX_ITEMS || ids.some((x) => !Number.isInteger(x))) fail(400, 'food_ids: Choose between 1 and 200 foods.');
    if (!conn.list_id) fail(409, NO_LIST);
    const wanted = new Set(ids);
    const items = this._listItems(body).filter((i) => wanted.has(i.food_id));
    if (!items.length) fail(400, 'None of those foods are on this list. Open the list again and choose what to send.');
    this._listsState().sent.push(...items.map((i) => ({ list: conn.list_id, text: i.text })));
    conn.last_sent_at = new Date().toISOString();
    conn.last_sent_count = items.length;
    return { sent: items.length, error: null, message: null, connection: { ...conn } };
  });

  // ---- Instacart (twin of app/instacart.py, design note 33) ----
  // The demo answers like a server with Instacart on. Send gives a placeholder link that stays in the page: nothing is sent.
  const INSTACART_TITLE = 'Shopping list';
  const INSTACART_DEMO_LINK = '#instacart-demo';
  route('GET', '/api/instacart', function () {
    this._currentUser();
    if (DEVICE) return serverStatus('instacart', '/api/instacart', { enabled: false, max_items: MAX_ITEMS });
    return { enabled: true, max_items: MAX_ITEMS };
  });
  route('POST', '/api/instacart/preview', function ({ body }) {
    this._currentUser();
    if (DEVICE) return viaServer('instacart', 'POST', '/api/instacart/preview', rangeOf(body)).then((json) => shownHere(this, 'instacart', rangeOf(body), json));
    return { title: INSTACART_TITLE, items: this._listItems(body) };
  });
  route('POST', '/api/instacart/send', function ({ body }) {
    this._currentUser();
    if (DEVICE) return viaServer('instacart', 'POST', '/api/instacart/send', toServer('instacart', body));
    const ids = body && Array.isArray(body.food_ids) ? body.food_ids : null;
    if (!ids || !ids.length || ids.length > MAX_ITEMS || ids.some((x) => !Number.isInteger(x))) fail(400, 'food_ids: Choose between 1 and 200 foods.');
    const wanted = new Set(ids);
    const items = this._listItems(body).filter((i) => wanted.has(i.food_id));
    if (!items.length) fail(400, 'None of those foods are on this list. Open the list again and choose what to send.');
    return { url: INSTACART_DEMO_LINK, items: items.length, error: null, message: null };
  });

  // ---- recipe import ----
  // The demo's one recipe page: what a recipe site's schema.org Recipe data looks like. Its foods are in the built-in list, but the
  // thyme, so one line shows how an ingredient the app cannot match looks.
  const SAMPLE_PAGE = {
    '@context': 'https://schema.org',
    '@graph': [
      { '@type': 'WebSite', name: 'A sample recipe site' },
      { '@type': 'Recipe', name: 'Lemon garlic chicken with rice', recipeYield: ['4', '4 servings'],
        recipeIngredient: ['1 lb boneless skinless chicken breast', '2 cups cooked white rice', '1 cup low-sodium chicken broth',
          '2 cups green beans, trimmed', '3 cloves garlic, minced', '2 tbsp fresh lemon juice', '1 tbsp olive oil',
          '1/4 tsp black pepper', '1 tsp dried thyme'],
        recipeInstructions: [
          { '@type': 'HowToStep', text: 'Cut the chicken into bite-size pieces.' },
          { '@type': 'HowToStep', text: 'Heat the oil in a large pan. Cook the chicken and garlic for 6 to 8 minutes, until cooked through.' },
          { '@type': 'HowToStep', text: 'Add the broth, green beans, thyme and pepper. Cover and simmer for 5 minutes.' },
          { '@type': 'HowToStep', text: 'Stir in the lemon juice and serve over the rice.' }],
        nutrition: { '@type': 'NutritionInformation', calories: '380 kcal', sodiumContent: '210 mg' } },
    ],
  };
  route('GET', '/api/recipe-import', function () {
    this._currentUser();
    if (DEVICE) return serverStatus('recipe', '/api/recipe-import', { web: false, max_lines: R.MAX_LINES, estimate: ESTIMATE_TEXT });
    return { web: true, max_lines: R.MAX_LINES, estimate: ESTIMATE_TEXT };
  });
  route('POST', '/api/recipe-import/page', function ({ body }) {
    this._currentUser();
    const c = new Check(body);
    c.str('url', { required: true, min: 1, max: 900, nullable: false });
    const b = c.done();
    const url = b.url.trim();
    if (DEVICE) { // the server reads the page; this phone matches its lines with its own foods
      return viaServer('recipe', 'POST', '/api/recipe-import/page', { url }).then((d) => this._importDraft({ name: d.name || null,
        servings_made: d.servings_made ?? null, steps: Array.isArray(d.steps) ? d.steps : [], steps_cut: !!d.steps_cut, lines_cut: !!d.lines_cut,
        lines: (Array.isArray(d.lines) ? d.lines : []).map((line) => String((line && line.text) || '')) }, typeof d.source_url === 'string' ? d.source_url : url));
    }
    let port = '';
    try { port = new URL(url).port; } catch { /* checked below */ }
    if (M.checkSourceUrl(url) || (port && !['80', '443'].includes(port))) {
      fail(400, 'That link cannot be read. Use a web address that starts with http:// or https://.', { code: 'bad_link' });
    }
    return this._importDraft(R.recipeFromJsonld(R.findRecipe(SAMPLE_PAGE)), url);
  });
  route('POST', '/api/recipe-import/text', function ({ body }) {
    this._currentUser();
    const c = new Check(body);
    c.str('text', { required: true, min: 1, max: 20000, nullable: false });
    c.str('name', { max: 200, def: null, emptyToNull: true });
    c.num('servings', { gt: 0, le: 100 });
    const b = c.done();
    const [lines, cut] = R.linesOfText(b.text.trim());
    return this._importDraft({ name: b.name ? b.name.trim() || null : null, servings_made: b.servings ?? null, steps: [], steps_cut: false,
      lines, lines_cut: cut }, null);
  });

  M.lists = { APPS, listItem, checkBaseUrl, SAMPLE_PAGE, CHECK_TEXT, ESTIMATE_TEXT };
})();
