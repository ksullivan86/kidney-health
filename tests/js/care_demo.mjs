// The demo's sample Care team (js/mock/care.js, design notes 25 and 29), run in Node for tests/test_care_team_ui.py: the lists,
// an invite, a role change, the switches, accept, a helper planning and logging on Ana's days (which never reach the demo person's
// own log), Ana's saved meal, a low treatment no helper changes, and suggestions both ways. Prints one JSON object.
import { loadDemo, newDemo } from './demo_loader.mjs';

const KH = loadDemo();
const api = newDemo(KH);
const call = (method, path, body, headers) => {
  try { return { status: 200, body: JSON.parse(JSON.stringify(api.handle(method, path, body, headers) ?? null)) }; } catch (e) {
    return { status: e.status || 500, detail: e.detail || String(e) };
  }
};
const today = KH.util.todayStr();
const tomorrow = KH.util.addDays(today, 1);
const out = {};
out.mine = call('GET', '/api/me/shares').body;
out.shared = call('GET', '/api/shared').body;
out.invite = call('POST', '/api/me/shares/invite', { username: 'Robin', areas: ['labs'], role: 'care_helper' }).body;
out.own = call('POST', '/api/me/shares/invite', { username: api._currentUser().username, areas: ['food'] });
out.role = call('PUT', '/api/me/shares/1/role', { role: 'viewer' }).body;
out.accept = call('POST', '/api/shared/invites/4/accept').body;
const ownBefore = call('GET', `/api/log?date=${tomorrow}`).body.entries.length;
const anaDay = call('GET', `/api/shared/3/log?date=${tomorrow}`).body;
out.anaPlanned = anaDay.entries.map((e) => [e.food_name, e.status]);
const food = call('GET', '/api/shared/3/foods?q=apple').body.foods[0];
const added = call('POST', '/api/shared/3/log', { date: tomorrow, meal: 'snack', food_id: food.id, servings: 2 });
out.added = { status: added.status, added_by: added.body && added.body.added_by, status_field: added.body && added.body.status };
out.eaten = call('POST', '/api/shared/3/log', { date: tomorrow, meal: 'snack', food_id: food.id, servings: 1, status: 'eaten' }).status;
const eatenEntry = call('GET', `/api/shared/3/log?date=${today}`).body.entries.find((e) => e.status === 'eaten');
out.changeEaten = eatenEntry ? call('PUT', `/api/shared/3/log/${eatenEntry.id}`, { servings: 3 }).status : null;
out.change = call('PUT', `/api/shared/3/log/${added.body.id}`, { servings: 1 }).body.servings;
out.statusChange = call('PUT', `/api/shared/3/log/${added.body.id}`, { status: 'eaten' }).status;
out.shopping = call('GET', `/api/shared/3/plan/shopping?start=${today}&end=${KH.util.addDays(today, 6)}`).body.items.map((i) => i.food_name);
out.viewer = call('POST', `/api/shared/${out.accept.id}/log`, { date: tomorrow, meal: 'snack', food_id: food.id, servings: 1 });
out.labs = call('GET', '/api/shared/3/labs').status;
out.remove = call('DELETE', `/api/shared/3/log/${added.body.id}`).status;
out.ownAfter = call('GET', `/api/log?date=${tomorrow}`).body.entries.length;
out.ownBefore = ownBefore;
out.plan = call('POST', '/api/shared/3/guidance/plan-days', { start: tomorrow, days: 2 });
out.plan = { status: out.plan.status, kind: out.plan.body && out.plan.body.status };
out.link = call('POST', '/api/shared/info', { code: 'x' });
// design note 29: switches, eaten food, saved meals, a low treatment, suggestions
out.switches = call('PUT', '/api/me/shares/1/switches', { may_log: true, areas: ['labs'] }).body;
out.badSwitch = call('PUT', '/api/me/shares/1/switches', { may_log: 'yes' }).status;
out.meals = call('GET', '/api/shared/3/meals').body.meals.map((m) => m.name);
const meal = call('GET', '/api/shared/3/meals').body.meals[0];
const applied = call('POST', `/api/shared/3/meals/${meal.id}/apply`, { date: today, meal: 'lunch', status: 'eaten' });
out.applied = applied.body.entries.map((e) => [e.status, e.added_by]);
const glucose = call('GET', '/api/shared/3/foods?q=glucose').body.foods[0];
const low = call('POST', '/api/shared/3/log', { date: today, meal: 'snack', food_id: glucose.id, servings: 1, status: 'eaten' }).body;
out.low = { purpose: low.purpose, change: call('PUT', `/api/shared/3/log/${low.id}`, { servings: 2 }), remove: call('DELETE', `/api/shared/3/log/${low.id}`) };
const forMe = call('GET', '/api/me/suggestions').body;
out.forMe = forMe.suggestions.map((sg) => [sg.from_name, sg.meal, sg.items.length, !!sg.fit.day_status]);
const tomorrowBefore = call('GET', `/api/log?date=${tomorrow}`).body;
const fitWas = forMe.suggestions[0].fit.day_status;
out.acceptMine = call('POST', `/api/me/suggestions/${forMe.suggestions[0].id}/accept`).body;
out.fitMatches = JSON.stringify(call('GET', `/api/log?date=${tomorrow}`).body.projected_status) === JSON.stringify(fitWas);
out.ownGrew = call('GET', `/api/log?date=${tomorrow}`).body.entries.length - tomorrowBefore.entries.length;
out.forMeAfter = call('GET', '/api/me/suggestions').body.suggestions.length;
const sent = call('POST', '/api/shared/3/suggestions', { date: tomorrow, meal: 'dinner', items: [{ food_id: food.id, servings: 1 }], note: 'Apples are in the fruit bowl.' });
out.sent = { status: sent.status, answer: sent.body.answer, fit: !!sent.body.fit };
out.badNote = call('POST', '/api/shared/3/suggestions', { date: tomorrow, meal: 'dinner', items: [{ food_id: food.id, servings: 1 }], note: 'Take your insulin' });
out.lowFood = call('POST', '/api/shared/3/suggestions', { date: tomorrow, meal: 'dinner', items: [{ food_id: glucose.id, servings: 1 }] });
out.sentList = call('GET', '/api/shared/3/suggestions').body.suggestions.map((sg) => sg.answer);
out.export = call('GET', '/api/me/export.json').body.care_suggestions.map((sg) => [sg.from, sg.answer]);
console.log(JSON.stringify(out));
