/* Kidney Diet Log — voice for the Ask screen (docs/assistant.md "Talking to the Ask screen", ARCHITECTURE.md "Voice input").

   Two separate things, both small, both optional, both off until the person turns them on:

   * A microphone button in the Ask input, only when the server says voice is available (GET /api/ai/status →
     features.voice: the admin set up a transcription server and switched voice on). Tap to record, tap again to stop
     (or it stops at 60 seconds); a visible "Recording" row shows the time; the recording is sent to the server's
     POST /api/ai/transcribe, which forwards it to the transcription server and returns text. The TEXT GOES INTO THE
     QUESTION BOX for the person to read and edit. It is never sent to the AI automatically: only the Send button does.
     The recording lives in memory only (no file, no playback, no storage) and is dropped as soon as it is sent. The
     first use asks for consent first ("Your recording is sent to <host> to turn it into text, then deleted.").
   * "Read answers aloud", a per-device switch (localStorage, optional) that speaks the checked answer text with a voice
     built into this device (speechSynthesis voices with localService === true only; a network voice would send the
     answer to the browser maker, so it is never used). Without such a voice the switch is hidden with a note.

   What this file never does: use the browser's speech recognition (Chrome sends that audio to Google, Safari to Apple,
   outside the owner's control: the recording goes only to the server's transcription host), load anything from another
   origin, or put text into the page as HTML (textContent / text nodes only). No inline scripts or styles (CSP). */
(() => {
  'use strict';
  const KH = window.KH;
  const { $, h, s } = KH;
  const { MOCK } = KH.flags;

  const MAX_MS = 60000; // the server's limit; the recording stops by itself here
  const MIN_BYTES = 400; // anything smaller holds no speech
  const MAX_CHARS = 2000; // the question box's limit
  const BITRATE = 32000; // speech: 60 s is about 240 KB, far under the server's limit
  const TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg', 'audio/mp4']; // preference order
  const SENDABLE = new Set(['audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav']); // what the server accepts
  const READ_KEY = 'kh.ask.readAloud';
  const SPOKEN_KINDS = new Set(['answer', 'confirm_save', 'treat_low', 'get_help_now']); // the checked text (or the app's fixed save prompt), never withheld/error notices
  const LINK_TEXT = /(?:https?:\/\/|www\.)\S+|\/learn\/[A-Za-z0-9_\-/#]+|[^\s@]+@[^\s@]+\.[a-z]{2,}/gi;

  const els = {};
  let built = false;
  let info = null; // GET /api/ai/status → voice
  let state = 'idle'; // idle | recording | sending
  let session = null; // { stream, recorder, chunks, type, started, timer, stopAt, discard }
  let abort = null; // AbortController of the upload
  let voices = [];
  let voiceTimer = null;
  let chatAvailable = false;
  let watching = false; // the speech engine's voiceschanged listener is set

  // ---------------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------------
  const supportsRecording = () => !!(navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === 'function'
    && typeof window.MediaRecorder === 'function');
  const clock = (ms) => { const sec = Math.floor(ms / 1000); return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`; };
  function say(text) { const live = $('#ask-live'); if (live) live.textContent = text; }
  function line(text, tone) {
    els.line.textContent = text || '';
    els.line.hidden = !text;
    els.line.classList.toggle('ask-voice-problem', tone === 'problem');
  }
  function stored() { try { return localStorage.getItem(READ_KEY) === '1'; } catch (e) { return false; } }
  function store(on) { try { if (on) localStorage.setItem(READ_KEY, '1'); else localStorage.removeItem(READ_KEY); } catch (e) { /* storage unavailable */ } }

  function micIcon() {
    const svg = s('svg', { class: 'ask-mic-icon', viewBox: '0 0 24 24', focusable: 'false', 'aria-hidden': 'true' });
    svg.append(s('rect', { class: 'ask-mic-body', x: 9, y: 2.5, width: 6, height: 12, rx: 3 }));
    svg.append(s('path', { class: 'ask-mic-stand', d: 'M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3.5M8.5 21.5h7', fill: 'none' }));
    return svg;
  }

  // ---------------------------------------------------------------------------
  // The page pieces (built once, inside the Ask input)
  // ---------------------------------------------------------------------------
  function build() {
    if (built) return true;
    const dock = $('#ask-composer');
    const row = dock && dock.querySelector('.ask-composer');
    const input = $('#ask-input');
    const sendBtn = $('#ask-send');
    const note = $('#ask-note');
    if (!dock || !row || !input || !sendBtn || !note) return false;
    els.input = input;
    els.send = sendBtn;
    // One button whose name changes with what it will do (an ARIA toggle would repeat the name and add "pressed").
    els.mic = h('button', { class: 'btn secondary ask-mic', type: 'button', id: 'ask-mic', hidden: true,
      'aria-label': 'Record your question', title: 'Record your question' }, micIcon());
    els.mic.addEventListener('click', () => onMic());
    row.insertBefore(els.mic, sendBtn);

    // The recording row: the visible "recording" indicator, the time and Discard / Cancel.
    els.bar = h('div', { class: 'ask-voice-bar', hidden: true, role: 'group', 'aria-label': 'Voice input' });
    els.dot = h('span', { class: 'ask-rec-dot', 'aria-hidden': 'true' });
    els.what = h('span', { class: 'ask-voice-what' }, 'Recording');
    els.time = h('span', { class: 'ask-rec-time', 'aria-hidden': 'true' }, '');
    els.cancel = h('button', { class: 'btn secondary ask-voice-cancel', type: 'button' }, 'Discard');
    els.cancel.addEventListener('click', () => cancelAll('Nothing was kept.'));
    els.bar.append(els.dot, els.what, els.time, els.cancel);
    dock.insertBefore(els.bar, row);

    // One line for what happened or what to do next (errors included).
    els.line = h('p', { class: 'hint ask-line ask-voice-line', id: 'ask-voice-line', role: 'status', hidden: true });
    note.after(els.line);

    // Read aloud: a per-device switch, or a note when this device has no voice of its own.
    els.readBox = h('div', { class: 'ask-voice-opts', hidden: true });
    els.readInput = h('input', { type: 'checkbox', id: 'ask-read-aloud' });
    els.readInput.addEventListener('change', () => onReadToggle());
    els.readLabel = h('label', { class: 'check ask-read-label', for: 'ask-read-aloud' }, els.readInput,
      h('span', { class: 'check-text' }, 'Read answers aloud', h('span', { class: 'hint' }, 'Uses a voice built into this device. Nothing is sent anywhere.')));
    els.stopReading = h('button', { class: 'btn secondary ask-stop-reading', type: 'button', hidden: true }, 'Stop reading');
    els.stopReading.addEventListener('click', () => stopSpeaking());
    els.readNote = h('p', { class: 'hint ask-line ask-read-note', hidden: true }, 'Reading answers aloud is off: this device has no voice of its own, and the app will not use an online one.');
    els.readBox.append(els.readLabel, els.stopReading, els.readNote);
    els.line.after(els.readBox);

    // Stop what is happening when the person acts elsewhere.
    els.send.addEventListener('click', () => stopSpeaking());
    els.input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) stopSpeaking(); });
    const fresh = $('#ask-new');
    if (fresh) fresh.addEventListener('click', () => stopSpeaking());
    const view = $('#view-ask');
    if (view && typeof MutationObserver === 'function') {
      new MutationObserver(() => { if (view.hidden) { cancelAll(''); stopSpeaking(); } }).observe(view, { attributes: true, attributeFilter: ['hidden'] });
    }
    document.addEventListener('visibilitychange', () => { if (document.hidden) { cancelAll('Recording stopped because you left the page. Nothing was kept.'); stopSpeaking(); } });
    window.addEventListener('pagehide', () => { cancelAll(''); stopSpeaking(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && state !== 'idle') cancelAll('Nothing was kept.'); });
    built = true;
    return true;
  }

  function setState(next) {
    state = next;
    const recording = next === 'recording';
    const sending = next === 'sending';
    els.bar.hidden = next === 'idle';
    els.dot.hidden = !recording;
    els.cancel.textContent = sending ? 'Cancel' : 'Discard';
    els.what.textContent = recording ? 'Recording. Tap the microphone to stop.' : (sending ? 'Turning your recording into text…' : '');
    els.mic.classList.toggle('recording', recording);
    const label = recording ? 'Stop recording' : 'Record your question';
    els.mic.setAttribute('aria-label', label);
    els.mic.title = label;
    els.mic.disabled = sending || (!supportsRecording() && !recording);
    if (!recording) els.time.textContent = '';
  }

  // ---------------------------------------------------------------------------
  // Showing and hiding: the Ask screen calls sync() whenever it learns what the server offers
  // ---------------------------------------------------------------------------
  async function sync(chatOn) {
    chatAvailable = !!chatOn;
    if (MOCK || !build()) return;
    let status = null;
    try { status = await KH.ai.status(); } catch (err) { /* the switches stay as they were */ }
    const voiceOn = chatAvailable && !!(status && status.features && status.features.voice && status.voice);
    info = voiceOn ? status.voice : null;
    if (!voiceOn && state !== 'idle') cancelAll('');
    els.mic.hidden = !voiceOn;
    if (voiceOn) {
      setState(state);
      if (!supportsRecording() && state === 'idle') line(unsupportedText());
    } else if (state === 'idle') {
      line('');
    }
    refreshVoices();
    renderRead();
  }
  const unsupportedText = () => (window.isSecureContext === false
    ? 'Voice input needs a secure (https) connection. Type your question instead.'
    : 'This browser cannot record audio. Type your question instead.');

  // ---------------------------------------------------------------------------
  // Recording
  // ---------------------------------------------------------------------------
  function pickType() {
    if (typeof MediaRecorder.isTypeSupported !== 'function') return '';
    for (const t of TYPES) { try { if (MediaRecorder.isTypeSupported(t)) return t; } catch (e) { /* try the next */ } }
    return '';
  }

  function releaseStream(stream) {
    if (!stream) return;
    for (const track of stream.getTracks()) { try { track.stop(); } catch (e) { /* already stopped */ } }
  }

  async function onMic() {
    if (state === 'recording') { stopRecording(); return; }
    if (state !== 'idle' || !info) return;
    if (!supportsRecording()) {
      line(unsupportedText(), 'problem');
      return;
    }
    line('');
    // Consent comes first: nothing is recorded until the person has agreed to send a recording to this host.
    if (!info.consent) {
      let agreed = false;
      try { agreed = await KH.ai.askConsent(info.request, null, els.mic); } catch (err) { KH.toastError(err); return; }
      if (!agreed) { line('Nothing was recorded. You can still type your question.'); return; }
      try { const fresh = await KH.ai.status(true); info = (fresh && fresh.voice) || info; } catch (err) { /* the next send tells */ }
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      line(micProblem(err), 'problem');
      return;
    }
    const type = pickType();
    let recorder;
    try {
      recorder = new MediaRecorder(stream, { ...(type ? { mimeType: type } : {}), audioBitsPerSecond: BITRATE });
    } catch (err) {
      releaseStream(stream);
      line('This browser could not start recording. Type your question instead.', 'problem');
      return;
    }
    const mine = { stream, recorder, chunks: [], type: recorder.mimeType || type || '', started: Date.now(), timer: null, discard: false };
    session = mine;
    recorder.addEventListener('dataavailable', (e) => { if (e.data && e.data.size) mine.chunks.push(e.data); });
    recorder.addEventListener('stop', () => finishRecording(mine));
    recorder.addEventListener('error', () => { mine.discard = true; line('Recording failed. Type your question instead.', 'problem'); try { recorder.stop(); } catch (e) { finishRecording(mine); } });
    try { recorder.start(); } catch (err) { releaseStream(stream); session = null; line('This browser could not start recording. Type your question instead.', 'problem'); return; }
    setState('recording');
    say('Recording started. Tap the microphone again to stop.');
    tick(mine);
    mine.timer = setInterval(() => tick(mine), 250);
  }

  function micProblem(err) {
    const name = err && err.name;
    if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') {
      return 'The microphone is blocked for this site. Allow it in your browser\'s settings, or type your question.';
    }
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return 'No microphone was found. Type your question instead.';
    if (name === 'NotReadableError') return 'The microphone is in use by another app. Type your question instead.';
    return 'The microphone could not be opened. Type your question instead.';
  }

  function tick(mine) {
    if (session !== mine) return;
    const view = $('#view-ask');
    if (document.hidden || (view && view.hidden)) { cancelAll('Recording stopped because you left the page. Nothing was kept.'); return; }
    const elapsed = Date.now() - mine.started;
    els.time.textContent = `${clock(Math.min(elapsed, MAX_MS))} of ${clock(MAX_MS)}`;
    if (elapsed >= MAX_MS) stopRecording();
  }

  function stopRecording() {
    if (!session || state !== 'recording') return;
    const mine = session;
    clearInterval(mine.timer);
    mine.timer = null;
    try { if (mine.recorder.state !== 'inactive') mine.recorder.stop(); else finishRecording(mine); } catch (err) { finishRecording(mine); }
  }

  // The recorder has stopped (the "stop" event): release the microphone at once, then send or drop the audio.
  async function finishRecording(mine) {
    if (session !== mine) return;
    clearInterval(mine.timer);
    releaseStream(mine.stream);
    session = null;
    const seconds = Math.min(60, Math.max(0, Math.round((Date.now() - mine.started) / 1000)));
    const type = (mine.recorder.mimeType || mine.type || (mine.chunks[0] && mine.chunks[0].type) || '').split(';')[0].trim().toLowerCase();
    const blob = mine.discard ? null : new Blob(mine.chunks, { type: type || 'application/octet-stream' });
    mine.chunks.length = 0;
    if (!blob) { setState('idle'); return; }
    if (blob.size < MIN_BYTES) { setState('idle'); line('Nothing was recorded. Try again, closer to the microphone.', 'problem'); say('Nothing was recorded.'); return; }
    if (!SENDABLE.has(type)) { setState('idle'); line('This browser records in a format the app cannot send. Type your question instead.', 'problem'); return; }
    if (info && blob.size > info.max_bytes) { setState('idle'); line('The recording is too long to send. Try a shorter one.', 'problem'); return; }
    await upload(blob, type, seconds);
  }

  function cancelAll(message) {
    if (session) {
      const mine = session;
      mine.discard = true;
      clearInterval(mine.timer);
      mine.chunks.length = 0;
      releaseStream(mine.stream);
      session = null;
      try { if (mine.recorder.state !== 'inactive') mine.recorder.stop(); } catch (e) { /* already stopped */ }
    }
    if (abort) { abort.abort(); abort = null; }
    if (state !== 'idle') { setState('idle'); say(message || ''); }
    if (message) line(message);
  }

  // ---------------------------------------------------------------------------
  // Sending the recording; the text goes into the box and nowhere else
  // ---------------------------------------------------------------------------
  async function post(blob, type, seconds, signal) {
    let res;
    try {
      res = await fetch(`/api/ai/transcribe?seconds=${seconds}`, {
        method: 'POST',
        headers: { 'Content-Type': type, Accept: 'application/json', 'X-Requested-With': KH.brand.csrfHeaderValue },
        body: blob,
        credentials: 'same-origin',
        signal,
      });
    } catch (e) {
      if (e && e.name === 'AbortError') throw Object.assign(new Error('cancelled'), { cancelled: true });
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

  async function upload(blob, type, seconds) {
    setState('sending');
    say('Turning your recording into text.');
    abort = new AbortController();
    const mine = abort;
    let result = null;
    let failure = null;
    try {
      try {
        result = await post(blob, type, seconds, mine.signal);
      } catch (err) {
        if (err.status === 409 && err.data && err.data.consent_required && !mine.signal.aborted) {
          // The host or the wording changed since the person agreed: ask again, then send the same recording once more.
          if (!(await KH.ai.askConsent(err.data.consent, null, els.mic))) throw Object.assign(new Error('declined'), { declined: true });
          result = await post(blob, type, seconds, mine.signal);
        } else {
          throw err;
        }
      }
    } catch (err) {
      failure = err;
    }
    blob = null; // the recording is not kept
    if (abort === mine) abort = null;
    if (failure && failure.cancelled) return; // cancelAll() has already put the screen back
    setState('idle');
    if (failure && failure.handled) return; // signed out: the sign-in screen is showing
    if (failure && failure.declined) { line('Nothing was sent. You can still type your question.'); return; }
    if (failure) { problem(failure); return; }
    const text = result && typeof result.text === 'string' ? result.text.trim() : '';
    if (!text) { line('No words were heard. Try again, closer to the microphone, or type your question.', 'problem'); say('No words were heard.'); return; }
    put(text);
    try { const fresh = await KH.ai.status(true); info = (fresh && fresh.voice) || info; } catch (err) { /* only the remaining count */ }
  }

  function problem(err) {
    const status = err && err.status;
    if (status === 404) { line('Voice input is switched off on this server.', 'problem'); if (KH.views.ask) KH.views.ask.refreshTab(); return; }
    if (status === 413) { line('The recording is too long to send. Try a shorter one.', 'problem'); return; }
    if (status === 400 || status === 415) { line('The app could not use that recording. Try again, or type your question.', 'problem'); return; }
    line((err && (err.detail || err.message)) || 'The recording could not be turned into text. Type your question instead.', 'problem');
  }

  // The transcript goes into the question box, after anything already typed, for the person to read and edit.
  // Nothing here presses Send: only the person does.
  function put(text) {
    const before = els.input.value.replace(/\s+$/, '');
    els.input.value = (before ? `${before} ${text}` : text).slice(0, MAX_CHARS);
    els.input.dispatchEvent(new Event('input', { bubbles: true }));
    els.input.focus();
    const end = els.input.value.length;
    try { els.input.setSelectionRange(end, end); } catch (e) { /* not supported here */ }
    line('Check the words, fix anything wrong, then press Send. Nothing has been sent to the AI.');
    say('The words are in the question box. Check them, then press Send.');
  }

  // ---------------------------------------------------------------------------
  // Read aloud: voices built into this device only
  // ---------------------------------------------------------------------------
  const synth = () => (typeof window.speechSynthesis === 'object' && window.speechSynthesis && typeof window.SpeechSynthesisUtterance === 'function' ? window.speechSynthesis : null);

  function localVoices() {
    const engine = synth();
    if (!engine) return [];
    let all = [];
    try { all = engine.getVoices() || []; } catch (e) { all = []; }
    return all.filter((v) => v && v.localService === true);
  }

  function pickVoice() {
    if (!voices.length) return null;
    const wanted = String(document.documentElement.lang || navigator.language || 'en').toLowerCase().split('-')[0];
    return voices.find((v) => String(v.lang || '').toLowerCase().startsWith(wanted) && v.default)
      || voices.find((v) => String(v.lang || '').toLowerCase().startsWith(wanted))
      || voices.find((v) => v.default) || voices[0];
  }

  function refreshVoices() {
    const engine = synth();
    voices = localVoices();
    if (engine && !watching && typeof engine.addEventListener === 'function') {
      watching = true;
      engine.addEventListener('voiceschanged', () => { voices = localVoices(); renderRead(); });
    }
    if (!voices.length && engine && !voiceTimer) {
      // Some browsers list their voices a moment later (voiceschanged); decide after a short wait.
      voiceTimer = setTimeout(() => { voiceTimer = null; voices = localVoices(); renderRead(true); }, 1500);
    }
  }

  function renderRead(settled) {
    if (!built) return;
    const waiting = !!voiceTimer && !voices.length && !settled;
    const show = chatAvailable && !MOCK;
    els.readBox.hidden = !show || waiting;
    if (!show || waiting) return;
    const has = voices.length > 0;
    els.readLabel.hidden = !has;
    els.readNote.hidden = has;
    els.readInput.checked = has && stored();
    if (!has) stopSpeaking();
  }

  function onReadToggle() {
    store(els.readInput.checked);
    if (!els.readInput.checked) stopSpeaking();
  }

  function stopSpeaking() {
    const engine = synth();
    if (engine) { try { engine.cancel(); } catch (e) { /* nothing to cancel */ } }
    if (els.stopReading) els.stopReading.hidden = true;
  }

  // The text that may be spoken: the checked answer only, no links, handbook paths or addresses.
  function spokenText(answer) {
    if (!answer || !SPOKEN_KINDS.has(answer.kind) || typeof answer.text !== 'string') return '';
    return answer.text.replace(LINK_TEXT, ' ').replace(/\s+/g, ' ').trim();
  }

  function speak(answer) {
    if (MOCK || !built || !els.readInput.checked) return;
    const engine = synth();
    const voice = pickVoice();
    const text = spokenText(answer);
    if (!engine || !voice || !text) return;
    stopSpeaking();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = voice; // always one of this device's own voices
    utterance.lang = voice.lang || utterance.lang;
    const done = () => { els.stopReading.hidden = true; };
    utterance.onend = done;
    utterance.onerror = done;
    els.stopReading.hidden = false;
    try { engine.speak(utterance); } catch (e) { done(); }
  }

  // Nothing is built, requested or shown until the Ask screen calls sync(): a page without Ask never touches the
  // microphone or the speech engine.
  KH.askVoice = { sync, speak, stop: stopSpeaking, cancel: () => cancelAll('') };
})();
