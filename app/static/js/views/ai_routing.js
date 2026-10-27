/* Kidney Diet Log — which AI each feature uses (KH.aiRouting; ARCHITECTURE.md "Privacy tiers", docs/ai.md
   "Which AI does each feature use?").

   * Server administration → AI providers: the table "Which AI does each feature use?" (photos, meal ideas, describe a meal,
     Ask: local, cloud or off; photos, meal ideas and describe a meal can also be "Local, then cloud": the cloud AI is asked
     only if the local AI's answer fails the app's checks; lab report photos: local or off only, because a report shows a name
     and a date of birth that cannot be removed from an image), the shared provider that is the local AI and the one that is
     the cloud AI, and a warning for every feature that sends something to the cloud. Saved with PUT /api/admin/ai-routing
     (through KH.ai.api), which refuses a local AI that is not on a private address and "Local, then cloud" for Ask and lab
     report photos. When the environment defines the cloud AI (AI_CLOUD_PROVIDER, `env_cloud`), that choice is fixed and says so.
   * Settings → AI (a person): one line per feature saying where it runs ("Runs on your local AI (host)").

   Rules: everything the server sends is drawn with textContent (the h() helper); no inline scripts or handlers;
   nothing here sends health data anywhere, it only edits the admin's routing and reads the person's status. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, clear, toast } = KH;

  const ROUTE_TEXT = { local: 'Local', cloud: 'Cloud', off: 'Off', any: 'As before', local_then_cloud: 'Local, then cloud' };
  const FALLBACK = 'local_then_cloud';
  // The one rule for "Local, then cloud" (the same words as the server's consent sheet and docs/ai.md).
  const FALLBACK_RULE = 'The cloud AI is asked only if the local AI\'s answer fails the app\'s checks. '
    + 'It is not asked when the local AI cannot be reached, takes too long, is over its limit or declines the question.';
  let seq = 0;
  const uid = (p) => `${p}-${++seq}`;
  const api = () => KH.ai.api;

  function note(kind, ...children) { return h('div', { class: `settings-note ${kind}`, role: 'note' }, ...children); }

  // The sentence an admin reads when a feature goes (or stays) outside the network.
  function warningFor(feature, route, cloud, hasLocal = true) {
    if (route === 'cloud') {
      return `${feature.label}: this sends ${feature.sends} to ${cloud ? cloud.host : 'the cloud AI you choose below'}, outside your network.`;
    }
    if (route === 'any') {
      return `${feature.label}: as before, this goes to whichever shared provider each person chose, which may be a cloud AI outside your network.`;
    }
    if (route === FALLBACK && cloud && hasLocal) { // with no cloud AI chosen it behaves as local, with no local AI it is off: nothing leaves the network
      return `${feature.label}: local first. If the local AI's answer fails the app's checks, this sends ${feature.sends} to ${cloud.host}, `
        + 'outside your network, for people who agreed to that.';
    }
    return null;
  }

  // Settings → AI (a person): where each feature runs.
  function personLines(routing) {
    if (!routing || !Array.isArray(routing.features)) return null;
    const list = h('ul', { class: 'ai-routing-lines' });
    for (const f of routing.features) {
      const li = h('li', {}, h('b', {}, `${f.label}: `), f.text);
      const fb = f.fallback;
      if (fb && fb.request && !fb.given && KH.ai && typeof KH.ai.askConsent === 'function') { // local, then cloud: the person can agree to the cloud AI later
        const host = fb.runs_on.host;
        const line = h('span', { class: 'hint ai-fallback-line' }, ` You have not agreed to send this to ${host}, so the cloud AI is never asked.`);
        const agree = h('button', { class: 'btn secondary', type: 'button' }, `Allow the cloud AI (${host}) as the fallback`);
        agree.addEventListener('click', async () => {
          try {
            if (!(await KH.ai.askConsent(fb.request, null, agree))) return;
            fb.given = true;
            agree.hidden = true;
            clear(line).append(` Agreed: if the local AI's answer fails the app's checks, ${host} is asked.`);
          } catch (e) { if (!e.handled && !e.cancelled && KH.toastError) KH.toastError(e); }
        });
        li.append(line, ' ', agree);
      }
      list.append(li);
    }
    return h('div', { class: 'ai-routing-person' },
      h('h3', { class: 'settings-subtitle' }, 'Where each AI feature runs'),
      list,
      routing.mode === 'routed'
        ? h('p', { class: 'hint' }, 'Your admin decides this. A feature that is switched off here is off for everyone, whatever provider they use.')
        : h('p', { class: 'hint' }, 'Your admin has not set up local and cloud routing, so the server uses the provider chosen above, as before.'));
  }

  // Server administration → AI providers: the routing table. `data` is GET /api/admin/ai-routing; `after` runs once a change is saved.
  function adminPart(data, after) {
    const wrap = h('div', { class: 'ai-routing', id: 'ai-routing' });
    wrap.append(h('h3', { class: 'settings-subtitle' }, 'Which AI does each feature use?'));
    wrap.append(h('p', { class: 'hint' },
      'A local AI runs on your own network (for example Ollama on a home computer): what a feature sends never leaves it. '
      + 'A cloud AI is a company\'s service outside your network. Each feature is pinned to one of them, or switched off. '
      + 'Photos can show more than a label, so the safe choice for them is local. Lab report photos can only be local or off: '
      + 'a report shows your name and date of birth, which cannot be removed from a photo, so they never go to a cloud AI. '
      + 'Local, then cloud (photos, meal ideas and describe a meal) tries the local AI first; Ask makes several calls in a row, so it cannot use it.'));
    if (data.as_before) {
      wrap.append(note('caution', h('p', {},
        'Routing is not set up yet, so a feature marked "As before" uses the shared provider each person chose, as it did before this table existed. '
        + 'Choose a row below to pin it. On a new server every feature starts on local and stays off until a local AI is chosen.')));
    }
    if (!data.writable) {
      wrap.append(note('caution', h('p', {}, 'Sign-in is off on this server (AUTH_MODE=none), so routing can be set only with the environment variables AI_ROUTE_PHOTOS, AI_ROUTE_MEAL_IDEAS, AI_ROUTE_DESCRIBE, AI_ROUTE_CHAT, AI_ROUTE_LABS, AI_PROVIDER_ROLE and AI_CLOUD_PROVIDER (docs/ai.md).')));
    }

    const chosen = {}; // feature → the route picked now
    const table = h('table', { class: 'ai-routing-table' });
    table.append(h('caption', { class: 'sr-only' }, 'Which AI does each feature use?'));
    const head = h('tr', {}, h('th', { scope: 'col' }, 'Feature'));
    const showAny = data.features.some((f) => f.route === 'any'); // "As before" is offered only while it is the current setting
    const showFallback = data.features.some((f) => (f.allowed || []).includes(FALLBACK)); // only where the server allows it
    const columns = [...(showAny ? ['local', 'cloud', 'off', 'any'] : ['local', 'cloud', 'off']), ...(showFallback ? [FALLBACK] : [])];
    for (const c of columns) head.append(h('th', { scope: 'col' }, ROUTE_TEXT[c]));
    table.append(h('thead', {}, head));
    const body = h('tbody');
    for (const f of data.features) {
      chosen[f.feature] = f.route;
      const name = uid(`ai-route-${f.feature}`);
      const only = f.allowed && !f.allowed.includes('cloud'); // a feature that may only be local or off (lab report photos)
      const row = h('tr', {}, h('th', { scope: 'row' }, f.label,
        only ? h('span', { class: 'hint ai-route-lock' }, 'Local or off, never sent to a cloud AI') : null,
        f.locked_by_env ? h('span', { class: 'hint ai-route-lock' }, `Set by the server (${f.locked_by_env})`) : null));
      for (const c of columns) {
        if (f.allowed && !f.allowed.includes(c)) { // not offered for this feature: no choice to make
          row.append(h('td', { class: 'ai-route-na' }, h('span', { 'aria-hidden': 'true' }, '–'), h('span', { class: 'sr-only' }, `${f.label}: ${ROUTE_TEXT[c]} is not offered`)));
          continue;
        }
        const input = h('input', { type: 'radio', name, value: c, checked: f.route === c, 'aria-label': `${f.label}: ${ROUTE_TEXT[c]}` });
        input.disabled = !data.writable || !!f.locked_by_env || (c === 'any' && f.route !== 'any');
        input.addEventListener('change', () => { chosen[f.feature] = c; refresh(); });
        row.append(h('td', {}, input));
      }
      body.append(row);
    }
    table.append(body);
    wrap.append(table);
    if (showFallback) {
      wrap.append(h('p', { class: 'hint ai-route-rule' }, h('b', {}, 'Local, then cloud: '), FALLBACK_RULE,
        ' Only people who agreed to send that to the cloud host are affected. Ask and lab report photos cannot use it.'));
    }

    // Roles: which shared provider is the local AI and which is the cloud AI.
    const roleSel = {};
    const roleBox = h('div', { class: 'form-grid' });
    for (const role of ['local', 'cloud']) {
      const sel = h('select', { id: uid(`ai-role-${role}`) });
      sel.append(h('option', { value: '0' }, 'None'));
      for (const p of data.providers) {
        if (role === 'local' && !p.private) continue; // only a provider on the private network can be the local AI
        if (p.role && p.role !== role) continue; // already holds the other role
        sel.append(h('option', { value: String(p.id), selected: data.roles[role] && data.roles[role].id === p.id }, `${p.label} (${p.host})`));
      }
      const fromCloudVar = role === 'cloud' && !!data.env_cloud; // AI_CLOUD_PROVIDER is always the cloud AI
      const fixed = data.env_role === role || fromCloudVar;
      sel.disabled = !data.writable || fixed;
      sel.addEventListener('change', refresh);
      roleSel[role] = sel;
      roleBox.append(h('div', { class: 'field' },
        h('label', { for: sel.id }, role === 'local' ? 'The local AI' : 'The cloud AI'), sel,
        h('span', { class: 'hint' }, role === 'local'
          ? (fixed ? 'The server\'s own provider (AI_PROVIDER_ROLE=local).'
            : 'Only a provider on your own network can be chosen: its host and port must be listed in AI_PRIVATE_HOSTS (a name must be listed by name).')
          : (fromCloudVar ? 'The server\'s own cloud provider (AI_CLOUD_PROVIDER). Set it in the environment.'
            : fixed ? 'The server\'s own provider (AI_PROVIDER_ROLE=cloud).'
              : 'A company\'s service outside your network. What a feature sends there leaves your network.'))));
    }
    wrap.append(roleBox);
    if (!data.providers.some((p) => p.private)) {
      wrap.append(h('p', { class: 'hint' }, 'No shared provider is on a private address yet. Add your local AI below (Add a shared provider) after listing its host and port in AI_PRIVATE_HOSTS.'));
    }

    const warnings = h('div', { class: 'ai-routing-warnings', 'aria-live': 'polite' });
    wrap.append(warnings);
    const err = h('div', { class: 'form-error', role: 'alert' });
    const msg = h('p', { class: 'status-msg', role: 'status', 'aria-live': 'polite' });
    const save = h('button', { class: 'btn primary', type: 'button' }, 'Save routing');
    save.disabled = !data.writable;

    function cloudProvider() {
      const id = Number(roleSel.cloud.value);
      return data.providers.find((p) => p.id === id) || null;
    }
    function refresh() {
      // A feature pinned to cloud with no cloud AI chosen yet: if one provider is left over, offer it (visibly) rather than leave the feature off.
      if (Object.values(chosen).some((r) => r === 'cloud' || r === FALLBACK) && roleSel.cloud.value === '0') {
        const free = data.providers.filter((p) => !p.role || p.role === 'cloud').filter((p) => Number(roleSel.local.value) !== p.id);
        if (free.length === 1) roleSel.cloud.value = String(free[0].id);
      }
      clear(warnings);
      const cloud = cloudProvider();
      for (const f of data.features) {
        const route = chosen[f.feature];
        const text = warningFor(f, route, cloud, roleSel.local.value !== '0');
        if (text) warnings.append(note('caution', h('p', {}, text)));
        else if (route === 'local' && roleSel.local.value === '0') {
          warnings.append(h('p', { class: 'hint' }, `${f.label}: local, but no local AI is chosen, so it is off until you choose one.`));
        } else if (route === 'cloud' && !cloud) {
          warnings.append(h('p', { class: 'hint' }, `${f.label}: cloud, but no cloud AI is chosen, so it is off until you choose one.`));
        }
        if (route === FALLBACK && roleSel.local.value === '0') { // both roles must be held: with no local AI it is off, with no cloud AI it is local
          warnings.append(h('p', { class: 'hint' }, `${f.label}: local, then cloud, but no local AI is chosen, so it is off until you choose one.`));
        } else if (route === FALLBACK && !cloud) {
          warnings.append(h('p', { class: 'hint' }, `${f.label}: local, then cloud, but no cloud AI is chosen, so it works as local: the cloud AI is never asked.`));
        }
      }
    }

    save.addEventListener('click', async () => {
      clear(err);
      msg.textContent = '';
      const body = {};
      for (const f of data.features) if (chosen[f.feature] !== f.route) body[f.feature] = chosen[f.feature];
      for (const role of ['local', 'cloud']) {
        if (roleSel[role].disabled) continue;
        const now = Number(roleSel[role].value);
        const before = data.roles[role] ? data.roles[role].id : 0;
        if (now !== before) body[`${role}_provider`] = now;
      }
      if (!Object.keys(body).length) { msg.textContent = 'Nothing changed.'; return; }
      save.disabled = true;
      try {
        await api().setRouting(body);
        KH.ai.forget();
        toast('Routing saved', 'ok');
        if (typeof after === 'function') after();
      } catch (e) {
        if (!e.handled && !e.cancelled) err.append(h('p', {}, e.detail || e.message || 'Something went wrong'));
      } finally { if (document.contains(save)) save.disabled = !data.writable; }
    });
    wrap.append(err, msg, h('div', { class: 'settings-actions' }, save));
    refresh();
    return wrap;
  }

  KH.aiRouting = { adminPart, personLines };
})();
