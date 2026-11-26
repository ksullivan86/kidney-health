#!/usr/bin/env node
// Withings and Whoop from the iPhone app (owner, 2026-11-26; js/mock/devices.js and activity.js in device mode). A stand-in for the
// iPhone app answers the bridge: the phone's own developer apps (deviceStatus, deviceConnect, deviceFetch, deviceDisconnect), the
// server's page (serverPage) and a fake of the server's gateway. Checks: with nothing set up, Connect says where to add the developer
// app; on this iPhone, connecting adds the readings with the server's rules (the same reading from Apple Health is already there, a
// deleted one never comes back, a second sync adds nothing, the cursor moves on), Whoop days are added and later replaced, a refused
// sign-in means connect again, Disconnect can delete what came from the company; with a server both ways that has the company set
// up, Connect opens the server's page, Sync now and Disconnect are the server's, the phone's own connection waits, and the Whoop days
// and the active-day setting are the server's (kept for when it cannot be reached). pytest (tests/test_phone_devices.py) runs it.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadDemo } from './demo_loader.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FOODS = JSON.parse(readFileSync(join(ROOT, 'data', 'foods.json'), 'utf8'));
const plain = (v) => JSON.parse(JSON.stringify(v));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };
const fails = (promise, code, label, test = () => true) => {
  checks += 1;
  return assert.rejects(promise, (e) => e.status === code && test(e), label);
};

const DAY = 86400;
const NOW = Math.floor(Date.now() / 1000);
const utcDay = (epoch) => new Date(epoch * 1000).toISOString().slice(0, 10);
const utcTime = (epoch) => new Date(epoch * 1000).toISOString().slice(11, 16);
const at = (daysAgo, hour, minute = 0) => { const d = new Date((NOW - daysAgo * DAY) * 1000); d.setUTCHours(hour, minute, 0, 0); return Math.floor(d.getTime() / 1000); };

function page({ paired = false, apps = {}, gw = {}, fetches = {} } = {}) {
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  const api = new KH.mock.MockApi({ foodsData: FOODS, seed: false });
  KH.mock.instance = api;
  const raw = api.request.bind(api);
  api.request = async (...args) => plain(await raw(...args)); // answers cross the V8 context: compare plain copies
  const global = new KH.constructor.constructor('return globalThis')();
  const log = [];
  const app = { connected: {}, connectAnswer: { ok: true } };
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => {
    log.push(plain(req));
    switch (req.kind) {
      case 'serverInfo': return paired ? { ok: true, paired: true, server: 'kidney.example.org' } : { ok: true, paired: false };
      case 'deviceStatus': return { ok: true, relay: 'https://example.github.io/kidney-health/oauth/',
        providers: Object.fromEntries(['withings', 'whoop'].map((p) => [p, { app: !!apps[p], connected: !!app.connected[p] }])) };
      case 'deviceConnect': if (app.connectAnswer.ok) app.connected[req.provider] = true; return app.connectAnswer;
      case 'deviceDisconnect': app.connected[req.provider] = false; return { ok: true, revoked: true };
      case 'deviceFetch': { const f = fetches[req.provider]; const a = typeof f === 'function' ? f(req) : f; return a || { error: 'not_connected' }; }
      case 'serverPage': return paired ? { ok: true } : { error: 'not_paired' };
      case 'serverApi': {
        if (!paired) return { error: 'not_paired' };
        let a = gw[`${req.method} ${req.path.split('?')[0]}`];
        if (typeof a === 'function') a = a(req);
        if (a === undefined) return { ok: true, status: 404, json: '{"detail":"This is not open to the iPhone app."}' };
        if (a === 'offline') return { error: 'offline' };
        return { ok: true, status: a.http || 200, json: JSON.stringify(a.http || a.json ? a.json : a) };
      }
      default: return { error: 'bad_request' };
    }
  } } } };
  const asked = (kind) => log.filter((r) => r.kind === kind);
  return { KH, api, log, asked, app };
}
const W = (grpid, epoch, kg100) => ({ grpid, attrib: 0, date: epoch, category: 1, measures: [{ type: 1, value: kg100, unit: -2 }] });
const BP = (grpid, epoch, sys, dia, pulse) => ({ grpid, attrib: 0, date: epoch, category: 1,
  measures: [{ type: 10, value: sys, unit: 0 }, { type: 9, value: dia, unit: 0 }, { type: 11, value: pulse, unit: 0 }] });
const withingsAnswer = (groups, updatetime = 1_900_000_000) => ({ ok: true, now: NOW,
  json: JSON.stringify({ pages: [{ updatetime, timezone: 'UTC', more: false, offset: 0, measuregrps: groups }] }) });

// 1. Nothing set up: no company is available; Connect says where to add the developer app; nothing is fetched.
{
  const { api, asked } = page();
  const list = await api.request('GET', '/api/devices');
  ok(() => assert.deepEqual(list.providers.map((p) => [p.id, p.available, p.where, p.connect_via]),
    [['withings', false, null, null], ['whoop', false, null, null]]), 'nothing set up');
  ok(() => assert.equal(list.device.server, null), 'no server');
  await fails(api.request('POST', '/api/devices/withings/start'), 409, 'connect without a developer app',
    (e) => e.detail.includes('Keys and services'));
  ok(() => assert.equal(asked('deviceFetch').length + asked('deviceConnect').length, 0), 'nothing asked of the app');
}

// 2. Withings on this iPhone: the server's rules for what is added.
{
  const w1 = at(2, 7, 15); const b1 = at(2, 7, 20); const w2 = at(1, 7, 10);
  let groups = [W(11, w1, 7512), BP(12, b1, 131, 82, 66), W(13, w2, 7488), { grpid: 14, attrib: 1, date: w2, category: 1, measures: [{ type: 1, value: 70, unit: 0 }] }];
  const { api, asked } = page({ apps: { withings: true }, fetches: { withings: () => withingsAnswer(groups) } });
  // the same weight already came from Apple Health (the Withings app writes to it too)
  await api.request('POST', '/api/body/weights/batch', { rows: [{ date: utcDay(w2), time: utcTime(w2), kg: 74.88, context: 'morning',
    source: 'apple_health', source_key: 'ah:sample-1' }] });
  const listed = await api.request('GET', '/api/devices');
  ok(() => assert.deepEqual([listed.providers[0].available, listed.providers[0].connect_via], [true, 'phone']), 'the developer app is set');
  const started = await api.request('POST', '/api/devices/withings/start');
  ok(() => assert.equal(started.opened, 'phone'), 'connected on the phone');
  ok(() => assert.deepEqual(started.result.added, { weights: 1, readings: 1, days: 0, workouts: 0 }), 'one weight and one reading added');
  ok(() => assert.deepEqual([started.result.already_there, started.result.left_out], [1, 1]), 'Apple Health had one; one is ambiguous');
  const since = asked('deviceFetch')[0].since;
  ok(() => assert.ok(Math.abs(since - (NOW - 365 * DAY)) < 120), 'the first fetch reaches a year back');
  const weights = (await api.request('GET', `/api/body/weights?start=${utcDay(w1)}&end=${utcDay(w2)}`)).weights;
  ok(() => assert.deepEqual(weights.map((w) => [w.time, w.kg, w.source]).sort(),
    [[utcTime(w1), 75.12, 'withings'], [utcTime(w2), 74.88, 'apple_health']].sort()), 'the rows and their sources');
  const bps = (await api.request('GET', `/api/body/blood-pressure?start=${utcDay(b1)}&end=${utcDay(b1)}`)).readings;
  ok(() => assert.deepEqual(bps.map((b) => [b.systolic, b.diastolic, b.pulse, b.source, b.context]), [[131, 82, 66, 'withings', 'morning']]), 'the reading');
  const view = (await api.request('GET', '/api/devices')).providers[0];
  ok(() => assert.deepEqual([view.where, view.connection.status, view.connection.imported.weights, view.connection.imported.readings],
    ['phone', 'active', 1, 1]), 'shown as on this iPhone');
  // Sync now waits ten minutes, as the server's
  await fails(api.request('POST', '/api/devices/withings/sync'), 429, 'Sync now within ten minutes');
  // a deleted reading never comes back; a second sync adds nothing; the cursor is Withings' updatetime
  await api.request('DELETE', `/api/body/blood-pressure/${bps[0].id}`);
  api._devicesState.phone.withings.last_sync_at = new Date(Date.now() - 3600e3).toISOString();
  groups = [...groups, W(15, at(0, 6, 5), 7466)];
  const again = await api.request('POST', '/api/devices/withings/sync');
  ok(() => assert.deepEqual(again.result.added, { weights: 1, readings: 0, days: 0, workouts: 0 }), 'only the new weight');
  ok(() => assert.equal(asked('deviceFetch')[1].since, 1_900_000_000), 'the next fetch is since the updatetime');
  const left = (await api.request('GET', `/api/body/blood-pressure?start=${utcDay(b1)}&end=${utcDay(b1)}`)).readings;
  ok(() => assert.equal(left.length, 0), 'the deleted reading stayed deleted');
  // a refused sign-in at Withings: connect again
  const fetchAuth = page({ apps: { withings: true }, fetches: { withings: { error: 'auth' } } });
  await fetchAuth.api.request('POST', '/api/devices/withings/start');
  const authView = (await fetchAuth.api.request('GET', '/api/devices')).providers[0];
  ok(() => assert.deepEqual([authView.connection.status, authView.connection.last_error], ['needs_reconnect', 'auth']), 'refused: connect again');
  await fails(fetchAuth.api.request('POST', '/api/devices/withings/sync'), 409, 'no sync until connected again');
  // Disconnect, also deleting what came from Withings (the Apple Health weight stays)
  const removed = await api.request('DELETE', '/api/devices/withings?delete_readings=true');
  ok(() => assert.deepEqual([removed.removed.weights, removed.revoked], [2, true]), 'two Withings weights deleted');
  const rest = (await api.request('GET', `/api/body/weights?start=${utcDay(w1)}&end=${utcDay(NOW)}`)).weights;
  ok(() => assert.deepEqual(rest.map((w) => w.source), ['apple_health']), 'the Apple Health weight stays');
  const afterOff = await api.request('GET', '/api/devices');
  ok(() => assert.equal(afterOff.providers[0].connection, null), 'disconnected');
  ok(() => assert.equal(asked('deviceDisconnect').length, 1), 'the app ended the access');
  // what is due when the app opens: nothing while disconnected
  const due = await api.request('POST', '/api/device/devices/sync-due');
  ok(() => assert.deepEqual(due.synced, []), 'nothing due');
}

// 3. Whoop on this iPhone: days and workouts, later replaced; the day goes to Trends.
{
  const iso = (epoch) => new Date(epoch * 1000).toISOString();
  let kj = 9000;
  const answer = () => {
    const cycles = [];
    for (let n = 3; n >= 1; n -= 1) cycles.push({ id: 100 + n, user_id: 5, start: iso(at(n, 4)), end: iso(at(n - 1, 4)), timezone_offset: '+00:00',
      score_state: 'SCORED', score: { kilojoule: kj + n, strain: 10.04 } });
    return { ok: true, now: NOW, json: JSON.stringify({ cycles, recoveries: [], sleeps: [],
      workouts: [{ id: 'aaaa-1', start: iso(at(1, 18)), end: iso(at(1, 18, 45)), timezone_offset: '+00:00', sport_name: 'running', score_state: 'SCORED',
        score: { kilojoule: 1500, strain: 9 } }] }) };
  };
  const { api, asked } = page({ apps: { whoop: true }, fetches: { whoop: answer } });
  const started = await api.request('POST', '/api/devices/whoop/start');
  ok(() => assert.deepEqual(started.result.added, { weights: 0, readings: 0, days: 3, workouts: 1 }), 'three days and a workout');
  ok(() => assert.ok(Math.abs(asked('deviceFetch')[0].since - (NOW - 90 * DAY)) < 120), 'the first fetch reaches 90 days back');
  const act = await api.request('GET', `/api/activity?start=${utcDay(at(5, 0))}&end=${utcDay(NOW)}`);
  ok(() => assert.equal(act.days.length, 3), 'the days are on Trends');
  ok(() => assert.equal(act.days[0].kcal, Math.round((9000 + 3) / 4.184)), 'kJ to kcal');
  ok(() => assert.deepEqual(act.workouts.map((w) => [w.sport, w.minutes, w.source]), [['running', 45, 'whoop']]), 'the workout');
  kj = 12000;
  api._devicesState.phone.whoop.last_sync_at = null;
  const again = await api.request('POST', '/api/devices/whoop/sync');
  ok(() => assert.deepEqual([again.result.added.days, again.result.updated], [0, 4]), 'seen days are replaced');
  ok(() => assert.equal(asked('deviceFetch')[1].since, NOW - 3 * DAY), 'later fetches look again at the last 3 days');
  const after = await api.request('GET', `/api/activity?start=${utcDay(at(5, 0))}&end=${utcDay(NOW)}`);
  ok(() => assert.equal(after.days[0].kcal, Math.round((12000 + 3) / 4.184)), 'the newer number');
}

// 4. With a server both ways that has Withings and Whoop: the server's connection is used.
{
  const conn = { status: 'active', connected_at: '2026-11-01T08:00:00Z', last_sync_at: '2026-11-26T06:00:00Z', last_success_at: '2026-11-26T06:00:00Z',
    last_error: null, imported: { weights: 4, readings: 2, days: 0, workouts: 0 } };
  const devices = { enabled: true, can_connect: true, sync_hours: 4, providers: [
    { id: 'withings', name: 'Withings', what: ['weight'], available: true, connection: conn },
    { id: 'whoop', name: 'Whoop', what: ['strain'], available: true, connection: null }] };
  const serverDays = [{ date: utcDay(at(1, 0)), kcal: 2600, strain: 9.1, recovery_pct: 60, resting_hr: 55, hrv_ms: 40, sleep_minutes: 400,
    sleep_performance_pct: 80, finished: true, source: 'whoop' }];
  let reachable = true;
  const gw = {
    'GET /push/v1/about': { json: { account: 'acct-1', api_version: 1, features: {}, services: {} } },
    'GET /push/v1/api/devices': () => (reachable ? { json: devices } : 'offline'),
    'POST /push/v1/api/devices/withings/sync': { json: { connection: conn, result: { added: { weights: 1, readings: 0, days: 0, workouts: 0 },
      already_there: 0, skipped: 0, left_out: 0, updated: 0 }, error: null } },
    'DELETE /push/v1/api/devices/withings': (req) => ({ json: { removed: { weights: req.path.includes('delete_readings=true') ? 4 : 0, readings: 0, days: 0, workouts: 0 }, revoked: true } }),
    'GET /push/v1/api/activity': () => (reachable === 'busy' ? { http: 503, json: { detail: 'Busy' } } : reachable ? { json: { start: 'x', end: 'y', days: serverDays, workouts: [], extra: { enabled: true, share_pct: 50, ceiling_kcal: null } } } : 'offline'),
    'PUT /push/v1/api/activity/extra': (req) => ({ json: JSON.parse(req.body) }),
  };
  const { api, asked, log } = page({ paired: true, apps: { withings: true }, gw, fetches: { withings: () => withingsAnswer([]) } });
  // this iPhone's own Withings connection from before: it waits while the server's is connected
  api._devices().phone = { withings: { connected_at: '2026-11-20T08:00:00Z', status: 'active', last_sync_at: null, seen: {} } };
  const list = await api.request('GET', '/api/devices');
  const [w, wh] = list.providers;
  ok(() => assert.deepEqual([w.where, w.connection.imported.weights, w.connect_via, w.phone.connection.status], ['server', 4, 'server', 'active']),
    'Withings is the server\'s');
  ok(() => assert.deepEqual([wh.where, wh.connect_via], [null, 'server']), 'Whoop connects on the server');
  ok(() => assert.equal(list.device.server, 'kidney.example.org'), 'the server is named');
  const due = await api.request('POST', '/api/device/devices/sync-due');
  ok(() => assert.deepEqual([due.synced, asked('deviceFetch').length], [[], 0]), 'the phone\'s own waits while the server\'s is connected');
  const opened = await api.request('POST', '/api/devices/whoop/start');
  ok(() => assert.deepEqual([opened.url, opened.opened, asked('serverPage')[0]], [null, 'server', { kind: 'serverPage', page: 'devices', provider: 'whoop' }]),
    'Connect opens the server\'s page');
  ok(() => assert.equal(asked('deviceConnect').length, 0), 'never the phone\'s own sign-in then');
  const synced = await api.request('POST', '/api/devices/withings/sync');
  ok(() => assert.equal(synced.result.added.weights, 1), 'Sync now is the server\'s');
  const gone = await api.request('DELETE', '/api/devices/withings?delete_readings=true');
  ok(() => assert.equal(gone.removed.weights, 4), 'Disconnect is the server\'s, with the box');
  ok(() => assert.ok(log.some((r) => r.kind === 'serverApi' && r.method === 'DELETE' && r.path === '/push/v1/api/devices/withings?delete_readings=true')),
    'the query went to the server');
  // the Whoop days and the setting are the server's; Today's extra uses them; offline, the kept copy answers
  const act = await api.request('GET', `/api/activity?start=${utcDay(at(5, 0))}&end=${utcDay(NOW)}`);
  ok(() => assert.deepEqual([act.days.length, act.extra.enabled], [1, true]), 'the server\'s days');
  ok(() => assert.equal(api._activitySource(), api._activityServer), 'Today uses the server\'s days and setting');
  const put = await api.request('PUT', '/api/activity/extra', { enabled: false, share_pct: 40, ceiling_kcal: 300 });
  ok(() => assert.deepEqual(put, { enabled: false, share_pct: 40, ceiling_kcal: 300 }), 'the setting is changed on the server');
  const kept = api._activityServer;
  // an empty kept copy (the server has no Whoop) never stands in for this phone's own days (audit, 2026-11-26)
  reachable = 'busy'; // the server answers, with an error
  api._activityServer = { days: [], workouts: [], extra: { enabled: false, share_pct: 77, ceiling_kcal: null } };
  const own = await api.request('GET', `/api/activity?start=${utcDay(at(5, 0))}&end=${utcDay(NOW)}`);
  ok(() => assert.notEqual(own.extra && own.extra.share_pct, 77), 'an error with an empty copy: the phone\'s own');
  api._activityServer = kept;
  reachable = false;
  const cached = await api.request('GET', `/api/activity?start=${utcDay(at(5, 0))}&end=${utcDay(NOW)}`);
  ok(() => assert.deepEqual(cached.days.map((d) => d.kcal), [2600]), 'offline: the kept copy');
}

console.log(JSON.stringify({ ok: true, checks }));
