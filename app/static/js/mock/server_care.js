/* Kidney Diet Log — device mode only: notes and suggestions from the person's Care team, from their own server (design notes 37
   and 29; owner, 2026-11-26: "Should the phone show care team notes?" "yes"; ARCHITECTURE.md "Device mode").

   A Care team lives on a server: the people on it have accounts there. So once this iPhone is paired with a server, the person's
   notes and suggestions are the server's, read through its gateway (js/mock/server_api.js) with the token both ways:
       GET    /api/me/notes?before=&limit=                    the notes, newest first
       POST   /api/me/notes/{id}/read   with If-Match          marked read with the version on screen (412: it changed, read again)
       DELETE /api/me/notes/{id}                               gone for both
       GET    /api/me/suggestions                              the suggestions waiting for an answer, with the fit worked out there
       POST   /api/me/suggestions/{id}/accept | decline        added to the plan on the server, or no thanks
   js/mock/care.js asks `answer` first on each of those routes. Rules:
   * Not paired: the phone's own answer, as before (an empty start has no Care team).
   * Paired: always the server's. Nothing is kept: no note text is stored on this phone, in its saved log, its safety copy or its
     export. While the server cannot be reached the answer is an error that says so, and the screens show that, never an old copy.
   * Paired with a token that only adds rows (or a server without the gateway): an error that says what is needed.
   * Add to my plan makes planned entries on the server, which reach this phone through sync both ways. So it needs sync both ways
     to be on (js/mock/server_changes.js); then a sync runs at once and the answer names the entries as they are on this phone.
   * Notes never reach the AI: nothing here hands them to js/mock/ai.js, and they are not stored where it reads.
   GET /api/device/care-team (Settings → Care team, read-only) answers what GET /push/v1/about says of the Care team:
       { paired, state, server, care_team: { enabled, notes, team: [{name, role, areas}], on: [{name, role}] } | null }
   No DOM, nothing stored. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  if (!KH.flags || KH.flags.DEVICE !== true || !M) return;

  const UNREACHABLE = 'Your server cannot be reached right now. Notes and suggestions from your Care team show only while it can be reached.';
  const NEEDS_BOTH_WAYS = 'Notes and suggestions from your Care team need a token "For the iPhone app, both ways". Make one in your server\'s web app, under Settings → Phone shortcuts.';
  const NEEDS_SYNC = 'Turn on sync with your server first (Settings → This iPhone), so the foods this adds reach this iPhone.';
  const REFUSED = 'This version of the app cannot ask your server for this. Update the app.';
  const NOT_PAIRED = new Set(['not_paired', 'no_app']);
  const isDict = (v) => v != null && typeof v === 'object' && !Array.isArray(v);

  // The paired server's state, or null when this iPhone has no server.
  async function paired() {
    const S = M.serverApi;
    if (!S) return null;
    const k = await S.check();
    return NOT_PAIRED.has(k.state) ? null : k;
  }

  // One request to the server's route: its JSON (null for 204), or its error as the page's own.
  async function viaServer(k, method, path, { ifMatch } = {}) {
    if (k.state === 'add_only' || k.state === 'old_server') M.fail(409, NEEDS_BOTH_WAYS);
    const S = M.serverApi;
    const res = await S.call(method, path, ifMatch ? { ifMatch } : {});
    if (res.offline) M.fail(503, UNREACHABLE);
    if (res.error === 'refused') M.fail(503, REFUSED);
    if (res.error) M.fail(503, UNREACHABLE);
    if (res.status === 204) return null;
    if (res.status >= 400) S.failWith(res);
    if (!isDict(res.json)) M.fail(502, 'Your server gave an answer the app could not read.');
    return res.json;
  }

  const ROUTES = [
    ['GET', /^\/api\/me\/notes$/, 'notes'],
    ['POST', /^\/api\/me\/notes\/(\d{1,18})\/read$/, 'read'],
    ['DELETE', /^\/api\/me\/notes\/(\d{1,18})$/, 'delete'],
    ['GET', /^\/api\/me\/suggestions$/, 'suggestions'],
    ['POST', /^\/api\/me\/suggestions\/(\d{1,18})\/(accept|decline)$/, 'answer'],
  ];

  // The page's request on one of the routes above: the server's answer when paired, else `local` (the phone's own handler).
  async function answer(api, ctx, local) {
    const k = await paired();
    if (!k) return local.call(api, ctx);
    const found = ROUTES.find(([m, re]) => m === ctx.method && re.test(ctx.path));
    if (!found) M.fail(404, 'Not Found');
    const [, re, what] = found;
    const ids = ctx.path.match(re).slice(1);
    if (what === 'notes') {
      const q = new URLSearchParams();
      for (const name of ['before', 'limit']) if (ctx.qp(name) != null) q.set(name, ctx.qp(name));
      return viaServer(k, 'GET', `/api/me/notes${q.toString() ? `?${q}` : ''}`);
    }
    if (what === 'read') return viaServer(k, 'POST', `/api/me/notes/${ids[0]}/read`, { ifMatch: ctx.header('If-Match') || undefined });
    if (what === 'delete') return viaServer(k, 'DELETE', `/api/me/notes/${ids[0]}`);
    if (what === 'suggestions') return viaServer(k, 'GET', '/api/me/suggestions');
    if (ids[1] === 'decline') return viaServer(k, 'POST', `/api/me/suggestions/${ids[0]}/decline`);
    if (!(M.serverChanges && M.serverChanges.active(api))) M.fail(409, NEEDS_SYNC);
    const got = await viaServer(k, 'POST', `/api/me/suggestions/${ids[0]}/accept`);
    // The entries are the server's: bring them here now, and answer with this phone's rows (by their one client_id).
    try { if (M.serverSync) await M.serverSync.sendNow(); } catch (e) { /* the next sync brings them */ }
    const entries = [];
    for (const e of Array.isArray(got.entries) ? got.entries : []) {
      const row = isDict(e) ? api._entryByClientId(e.client_id) : null;
      if (row) entries.push(api._entryView(row));
    }
    const brought = Array.isArray(got.entries) ? got.entries.length : 0;
    return { entries, skipped: Number(got.skipped) || 0, waiting: brought - entries.length };
  }

  // Settings → Care team on this iPhone: who is on the person's Care team, read-only, from `about`.
  M.route('GET', '/api/device/care-team', async function () {
    this._currentUser();
    const S = M.serverApi;
    const k = S ? await S.check() : { state: 'no_app' };
    const team = k.about && isDict(k.about.careTeam) ? k.about.careTeam : null;
    return { paired: !NOT_PAIRED.has(k.state), state: k.state, server: k.server || null, care_team: k.state === 'both' ? team : null };
  });

  M.serverCare = { answer, paired, texts: { unreachable: UNREACHABLE, needs_both_ways: NEEDS_BOTH_WAYS, needs_sync: NEEDS_SYNC, refused: REFUSED } };
})();
