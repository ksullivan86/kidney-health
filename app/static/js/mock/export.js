/* Kidney Diet Log — demo API: the export (twin of app/account.py export_data).

   GET /api/me/export.json answers the document that is export.json inside the server's GET /api/me/export.zip: the same
   keys, the same record shapes, so the file can be chosen in "Import from a file" on a real server (app/data_import.py) and
   in this demo (js/mock/import.js). The server's zip also holds CSV files and a README; the demo gives the JSON only (it
   cannot write a zip), and Settings → Your data downloads it as export.json.

   What differs from a server's file, on purpose: `linked_foods` items have `linked_at: null` (the demo does not keep when a
   shared food was scanned), the AI sections are empty (`ai_audit`, `ai_usage`, `ai_consents`, `ai_provider: null`: the
   demo has no AI), and `app_version` is the page's own version. Passwords, sessions and keys are never in it. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi } = M;
  const EXPORT_FORMAT = 'kidney-health-export';
  const EXPORT_VERSION = 1;
  const MAX_EVENTS = 500;

  const byId = (a, b) => a.id - b.id;

  Object.assign(MockApi.prototype, {
    // The export.json document of the signed-in person (app/account.py export_data), key order included.
    _exportDocument() {
      const u = this._currentUser();
      const uid = u.id;
      const own = this._settingsState().users[uid] || {};
      const settings = {};
      for (const key of Object.keys(own).sort()) settings[key] = JSON.parse(JSON.stringify(own[key]));

      const entries = this._fetchEntries().map((row) => { const v = this._entryView(row); delete v.version; return v; }); // the version is derived, not data
      const customFoods = this._foods.filter((f) => f.source === 'custom').sort(byId).map((f) => this._foodView(f));
      const linked = this._foods.filter((f) => f.source !== 'builtin' && f.source !== 'custom' && this._foodLinks().has(f.id)).sort(byId)
        .map((f) => ({ id: f.id, name: f.name, source: f.source, fdc_id: f.fdc_id, linked_at: null, gtin: f.gtin || null, food: this._foodView(f) }));
      const templates = this._templates.slice().sort(byId).map((t) => this._templateView(t));
      const labs = this._labsOf(uid).slice().sort((a, b) => (a.taken_on < b.taken_on ? -1 : a.taken_on > b.taken_on ? 1 : a.id - b.id)).map((r) => ({
        id: r.id, analyte: r.analyte, value: r.value, unit: (KH.kidney.ANALYTES[r.analyte] || {}).canonical_unit || '',
        entered_value: r.entered_value, entered_unit: r.entered_unit, taken_on: r.taken_on, note: r.note, created_at: r.created_at }));
      const symptoms = this._symptomsOf(uid).slice().sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.id - b.id)).map((r) => ({
        id: r.id, date: r.date, symptom: r.symptom, label: r.label, severity: r.severity, note: r.note, created_at: r.created_at }));
      const prefs = [...this._foodPreferences().entries()].map(([foodId, createdAt]) => ({ food: this._food(foodId), createdAt }))
        .filter((p) => p.food).sort((a, b) => a.food.id - b.food.id)
        .map((p) => ({ food_id: p.food.id, name: p.food.name, preference: 'not_for_me', created_at: p.createdAt }));
      // The built-in foods the entries, saved meals and "Not for me" list point at, so another server can find them by FoodData Central id.
      const used = new Set(entries.map((e) => e.food_id));
      for (const t of this._templates) for (const it of t.items) used.add(it.food_id);
      for (const p of prefs) used.add(p.food_id);
      const builtin = [...used].map((id) => this._food(id)).filter((f) => f && f.source === 'builtin').sort(byId)
        .map((f) => ({ id: f.id, name: f.name, fdc_id: f.fdc_id }));
      const a = this._authState();
      const activity = a.events.filter((e) => (e.target_type === 'user' && e.target_id === String(uid))
        || (e.actor_user_id === uid && (e.target_type !== 'user' || e.target_id == null || e.target_id === String(uid))))
        .sort((x, y) => y.id - x.id).slice(0, MAX_EVENTS).map((e) => JSON.parse(JSON.stringify(e)));
      const views = KH.views || {};
      return {
        format: EXPORT_FORMAT,
        version: EXPORT_VERSION,
        exported_at: this._stamp(new Date()),
        app_version: views.settings && views.settings.APP_VERSION ? views.settings.APP_VERSION : null,
        user: { username: u.username, display_name: u.display_name || '', created_at: u.created_at },
        profile: this._profileView(),
        settings,
        log_entries: entries,
        custom_foods: customFoods,
        linked_foods: linked,
        meal_templates: templates,
        lab_results: labs,
        symptoms,
        ai_audit: [],
        activity,
        food_preferences: prefs,
        ai_usage: [],
        ai_consents: [],
        ai_provider: null,
        builtin_foods: builtin,
      };
    },
  });

  route('GET', '/api/me/export.json', function () {
    const doc = this._exportDocument();
    this._audit(this._currentUser().id, 'export.created', 'user', this._currentUser().id, { bytes: JSON.stringify(doc).length });
    return doc;
  });

  Object.assign(M, { EXPORT_FORMAT, EXPORT_VERSION });
})();
