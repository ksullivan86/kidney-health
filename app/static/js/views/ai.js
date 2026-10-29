/* Kidney Diet Log — optional AI (KH.ai; ARCHITECTURE.md "M2 API: AI and photos", docs/ai.md).

   * Settings → AI ideas (fills the #set-ai-slot that js/views/settings.js leaves for M2): the person's
     opt-in, provider choice, own provider and write-only key, age band and sex, preferences, consents,
     AI activity; for admins the providers ("Test connection"), AI_PRIVATE_HOSTS and usage counts.
   * The consent sheet (provider, destination host, policy line, the exact request) and "What will be
     sent?" (the server's dry run: destination, headers without the key, body, photo size).
   * The Add view's AI buttons (#ai-add-slot): AI meal ideas, describe a meal, read a label, plate photo.
     Guidance can show AI ideas too: KH.ai.openIdeas({date, meal}) or KH.ai.mountIdeas(el, {date, meal}).
   * The Ask screen (js/views/ask.js) uses this file's consent flow (withConsent with purpose 'chat'), its API
     object (api.chat and the routes a saved card uses) and its alert cards (cardEl).
   * How much the person trusts the assistant to save (Settings → AI ideas, assistant step 2 part C): the choice
     (ask | conversation | always), and the warning sheet (confirmTrust) that comes before conversation or always.

   Rules: AI answers are rendered with textContent only (titles and sentences come from the server's
   templates; numbers from its rule check); nothing is logged or saved without a tap, and then through
   the ordinary /api/log/batch and /api/foods routes; photos are redrawn on the device as JPEG (≤ 1600 px,
   no EXIF) before they leave. Demo mode never calls a provider. */
(() => {
  'use strict';
  const KH = window.KH;
  const { $, $$, h, clear, request, toast, toastError, state, util, ui, sheets, confirm, rules } = KH;
  const { MOCK, PREVIEW } = KH.flags;
  const { NUTRIENTS, NUT, MEAL_LABEL, MEAL_KEYS, fmtNum } = rules;

  const PHOTO_EDGE = 1600; // note 02 R7: long edge on the device
  const PHOTO_QUALITY = 0.85;
  const STATUS_TTL_MS = 30000;
  const PURPOSE_TEXT = {
    text: 'your meal data (stage, targets, today\'s totals, candidate foods), the meal you describe, or the foods and amounts of a recipe (never its name, note, steps or link)',
    photos: 'your photo (location and camera data removed)',
    chat: 'your messages in this conversation, and the app\'s own numbers the assistant looks up (your targets, today\'s totals, food names and nutrients)',
    voice: 'your voice recording (up to a minute)',
    labs: 'your photo of a lab report (location and camera data removed)',
  };
  // What the consent sheet adds under "Never sent", by purpose.
  const NEVER_SENT_TEXT = {
    chat: 'Never sent: your name, user name, e-mail, weight, height, exact age or notes. Each question can take several AI calls. '
      + 'AI never gives insulin doses or medicine advice, and the app checks every number in an answer before you see it.',
    voice: 'Nothing but the recording is sent: no name, user name, e-mail or account details. The words come back into the question box for you to read and edit; '
      + 'nothing goes to the AI until you press Send. The recording is not kept on this device or on the server.',
  };
  const FEATURE_TEXT = { next_meal: 'Meal ideas', parse_meal: 'Describe a meal', read_label: 'Read a label', plate: 'Plate photo', chat: 'Ask', voice: 'Voice',
    read_lab_report: 'Read a lab report', recipes: 'AI recipes' };
  const CONSENT_NAME = { text: 'Meal data', photos: 'Photos', chat: 'Ask conversations', voice: 'Voice recordings', labs: 'Lab report photos' };
  const CONSENT_STOP = { text: 'meal data', photos: 'photos', chat: 'your Ask conversations', voice: 'your voice recordings', labs: 'your lab report photos' };
  const CONFIDENCE_TEXT = { low: 'not sure', medium: 'fairly sure', high: 'sure' };
  // Why the rules left an AI idea out (app/guidance/ai_bridge.py, app/ai/guard.py reason codes).
  const DROP_TEXT = {
    not_a_candidate: 'a food the rules had not offered', quarters_out_of_range: 'an amount outside ¼ to 3 servings',
    portion_out_of_range: 'an amount outside ¼ to 3 servings', too_many_carbs: 'too much carbohydrate for this meal',
    hypo_treatment: 'a low treatment (kept for treating lows)', avoid_ckd: 'a food to avoid with kidney disease',
    high_portion_too_large: 'more than one serving of a food that is high in something', too_many_ideas: 'more than three ideas',
    too_many_items: 'more than five foods', duplicate: 'a repeat', too_many: 'more than the app shows', empty: 'no foods',
    malformed_idea: 'an answer the app could not check', malformed_item: 'an answer the app could not check',
    unexpected_field: 'an answer the app could not check', poor: 'a weak fit for this meal',
    too_many_recipes: 'more recipes than were asked for', too_few_items: 'fewer than two foods', malformed_recipe: 'an answer the app could not check',
    share_too_large: 'more than 3 servings of one food in each serving', not_for_me: 'a food you marked Not for me',
    excluded_category: 'a food from a group you do not want suggested',
  };
  // AI recipes (note 16 §8): the fixed lists the request offers.
  const DISHES = [['bowl', 'Bowl'], ['soup', 'Soup'], ['stew', 'Stew'], ['stir_fry', 'Stir-fry'], ['bake', 'Bake'], ['salad', 'Salad'],
    ['sandwich', 'Sandwich'], ['pasta', 'Pasta'], ['rice_dish', 'Rice dish'], ['egg_dish', 'Egg dish'], ['porridge', 'Porridge'],
    ['snack', 'Snack'], ['drink', 'Drink']];
  const MAKES = [1, 2, 4, 6];
  const RECIPE_KEYS = ['carbs_g', 'protein_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg', 'fluid_ml'];
  const UNIT_TEXT = { serving: ['serving', 'servings'], g: ['g', 'g'], ml: ['ml', 'ml'], cup: ['cup', 'cups'], tbsp: ['tbsp', 'tbsp'],
    tsp: ['tsp', 'tsp'], slice: ['slice', 'slices'], piece: ['piece', 'pieces'], oz: ['oz', 'oz'], fl_oz: ['fl oz', 'fl oz'] };
  const STATUS_TEXT = { ok: 'checked', dropped_all: 'no idea fitted', no_fit: 'nothing fitted', refused: 'declined by the AI', invalid: 'answer not usable',
    cached: 'reused (the same question within 10 minutes; no new AI call)' };
  function dropText(code) {
    const [kind, key] = String(code).split(':');
    const label = key && NUT[key] ? NUT[key].label.toLowerCase() : key;
    if (kind === 'would_exceed') return `too much ${label} for today`;
    if (kind === 'high_warning') return `high in ${label} while ${label} is not OK today`;
    if (kind === 'unknown') return `${label} not known for a food`;
    if (kind === 'text_policy') return 'text the app does not show';
    return DROP_TEXT[kind] || kind.replace(/_/g, ' ');
  }
  function statusText(raw) {
    if (STATUS_TEXT[raw]) return STATUS_TEXT[raw];
    return raw.startsWith('error:') ? `failed (${raw.slice(6).replace(/_/g, ' ')})` : raw;
  }
  let seq = 0;
  const uid = (p) => `${p}-${++seq}`;

  // ---------------------------------------------------------------------------
  // API
  // ---------------------------------------------------------------------------
  const api = {
    status: () => request('GET', '/api/ai/status'),
    me: () => request('GET', '/api/me/ai'),
    updateMe: (b) => request('PATCH', '/api/me/ai', b),
    setOwn: (b) => request('PUT', '/api/me/ai/provider', b),
    deleteOwn: () => request('DELETE', '/api/me/ai/provider'),
    probeOwn: () => request('POST', '/api/me/ai/probe'),
    consent: (b) => request('POST', '/api/ai/consent', b),
    withdraw: (id, purpose) => request('DELETE', `/api/ai/consent/${id}?` + util.qs({ purpose })),
    audit: (before) => request('GET', '/api/ai/audit?' + util.qs({ before, limit: 20 })),
    deleteAudit: () => request('DELETE', '/api/ai/audit'),
    nextMeal: (b, dry) => request('POST', `/api/ai/next-meal${dry ? '?dry_run=true' : ''}`, b),
    recipes: (b, dry) => request('POST', `/api/ai/recipes${dry ? '?dry_run=true' : ''}`, b),
    parseMeal: (b, dry) => request('POST', `/api/ai/parse-meal${dry ? '?dry_run=true' : ''}`, b),
    chat: (b, dry) => request('POST', `/api/ai/chat${dry ? '?dry_run=true' : ''}`, b),
    providers: () => request('GET', '/api/admin/ai-providers'),
    createProvider: (b) => request('POST', '/api/admin/ai-providers', b),
    updateProvider: (id, b) => request('PUT', `/api/admin/ai-providers/${id}`, b),
    deleteProvider: (id) => request('DELETE', `/api/admin/ai-providers/${id}`),
    probeProvider: (id) => request('POST', `/api/admin/ai-providers/${id}/probe`),
    usage: () => request('GET', '/api/admin/ai-usage?days=30'),
    routing: () => request('GET', '/api/admin/ai-routing'),
    quality: () => request('GET', '/api/admin/ai-quality'),
    setRouting: (b) => request('PUT', '/api/admin/ai-routing', b),
    probeVoice: () => request('POST', '/api/admin/ai-voice/probe'),
    logBatch: (entries) => request('POST', '/api/log/batch', { entries }),
    createFood: (b) => request('POST', '/api/foods', b),
    addEntry: (b) => request('POST', '/api/log', b),
    // The routes the Ask screen's cards use (the normal save, import and delete routes; the model is never involved).
    importUsda: (fdcId) => request('POST', '/api/foods/usda/import', { fdc_id: fdcId }),
    createMeal: (b) => request('POST', '/api/meals', b),
    deleteEntry: (id) => request('DELETE', `/api/log/${id}`),
    deleteMeal: (id) => request('DELETE', `/api/meals/${id}`),
  };

  // A photo goes as the raw JPEG body (no multipart, note 03 R8): the shared JSON client cannot send it. `kind` is label or
  // plate (POST /api/vision/<kind>), or lab-report (POST /api/ai/read-lab-report: a report photo, local AI only). `signal` (optional,
  // an AbortSignal) lets the caller stop the request: it rejects with the browser's AbortError, which is not turned into a message
  // (a PDF lab report is read page by page and has a Cancel button, js/views/lab_photo.js).
  async function uploadPhoto(kind, blob, dry, signal) {
    if (MOCK) throw Object.assign(new Error('Photos are read by AI only in the installed app.'), { status: 0 });
    let res;
    try {
      res = await fetch(`${kind === 'lab-report' ? '/api/ai/read-lab-report' : `/api/vision/${kind}`}${dry ? '?dry_run=true' : ''}`, {
        method: 'POST',
        headers: { 'Content-Type': 'image/jpeg', Accept: 'application/json', 'X-Requested-With': KH.brand.csrfHeaderValue },
        body: blob,
        credentials: 'same-origin',
        ...(signal ? { signal } : {}),
      });
    } catch (e) {
      if (e && e.name === 'AbortError') throw e;
      throw Object.assign(new Error('Cannot reach the server. Check your connection.'), { status: 0 });
    }
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text.slice(0, 200) }; }
    if (res.ok) return data;
    const err = new Error((data && typeof data.detail === 'string' && data.detail) || `${res.status} ${res.statusText || 'error'}`);
    err.status = res.status; err.detail = err.message; err.data = data || {};
    if (res.status === 401) { err.handled = true; try { KH.auth.onUnauthorized(err); } catch (e) { console.error(e); } }
    throw err;
  }

  // GET /api/ai/status, cached briefly (404 = AI is off on this server).
  let statusCache = null;
  let statusAt = 0;
  async function status(force = false) {
    if (MOCK) return { enabled: false, demo: true };
    if (!force && statusCache && Date.now() - statusAt < STATUS_TTL_MS) return statusCache;
    try {
      // /api/me/ai is always there; /api/ai/status answers 404 while AI is off (as if not registered).
      const me = await api.me();
      statusCache = me.enabled ? await api.status() : { enabled: false };
    } catch (err) {
      if (err.status === 404) statusCache = { enabled: false };
      else { if (!err.handled) console.warn('AI status unavailable:', err.message); return statusCache || { enabled: false, error: true }; }
    }
    statusAt = Date.now();
    return statusCache;
  }
  // After a change of the AI choices, consent or switches: the Ask tab follows what the server now says.
  function forget() {
    statusCache = null;
    statusAt = 0;
    if (KH.views.ask && typeof KH.views.ask.refreshTab === 'function') KH.views.ask.refreshTab();
  }

  // ---------------------------------------------------------------------------
  // Small DOM helpers
  // ---------------------------------------------------------------------------
  function statusMsg(id) { return h('p', { class: 'status-msg', id: id || uid('ai-msg'), role: 'status', 'aria-live': 'polite' }); }
  function formError() { return h('div', { class: 'form-error', role: 'alert' }); }
  function showError(box, err) {
    clear(box);
    if (!err) return;
    box.append(h('p', {}, typeof err === 'string' ? err : (err.detail || err.message || 'Something went wrong')));
  }
  function note(kind, ...children) { return h('div', { class: `settings-note ${kind}`, role: 'note' }, ...children); }
  function subtitle(text) { return h('h3', { class: 'settings-subtitle' }, text); }
  function button(label, cls, fn, attrs = {}) {
    const btn = h('button', { class: `btn ${cls}`, type: 'button', ...attrs }, label);
    btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      try { await fn(btn); } catch (err) { if (!err.handled && !err.cancelled) toastError(err); } finally { if (document.contains(btn)) btn.disabled = false; }
    });
    return btn;
  }
  function field(label, input, hint) {
    const hintEl = hint ? h('span', { class: 'hint', id: `${input.id}-hint` }, hint) : null;
    if (hintEl) input.setAttribute('aria-describedby', hintEl.id);
    return h('div', { class: 'field' }, h('label', { for: input.id }, label), input, hintEl);
  }
  function check(label, input, hint) {
    return h('label', { class: 'check', for: input.id }, input, h('span', { class: 'check-text' }, label, hint ? h('span', { class: 'hint' }, hint) : null));
  }
  function pre(value) {
    return h('pre', { class: 'ai-pre', tabindex: '0' }, typeof value === 'string' ? value : JSON.stringify(value, null, 2));
  }
  function segmented(name, options, value, legend) {
    const wrap = h('div', { class: `segmented meal-seg${options.length === 2 ? ' status-seg' : ''}`, role: 'radiogroup', 'aria-label': legend });
    for (const [key, text] of options) {
      const id = uid(`${name}-${key}`);
      wrap.append(h('input', { type: 'radio', name, id, value: key, checked: key === value }), h('label', { for: id }, text));
    }
    return h('fieldset', { class: 'field' }, h('legend', {}, legend), wrap);
  }
  function segValue(root, name) { const r = $(`input[name="${name}"]:checked`, root); return r ? r.value : null; }
  function mealPicker(name, meal) { return segmented(name, MEAL_KEYS.map((k) => [k, MEAL_LABEL[k]]), meal, 'Meal'); }
  function statusPicker(name, value) { return segmented(name, [['eaten', 'Eaten'], ['planned', 'Planned']], value, 'Status'); }
  function learnLink(page) {
    const target = KH.learn && page && page.url ? KH.learn.href(page.url) : null;
    if (!target) return null;
    return h('a', { class: 'learn-more', href: target, target: '_blank', rel: 'noopener' }, `Learn: ${page.title}`, h('span', { class: 'sr-only' }, ' (opens in a new tab)'));
  }
  function nutrientLine(values, keys) {
    const parts = [];
    for (const key of keys) {
      const v = values ? values[key] : null;
      if (v == null || !NUT[key]) continue;
      parts.push(`${NUT[key].label} ${fmtNum(v, key)} ${NUT[key].unit}`);
    }
    return parts.join(' · ');
  }
  function refreshDayCaches() { state.dayLoadedFor = null; state.plan = null; state.trends = null; state.summary = null; }

  // ---------------------------------------------------------------------------
  // Sheets: one dialog for the features, one for consent, one for "What will be sent?"
  // ---------------------------------------------------------------------------
  const sheetEl = $('#sheet-ai');
  const consentEl = $('#sheet-ai-consent');
  const sentEl = $('#sheet-ai-sent');
  const trustEl = $('#sheet-ai-trust');
  for (const d of [sheetEl, consentEl, sentEl, trustEl]) if (d) sheets.setup(d);

  function fillSheet(dlg, title, sub) {
    $('.sheet-title', dlg).textContent = title;
    const subEl = $('.sheet-sub', dlg);
    subEl.textContent = sub || '';
    subEl.hidden = !sub;
    return { body: clear($('.sheet-body', dlg)), foot: clear($('.sheet-foot', dlg)) };
  }
  // Resolves true when `okButton` is pressed, false when the sheet closes otherwise. `focus` is the button that has
  // the focus when the sheet opens (the OK button unless a caller wants the safe choice first).
  function awaitChoice(dlg, okButton, trigger, focus = okButton) {
    return new Promise((resolve) => {
      let done = false;
      const finish = (v) => { if (!done) { done = true; resolve(v); } };
      okButton.addEventListener('click', () => { finish(true); dlg.close(); });
      dlg.addEventListener('close', () => finish(false), { once: true });
      sheets.open(dlg, trigger, focus);
    });
  }

  // "What will be sent?": the dry run (ARCHITECTURE: destination, headers without the key, body, photo size).
  function renderDryRun(container, dry) {
    container.append(
      h('dl', { class: 'kv' },
        h('div', { class: 'kv-row' }, h('dt', {}, 'Goes to'), h('dd', {}, `${dry.provider ? dry.provider.label : ''} · ${dry.host}${dry.provider && dry.provider.local ? ' (your local AI, on your network)' : ''}`)),
        h('div', { class: 'kv-row' }, h('dt', {}, 'Address'), h('dd', {}, `${dry.method} ${dry.destination}`)),
        dry.image_bytes ? h('div', { class: 'kv-row' }, h('dt', {}, 'Photo'), h('dd', {}, `${Math.round(dry.image_bytes / 1024)} KiB JPEG, ${dry.images.map((i) => `${i.width}×${i.height}`).join(', ')}, location and camera data removed`)) : null,
        dry.trimmed_candidates ? h('div', { class: 'kv-row' }, h('dt', {}, 'Left out'), h('dd', {}, `${dry.trimmed_candidates} lower-ranked foods, to fit the provider's prompt size`)) : null),
      h('details', { class: 'settings-details' }, h('summary', {}, 'Headers'), pre(dry.headers)),
      h('details', { class: 'settings-details', open: true }, h('summary', {}, 'Body (exactly as sent)'), pre(dry.body)),
      dry.cloud_fallback ? fallbackDryRun(dry.cloud_fallback) : null);
  }
  // Privacy tier 3 (local first, cloud only when the local answer fails): a second request with the same content may go to the
  // cloud AI, but only if the local AI's answer fails the app's checks. Shown under the request that is sent first.
  function fallbackDryRun(f) {
    return h('section', { class: 'ai-dry-fallback' },
      h('h4', { class: 'settings-minor' }, 'Only if the local AI\'s answer fails the app\'s checks'),
      h('p', {}, f.message),
      h('dl', { class: 'kv' },
        h('div', { class: 'kv-row' }, h('dt', {}, 'Would go to'), h('dd', {}, `${f.provider ? f.provider.label : ''} · ${f.host}`)),
        h('div', { class: 'kv-row' }, h('dt', {}, 'Address'), h('dd', {}, `${f.method} ${f.destination}`)),
        f.image_bytes ? h('div', { class: 'kv-row' }, h('dt', {}, 'Photo'), h('dd', {}, 'The same photo, location and camera data removed')) : null),
      h('details', { class: 'settings-details' }, h('summary', {}, 'Second request (exactly as it would be sent)'), pre(f.body)));
  }
  async function showSent(dry, { trigger = null, confirmText = null } = {}) {
    const { body, foot } = fillSheet(sentEl, 'What will be sent?', 'Exactly this request leaves the server. Your key is never shown.');
    renderDryRun(body, dry);
    if (!confirmText) {
      const close = h('button', { class: 'btn primary', type: 'button', 'data-close': '' }, 'Close');
      close.addEventListener('click', () => sentEl.close());
      foot.append(h('span', { class: 'spacer' }), close);
      sheets.open(sentEl, trigger, close);
      return true;
    }
    const cancel = h('button', { class: 'btn secondary', type: 'button' }, 'Cancel');
    cancel.addEventListener('click', () => sentEl.close());
    const ok = h('button', { class: 'btn primary', type: 'button' }, confirmText);
    foot.append(h('span', { class: 'spacer' }), cancel, ok);
    return awaitChoice(sentEl, ok, trigger);
  }

  // The consent sheet (note 04 R9 step 3): provider, destination host, policy line, the exact request.
  async function askConsent(consent, dry, trigger) {
    // A voice recording goes to the speech-to-text server, not to the AI provider, and there is no request to preview
    // before it exists: its sheet says where it goes and what comes back, with no "show me the request" choice.
    const voice = consent.purpose === 'voice';
    const fb = !voice && consent.fallback ? consent.fallback : null; // local first, then this cloud AI only if the answer fails the checks
    const sub = `${consent.provider_label} · ${consent.host}`
      + (fb ? `, then ${fb.provider_label} · ${fb.host} only if the answer fails the app's checks` : '');
    const { body, foot } = fillSheet(consentEl, voice ? 'Before your recording is sent' : 'Before anything is sent', sub);
    const showId = uid('ai-preview');
    const showEach = h('input', { type: 'checkbox', id: showId });
    const allowCloud = fb && !fb.given ? h('input', { type: 'checkbox', id: uid('ai-cloud-fallback') }) : null;
    // A lab report photo (purpose labs) is explained in the server's own words (consent.notice): where it goes, that a report can
    // show a name, a date of birth and record numbers, that the photo is not kept, and to crop it. The generic "never sent" line
    // is left out for it, because it would be untrue of a photo.
    const notice = consent.purpose === 'labs' && Array.isArray(consent.notice) ? consent.notice : null;
    body.append(...[ // an absent part is null: leave it out (append(null) would write the word "null")
      notice ? h('div', { class: 'ai-consent-notice' }, notice.map((line) => h('p', {}, line)))
        : voice ? null : h('p', {}, `To use AI for this, the server sends ${PURPOSE_TEXT[consent.purpose] || 'data'} to `, h('strong', {}, consent.provider_label),
          ' at ', h('strong', { class: 'ai-host' }, consent.host), consent.local ? ', which runs on your own network.' : '.'),
      consent.as_fallback ? h('p', { class: 'hint' }, `This is the cloud AI your admin set as the fallback. ${consent.rule || ''}`) : null,
      note('caution', h('p', {}, consent.policy)),
      fb ? h('div', { class: 'ai-consent-fallback' },
        h('p', {}, 'Only if the local AI\'s answer fails the app\'s checks, the same request goes a second time to ', h('strong', {}, fb.provider_label),
          ' at ', h('strong', { class: 'ai-host' }, fb.host), ', outside your network.'),
        h('p', { class: 'hint' }, fb.rule),
        note('caution', h('p', {}, fb.policy)),
        allowCloud ? check(`Also allow the cloud AI (${fb.host}) as the fallback`, allowCloud,
          'Leave this off and the cloud AI is never asked: you see the local AI\'s answer, or that it failed.')
          : h('p', { class: 'hint' }, `You already agreed to send this to ${fb.host}.`)) : null,
      notice ? null : h('p', { class: 'hint' }, NEVER_SENT_TEXT[consent.purpose] || 'Never sent: your name, user name, e-mail, weight, height, exact age, dates or notes. AI never gives insulin doses or medicine advice, and every idea is checked against your targets before you see it.'),
      dry ? h('details', { class: 'settings-details' }, h('summary', {}, 'Exactly what will be sent'), h('div', { class: 'ai-dry' }, (() => { const box = h('div'); renderDryRun(box, dry); return box; })())) : null,
      voice ? null : check('Show me the request before every AI call to this server', showEach, 'You can change this by withdrawing and giving consent again in Settings → AI ideas.')].filter(Boolean));
    const cancel = h('button', { class: 'btn secondary', type: 'button' }, 'Not now');
    cancel.addEventListener('click', () => consentEl.close());
    const ok = h('button', { class: 'btn primary', type: 'button' }, voice ? 'Agree and record' : 'Agree and send');
    foot.append(h('span', { class: 'spacer' }), cancel, ok);
    const agreed = await awaitChoice(consentEl, ok, trigger);
    if (!agreed) return false;
    await api.consent({ provider_id: consent.provider_id, purpose: consent.purpose, skip_preview: !showEach.checked });
    if (allowCloud && allowCloud.checked) await api.consent({ provider_id: fb.provider_id, purpose: consent.purpose, skip_preview: !showEach.checked });
    forget();
    return true;
  }

  // Runs `send` once the person has agreed to send to this provider for `purpose` (409 → consent sheet,
  // then one more try); shows the request first when they asked for that. null = the person declined.
  // `feature` (privacy tiers: photos, meal_ideas, describe or chat) names whose provider the consent is about, since two
  // features of one purpose can run on different providers; it defaults to the purpose's usual feature.
  const FEATURE_OF = { text: 'meal_ideas', photos: 'photos', chat: 'chat', labs: 'labs' }; // AI recipes pass 'recipes'
  async function withConsent(purpose, send, preview, trigger, feature = FEATURE_OF[purpose]) {
    const st = await status();
    const route = st && st.routes && st.routes[feature];
    const given = route ? route.consent : st && st.consent && st.consent[purpose];
    if (given && !given.skip_preview) {
      const dry = await preview();
      if (!dry || !dry.dry_run) return dry; // answered without AI (a low, a red flag, no targets): nothing to send
      if (!(await showSent(dry, { trigger, confirmText: 'Send' }))) return null;
    }
    try {
      return await send();
    } catch (err) {
      if (err.status === 409 && err.data && err.data.consent_required) {
        let dry = null;
        try { dry = await preview(); } catch (e) { /* the sheet still names the host */ }
        if (dry && !dry.dry_run) dry = null;
        if (!(await askConsent(err.data.consent, dry, trigger))) return null;
        return send();
      }
      throw err;
    }
  }

  // ---------------------------------------------------------------------------
  // Answers
  // ---------------------------------------------------------------------------
  function answerHead(answer) {
    const out = [];
    if (answer.status === 'error') out.push(note('caution', h('p', {}, answer.message || 'The AI request failed.')));
    else if (answer.message) out.push(note('caution', h('p', {}, answer.message)));
    return out.concat(droppedNotes(answer));
  }
  // Privacy tier 3 (route local_then_cloud): when the local AI's answer did not pass the app's checks, say which AI answered, or why
  // the cloud AI was not asked. Without the person's consent for the cloud host nothing was sent; the button offers to agree.
  function fallbackNotes(answer) {
    const f = answer && answer.cloud_fallback;
    if (!f || !f.message) return [];
    const out = [h('p', { class: 'hint ai-fallback-line' }, f.message)];
    if (f.reason === 'no_consent' && f.consent) {
      const agree = button(`Allow the cloud AI (${f.consent.host}) as the fallback`, 'secondary', async (btn) => {
        if (await askConsent(f.consent, null, btn)) {
          btn.hidden = true;
          toast('Agreed. If the local AI\'s answer fails the app\'s checks again, the cloud AI will be asked.');
        }
      });
      out.push(h('div', { class: 'settings-actions' }, agree));
    }
    return out;
  }
  // G13: how many AI ideas or picks the rules left out and why, and how many claimed reasons they removed. The
  // guidance views' AI order, AI pick and AI plan show the same lines (KH.ai.droppedNotes).
  function droppedNotes(answer, what = null) {
    const out = [...fallbackNotes(answer)];
    const dropped = ((answer && answer.dropped) || []).length;
    if (dropped) {
      const noun = what || (answer.feature === 'next_meal' ? ['AI idea was', 'AI ideas were']
        : answer.feature === 'recipes' ? ['AI recipe was', 'AI recipes were'] : ['AI answer was', 'AI answers were']);
      out.push(h('p', { class: 'hint g-ai-dropped' }, `${dropped} ${noun[dropped === 1 ? 0 : 1]} left out by the app's rules: `
        + `${[...new Set(answer.dropped.map((d) => dropText(d.reason)))].join('; ')}.`));
    }
    if (answer && answer.claims_corrected) out.push(h('p', { class: 'hint' }, `The app removed ${answer.claims_corrected} ${answer.claims_corrected === 1 ? 'reason' : 'reasons'} the AI gave that the numbers did not support.`));
    return out;
  }
  // One rule-based card (G7 "Treating a low", G8 "Get help now"): shown instead of an AI answer, here and in the Ask screen.
  function cardEl(card, danger) {
    return h('section', { class: `ai-card-alert ${danger ? 'danger' : 'low'}`, role: 'alert' },
      h('h3', {}, card.title),
      h('ul', {}, card.lines.map((line) => h('li', {}, line))),
      learnLink({ url: card.url, title: card.title }));
  }
  function cardsBlock(answer) {
    return (answer.cards || []).map((card) => cardEl(card, answer.status === 'red_flag'));
  }

  function itemRow(it) {
    const warn = (it.warnings || []).filter((w) => w.message);
    return h('li', { class: 'ai-item' },
      ui.ratingIcon(it.renal_rating || 'green', { label: ui.RATING_LABEL[it.renal_rating] || '' }),
      h('div', { class: 'ai-item-main' },
        h('span', { class: 'ai-item-name' }, it.name),
        h('span', { class: 'muted small' }, it.portion_text || `${it.servings} × ${it.serving_desc}`),
        warn.length ? h('ul', { class: 'ai-warnings' }, warn.map((w) => h('li', { class: `w-${w.level}` }, `${w.level === 'high' ? 'High' : 'Moderate'}: ${w.message}`))) : null));
  }

  function ideaCard(idea, ctx) {
    const after = idea.after || {};
    const afterParts = [];
    for (const [key, v] of Object.entries(after)) {
      if (key === 'carbs_g') afterParts.push(`${MEAL_LABEL[ctx.meal]} carbohydrate ${fmtNum(v.meal_after, 'carbs_g')} of ${fmtNum(v.goal, 'carbs_g')} g`);
      else if (NUT[key]) afterParts.push(`${NUT[key].label} left today ${fmtNum(v.left_today_after, key)} ${NUT[key].unit}`);
    }
    const add = button('Add to plan', 'primary', async (btn) => {
      const entries = idea.items.map((it) => ({ date: ctx.date, meal: ctx.meal, food_id: it.food_id, servings: it.servings, status: 'planned' }));
      await api.logBatch(entries);
      refreshDayCaches();
      btn.textContent = 'Added to your plan';
      toast(`Added to your plan for ${MEAL_LABEL[ctx.meal].toLowerCase()}`);
    });
    return h('article', { class: 'ai-idea' },
      h('h3', { class: 'ai-idea-title' }, idea.title),
      h('p', { class: 'ai-why' }, idea.why),
      h('ul', { class: 'ai-items' }, idea.items.map(itemRow)),
      h('p', { class: 'small' }, nutrientLine(idea.totals, ['carbs_g', 'protein_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg'])),
      afterParts.length ? h('p', { class: 'muted small' }, afterParts.join(' · ')) : null,
      (idea.handbook || []).length ? h('p', { class: 'ai-links' }, idea.handbook.map(learnLink).filter(Boolean)) : null,
      h('p', { class: 'ai-label' }, idea.notice),
      h('div', { class: 'settings-actions' }, add));
  }

  function fallbackBlock(fallback, ctx) {
    if (!fallback) return null;
    return h('section', { class: 'ai-fallback' },
      h('h3', { class: 'settings-minor' }, "The app's own ideas"),
      (fallback.foods || []).length ? h('ul', { class: 'ai-items' }, fallback.foods.map((f) => h('li', { class: 'ai-item' },
        ui.ratingIcon(f.renal_rating || 'green', { label: ui.RATING_LABEL[f.renal_rating] || '' }),
        h('div', { class: 'ai-item-main' }, h('span', { class: 'ai-item-name' }, f.name), f.fit_text ? h('span', { class: 'muted small' }, f.fit_text) : null),
        button('Add', 'secondary', async (btn) => {
          await api.logBatch([{ date: ctx.date, meal: ctx.meal, food_id: f.food_id, servings: f.portion, status: 'planned' }]);
          refreshDayCaches();
          btn.textContent = 'Added';
        }, { 'aria-label': `Add ${f.name} to your plan` })))) : h('p', { class: 'muted small' }, 'Nothing else fits this meal today.'));
  }

  // "Other ideas" and "Other recipes" send the foods already shown, so the AI gets other candidates. The server takes at most 60:
  // past that, it starts again from the last answer.
  const MAX_SEEN = 60;
  function foodIdsOf(items) { return [...new Set(items.map((it) => it.food_id).filter((id) => Number.isInteger(id)))]; }
  function moreSeen(seen, last) {
    const next = [...new Set([...seen, ...last])];
    return next.length > MAX_SEEN ? last.slice(0, MAX_SEEN) : next;
  }
  function renderIdeas(out, answer, ctx) {
    clear(out);
    if (!answer) return;
    out.append(...answerHead(answer), ...cardsBlock(answer));
    for (const idea of answer.ideas || []) out.append(ideaCard(idea, ctx));
    if (answer.fallback) out.append(fallbackBlock(answer.fallback, ctx));
    for (const n of answer.notes || []) out.append(h('p', { class: 'muted small' }, n));
  }

  // ---------------------------------------------------------------------------
  // AI meal ideas
  // ---------------------------------------------------------------------------
  // The person's AI ideas for one meal, as a block (guidance's "What fits now" can mount it).
  function mountIdeas(container, { date = state.date, meal = util.defaultMealForNow() } = {}) {
    const ctx = { date, meal, seen: [], last: [] }; // seen: foods of the ideas shown so far, for "Other ideas"
    let request = 0;
    const out = h('div', { class: 'ai-results', 'aria-live': 'polite' });
    const err = formError();
    async function run(btn, exclude) {
      const req = ++request;
      const requested = { date: ctx.date, meal: ctx.meal };
      clear(err);
      const label = btn.textContent;
      btn.textContent = 'Asking…';
      out.setAttribute('aria-busy', 'true');
      try {
        const body = { ...requested, mode: 'ideas', ...(exclude.length ? { exclude_food_ids: exclude } : {}) };
        const answer = await withConsent('text', () => api.nextMeal(body), () => api.nextMeal(body, true), btn);
        if (req !== request) return;
        if (answer) {
          renderIdeas(out, answer, requested);
          ctx.seen = exclude;
          ctx.last = foodIdsOf((answer.ideas || []).flatMap((i) => i.items || []));
          other.hidden = !ctx.last.length;
        }
      } catch (e) {
        if (req === request && !e.handled && !e.cancelled) showError(err, e);
      } finally {
        btn.textContent = label;
        if (req === request) out.removeAttribute('aria-busy');
      }
    }
    const ask = button('Ask AI for ideas', 'primary', (btn) => run(btn, []));
    const other = button('Other ideas', 'secondary', (btn) => run(btn, moreSeen(ctx.seen, ctx.last)), { hidden: '' });
    const what = button('What will be sent?', 'secondary', async (btn) => {
      clear(err);
      try { await showSent(await api.nextMeal({ meal: ctx.meal, date: ctx.date, mode: 'ideas' }, true), { trigger: btn }); } catch (e) { showError(err, e); }
    });
    const reset = () => { ++request; clear(out); clear(err); out.removeAttribute('aria-busy'); ctx.seen = []; ctx.last = []; other.hidden = true; };
    clear(container).append(h('div', { class: 'settings-actions' }, ask, other, what), err, out);
    return { setMeal(m) { ctx.meal = m; reset(); }, setDate(d) { ctx.date = d; reset(); } };
  }
  function openIdeas({ date = state.date, meal = state.addMealHint || util.defaultMealForNow(), trigger = null } = {}) {
    const { body, foot } = fillSheet(sheetEl, 'AI meal ideas', `Checked against your targets for ${util.fmtDateLong(date)}. Not medical advice.`);
    const box = h('div', { class: 'ai-block' });
    const name = uid('ai-ideas-meal');
    const picker = mealPicker(name, meal);
    body.append(h('p', { class: 'hint' }, "The app's rules choose the foods the AI may use and check every idea it returns; nothing is added until you tap Add to plan."), picker, box);
    const block = mountIdeas(box, { date, meal });
    picker.addEventListener('change', () => block.setMeal(segValue(picker, name)));
    foot.append(h('span', { class: 'spacer' }), closeButton(sheetEl));
    sheets.open(sheetEl, trigger);
  }
  // ---------------------------------------------------------------------------
  // AI recipes (note 16 §8, §10): suggest a recipe, or rework a saved one. The server checks and fits every recipe and saves
  // nothing; each card carries the exact body for POST /api/meals, saved only by the person's tap.
  // ---------------------------------------------------------------------------
  function recipeCard(card, ctx, onSaved) {
    const art = h('article', { class: 'ai-idea ai-recipe' });
    const unknown = Object.keys(card.unknown || {}).filter((k) => NUT[k] && RECIPE_KEYS.includes(k));
    const changes = ((card.fit && card.fit.changes) || []).filter((c) => c.code !== 'does_not_fit');
    const save = button('Save recipe', 'primary', async (btn) => {
      if (btn.dataset.saved) return; // saved once already: a second tap must not make a copy
      const saved = await api.createMeal(card.body);
      btn.dataset.saved = '1';
      btn.textContent = 'Saved';
      toast(`Saved “${saved.name}” to your saved meals`, 'ok');
      if (onSaved) await onSaved(saved);
    });
    const add = button('Add to plan', 'secondary', async (btn) => {
      // One serving at the size that fits: each food's pot amount divided by the servings the saved recipe would make.
      const n = card.body.servings_made || 1;
      const meal = ctx.meal || 'dinner';
      const entries = card.body.items.map((it) => ({ date: ctx.date, meal, food_id: it.food_id,
        servings: Math.round((it.servings / n) * 100) / 100, status: 'planned' })).filter((e) => e.servings > 0);
      await api.logBatch(entries);
      refreshDayCaches();
      btn.textContent = 'Added to your plan';
      toast(`One serving added to your plan for ${MEAL_LABEL[meal].toLowerCase()}`);
    });
    const dismiss = button('Dismiss', 'secondary', () => art.remove());
    art.append(...[
      h('h3', { class: 'ai-idea-title' }, card.title),
      h('p', { class: 'ai-why' }, card.why),
      h('p', { class: 'muted small' }, `Makes ${card.makes === 1 ? '1 serving' : `${card.makes} servings`}. The numbers are for one serving.`),
      (card.differences || []).length ? h('ul', { class: 'fit-changes' }, card.differences.map((t) => h('li', {}, t))) : null,
      h('h4', { class: 'settings-minor' }, 'Foods for the whole recipe'),
      h('ul', { class: 'compact-items' }, card.items.map((it) => h('li', {}, `${it.portion_text} ${it.name}`))),
      h('p', { class: 'small' }, nutrientLine(card.per_serving, RECIPE_KEYS)),
      unknown.length ? h('p', { class: 'muted small' }, `Some foods do not list ${unknown.map((k) => NUT[k].short.toLowerCase()).join(', ')}, so those numbers are at least what is shown.`) : null,
      changes.length ? h('div', {}, h('h4', { class: 'settings-minor' }, 'What the app changed to fit your targets'),
        h('ul', { class: 'fit-changes' }, changes.map((c) => h('li', {}, c.text)))) : null,
      (card.steps || []).length ? h('div', { class: 'ai-steps' }, h('h4', { class: 'settings-minor' }, 'Steps'),
        h('ol', {}, card.steps.map((s) => h('li', {}, s))), h('p', { class: 'hint' }, card.steps_label)) : null,
      card.steps_note ? h('p', { class: 'hint' }, card.steps_note) : null,
      h('p', { class: 'ai-label' }, card.notice),
      h('div', { class: 'settings-actions' }, save, add, dismiss)].filter(Boolean));
    return art;
  }
  function renderRecipes(out, answer, ctx, onSaved) {
    clear(out);
    if (!answer) return;
    out.append(...answerHead(answer));
    for (const card of answer.recipes || []) out.append(recipeCard(card, ctx, onSaved));
    for (const n of answer.notes || []) out.append(h('p', { class: 'muted small' }, n));
  }
  function openRecipes({ mode = 'suggest', mealId = null, name = '', meal = null, date = state.date, trigger = null, onSaved = null } = {}) {
    const change = mode === 'change';
    const { body, foot } = fillSheet(sheetEl, change ? 'Rework with AI' : 'AI recipes',
      `Checked against your targets for ${util.fmtDateLong(date)}. Not medical advice.`);
    const ctx = { date, meal: meal || util.defaultMealForNow() };
    const pickName = uid('ai-recipe-meal');
    const picker = mealPicker(pickName, ctx.meal);
    picker.addEventListener('change', () => { ctx.meal = segValue(picker, pickName); reset(); });
    const dish = h('select', { id: uid('ai-dish') }, DISHES.map(([v, label]) => h('option', { value: v }, label)));
    const makes = h('select', { id: uid('ai-makes') }, MAKES.map((n) => h('option', { value: String(n), selected: n === 4 ? '' : null }, n === 1 ? '1 serving' : `${n} servings`)));
    const out = h('div', { class: 'ai-results', 'aria-live': 'polite' });
    const err = formError();
    const reqBody = () => (change ? { mode: 'change', meal_id: mealId, meal: ctx.meal, date: ctx.date }
      : { mode: 'suggest', dish: dish.value, makes: Number(makes.value), meal: ctx.meal, date: ctx.date });
    const seen = { foods: [], last: [] }; // foods of the recipes shown so far, for "Other recipes"
    let request = 0;
    async function run(btn, exclude) {
      const req = ++request;
      const requested = { date: ctx.date, meal: ctx.meal };
      clear(err);
      const label = btn.textContent;
      btn.textContent = 'Asking…';
      out.setAttribute('aria-busy', 'true');
      try {
        const b = { ...reqBody(), ...(exclude.length ? { exclude_food_ids: exclude } : {}) };
        const answer = await withConsent('text', () => api.recipes(b), () => api.recipes(b, true), btn, 'recipes');
        if (req !== request) return;
        if (answer) {
          renderRecipes(out, answer, requested, onSaved);
          seen.foods = exclude;
          seen.last = foodIdsOf((answer.recipes || []).flatMap((r) => (r.body && r.body.items) || []));
          other.hidden = !seen.last.length;
        }
      } catch (e) {
        if (req === request && !e.handled && !e.cancelled) showError(err, e);
      } finally {
        btn.textContent = label;
        if (req === request) out.removeAttribute('aria-busy');
      }
    }
    const ask = button(change ? 'Ask AI to rework it' : 'Ask AI for recipes', 'primary', (btn) => run(btn, []));
    const other = button(change ? 'Another way' : 'Other recipes', 'secondary', (btn) => run(btn, moreSeen(seen.foods, seen.last)), { hidden: '' });
    const reset = () => { ++request; clear(out); clear(err); out.removeAttribute('aria-busy'); seen.foods = []; seen.last = []; other.hidden = true; };
    for (const el of [dish, makes]) el.addEventListener('change', reset);
    const what = button('What will be sent?', 'secondary', async (btn) => {
      clear(err);
      try { await showSent(await api.recipes(reqBody(), true), { trigger: btn }); } catch (e) { showError(err, e); }
    });
    body.append(...[
      h('p', { class: 'hint' }, change
        ? `The app sends the foods and amounts of “${name}” and where one serving does not fit. Its name, note, steps and link are never sent. Nothing is saved until you tap Save recipe.`
        : 'The app\'s rules choose the foods the AI may use, work out every number and fit each recipe to your targets. Nothing is saved until you tap Save recipe.'),
      picker,
      change ? null : field('Kind of dish', dish),
      change ? null : field('Makes', makes),
      h('div', { class: 'settings-actions' }, ask, other, what), err, out].filter(Boolean));
    foot.append(h('span', { class: 'spacer' }), closeButton(sheetEl));
    sheets.open(sheetEl, trigger);
  }
  function closeButton(dlg) {
    const b = h('button', { class: 'btn secondary', type: 'button' }, 'Close');
    b.addEventListener('click', () => dlg.close());
    return b;
  }

  // ---------------------------------------------------------------------------
  // Describe a meal
  // ---------------------------------------------------------------------------
  function openDescribe({ date = state.date, meal = state.addMealHint || util.defaultMealForNow(), trigger = null } = {}) {
    const { body, foot } = fillSheet(sheetEl, 'Describe a meal', 'AI splits what you write into foods; you pick each match from your food list.');
    const textId = uid('ai-text');
    const text = h('textarea', { id: textId, rows: '3', maxlength: '300', placeholder: 'e.g. 2 eggs, toast with butter, tea' });
    const mealName = uid('ai-describe-meal');
    const statusName = uid('ai-describe-status');
    const err = formError();
    const out = h('div', { class: 'ai-results', 'aria-live': 'polite' });
    const counter = h('span', { class: 'hint' }, '0 / 300');
    text.addEventListener('input', () => { counter.textContent = `${text.value.length} / 300`; });
    const payload = () => ({ text: text.value.trim(), meal: segValue(body, mealName), date });
    const find = button('Find foods', 'primary', async (btn) => {
      clear(err);
      if (!text.value.trim()) { showError(err, 'Write what you ate first.'); text.focus(); return; }
      btn.textContent = 'Asking…';
      try {
        const answer = await withConsent('text', () => api.parseMeal(payload()), () => api.parseMeal(payload(), true), btn, 'describe');
        if (answer) renderParsed(out, answer, () => ({ date, meal: segValue(body, mealName), status: segValue(body, statusName) }));
      } catch (e) { if (!e.handled && !e.cancelled) showError(err, e); } finally { btn.textContent = 'Find foods'; }
    });
    const what = button('What will be sent?', 'secondary', async (btn) => {
      clear(err);
      if (!text.value.trim()) { showError(err, 'Write what you ate first.'); text.focus(); return; }
      try {
        const dry = await api.parseMeal(payload(), true);
        if (dry.cards) { renderParsed(out, dry, () => ({})); return; } // a low or a red flag: nothing would be sent
        await showSent(dry, { trigger: btn });
      } catch (e) { showError(err, e); }
    });
    body.append(field('What did you eat, or plan to eat?', text), counter, mealPicker(mealName, meal),
      statusPicker(statusName, util.defaultStatusFor(date)), h('div', { class: 'settings-actions' }, find, what), err, out);
    foot.append(h('span', { class: 'spacer' }), closeButton(sheetEl));
    sheets.open(sheetEl, trigger, text);
  }
  function renderParsed(out, answer, where) {
    clear(out);
    out.append(...answerHead(answer), ...cardsBlock(answer));
    const items = answer.items || [];
    if (answer.cards || answer.status !== 'ok') return;
    if (!items.length) { out.append(h('p', { class: 'muted' }, 'No foods were found in that text.')); return; }
    const rows = [];
    for (const item of items) {
      const name = uid('ai-match');
      const servId = uid('ai-serv');
      const servings = h('input', { id: servId, type: 'number', inputmode: 'decimal', min: '0.25', max: '20', step: '0.25', value: '1' });
      const choices = h('div', { class: 'ai-choices' });
      item.matches.forEach((m, i) => {
        const id = uid('ai-m');
        const radio = h('input', { type: 'radio', name, id, value: String(m.food.id), checked: i === 0 });
        radio.addEventListener('change', () => { if (m.servings) servings.value = String(m.servings); });
        choices.append(h('label', { class: 'check', for: id }, radio, h('span', { class: 'check-text' }, m.food.name,
          h('span', { class: 'hint' }, `${m.food.serving_desc}${m.servings ? ` · about ${m.servings} serving${m.servings === 1 ? '' : 's'}` : ''}`))));
      });
      const noneId = uid('ai-m');
      choices.append(h('label', { class: 'check', for: noneId }, h('input', { type: 'radio', name, id: noneId, value: '', checked: !item.matches.length }),
        h('span', { class: 'check-text' }, item.matches.length ? 'None of these' : 'No match in your foods: search for it in Add')));
      if (item.matches[0] && item.matches[0].servings) servings.value = String(item.matches[0].servings);
      const words = UNIT_TEXT[item.unit];
      const unit = item.amount != null ? ` (${item.amount}${words ? ` ${item.amount === 1 ? words[0] : words[1]}` : ''})` : '';
      const fs = h('fieldset', { class: 'ai-parse-item field' }, h('legend', {}, `${item.text}${unit}`), choices, field('Servings', servings));
      rows.push({ fs, name, servings });
      out.append(fs);
    }
    const err = formError();
    const add = button('Add selected', 'primary', async (btn) => {
      clear(err);
      const w = where();
      const entries = [];
      for (const r of rows) {
        const picked = segValue(r.fs, r.name);
        if (!picked) continue;
        const s = Number(r.servings.value);
        if (!(s > 0 && s <= 20)) { showError(err, 'Servings must be between 0.25 and 20.'); r.servings.focus(); return; }
        entries.push({ date: w.date, meal: w.meal, food_id: Number(picked), servings: s, status: w.status || 'eaten' });
      }
      if (!entries.length) { showError(err, 'Pick at least one food.'); return; }
      await api.logBatch(entries);
      refreshDayCaches();
      btn.textContent = `Added ${entries.length}`;
      toast(`Added ${entries.length} ${entries.length === 1 ? 'food' : 'foods'} to ${MEAL_LABEL[w.meal].toLowerCase()}`);
    });
    out.append(err, h('div', { class: 'settings-actions' }, add));
    if (answer.notice) out.append(h('p', { class: 'muted small' }, answer.notice));
  }

  // ---------------------------------------------------------------------------
  // Photos
  // ---------------------------------------------------------------------------
  // Redraw on the device: JPEG, long edge ≤ 1600 px, no EXIF/GPS (note 02 R7). The server checks again.
  async function prepareJpeg(file) {
    let source;
    try {
      source = await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch (e) {
      source = await new Promise((resolve, reject) => {
        const img = new Image();
        const url = URL.createObjectURL(file);
        img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
        img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('This photo could not be opened. Try a JPEG or PNG.')); };
        img.src = url;
      });
    }
    const w0 = source.width || source.naturalWidth;
    const h0 = source.height || source.naturalHeight;
    if (!w0 || !h0) throw new Error('This photo could not be opened.');
    const scale = Math.min(1, PHOTO_EDGE / Math.max(w0, h0));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(w0 * scale));
    canvas.height = Math.max(1, Math.round(h0 * scale));
    canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
    if (source.close) source.close();
    return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('The photo could not be prepared.'))), 'image/jpeg', PHOTO_QUALITY));
  }

  function photoPicker(label, onPicked) {
    const id = uid('ai-photo');
    const input = h('input', { id, type: 'file', accept: 'image/*', capture: 'environment', class: 'ai-file' });
    const preview = h('img', { class: 'ai-photo', alt: '', hidden: true });
    let url = null;
    input.addEventListener('change', () => {
      if (url) URL.revokeObjectURL(url);
      const file = input.files && input.files[0];
      url = file ? URL.createObjectURL(file) : null;
      preview.hidden = !url;
      if (url) { preview.src = url; preview.alt = 'Your photo'; }
      onPicked(file || null);
    });
    sheetEl.addEventListener('close', () => { if (url) URL.revokeObjectURL(url); url = null; }, { once: true });
    return { el: h('div', { class: 'field' }, h('label', { for: id }, label), input), preview };
  }

  function photoFlow({ kind, title, sub, intro, buttonText, render, trigger }) {
    const { body, foot } = fillSheet(sheetEl, title, sub);
    let file = null;
    let jpeg = null;
    const err = formError();
    const out = h('div', { class: 'ai-results', 'aria-live': 'polite' });
    const picker = photoPicker('Take or choose a photo', (f) => { file = f; jpeg = null; clear(out); clear(err); });
    const ready = async () => {
      if (!file) { showError(err, 'Choose a photo first.'); return null; }
      if (!jpeg) jpeg = await prepareJpeg(file);
      return jpeg;
    };
    const go = button(buttonText, 'primary', async (btn) => {
      clear(err);
      btn.textContent = 'Reading…';
      out.setAttribute('aria-busy', 'true');
      try {
        const blob = await ready();
        if (!blob) return;
        const answer = await withConsent('photos', () => uploadPhoto(kind, blob, false), () => uploadPhoto(kind, blob, true), btn);
        if (answer) render(out, answer);
      } catch (e) { if (!e.handled && !e.cancelled) showError(err, e); } finally { btn.textContent = buttonText; out.removeAttribute('aria-busy'); }
    });
    const what = button('What will be sent?', 'secondary', async (btn) => {
      clear(err);
      try { const blob = await ready(); if (blob) await showSent(await uploadPhoto(kind, blob, true), { trigger: btn }); } catch (e) { showError(err, e); }
    });
    body.append(h('div', { class: 'ai-photo-layout' },
      h('div', { class: 'ai-photo-side' }, picker.preview),
      h('div', { class: 'ai-photo-main' }, intro, picker.el, h('div', { class: 'settings-actions' }, go, what), err, out)));
    foot.append(h('span', { class: 'spacer' }), closeButton(sheetEl));
    sheets.open(sheetEl, trigger, $('input[type="file"]', body));
  }

  const LABEL_FIELDS = NUTRIENTS.filter((n) => n.key !== 'fluid_ml');
  function openLabel({ trigger = null } = {}) {
    photoFlow({
      kind: 'label', title: 'Read a label', sub: 'AI copies the printed numbers; you check them and save.', buttonText: 'Read the label', trigger,
      intro: h('p', { class: 'hint' }, 'Photograph the Nutrition Facts panel and, if it fits, the ingredient list. Nothing is saved until you tap Save.'),
      render: renderLabel,
    });
  }
  function renderLabel(out, answer) {
    clear(out);
    out.append(...answerHead(answer));
    if (!answer.draft) return;
    const d = answer.draft;
    const fromPhoto = new Set(answer.from_photo || []);
    const estimated = new Set(answer.estimated || []);
    const tag = (key) => (estimated.has(key) ? h('span', { class: 'ai-tag est' }, 'estimated') : fromPhoto.has(key) ? h('span', { class: 'ai-tag' }, 'from photo') : null);
    const mk = (key, attrs) => h('input', { id: uid(`ai-l-${key}`), class: fromPhoto.has(key) || estimated.has(key) ? 'from-photo' : null, ...attrs });
    const name = mk('name', { type: 'text', maxlength: '120', value: d.name || '', required: true });
    const desc = mk('serving_desc', { type: 'text', maxlength: '60', value: d.serving_desc || '' });
    const grams = mk('serving_g', { type: 'number', inputmode: 'decimal', min: '0.1', max: '100000', step: '0.1', value: d.serving_g == null ? '' : String(d.serving_g), required: true });
    const nut = {};
    const grid = h('div', { class: 'form-grid nutrient-inputs' });
    for (const n of LABEL_FIELDS) {
      const v = d.nutrients[n.key];
      nut[n.key] = mk(n.key, { type: 'number', inputmode: 'decimal', min: '0', step: 'any', value: v == null ? '' : String(v), placeholder: 'not on the label' });
      grid.append(h('div', { class: 'field' }, h('label', { for: nut[n.key].id }, `${n.label} (${n.unit})`, ' ', tag(n.key)), nut[n.key]));
    }
    const ingId = uid('ai-l-ing');
    const ing = h('textarea', { id: ingId, rows: '3', maxlength: '4000', class: fromPhoto.has('ingredients_text') ? 'from-photo' : null }, d.ingredients_text || '');
    const err = formError();
    const checks = (answer.checks || []).map((c) => h('li', {}, c.message));
    out.append(
      note('caution', h('p', {}, h('strong', {}, answer.notice || 'Check every number against the label before saving.'))),
      checks.length ? h('ul', { class: 'ai-checks' }, checks) : null,
      h('div', { class: 'form-grid' },
        h('div', { class: 'field span-2' }, h('label', { for: name.id }, 'Food name ', tag('name')), name),
        field('Serving', desc), field('Serving weight (g)', grams)),
      h('fieldset', { class: 'field' }, h('legend', {}, 'Nutrients per serving'), grid),
      h('div', { class: 'field' }, h('label', { for: ingId }, 'Ingredients ', tag('ingredients_text')), ing,
        h('span', { class: 'hint' }, 'Saving checks this text for phosphate and potassium additives. Correct it if the AI misread it.')),
      err);
    const saved = h('div', { class: 'ai-saved' });
    const save = button('Save as my food', 'primary', async (btn) => {
      clear(err);
      KH.forms.clearFieldErrors(out);
      const body = { name: name.value.trim(), serving_desc: desc.value.trim() || '1 serving', serving_g: Number(grams.value), nutrients: {}, ingredients_text: ing.value.trim() || null, flags: [] };
      if (!body.name) { KH.forms.fieldError(name, 'Enter the food name.'); name.focus(); return; }
      if (!(body.serving_g > 0)) { KH.forms.fieldError(grams, 'Enter the serving weight in grams (it is on the label, often in brackets).'); grams.focus(); return; }
      for (const n of LABEL_FIELDS) { const v = nut[n.key].value.trim(); body.nutrients[n.key] = v === '' ? null : Number(v); }
      body.nutrients.fluid_ml = null;
      try {
        const food = await api.createFood(body);
        refreshDayCaches();
        btn.hidden = true;
        renderLogIt(saved, food);
      } catch (e) {
        if (e.handled || e.cancelled) return;
        for (const p of KH.forms.splitFieldErrors(e.detail)) {
          const target = p.field === 'name' ? name : p.field === 'serving_g' ? grams : null;
          if (target) KH.forms.fieldError(target, p.message); else showError(err, p.message);
        }
      }
    });
    out.append(h('div', { class: 'settings-actions' }, save), saved);
    const needs = (answer.needs || [])[0];
    if (needs === 'name') setTimeout(() => name.focus(), 0);
    else if (needs === 'serving_g') setTimeout(() => grams.focus(), 0);
  }
  function renderLogIt(box, food) {
    const mealName = uid('ai-log-meal');
    const statusName = uid('ai-log-status');
    const servId = uid('ai-log-serv');
    const servings = h('input', { id: servId, type: 'number', inputmode: 'decimal', min: '0.25', max: '20', step: '0.25', value: '1' });
    const warnings = h('div', { class: 'warnings' });
    ui.renderWarnings(warnings, food.warnings || []);
    const logIt = button('Log it', 'primary', async (btn) => {
      const s = Number(servings.value);
      if (!(s > 0)) { KH.forms.fieldError(servings, 'Enter how many servings.'); return; }
      await api.addEntry({ date: state.date, meal: segValue(box, mealName), food_id: food.id, servings: s, status: segValue(box, statusName) });
      refreshDayCaches();
      btn.textContent = 'Logged';
      toast(`${food.name} logged`);
    });
    clear(box).append(h('p', { class: 'setting-status' }, `Saved "${food.name}" to your foods.`), warnings,
      mealPicker(mealName, state.addMealHint || util.defaultMealForNow()), statusPicker(statusName, util.defaultStatusFor(state.date)),
      field('Servings', servings), h('div', { class: 'settings-actions' }, logIt));
  }

  function openPlate({ trigger = null } = {}) {
    photoFlow({
      kind: 'plate', title: 'Plate photo', sub: 'AI names the foods; the numbers come from your food list.', buttonText: 'Find the foods', trigger,
      intro: h('div', { class: 'settings-note caution ai-plate-banner', role: 'note' }, h('p', {}, h('strong', {}, 'AI estimate from a photo. In studies, portion estimates were off by about a third and too small for big plates. Weigh or measure when it matters, and do not dose insulin from this alone.'))),
      render: renderPlate,
    });
  }
  function renderPlate(out, answer) {
    clear(out);
    out.append(...answerHead(answer));
    if (answer.status !== 'ok') return;
    const banner = $('#sheet-ai .ai-plate-banner strong');
    if (answer.banner && banner) banner.textContent = answer.banner; // the server's wording, shown once
    const rows = [];
    for (const item of answer.items || []) {
      const tick = h('input', { type: 'checkbox', id: uid('ai-p-tick'), checked: item.ticked && item.candidates.length > 0 });
      const select = h('select', { id: uid('ai-p-food') }, item.candidates.map((c) => h('option', { value: String(c.food.id) }, `${c.food.name} (${c.food.serving_desc})`)));
      const servings = h('input', { id: uid('ai-p-serv'), type: 'number', inputmode: 'decimal', min: '0.25', max: '20', step: '0.25', value: String((item.candidates[0] && item.candidates[0].servings) || 1) });
      select.addEventListener('change', () => { const c = item.candidates[select.selectedIndex]; if (c && c.servings) servings.value = String(c.servings); });
      const head = check(`${item.name}${item.portion_text ? ` · ${item.portion_text}` : ''}`, tick, `AI was ${CONFIDENCE_TEXT[item.confidence] || item.confidence}`);
      const box = h('div', { class: 'ai-parse-item' }, head,
        item.candidates.length ? h('div', { class: 'form-grid' }, field('Food', select), field('Servings', servings))
          : h('p', { class: 'muted small' }, 'No match in your foods: search for it in Add.'));
      rows.push({ tick, select, servings, item });
      out.append(box);
    }
    const mealName = uid('ai-plate-meal');
    const statusName = uid('ai-plate-status');
    const err = formError();
    const add = button('Add selected', 'primary', async (btn) => {
      clear(err);
      const meal = segValue(out, mealName);
      const st = segValue(out, statusName);
      const entries = [];
      for (const r of rows) {
        if (!r.tick.checked || !r.item.candidates.length) continue;
        const s = Number(r.servings.value);
        if (!(s > 0 && s <= 20)) { showError(err, 'Servings must be between 0.25 and 20.'); r.servings.focus(); return; }
        entries.push({ date: state.date, meal, food_id: Number(r.select.value), servings: s, status: st });
      }
      if (!entries.length) { showError(err, 'Tick at least one food.'); return; }
      await api.logBatch(entries);
      refreshDayCaches();
      btn.textContent = `Added ${entries.length}`;
      toast(`Added ${entries.length} ${entries.length === 1 ? 'food' : 'foods'}`);
    });
    out.append(mealPicker(mealName, state.addMealHint || util.defaultMealForNow()), statusPicker(statusName, 'planned'), err,
      h('div', { class: 'settings-actions' }, add));
  }

  // ---------------------------------------------------------------------------
  // The Add view's AI buttons (#ai-add-slot)
  // ---------------------------------------------------------------------------
  async function renderAddSlot() {
    const slot = $('#ai-add-slot');
    if (!slot) return;
    const st = await status();
    clear(slot);
    if (!st || !st.enabled) { slot.hidden = true; return; }
    if (!st.available) {
      slot.append(h('p', { class: 'muted small' }, st.reason === 'not_opted_in' ? 'AI ideas are off for you. ' : `${st.message || 'AI is not available.'} `,
        st.reason === 'not_opted_in' ? h('button', { class: 'link-btn', type: 'button', onclick: () => KH.router.show('settings') }, 'Turn them on in Settings') : null));
      slot.hidden = false;
      return;
    }
    const f = st.features || {};
    const btns = [];
    if (f.next_meal) btns.push(h('button', { class: 'btn secondary', type: 'button', onclick: (e) => openIdeas({ trigger: e.currentTarget }) }, 'AI meal ideas'));
    if (f.parse_meal) btns.push(h('button', { class: 'btn secondary', type: 'button', onclick: (e) => openDescribe({ trigger: e.currentTarget }) }, 'Describe a meal (AI)'));
    if (f.label) btns.push(h('button', { class: 'btn secondary', type: 'button', onclick: (e) => openLabel({ trigger: e.currentTarget }) }, 'Read a label (AI)'));
    if (f.plate) btns.push(h('button', { class: 'btn secondary', type: 'button', onclick: (e) => openPlate({ trigger: e.currentTarget }) }, 'Plate photo (AI)'));
    slot.append(...btns);
    if (st.remaining_today != null) slot.append(h('span', { class: 'muted small ai-left' }, `${st.remaining_today} shared AI calls left today`));
    slot.hidden = !btns.length;
  }

  // ---------------------------------------------------------------------------
  // Settings → AI ideas
  // ---------------------------------------------------------------------------
  const isAdmin = () => !!(state.me && state.me.role === 'admin');

  // Renders overlap (the view is shown while an admin's AI switch change asks for a fresh one): each builds
  // its parts first and only the newest, after its last await, replaces the slot, so nothing shows twice.
  let settingsRender = 0;
  async function renderSettings() {
    const body = $('#set-ai-body');
    const slot = body && $('#set-ai-slot', body);
    if (!slot) return;
    const ticket = ++settingsRender;
    const current = () => ticket === settingsRender;
    for (const el of Array.from(body.children)) if (el !== slot) el.remove(); // the M1 placeholder text
    body.dataset.filled = '1';
    if (!slot.childElementCount) slot.append(h('p', { class: 'muted small' }, 'Loading…')); // a refresh keeps what is shown until it is ready
    if (MOCK) {
      clear(slot).append(h('p', { class: 'setting-status' }, h('span', { class: 'state-pill off' }, 'Not in the preview')),
        h('p', {}, `Optional AI ideas run in the installed app, with a provider your admin sets up and only after you opt in. The ${PREVIEW ? 'preview' : 'demo'} never sends anything to an AI service.`));
      return;
    }
    let me;
    try { me = await api.me(); } catch (err) {
      if (current()) clear(slot).append(h('p', { class: 'form-error' }, `Could not load this: ${err.detail || err.message}`));
      return;
    }
    if (!current()) return;
    const parts = [];
    if (me.enabled) parts.push(setupIntro());
    if (!me.enabled) {
      parts.push(h('p', { class: 'setting-status' }, h('span', { class: 'state-pill off' }, 'Off on this server')),
        h('p', {}, 'Optional AI help (meal ideas, describing a meal, reading a label from a photo) is switched off on this server. Nothing you log is sent to an AI service.'));
      if (isAdmin()) parts.push(h('p', { class: 'hint' }, 'Admins: switch "Optional AI ideas" on in Server administration → Server settings (or AI_ENABLED), and set up a provider under AI providers there (docs/ai.md).'));
    } else {
      parts.push(personalPart(me));
    }
    // v0.3.1: the shared providers are set up in Server administration (renderAdmin below), not here.
    if (isAdmin() && me.enabled) parts.push(h('p', { class: 'hint' }, 'Admins: the shared AI providers are set up in Server administration → AI providers.'));
    if (current()) slot.replaceChildren(...parts);
  }

  // "How AI help is set up": the three questions of docs/ai.md ("The setup in three questions") and the handbook's
  // "How the setup fits together", in a person's words (v0.3.1). Closed by default; the choices follow below it.
  function setupIntro() {
    const more = KH.learn ? KH.learn.link('pages', 'ai', { text: 'Learn: Optional AI' }) : null;
    return h('details', { class: 'settings-details ai-setup', id: 'set-ai-setup' },
      h('summary', {}, 'How AI help is set up: three questions'),
      h('ol', { class: 'ai-setup-list' },
        h('li', {}, h('b', {}, 'Which model answers? '),
          'Your admin chooses it: a model that runs at home, or a company\'s AI service. If your admin allows it, '
          + 'you can use your own key with a company\'s service instead (My own AI provider, below).'),
        h('li', {}, h('b', {}, 'What may it do? '),
          'Only what you switch on below: meal ideas, swaps and day plans made from foods the app\'s rules already allowed '
          + '(and checked again), turning what you describe into search words, reading a label photo into a draft you check '
          + 'and, if your admin allows it, naming the foods in a plate photo or answering a short question in Ask (the app checks '
          + 'every answer before you see it). It cannot give insulin or medicine doses. In Ask it can propose saving food or a recipe; '
          + 'by default nothing is saved until you press Save, and you can choose to trust it to save without asking if your admin allows that.'),
        h('li', {}, h('b', {}, 'Whose key pays, and who can read the request? '),
          'With the server\'s shared provider, the server\'s key pays and your admin can read what is sent. With your own key, '
          + 'your account at that company pays. Before you start, the consent step says where requests go, and '
          + '“What will be sent?” shows each request before it leaves.')),
      more ? h('p', { class: 'notes-learn' }, more) : null);
  }

  // ---------------------------------------------------------------------------
  // How much the person trusts the assistant to save (docs/dev/plans/assistant-step2.md "Part C")
  // ---------------------------------------------------------------------------
  const TRUST_CHOICES = [
    ['ask', 'Ask me before every save (recommended)',
      'Ask shows a card with what it would save. Nothing is saved until you press Save.'],
    ['conversation', 'Trust it for this conversation',
      'Ask saves food and recipes without asking while you chat. You turn this on in Ask; it ends when you start a new conversation or after 12 hours.'],
    ['always', 'Trust it always',
      'Ask saves food and recipes without asking, every time, until you change this.'],
  ];
  const TRUST_DONE = {
    ask: 'Ask will ask you before every save.',
    conversation: 'Ask can be trusted for one conversation at a time. Turn it on in Ask.',
    always: 'Ask will save food and recipes without asking you. Each save can be undone.',
  };
  const TRUST_WARNING = 'The assistant will save food and recipes without asking you first. It can pick the wrong food or the wrong amount.';
  const TRUST_POINTS = [
    'Every number still comes from the app. The low and emergency rules and the dose checks always stay on.',
    'You can undo each save, from the chat or from Today.',
    'Photo and label readings are always shown to you to check first.',
  ];
  const TRUST_SCOPE = {
    conversation: 'This lasts for one conversation: it ends when you start a new conversation or after 12 hours.',
    always: 'This stays on until you change it here.',
  };
  // The warning sheet. Resolves true only when "I understand, trust it" is pressed; closing it any other way (Keep asking
  // me, Escape, the close button) is false and changes nothing. The focus starts on the safe button.
  async function confirmTrust(kind, trigger) {
    if (!trustEl) return false;
    const { body, foot } = fillSheet(trustEl, 'Trust the assistant to save for you?',
      kind === 'always' ? 'Trust it always' : 'Trust it for this conversation');
    body.append(note('caution', h('p', {}, TRUST_WARNING)),
      h('ul', { class: 'trust-points' }, TRUST_POINTS.map((t) => h('li', {}, t))),
      h('p', { class: 'hint' }, TRUST_SCOPE[kind] || ''));
    const keep = h('button', { class: 'btn secondary', type: 'button' }, 'Keep asking me');
    keep.addEventListener('click', () => trustEl.close());
    const ok = h('button', { class: 'btn primary', type: 'button' }, 'I understand, trust it');
    foot.append(h('span', { class: 'spacer' }), keep, ok);
    return awaitChoice(trustEl, ok, trigger, keep);
  }

  // The choice in Settings → AI ideas. `save(patch, text)` is the section's own saver; the server writes the
  // activity-log row for every change. Shown only while the admin has the Ask chat on.
  function trustPart(me, save) {
    const current = () => (me.settings && me.settings.trust) || 'ask';
    const allowed = !!me.trusted_saves_allowed;
    const name = uid('ai-trust');
    const fs = h('fieldset', { class: 'field ai-trust', id: 'set-ai-trust' }, h('legend', {}, 'How much do you trust the assistant?'));
    fs.append(h('p', { class: 'hint' }, 'This is about Ask, the chat. Photo and label readings are always shown to you to check, whatever you choose.'));
    const radios = new Map();
    const show = () => { for (const [value, radio] of radios) radio.checked = value === current(); };
    for (const [value, label, hint] of TRUST_CHOICES) {
      const id = uid('ai-trust-opt');
      const radio = h('input', { type: 'radio', name, id, value, checked: value === current(), disabled: value !== 'ask' && !allowed });
      radio.addEventListener('change', async () => {
        if (!radio.checked || value === current()) return;
        if (value !== 'ask' && !(await confirmTrust(value, radio))) { show(); return; }
        try {
          await save({ trust: value }, TRUST_DONE[value]);
          me.settings.trust = value;
          if (KH.views.ask && typeof KH.views.ask.endTrust === 'function') KH.views.ask.endTrust(); // a changed choice ends any trusted conversation
        } catch (e) { /* shown by save */ }
        show();
      });
      radios.set(value, radio);
      fs.append(check(label, radio, hint));
    }
    if (!allowed) {
      const kept = TRUST_CHOICES.find((c) => c[0] === current())[1].replace(' (recommended)', '');
      fs.append(note('caution', h('p', {}, current() === 'ask'
        ? 'Your admin has not turned on trusted saves, so Ask always asks you before it saves.'
        : `Your admin turned trusted saves off, so Ask asks you before every save for now. Your choice (${kept}) is kept and applies again if your admin turns it back on.`)));
    }
    return fs;
  }

  // Server administration → AI providers (admins only). Overlapping renders keep only the newest, as above.
  let adminRender = 0;
  async function renderAdmin() {
    const body = $('#set-admin-ai-body');
    if (!body) return;
    if (!isAdmin()) { clear(body); return; }
    const ticket = ++adminRender;
    if (MOCK) {
      clear(body).append(h('p', {}, `AI providers are set up in the installed app. The ${PREVIEW ? 'preview' : 'demo'} never sends anything to an AI service.`));
      return;
    }
    // auth.require_two_step_admins (design note 17 §10): an admin without two-step sign-in gets 403 from every admin route; the
    // page above already says why (js/views/settings.js renderAdminFrame), so this part asks for nothing.
    const two = await request('GET', '/api/me/totp').catch(() => null);
    if (two && two.required && !two.enabled) { if (ticket === adminRender) clear(body); return; }
    if (!body.childElementCount) body.append(h('p', { class: 'muted small' }, 'Loading…'));
    const part = await adminPart();
    if (ticket === adminRender) body.replaceChildren(part);
  }
  // After a provider change both the person's choices (Settings) and the admin list change.
  function refreshProviders() {
    renderSettings().catch((e) => console.warn('AI settings:', e));
    renderAdmin().catch((e) => console.warn('AI providers:', e));
  }

  function personalPart(me) {
    const wrap = h('div', { class: 'settings-body' });
    const msg = statusMsg();
    const err = formError();
    const s = me.settings;
    const save = async (patch, text) => {
      clear(err);
      try { await api.updateMe(patch); forget(); msg.textContent = text; renderAddSlot(); } catch (e) { if (!e.handled) showError(err, e); throw e; }
    };
    const optId = uid('ai-opt');
    const opt = h('input', { type: 'checkbox', id: optId, checked: s.opt_in });
    opt.addEventListener('change', () => save({ opt_in: opt.checked }, opt.checked ? 'AI ideas are on for you.' : 'AI ideas are off for you. Nothing is sent.').catch(() => { opt.checked = !opt.checked; }));
    wrap.append(check('Use AI ideas', opt, 'Off by default. The app\'s own rules always run first and check every AI idea.'));

    // Provider choice. Once the admin has set up routing, which shared provider serves a feature is the admin's decision
    // (the lines below say where each runs); the person's choice is then the server's AI or their own provider.
    const routed = !!(me.routing && me.routing.mode === 'routed');
    const choices = [];
    if (routed && me.shared.length) choices.push(['auto', 'The server\'s AI', 'Your admin decides which AI each feature uses (below).']);
    else for (const p of me.shared) {
      choices.push([`shared:${p.id}`, `${p.label} (${p.host})`, `${p.policy}${p.usable ? '' : ' Switched off until its connection test passes.'}`]);
    }
    if (me.user_keys_allowed || me.own) choices.push(['own', 'My own provider and key', me.own ? `${me.own.label} (${me.own.host})` : 'Set it up below.']);
    if (choices.length) {
      const name = uid('ai-provider');
      const fs = h('fieldset', { class: 'field' }, h('legend', {}, 'Provider'));
      const current = routed ? (s.provider === 'own' ? 'own' : 'auto') : (s.provider === 'auto' && me.shared.length ? `shared:${me.shared[0].id}` : s.provider);
      for (const [value, label, hint] of choices) {
        const id = uid('ai-prov');
        const radio = h('input', { type: 'radio', name, id, value, checked: value === current });
        radio.addEventListener('change', () => save({ provider: value }, `Provider: ${label}.`).catch(() => {}));
        fs.append(check(label, radio, hint));
      }
      wrap.append(fs);
    } else {
      wrap.append(h('p', { class: 'muted' }, 'No AI provider is set up for your account yet.'));
    }

    const ageId = uid('ai-age');
    const age = h('input', { type: 'checkbox', id: ageId, checked: s.share_age_sex });
    age.addEventListener('change', () => save({ share_age_sex: age.checked }, age.checked ? 'Your age band and sex will be sent.' : 'Your age band and sex are not sent.').catch(() => { age.checked = !age.checked; }));
    wrap.append(check('Share my age band (10 years) and sex', age, 'Off by default. Your exact age and birth month are never sent.'));

    // The text for AI ideas moved to Settings → Meal guidance → Your food preferences (note 09 part B); same setting, ai.preferences.
    const moved = h('button', { class: 'link-btn', type: 'button' }, 'Settings → Meal guidance → Your food preferences');
    moved.addEventListener('click', () => { if (KH.guidance && typeof KH.guidance.openPreferences === 'function') KH.guidance.openPreferences(); });
    wrap.append(h('p', { class: 'hint ai-pref-moved', id: 'set-ai-pref-moved' }, 'Your food preferences for AI ideas are in ', moved, '.'));
    if (me.daily_limit) wrap.append(h('p', { class: 'muted small' }, `Shared AI calls left today: ${me.remaining_today} of ${me.daily_limit}.`));
    if (me.chat_enabled) wrap.append(trustPart(me, save));
    wrap.append(msg, err);
    const lines = KH.aiRouting ? KH.aiRouting.personLines(me.routing) : null;
    if (lines) wrap.append(lines);
    if (me.user_keys_allowed || me.own) wrap.append(ownProviderPart(me));
    wrap.append(consentsPart(me), activityPart());
    return wrap;
  }

  // "Food preferences for AI ideas" (setting ai.preferences, up to 200 characters): the field shown in Settings → Meal guidance → Your
  // food preferences (js/views/guidance.js asks for it), only when this server offers AI, like the rest of the AI choices. It saves
  // through the same call as before (PATCH /api/me/ai). Resolves to null in the demo and when AI is off.
  async function preferencesField() {
    if (MOCK) return null;
    let me;
    try { me = await api.me(); } catch (err) { return null; }
    if (!me || !me.enabled || !me.settings) return null;
    const msg = statusMsg();
    const err = formError();
    const id = uid('ai-pref');
    const pref = h('input', { type: 'text', id, maxlength: '200', value: me.settings.preferences || '', placeholder: 'e.g. vegetarian, no fish', 'aria-describedby': `${id}-hint` });
    const save = button('Save', 'secondary', async () => {
      clear(err);
      try { await api.updateMe({ preferences: pref.value.trim() }); forget(); msg.textContent = 'Preferences saved.'; } catch (e) { if (!e.handled) showError(err, e); }
    });
    pref.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); save.click(); } });
    return h('div', { class: 'field ai-pref' }, h('label', { for: id }, 'Food preferences for AI ideas'),
      h('div', { class: 'inline-row' }, pref, save), h('span', { class: 'hint', id: `${id}-hint` }, 'Up to 200 characters, sent with meal ideas when AI ideas are on for you (Settings → AI ideas). The app’s own suggestions do not read it.'), msg, err);
  }

  function ownProviderPart(me) {
    const own = me.own;
    const presets = me.presets;
    const box = h('details', { class: 'settings-details', open: !!own || me.settings.provider === 'own' });
    box.append(h('summary', {}, 'My own AI provider'));
    if (!me.user_keys_allowed) { box.append(note('caution', h('p', {}, 'Your admin has turned off personal AI providers. Yours is kept but not used.'))); }
    const presetId = uid('ai-own-preset');
    const presetSel = h('select', { id: presetId }, presets.map((p) => h('option', { value: p.name, selected: own ? own.preset === p.name : p.name === 'openai' }, p.label)));
    const model = h('input', { id: uid('ai-own-model'), type: 'text', maxlength: '200', value: own ? own.model : 'gpt-6-luna', autocomplete: 'off', spellcheck: 'false' });
    const vision = h('input', { id: uid('ai-own-vision'), type: 'text', maxlength: '200', value: own && own.vision_model ? own.vision_model : '', autocomplete: 'off', spellcheck: 'false', placeholder: 'empty: no photos' });
    const base = h('input', { id: uid('ai-own-base'), type: 'url', maxlength: '300', value: own ? own.base_url : '', placeholder: 'https://…/v1', autocomplete: 'off' });
    const baseField = field('Server address (https, port 443)', base, 'Only public https addresses are allowed.');
    const policy = h('p', { class: 'hint' });
    const sync = () => {
      const p = presets.find((x) => x.name === presetSel.value);
      baseField.hidden = !(p && p.kind === 'custom');
      policy.textContent = p ? p.policy : '';
      if (!own && p && p.default_model && !model.value) model.value = p.default_model;
    };
    presetSel.addEventListener('change', sync);
    const err = formError();
    const msg = statusMsg();
    const body = () => {
      const b = { preset: presetSel.value, model: model.value.trim(), vision_model: vision.value.trim() || null };
      if (!baseField.hidden) b.base_url = base.value.trim();
      return b;
    };
    const saveBtn = button(own ? 'Save' : 'Save provider', 'primary', async () => {
      clear(err);
      try { await api.setOwn(body()); forget(); msg.textContent = 'Saved.'; renderSettings(); } catch (e) { if (!e.handled && !e.cancelled) showError(err, e); }
    });
    box.append(field('Service', presetSel), policy, field('Model', model), field('Vision model (for photos)', vision), baseField);
    const keyStatus = own ? own.key : { set: false };
    const widget = KH.views.settings && KH.views.settings.keyWidget ? KH.views.settings.keyWidget({
      name: 'API key',
      // Read when a message is written, so it names the service chosen at that moment ("Saved, but OpenAI rejected …").
      get providerLabel() { const p = presets.find((x) => x.name === presetSel.value); return own ? own.label : (p ? p.label : 'Your AI service'); },
      status: keyStatus,
      addText: 'Add your key',
      removeText: 'Remove your AI key? AI calls with your own provider stop until you add one.',
      onSave: async (key, test) => {
        await api.setOwn({ ...body(), api_key: key });
        forget();
        if (!test) return null;
        const r = await api.probeOwn();
        const refused = (r.probe.errors || []).some((e) => /refused the key/.test(e));
        return { test: r.probe.ok ? 'ok' : refused ? 'rejected' : 'unreachable' };
      },
      onSaved: async (res, message) => { toast(message); renderSettings(); },
      onRemove: async () => { await api.setOwn({ ...body(), remove_key: true }); forget(); renderSettings(); },
    }) : null;
    if (widget) box.append(widget);
    const actions = h('div', { class: 'settings-actions' }, saveBtn);
    if (own) {
      actions.append(button('Test connection', 'secondary', async () => { clear(err); try { const r = await api.probeOwn(); msg.textContent = probeText(r.probe); } catch (e) { if (!e.handled) showError(err, e); } }));
      const remove = h('button', { class: 'btn danger', type: 'button' }, 'Remove my provider');
      remove.addEventListener('click', () => confirm.inline(actions, remove, {
        message: 'Remove your own AI provider and its key?', confirmText: 'Remove',
        onConfirm: async () => { await api.deleteOwn(); forget(); renderSettings(); return true; },
      }));
      actions.append(remove);
    }
    box.append(actions, msg, err);
    sync();
    return box;
  }

  function probeText(p) {
    if (!p) return '';
    if (p.ok) {
      const parts = [`Connection works (${p.structured === 'json_schema' ? 'structured JSON' : p.structured === 'json_object' ? 'JSON mode' : 'JSON in the prompt'})`];
      if (p.vision) parts.push(p.vision.ok ? 'photos work' : 'the vision model did not answer correctly');
      return `${parts.join('; ')}.${(p.warnings || []).length ? ` Note: ${p.warnings.join('; ')}.` : ''}`;
    }
    return `Connection test failed: ${(p.errors || []).join('; ') || 'unknown error'}.`;
  }

  function consentsPart(me) {
    const box = h('div', { class: 'settings-body' }, subtitle('What you agreed to send'));
    if (!me.consents.length) { box.append(h('p', { class: 'muted small' }, 'Nothing yet. You are asked before the first AI call to each server.')); return box; }
    const list = h('ul', { class: 'device-list' });
    for (const c of me.consents) {
      const row = h('li', { class: 'device' },
        h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, `${CONSENT_NAME[c.purpose] || 'Meal data'} → ${c.provider_label} (${c.host})`),
          h('span', { class: 'muted small' }, `Agreed ${util.fmtDateShort(c.at.slice(0, 10))}${c.current ? '' : ' · the policy text changed: you will be asked again'}${c.skip_preview ? '' : ' · request shown before each call'}`)));
      const btn = h('button', { class: 'btn secondary', type: 'button' }, 'Withdraw');
      btn.addEventListener('click', () => confirm.inline(btn, btn, {
        message: `Stop sending ${CONSENT_STOP[c.purpose] || 'meal data'} to ${c.host}?`, confirmText: 'Withdraw',
        onConfirm: async () => { await api.withdraw(c.provider_id, c.purpose); forget(); row.remove(); toast('Consent withdrawn'); return true; },
      }));
      row.append(btn);
      list.append(row);
    }
    box.append(list);
    return box;
  }

  function activityPart() {
    const box = h('details', { class: 'settings-details' });
    const list = h('div', { class: 'ai-activity' });
    let loaded = false;
    let before = null;
    const more = button('Show older', 'secondary', () => load());
    more.hidden = true;
    const load = async () => {
      const res = await api.audit(before);
      for (const ev of res.events) list.append(activityRow(ev));
      before = res.events.length ? res.events[res.events.length - 1].id : before;
      more.hidden = res.events.length < 20;
      if (!list.children.length) list.append(h('p', { class: 'muted small' }, 'No AI calls yet.'));
    };
    box.addEventListener('toggle', () => { if (box.open && !loaded) { loaded = true; load().catch(toastError); } });
    const del = h('button', { class: 'btn danger', type: 'button' }, 'Delete my AI history');
    const actions = h('div', { class: 'settings-actions' }, del);
    del.addEventListener('click', () => confirm.inline(actions, del, {
      message: 'Delete every record of what was sent to and received from AI for your account? Usage counts stay.', confirmText: 'Delete',
      onConfirm: async () => { await api.deleteAudit(); clear(list).append(h('p', { class: 'muted small' }, 'Your AI history was deleted.')); more.hidden = true; return true; },
    }));
    box.append(h('summary', {}, 'AI activity'),
      h('p', { class: 'hint' }, 'What each AI call sent and received, kept for a limited time; then only the time, server and outcome. Admins see only counts.'),
      list, more, actions);
    return box;
  }
  // A voice row holds no content at all: the host, the model, a length bucket and the outcome.
  function voiceRow(ev, when) {
    const verdict = ev.verdict_json || {};
    return h('details', { class: 'settings-details ai-event' },
      h('summary', {}, `${when} · Voice · ${ev.destination_host} · ${ev.status === 'ok' ? 'turned into text' : statusText(ev.status)}`),
      h('dl', { class: 'kv' },
        h('div', { class: 'kv-row' }, h('dt', {}, 'Model'), h('dd', {}, ev.model || '')),
        h('div', { class: 'kv-row' }, h('dt', {}, 'Length'), h('dd', {}, String(verdict.duration || 'unknown'))),
        h('div', { class: 'kv-row' }, h('dt', {}, 'Took'), h('dd', {}, `${((ev.latency_ms || 0) / 1000).toFixed(1)} s`))),
      h('p', { class: 'hint' }, 'Your recording and its words are not kept anywhere: not on this device, not on the server.'));
  }
  const FALLBACK_ROW = { asked: 'The cloud AI was asked next (the row above this one).', no_consent: 'The cloud AI was not asked: you have not agreed to send this there.',
    quota_exhausted: 'The cloud AI was not asked: today\'s shared AI calls were used up.' };
  function fallbackRowLine(verdict) {
    if (verdict && verdict.fallback_for) return 'A second request, sent because the local AI\'s answer did not pass the app\'s checks.';
    if (verdict && verdict.cloud_fallback) return `The answer did not pass the app\'s checks. ${FALLBACK_ROW[verdict.cloud_fallback] || 'The cloud AI was not asked.'}`;
    return null;
  }
  function activityRow(ev) {
    const when = `${util.fmtDateShort(ev.created_at.slice(0, 10))} ${ev.created_at.slice(11, 16)} UTC`;
    if (ev.feature === 'voice') return voiceRow(ev, when);
    const feature = FEATURE_TEXT[ev.feature.split(':')[0]] || ev.feature;
    const fallbackLine = fallbackRowLine(ev.verdict_json);
    return h('details', { class: 'settings-details ai-event' },
      h('summary', {}, `${when} · ${feature} · ${ev.destination_host} · ${statusText(ev.status)}`),
      h('dl', { class: 'kv' },
        h('div', { class: 'kv-row' }, h('dt', {}, 'Model'), h('dd', {}, ev.model || '')),
        h('div', { class: 'kv-row' }, h('dt', {}, 'Took'), h('dd', {}, `${((ev.latency_ms || 0) / 1000).toFixed(1)} s`)),
        h('div', { class: 'kv-row' }, h('dt', {}, 'Prompt version'), h('dd', {}, ev.prompt_version))),
      fallbackLine ? h('p', { class: 'hint ai-fallback-line' }, fallbackLine) : null,
      h('h4', { class: 'settings-minor' }, 'What the rules decided'), pre(ev.verdict_json),
      h('h4', { class: 'settings-minor' }, 'What was sent'), ev.request_json ? pre(ev.request_json) : h('p', { class: 'muted small' }, 'No longer kept.'),
      h('h4', { class: 'settings-minor' }, 'What came back (before the app\'s checks)'),
      ev.response_text ? [rawCaption(), pre(KH.aiguard.maskForDisplay(ev.response_text))]
        : h('p', { class: 'muted small' }, ev.feature === 'read_lab_report' ? 'Never kept: what the AI copied from a lab report is health data, so only the photo\'s fingerprint is recorded.' : 'No longer kept.'));
  }
  // The provider's raw answer was never shown as it is: the app kept only what passed its checks. Words the app
  // never shows (about insulin, doses, medicines…) are hidden in this copy too (KH.aiguard, the server's
  // blocklist); the stored record and the export keep the full text (v0.3.0 review L4).
  function rawCaption() {
    return h('p', { class: 'hint' }, 'The AI server\'s answer as it arrived, before the app checked it. The app used only the parts '
      + `that passed its checks. Words it never shows you, such as anything about insulin, doses or medicines, read ${KH.aiguard.MASK} `
      + 'here. This is not advice: ask your care team. Your data export keeps the full text.');
  }

  // ---- admin: providers, the private-host allowlist, usage ----
  async function adminPart() {
    const box = h('div', { class: 'settings-body ai-admin' }); // the card's title says "AI providers"
    let data;
    try { data = await api.providers(); } catch (err) {
      box.append(h('p', { class: 'form-error' }, `Could not load the providers: ${err.detail || err.message}`));
      return box;
    }
    if (!data.writable) box.append(note('caution', h('p', {}, 'Sign-in is off on this server (AUTH_MODE=none), so AI providers and AI settings can be set only with environment variables (docs/ai.md).')));
    try { box.append(KH.aiRouting.adminPart(await api.routing(), refreshProviders)); } catch (err) {
      box.append(h('p', { class: 'form-error' }, `Could not load the routing: ${err.detail || err.message}`));
    }
    try { box.append(KH.aiQuality.adminPart(await api.quality(), api.quality)); } catch (err) { // js/views/ai_quality.js: how well each AI is doing
      box.append(h('p', { class: 'form-error' }, `Could not load how well each AI is doing: ${err.detail || err.message}`));
    }
    const list = h('div', { class: 'setting-list' });
    if (!data.providers.length) list.append(h('p', { class: 'muted' }, 'No shared provider yet. Add one below, or set AI_PROVIDER (and AI_CLOUD_PROVIDER for a cloud AI) in the environment.'));
    for (const p of data.providers) list.append(providerRow(p, data));
    box.append(list);
    if (data.writable) box.append(h('details', { class: 'settings-details' }, h('summary', {}, 'Add a shared provider'), providerForm(null, data)));
    box.append(h('details', { class: 'settings-details' }, h('summary', {}, 'Private hosts (AI_PRIVATE_HOSTS)'),
      h('p', { class: 'hint' }, 'Shared providers may reach these private or local addresses; set in the environment only.'),
      data.private_hosts.length ? h('ul', {}, data.private_hosts.map((x) => h('li', {}, h('code', {}, x)))) : h('p', { class: 'muted small' }, 'None.'),
      data.deny_cidrs.length ? h('p', { class: 'hint' }, `Never contacted (AI_DENY_CIDRS): ${data.deny_cidrs.join(', ')}`) : null,
      data.proxy ? h('p', { class: 'hint' }, 'AI calls go through AI_HTTP_PROXY; personal server addresses are off.') : null));
    if (data.voice) box.append(voicePart(data.voice));
    box.append(usagePart());
    return box;
  }

  // The speech-to-text server for the Ask microphone: set in the environment, shown read-only (the key never), with a
  // test that sends one second of silence.
  function voicePart(v) {
    const box = h('details', { class: 'settings-details ai-voice-admin' }, h('summary', {}, 'Speech to text (voice input)'));
    if (!v.configured) {
      box.append(h('p', { class: 'hint' }, 'No transcription server is set. Voice input for Ask needs STT_BASE_URL and STT_MODEL in the environment (docs/ai.md, "Voice input").'));
      return box;
    }
    box.append(h('dl', { class: 'kv' },
      h('div', { class: 'kv-row' }, h('dt', {}, 'Server'), h('dd', {}, `${v.host} · ${v.local ? 'on your own network' : 'online service'}`)),
      h('div', { class: 'kv-row' }, h('dt', {}, 'Model'), h('dd', {}, v.model)),
      h('div', { class: 'kv-row' }, h('dt', {}, 'Key'), h('dd', {}, v.key_set ? 'set (never shown)' : 'none')),
      h('div', { class: 'kv-row' }, h('dt', {}, 'Limits'), h('dd', {}, `${v.max_seconds} seconds per recording${v.daily_limit ? `, ${v.daily_limit} per person per day` : ', no daily limit'}`)),
      h('div', { class: 'kv-row' }, h('dt', {}, 'Voice input'), h('dd', {}, v.enabled ? 'On' : 'Off (Server settings → Optional AI → Voice input for Ask)'))));
    box.append(h('p', { class: 'hint' }, 'Set with STT_BASE_URL, STT_MODEL and STT_API_KEY_FILE; the address follows the same rules as an AI provider (a private host must be listed in AI_PRIVATE_HOSTS). Recordings are transcribed and deleted, never stored.'));
    if (v.problem) box.append(note('caution', h('p', {}, `This server will be refused: ${v.problem}.`)));
    const msg = statusMsg();
    box.append(h('div', { class: 'settings-actions' }, button('Test transcription', 'secondary', async (btn) => {
      btn.textContent = 'Testing…';
      try {
        const r = (await api.probeVoice()).probe;
        msg.textContent = r.ok ? `The server answered a test recording in ${(r.latency_ms / 1000).toFixed(1)} s.` : `Test failed: ${r.message}`;
      } finally { btn.textContent = 'Test transcription'; }
    })), msg);
    return box;
  }

  function providerRow(p, data) {
    const badges = [];
    if (p.locked) badges.push(h('span', { class: 'badge status-pending_setup', title: p.env ? `Set by ${p.env}` : null }, 'Set by the server'));
    if (!p.enabled) badges.push(h('span', { class: 'badge status-disabled' }, 'Off'));
    if (p.disabled_reason) badges.push(h('span', { class: 'badge status-disabled' }, p.disabled_reason === 'hermes_tools' ? 'Hermes has tools enabled' : 'Hermes check failed'));
    const keyText = p.key.source === 'env' ? (p.key.set ? 'key from the environment' : 'no key') : p.key.status === 'unreadable' ? 'key unreadable: enter it again' : p.key.set ? `key set${p.key.last4 ? ` · ends in ${p.key.last4}` : ''}` : 'no key';
    const msg = statusMsg();
    const lastTest = (probe, at) => (probe ? `Last test${at ? ` ${util.fmtDateShort(at.slice(0, 10))}` : ''}: ${probeText(probe)}` : 'Not tested yet.');
    const testLine = h('p', { class: 'small' }, lastTest(p.probe, p.probed_at));
    const row = h('div', { class: 'setting-item' },
      h('div', { class: 'user-badges' }, h('span', { class: 'row-title' }, p.label), ...badges),
      h('p', { class: 'muted small' }, `${p.preset} · ${p.host} · ${p.model}${p.vision_model ? ` · photos: ${p.vision_model}` : ' · no photos'} · ${keyText}`),
      p.upstream ? h('p', { class: 'muted small' }, p.policy) : null, // a proxy that forwards to a company: what people are told before they agree
      testLine);
    const actions = h('div', { class: 'settings-actions' });
    actions.append(button('Test connection', 'secondary', async (btn) => {
      btn.textContent = 'Testing…';
      try {
        const r = await api.probeProvider(p.id);
        testLine.textContent = lastTest(r.provider.probe, r.provider.probed_at);
        msg.textContent = r.probe.error_body ? `The server said: ${r.probe.error_body}` : '';
      } finally { btn.textContent = 'Test connection'; }
    }));
    if (!p.locked && data.writable) {
      const edit = h('details', { class: 'settings-details' }, h('summary', {}, 'Edit'), providerForm(p, data));
      const remove = h('button', { class: 'btn danger', type: 'button' }, 'Delete');
      remove.addEventListener('click', () => confirm.inline(actions, remove, {
        message: `Delete ${p.label}? People using it lose AI until they choose another provider.`, confirmText: 'Delete',
        onConfirm: async () => { await api.deleteProvider(p.id); forget(); refreshProviders(); return true; },
      }));
      actions.append(remove);
      row.append(actions, msg, edit);
    } else {
      row.append(actions, msg);
    }
    return row;
  }

  function providerForm(p, data) {
    const form = h('div', { class: 'settings-form' });
    const presetSel = h('select', { id: uid('ai-adm-preset') }, data.presets.map((x) => h('option', { value: x.name, selected: p ? p.preset === x.name : x.name === 'ollama' }, x.label)));
    const label = h('input', { id: uid('ai-adm-label'), type: 'text', maxlength: '80', value: p ? p.label : '' });
    const base = h('input', { id: uid('ai-adm-base'), type: 'text', maxlength: '300', value: p ? p.base_url : '', autocomplete: 'off', spellcheck: 'false' });
    const model = h('input', { id: uid('ai-adm-model'), type: 'text', maxlength: '200', value: p ? p.model : '', autocomplete: 'off', spellcheck: 'false' });
    const vision = h('input', { id: uid('ai-adm-vision'), type: 'text', maxlength: '200', value: p && p.vision_model ? p.vision_model : '', autocomplete: 'off', spellcheck: 'false', placeholder: 'empty: no photos' });
    const key = h('input', { id: uid('ai-adm-key'), type: 'password', maxlength: '512', autocomplete: 'off', spellcheck: 'false', placeholder: p && p.key.set ? 'leave empty to keep the stored key' : '' });
    const removeKey = h('input', { type: 'checkbox', id: uid('ai-adm-rmkey') });
    const timeout = h('input', { id: uid('ai-adm-timeout'), type: 'number', min: '5', max: '600', step: '1', value: p && p.timeout_s != null ? String(p.timeout_s) : '' });
    const maxTokens = h('input', { id: uid('ai-adm-max'), type: 'number', min: '64', max: '32768', step: '1', value: p && p.max_tokens != null ? String(p.max_tokens) : '' });
    const ctx = h('input', { id: uid('ai-adm-ctx'), type: 'number', min: '1024', max: '2000000', step: '1', value: p && p.context_tokens != null ? String(p.context_tokens) : '' });
    const structured = h('select', { id: uid('ai-adm-struct') }, ['auto', 'json_schema', 'json_object', 'prompt'].map((v) => h('option', { value: v, selected: (p ? p.structured : 'auto') === v }, v)));
    const effort = h('select', { id: uid('ai-adm-effort') }, ['', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'].map((v) => h('option', { value: v, selected: (p && p.reasoning_effort ? p.reasoning_effort : '') === v }, v || 'preset default')));
    const enabled = h('input', { type: 'checkbox', id: uid('ai-adm-on'), checked: p ? p.enabled : true });
    const help = h('p', { class: 'hint' });
    const sync = () => {
      const x = data.presets.find((y) => y.name === presetSel.value);
      help.textContent = x ? `${x.policy}${x.key_help ? ` ${x.key_help}` : ''}${x.base_url ? ` Default address: ${x.base_url}.` : ' Enter the server address (…/v1).'}` : '';
      base.placeholder = x && x.base_url ? x.base_url : 'https://…/v1';
      if (x && x.default_model) model.placeholder = x.default_model;
    };
    presetSel.addEventListener('change', sync);
    const err = formError();
    const save = button(p ? 'Save changes' : 'Add provider', 'primary', async () => {
      clear(err);
      const num = (el) => (el.value.trim() === '' ? null : Number(el.value));
      const b = {
        preset: presetSel.value, model: model.value.trim() || model.placeholder, label: label.value.trim() || null,
        base_url: base.value.trim() || null, vision_model: vision.value.trim() || null, api_key: key.value.trim() || null,
        timeout_s: num(timeout), max_tokens: num(maxTokens), context_tokens: num(ctx), structured: structured.value,
        reasoning_effort: effort.value || null, enabled: enabled.checked,
      };
      if (p) b.remove_key = removeKey.checked;
      try {
        if (p) await api.updateProvider(p.id, b); else await api.createProvider(b);
        key.value = '';
        forget();
        refreshProviders();
      } catch (e) { if (!e.handled && !e.cancelled) showError(err, e); }
    });
    form.append(field('Service', presetSel), help, field('Name shown to people', label), field('Server address', base),
      field('Model', model), field('Vision model (for photos)', vision), field(p ? 'New key' : 'Key', key, 'Stored encrypted and never shown again.'),
      p && p.key.set ? check('Remove the stored key', removeKey) : null,
      h('details', { class: 'settings-details' }, h('summary', {}, 'Advanced'),
        h('div', { class: 'form-grid' }, field('Read timeout (s)', timeout), field('Max output tokens', maxTokens), field('Prompt budget (tokens)', ctx),
          field('JSON mode', structured), field('Reasoning effort', effort))),
      check('Offer it to people', enabled), err, h('div', { class: 'settings-actions' }, save));
    sync();
    return form;
  }

  function usagePart() {
    const box = h('details', { class: 'settings-details' });
    const list = h('div', { class: 'usage-list' });
    box.addEventListener('toggle', async () => {
      if (!box.open || list.dataset.loaded) return;
      list.dataset.loaded = '1';
      try {
        const res = await api.usage();
        if (!res.usage.length) list.append(h('p', { class: 'muted small ai-pad' }, 'No AI calls in the last 30 days.'));
        for (const u of res.usage) {
          list.append(h('div', { class: 'usage' }, h('span', {}, `${u.username || `#${u.user_id}`} · ${u.provider_id === 0 ? 'speech to text' : `provider ${u.provider_id} (${u.key_scope === 'own' ? 'own key' : 'shared'})`}`),
            h('span', { class: 'num' }, `${u.requests} calls`), h('span', { class: 'num muted small' }, `${u.prompt_tokens + u.completion_tokens} tokens`)));
        }
      } catch (err) { list.append(h('p', { class: 'form-error' }, err.detail || err.message)); }
    });
    box.append(h('summary', {}, 'AI usage (last 30 days)'), h('p', { class: 'hint' }, 'Counts only: admins never see what anyone sent.'), list);
    return box;
  }

  // ---------------------------------------------------------------------------
  // Wiring: render when Settings or Add is shown (no change to their modules needed)
  // ---------------------------------------------------------------------------
  function whenShown(viewId, fn) {
    const el = $(`#${viewId}`);
    if (!el) return;
    new MutationObserver(() => { if (!el.hidden && state.me) fn(); }).observe(el, { attributes: true, attributeFilter: ['hidden'] });
  }
  whenShown('view-settings', () => { renderSettings().catch(toastError); });
  whenShown('view-admin', () => { renderAdmin().catch(toastError); });
  whenShown('view-add', () => { renderAddSlot().catch((e) => console.warn(e)); });

  KH.ai = { status, forget, cardEl, confirmTrust, refreshDayCaches, askConsent, openIdeas, openRecipes, mountIdeas, openDescribe, openLabel, openPlate, renderSettings, renderAdmin, renderAddSlot, withConsent, showSent, api, prepareJpeg, preferencesField,
    uploadPhoto, fallbackNotes, droppedNotes }; // uploadPhoto, fallbackNotes: js/scan.js reads a label photo into Quick add
})();
