/* Kidney Diet Log — demo API: accounts (twin of app/auth/routes.py, me.py and admin_api.py).

   The demo person "Sam" (username sam) is a signed-in admin; a second, sample account ("Alex",
   invited 12 days ago) shows what the admin pages look like. Everything lives in memory and is
   gone on reload; nothing is sent anywhere. Sign-out works (the sign-in screen then accepts sam
   with any password of 15 or more characters); setup, invite and reset links answer like an
   already set-up server whose links have expired. Sensitive routes ask for the password again 10
   minutes after the last sign-in or password entry, as the server does (any password passes).

   Same routes, shapes and texts as the server (ARCHITECTURE.md "M1 API"), minus what needs a
   real server: no password blocklist, no throttling, no cookies, no zip export. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi, Check, fail } = M;

  const REAUTH_MS = 10 * 60 * 1000;
  const MIN_PASSWORD = 15;
  const MAX_PASSWORD = 128;
  const USERNAME_RE = /^[a-z0-9._@+-]{3,64}$/;
  const USERNAME_HELP = 'Use 3 to 64 characters: letters, digits and . _ @ + -';
  const DEMO_LINK_BASE = 'https://kidney.example';
  const PUBLIC_AUTH = new Set(['GET /api/auth/status', 'POST /api/auth/login', 'POST /api/auth/setup', 'POST /api/auth/register', 'POST /api/auth/reset',
    'POST /api/auth/reset/info']);
  const USER_VISIBLE_ACTIONS = new Set(['login.succeeded', 'login.failed', 'user.locked', 'user.password_changed', 'user.reset_link_issued',
    'user.reset_link_revoked', 'user.must_change_password', 'sessions.revoked', 'session.revoked_reauth', 'secret.set', 'secret.removed', 'export.created']);
  const LINK_INVALID = 'This link is not valid any more. Ask your admin for a new one.';
  const APP_WORDS = ['kidneyhealth', 'kidney health', 'kidney-health', 'kidney_health', 'kidney health food log'];
  const SEQUENCES = ['abcdefghijklmnopqrstuvwxyz', '0123456789', 'qwertyuiopasdfghjklzxcvbnm', 'qwertzuiopasdfghjklyxcvbnm',
    'azertyuiopqsdfghjklmwxcvbn', '1qaz2wsx3edc4rfv5tgb6yhn7ujm8ik9ol0p', 'qazwsxedcrfvtgbyhnujmikolp', '1234567890qwertyuiopasdfghjklzxcvbnm', '!@#$%^&*()'];

  const norm = (s) => String(s || '').normalize('NFKC').trim().toLowerCase();
  const fold = (s) => String(s || '').normalize('NFC').toLowerCase();
  const squash = (s) => Array.from(s).filter((c) => /[\p{L}\p{N}]/u.test(c)).join('');
  function straightRun(folded) {
    if (folded.length < 3) return false;
    return SEQUENCES.some((seq) => [seq, [...seq].reverse().join('')].some((c) => c.repeat(Math.floor(folded.length / c.length) + 2).includes(folded)));
  }
  // app/auth/policy.validate_new_password without the blocklist and the breach check.
  function passwordProblems(pw, { username = '', displayName = '', instanceName = '' } = {}) {
    const p = String(pw || '').normalize('NFC');
    const n = Array.from(p).length;
    if (n < MIN_PASSWORD) return [`Use at least ${MIN_PASSWORD} characters. A short sentence or three or four unrelated words works well.`];
    if (n > MAX_PASSWORD) return ['Use at most 128 characters.'];
    const folded = p.toLowerCase();
    const problems = [];
    const context = [username, displayName, instanceName, ...APP_WORDS].filter((w) => w && w.trim()).map(fold);
    if (context.includes(folded) || context.map(squash).filter(Boolean).includes(squash(folded))) {
      problems.push("Do not use your username, your name or the app's name as the password.");
    }
    if (new Set(Array.from(folded)).size === 1 || straightRun(folded)) problems.push('Avoid one repeated character or a straight run of keys, letters or digits.');
    return problems;
  }
  function cleanDisplay(raw, limit = 80) {
    return String(raw || '').normalize('NFC').replace(/[\u0000-\u001f\u007f]/g, '').replace(/\s+/g, ' ').trim().slice(0, limit);
  }
  function randomToken(n = 24) {
    const abc = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
    let out = '';
    const bytes = new Uint8Array(n);
    try { crypto.getRandomValues(bytes); } catch (e) { for (let i = 0; i < n; i++) bytes[i] = Math.floor(Math.random() * 256); }
    for (const b of bytes) out += abc[b % abc.length];
    return out;
  }

  Object.assign(MockApi.prototype, {
    // Lazily built, so the constructor in mock/core.js needs no change.
    _authState() {
      if (this._auth) return this._auth;
      const now = Date.now();
      const ago = (days, hours = 0) => this._stamp(new Date(now - days * 86400000 - hours * 3600000));
      const ua = (() => { try { return navigator.userAgent || 'This browser'; } catch (e) { return 'This browser'; } })();
      this._auth = {
        signedIn: true,
        userId: 1,
        reauthAt: now, // signing in counts as entering the password
        nextUserId: 3,
        nextEventId: 1,
        users: [
          { id: 1, username: 'sam', display_name: 'Sam', role: 'admin', status: 'active', auth_source: 'local', can_use_shared: true,
            must_change_password: false, has_password: true, created_at: ago(30), last_login_at: ago(0, 1) },
          { id: 2, username: 'alex', display_name: 'Alex', role: 'user', status: 'active', auth_source: 'local', can_use_shared: true,
            must_change_password: false, has_password: true, created_at: ago(12), last_login_at: ago(1, 3) },
        ],
        sessions: [
          { id: 'demo-this-browser', user_id: 1, created_at: ago(0, 1), last_seen_at: this._stamp(), expires_at: this._stamp(new Date(now + 30 * 86400000)),
            user_agent: ua, ip_prefix: '192.168.1.0/24' },
          { id: 'demo-sams-phone', user_id: 1, created_at: ago(9), last_seen_at: ago(1, 5), expires_at: this._stamp(new Date(now + 21 * 86400000)),
            user_agent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1',
            ip_prefix: '192.168.1.0/24' },
        ],
        invites: [
          { id: 'demo-invite-1', role: 'user', note: 'For Alex', created_by: 1, created_at: ago(12, 2), expires_at: ago(5, 2), used_at: ago(12), state: 'used' },
        ],
        events: [],
      };
      const ev = (at, actor, action, type, target, details = {}) => this._auth.events.push({ id: this._auth.nextEventId++, at, actor_user_id: actor,
        ip_prefix: '192.168.1.0/24', action, target_type: type, target_id: target == null ? null : String(target), details });
      ev(ago(30), 1, 'setup.completed', 'user', 1, { auth_source: 'local' });
      ev(ago(12, 2), 1, 'user.invited', 'invite', 'demo-invite-1', { role: 'user' });
      ev(ago(12), 2, 'user.registered', 'user', 2, { via: 'invite', invite_id: 'demo-invite-1', role: 'user' });
      ev(ago(9), 1, 'login.succeeded', 'user', 1);
      ev(ago(1, 3), 2, 'login.succeeded', 'user', 2);
      ev(ago(0, 1), 1, 'login.succeeded', 'user', 1);
      return this._auth;
    },
    _audit(actor, action, type, target, details = {}) {
      const a = this._authState();
      a.events.push({ id: a.nextEventId++, at: this._stamp(), actor_user_id: actor, ip_prefix: '192.168.1.0/24', action, target_type: type,
        target_id: target == null ? null : String(target), details });
    },
    _userById(id) { return this._authState().users.find((u) => u.id === Number(id)) || null; },
    _me(u) {
      return { id: u.id, username: u.username, display_name: u.display_name || '', role: u.role, auth_source: u.auth_source,
        must_change_password: !!u.must_change_password, created_at: u.created_at };
    },
    _adminUser(u) {
      const link = u.reset_link && u.reset_link.expires_at > this._stamp() ? u.reset_link : null;
      return { id: u.id, username: u.username, display_name: u.display_name || '', role: u.role, status: u.status, auth_source: u.auth_source,
        can_use_shared: !!u.can_use_shared, must_change_password: !!u.must_change_password, has_password: !!u.has_password,
        created_at: u.created_at, last_login_at: u.last_login_at, reset_link: link ? { ...link } : null };
    },
    // app/auth/tokens.py: an open reset/setup link per account (the demo never shows its token).
    _issueResetLink(u, adminId, ms) {
      u.reset_link = { id: `demo-link-${randomToken(8)}`, created_by: adminId, created_at: this._stamp(), expires_at: this._stamp(new Date(Date.now() + ms)) };
      return u.reset_link;
    },
    // tokens.void_issued_by: an admin who is demoted, disabled or deleted takes their links with them.
    _voidIssuedBy(adminId) {
      const a = this._authState();
      let n = 0;
      for (const x of a.users) if (x.reset_link && x.reset_link.created_by === adminId) { x.reset_link = null; n += 1; }
      const before = a.invites.length;
      a.invites = a.invites.filter((i) => i.used_at || i.created_by !== adminId);
      return n + (before - a.invites.length);
    },
    // CurrentUser / AdminUser / RecentUser (app/auth/deps.py).
    _currentUser() {
      const a = this._authState();
      const u = a.signedIn ? this._userById(a.userId) : null;
      if (!u || u.status !== 'active') fail(401, 'Sign in required');
      return u;
    },
    _requireAdmin() {
      const u = this._currentUser();
      if (u.role !== 'admin') fail(403, 'Admins only');
      return u;
    },
    _requireRecent() {
      const a = this._authState();
      if (Date.now() - a.reauthAt > REAUTH_MS) fail(403, 'Please enter your password again', { reauth_required: true });
    },
    _activeAdmins() { return this._authState().users.filter((u) => u.role === 'admin' && u.status === 'active'); },
    _wouldRemoveLastAdmin(id) {
      const admins = this._activeAdmins();
      return admins.length === 1 && admins[0].id === Number(id);
    },
    _checkUsername(raw) {
      const typed = String(raw || '').trim();
      const n = norm(typed);
      if (!USERNAME_RE.test(n)) fail(400, `username: ${USERNAME_HELP}.`, { field: 'username' });
      return [typed, n];
    },
    _checkNewPassword(pw, user) {
      const problems = passwordProblems(pw, { username: user.username, displayName: user.display_name, instanceName: this._settingValue('instance.name') });
      if (problems.length) fail(400, problems[0], { field: 'password', problems });
    },
    _settingValue(key) {
      // js/mock/settings.js supplies the store; before it loads, the registry default.
      if (typeof this._effectiveSetting === 'function') return this._effectiveSetting(key, null).value;
      return KH.settings.BY_KEY[key].default;
    },
    _authStatus() {
      const a = this._authState();
      const u = a.signedIn ? this._userById(a.userId) : null;
      return {
        setup_required: false,
        auth_mode: 'local',
        registration: this._settingValue('registration.mode'),
        insecure_http: false,
        https_required: false,
        password_min_length: MIN_PASSWORD,
        password_max_length: MAX_PASSWORD,
        instance_name: this._settingValue('instance.name'),
        user: u && u.status === 'active' ? this._me(u) : null,
        logout_url: null,
        no_login: false,
      };
    },
    _sessionView(s) {
      return { id: s.id, created_at: s.created_at, last_seen_at: s.last_seen_at, expires_at: s.expires_at, user_agent: s.user_agent,
        ip_prefix: s.ip_prefix, current: s.id === 'demo-this-browser' };
    },
    _demoLink(kind) { return `${DEMO_LINK_BASE}/#/${kind}/demo.${randomToken(20)}`; },
    _inviteView(i) {
      const state = i.used_at ? 'used' : (i.expires_at <= this._stamp() ? 'expired' : 'open');
      return { id: i.id, role: i.role, note: i.note || '', created_by: i.created_by, created_at: i.created_at, expires_at: i.expires_at, used_at: i.used_at, state };
    },
  });

  // Every /api route except the public auth ones needs a signed-in person (the server's
  // current_user dependency runs before anything else), so check before the route table.
  const baseHandle = MockApi.prototype.handle;
  MockApi.prototype.handle = function handle(method, path, body) {
    const p = new URL(path, 'http://demo.invalid').pathname;
    if (p.startsWith('/api/') && !PUBLIC_AUTH.has(`${method} ${p}`)) this._currentUser();
    return baseHandle.call(this, method, path, body);
  };

  // ---------------------------------------------------------------------------
  // /api/auth
  // ---------------------------------------------------------------------------
  route('GET', '/api/auth/status', function () { return this._authStatus(); });
  route('POST', '/api/auth/login', function ({ body }) {
    const c = new Check(body);
    c.str('username', { required: true, min: 1, max: 255, nullable: false });
    if (!c.has('password')) c.err('password', 'Field required');
    else if (typeof c.body.password !== 'string') c.err('password', 'Input should be a valid string');
    else if (!c.body.password.length) c.err('password', 'Value should have at least 1 item after validation, not 0');
    const data = c.done();
    const a = this._authState();
    const u = a.users.find((x) => norm(x.username) === norm(data.username));
    // The demo has no stored password: sam signs in with any password the policy would accept.
    if (!u || u.id !== 1 || u.status !== 'active' || Array.from(String(c.body.password)).length < MIN_PASSWORD) {
      if (u) this._audit(null, 'login.failed', 'user', u.id);
      fail(401, 'Username or password is incorrect');
    }
    a.signedIn = true; a.userId = u.id; a.reauthAt = Date.now();
    u.last_login_at = this._stamp();
    const cur = a.sessions.find((s) => s.id === 'demo-this-browser');
    if (cur) { cur.created_at = this._stamp(); cur.last_seen_at = cur.created_at; } else {
      a.sessions.unshift({ id: 'demo-this-browser', user_id: u.id, created_at: this._stamp(), last_seen_at: this._stamp(),
        expires_at: this._stamp(new Date(Date.now() + 30 * 86400000)), user_agent: navigator.userAgent || 'This browser', ip_prefix: '192.168.1.0/24' });
    }
    this._audit(u.id, 'login.succeeded', 'user', u.id);
    return { user: this._me(u), notice: null };
  });
  route('POST', '/api/auth/logout', function () {
    const a = this._authState();
    a.signedIn = false;
    a.sessions = a.sessions.filter((s) => s.id !== 'demo-this-browser');
    return { ok: true };
  });
  route('POST', '/api/auth/setup', function () { fail(409, 'Setup is already complete'); });
  route('POST', '/api/auth/register', function ({ body }) {
    const c = new Check(body);
    c.str('username', { required: true, min: 1, max: 255, nullable: false });
    const data = c.done();
    const token = M.isDict(body) && typeof body.token === 'string' ? body.token : '';
    if (token) fail(400, 'This invite link is not valid any more. Ask your admin for a new one.', { field: 'token' });
    const mode = this._settingValue('registration.mode');
    if (mode === 'closed') fail(403, 'Registration is closed on this server. Ask your admin to create an account for you.');
    if (mode === 'invite') fail(403, 'You need an invite link from your admin to create an account here.');
    void data;
    fail(400, 'HTTPS required to register on this server. See docs/https.md.', { https_required: true });
  });
  route('POST', '/api/auth/reset', function () {
    fail(400, LINK_INVALID, { field: 'token' });
  });
  route('POST', '/api/auth/reset/info', function () {
    fail(400, LINK_INVALID, { field: 'token' });
  });
  route('POST', '/api/auth/reauth', function ({ body }) {
    this._currentUser();
    const c = new Check(body);
    if (!c.has('password')) c.err('password', 'Field required');
    else if (typeof c.body.password !== 'string' || !c.body.password) c.err('password', 'Value should have at least 1 item after validation, not 0');
    c.done();
    const a = this._authState();
    a.reauthAt = Date.now();
    return { ok: true, reauth_until: this._stamp(new Date(a.reauthAt + REAUTH_MS)) };
  });

  // ---------------------------------------------------------------------------
  // /api/me
  // ---------------------------------------------------------------------------
  route('GET', '/api/me', function () { return this._me(this._currentUser()); });
  route('PATCH', '/api/me', function ({ body }) {
    const u = this._currentUser();
    const c = new Check(body);
    c.str('display_name', { required: true, max: 200, nullable: false });
    const data = c.done();
    u.display_name = cleanDisplay(data.display_name);
    return this._me(u);
  });
  route('POST', '/api/me/password', function ({ body }) {
    const u = this._currentUser();
    const c = new Check(body);
    for (const k of ['current_password', 'new_password']) {
      if (!c.has(k)) c.err(k, 'Field required');
      else if (typeof c.body[k] !== 'string' || !c.body[k]) c.err(k, 'Value should have at least 1 item after validation, not 0');
    }
    c.done();
    this._checkNewPassword(body.new_password, u);
    u.must_change_password = false;
    u.reset_link = null; // an older reset link must not undo this change
    const a = this._authState();
    a.sessions = a.sessions.filter((s) => s.id === 'demo-this-browser'); // other devices are signed out
    a.reauthAt = Date.now();
    this._audit(u.id, 'user.password_changed', 'user', u.id, { via: 'self' });
    return { user: this._me(u) };
  });
  route('DELETE', '/api/me', function ({ body }) {
    const u = this._currentUser();
    if (!M.isDict(body)) fail(400, 'Field required');
    if (body.confirm !== 'DELETE') fail(400, 'Type DELETE to confirm.', { field: 'confirm' });
    if (typeof body.password !== 'string' || !body.password) fail(403, 'Please enter your password again', { reauth_required: true });
    if (this._wouldRemoveLastAdmin(u.id)) fail(409, 'You are the only admin. Make someone else an admin first.');
    const a = this._authState();
    a.users = a.users.filter((x) => x.id !== u.id);
    a.signedIn = false;
    return null;
  });
  route('GET', '/api/me/sessions', function () {
    const u = this._currentUser();
    return { sessions: this._authState().sessions.filter((s) => s.user_id === u.id).map((s) => this._sessionView(s)) };
  });
  route('POST', '/api/me/sessions/revoke-others', function () {
    const u = this._currentUser();
    this._requireRecent();
    const a = this._authState();
    const before = a.sessions.length;
    a.sessions = a.sessions.filter((s) => s.user_id !== u.id || s.id === 'demo-this-browser');
    const count = before - a.sessions.length;
    this._audit(u.id, 'sessions.revoked', 'user', u.id, { count });
    return { revoked: count };
  });
  route('DELETE', /^\/api\/me\/sessions\/([^/]+)$/, function ({ id }) {
    const u = this._currentUser();
    const a = this._authState();
    const s = a.sessions.find((x) => x.id === decodeURIComponent(id) && x.user_id === u.id);
    if (!s) fail(404, 'session not found');
    a.sessions = a.sessions.filter((x) => x !== s);
    if (s.id === 'demo-this-browser') a.signedIn = false;
    this._audit(u.id, 'sessions.revoked', 'user', u.id, { count: 1 });
    return null;
  });
  route('GET', '/api/me/activity', function ({ qp }) {
    const u = this._currentUser();
    const limit = Math.max(1, Math.min(Number(qp('limit')) || 50, 200));
    const before = qp('before') != null ? Number(qp('before')) : null;
    const events = this._authState().events
      // app/audit.list_events: events about this account, and the person's own actions except those on another account.
      .filter((e) => USER_VISIBLE_ACTIONS.has(e.action) && ((e.target_type === 'user' && e.target_id === String(u.id))
        || (e.actor_user_id === u.id && (e.target_type !== 'user' || e.target_id == null || e.target_id === String(u.id)))))
      .filter((e) => before == null || e.id < before)
      .sort((x, y) => y.id - x.id).slice(0, limit);
    return { events };
  });
  route('GET', '/api/me/usage', function () { this._currentUser(); return { days: 30, usage: [], by_day: [] }; });

  // ---------------------------------------------------------------------------
  // /api/admin: accounts, invites, usage, audit, about (settings and keys: js/mock/settings.js)
  // ---------------------------------------------------------------------------
  const userIdRoute = (suffix) => new RegExp(`^/api/admin/users/(\\d+)${suffix}$`);
  function targetUser(api, id) {
    const u = api._userById(id);
    if (!u) fail(404, `user ${id} not found`);
    return u;
  }
  route('GET', '/api/admin/users', function () {
    this._requireAdmin();
    return { users: this._authState().users.slice().sort((x, y) => x.id - y.id).map((u) => this._adminUser(u)) };
  });
  route('POST', '/api/admin/users', function ({ body }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const c = new Check(body);
    c.str('username', { required: true, min: 1, max: 255, nullable: false });
    c.str('display_name', { max: 200 });
    c.choice('role', ['admin', 'user'], { def: 'user' });
    const data = c.done();
    const [typed, n] = this._checkUsername(data.username);
    const a = this._authState();
    if (a.users.some((u) => norm(u.username) === n)) fail(409, 'That username is taken.', { field: 'username' });
    const u = { id: a.nextUserId++, username: typed, display_name: cleanDisplay(data.display_name), role: data.role, status: 'pending_setup',
      auth_source: 'local', can_use_shared: true, must_change_password: false, has_password: false, created_at: this._stamp(), last_login_at: null };
    a.users.push(u);
    const ttl = this._settingValue('registration.invite_ttl_days');
    const link = this._issueResetLink(u, admin.id, ttl * 86400000);
    this._audit(admin.id, 'user.invited', 'user', u.id, { role: data.role, via: 'account' });
    return { user: this._adminUser(u), setup_url: this._demoLink('reset'), expires_at: link.expires_at };
  });
  route('PATCH', userIdRoute(''), function ({ id, body }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const u = targetUser(this, id);
    const c = new Check(body);
    c.choice('role', ['admin', 'user'], { nullable: true });
    c.choice('status', ['active', 'disabled'], { nullable: true });
    if (c.has('can_use_shared') && c.body.can_use_shared != null && typeof c.body.can_use_shared !== 'boolean') c.err('can_use_shared', 'Input should be a valid boolean');
    else if (c.has('can_use_shared')) c.out.can_use_shared = c.body.can_use_shared;
    if (c.has('must_change_password') && c.body.must_change_password != null && typeof c.body.must_change_password !== 'boolean') c.err('must_change_password', 'Input should be a valid boolean');
    else if (c.has('must_change_password')) c.out.must_change_password = c.body.must_change_password;
    c.str('display_name', { max: 200 });
    const data = c.done();
    if (data.role != null && data.role !== u.role) {
      if (data.role !== 'admin' && this._wouldRemoveLastAdmin(u.id)) fail(409, 'This is the only admin. Make someone else an admin first.');
      const voided = u.role === 'admin' ? this._voidIssuedBy(u.id) : 0;
      this._audit(admin.id, 'user.role_changed', 'user', u.id, { old: u.role, new: data.role, ...(voided ? { links_revoked: voided } : {}) });
      u.role = data.role;
    }
    if (data.status != null && data.status !== u.status) {
      if (data.status === 'disabled') {
        if (u.id === admin.id) fail(409, 'You cannot disable your own account.');
        if (this._wouldRemoveLastAdmin(u.id)) fail(409, 'This is the only admin. Make someone else an admin first.');
        u.status = 'disabled';
        this._authState().sessions = this._authState().sessions.filter((s) => s.user_id !== u.id);
        u.reset_link = null;
        const voided = this._voidIssuedBy(u.id);
        this._audit(admin.id, 'user.disabled', 'user', u.id, voided ? { links_revoked: voided } : {});
      } else {
        if (u.status !== 'disabled') fail(409, 'Only a disabled account can be enabled here. A locked or new account needs a reset link.');
        u.status = 'active';
        this._audit(admin.id, 'user.enabled', 'user', u.id);
      }
    }
    if (data.can_use_shared != null && !!data.can_use_shared !== !!u.can_use_shared) {
      u.can_use_shared = !!data.can_use_shared;
      this._audit(admin.id, 'user.updated', 'user', u.id, { can_use_shared: u.can_use_shared });
    }
    if (data.must_change_password && !u.must_change_password) {
      u.must_change_password = true;
      this._audit(admin.id, 'user.must_change_password', 'user', u.id);
    }
    if (data.display_name != null) u.display_name = cleanDisplay(data.display_name);
    return { user: this._adminUser(u) };
  });
  route('DELETE', userIdRoute(''), function ({ id, body }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const u = targetUser(this, id);
    if (u.id === admin.id) fail(409, 'Delete your own account from Settings → Account instead.');
    if (!M.isDict(body) || norm(body.confirm_username) !== norm(u.username)) fail(400, "Type the account's username to confirm.", { field: 'confirm_username' });
    if (this._wouldRemoveLastAdmin(u.id)) fail(409, 'This is the only admin. Make someone else an admin first.');
    const a = this._authState();
    const voided = this._voidIssuedBy(u.id);
    a.users = a.users.filter((x) => x.id !== u.id);
    a.sessions = a.sessions.filter((s) => s.user_id !== u.id);
    this._audit(admin.id, 'user.deleted', 'user', u.id, voided ? { links_revoked: voided } : {});
    return null;
  });
  route('POST', userIdRoute('/reset-link'), function ({ id }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const u = targetUser(this, id);
    if (u.status === 'disabled') fail(409, 'Enable the account first.');
    const link = this._issueResetLink(u, admin.id, 24 * 3600000);
    this._audit(admin.id, 'user.reset_link_issued', 'user', u.id);
    return { url: this._demoLink('reset'), expires_at: link.expires_at };
  });
  route('DELETE', userIdRoute('/reset-link'), function ({ id }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const u = targetUser(this, id);
    if (!this._adminUser(u).reset_link) fail(404, 'no open link for this account');
    u.reset_link = null;
    this._audit(admin.id, 'user.reset_link_revoked', 'user', u.id);
    return null;
  });
  route('POST', userIdRoute('/revoke-sessions'), function ({ id }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const u = targetUser(this, id);
    const a = this._authState();
    const before = a.sessions.length;
    a.sessions = a.sessions.filter((s) => s.user_id !== u.id);
    const count = before - a.sessions.length;
    if (u.id === admin.id && a.sessions.every((s) => s.id !== 'demo-this-browser')) a.signedIn = false;
    this._audit(admin.id, 'sessions.revoked', 'user', u.id, { count });
    return { revoked: count };
  });
  route('GET', '/api/admin/invites', function () {
    this._requireAdmin();
    return { invites: this._authState().invites.slice().sort((x, y) => (x.created_at < y.created_at ? 1 : -1)).map((i) => this._inviteView(i)) };
  });
  route('POST', '/api/admin/invites', function ({ body }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const c = new Check(body);
    c.choice('role', ['admin', 'user'], { def: 'user' });
    c.str('note', { max: 200 });
    c.num('ttl_days', { int: true, ge: 1, le: 90 });
    const data = c.done();
    if (this._settingValue('registration.mode') === 'closed') fail(409, 'Registration is closed. Create the account instead, or switch registration to invites.');
    const ttl = data.ttl_days || this._settingValue('registration.invite_ttl_days');
    const inv = { id: `demo-invite-${randomToken(8)}`, role: data.role, note: cleanDisplay(data.note, 200), created_by: admin.id, created_at: this._stamp(),
      expires_at: this._stamp(new Date(Date.now() + ttl * 86400000)), used_at: null };
    this._authState().invites.push(inv);
    this._audit(admin.id, 'user.invited', 'invite', inv.id, { role: inv.role });
    return { invite: this._inviteView(inv), url: this._demoLink('invite'), expires_at: inv.expires_at };
  });
  route('DELETE', /^\/api\/admin\/invites\/([^/]+)$/, function ({ id }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const a = this._authState();
    const inv = a.invites.find((i) => i.id === decodeURIComponent(id) && !i.used_at);
    if (!inv) fail(404, 'invite not found');
    a.invites = a.invites.filter((i) => i !== inv);
    this._audit(admin.id, 'invite.revoked', 'invite', inv.id);
    return null;
  });
  route('GET', '/api/admin/usage', function ({ qp }) {
    this._requireAdmin();
    return { days: Number(qp('days')) || 30, usage: [] };
  });
  route('GET', '/api/admin/audit', function ({ qp }) {
    this._requireAdmin();
    const limit = Math.max(1, Math.min(Number(qp('limit')) || 50, 500));
    const before = qp('before') != null ? Number(qp('before')) : null;
    return { events: this._authState().events.filter((e) => before == null || e.id < before).sort((x, y) => y.id - x.id).slice(0, limit) };
  });
  route('GET', '/api/admin/about', function () {
    this._requireAdmin();
    const users = this._authState().users;
    return {
      version: 'demo',
      schema_version: 3,
      auth_mode: 'local',
      accounts: { active: users.filter((u) => u.status === 'active').length, total: users.length },
      https: true,
      public_url: null,
      secret_key: { source: 'demo', on_data_volume: false, warning: null, secrets: { current: 0, older_key: 0, unreadable: 0 } },
      proxy: {},
      pre_v3_backup: null,
      last_backup_at: null,
    };
  });

  Object.assign(M, { passwordProblems });
})();
