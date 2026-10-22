"""Voice for the Ask screen, the browser side (``app/static/js/views/ask-voice.js``, ``css/ask-voice.css``, the two hook
lines in ``ask.js``, the voice text in ``ai.js``) against the contract of ``POST /api/ai/transcribe``.

What these tests keep from drifting (the behaviour itself is checked in Chromium with ``tools/e2e/ask_voice.py``):

* the browser's own speech recognition is never used (Chrome sends that audio to Google, Safari to Apple: the recording
  goes only to the server's transcription host);
* the transcript goes into the question box and is never sent by the code; only the person's Send does that;
* read aloud uses only voices built into the device (``localService === true``);
* no inline script or style, no HTML from text, no storage of audio, no request to another origin, the consent sheet
  before the first recording, the microphone released after every recording, the 60-second stop."""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
ASK_JS = (STATIC / "js" / "views" / "ask.js").read_text(encoding="utf-8")
AI_JS = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
VOICE_JS = (STATIC / "js" / "views" / "ask-voice.js").read_text(encoding="utf-8")
VOICE_CSS = (STATIC / "css" / "ask-voice.css").read_text(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]

# The browser's recognition API under every name it has had. Case-insensitive on purpose: `SpeechRecognition`,
# `webkitSpeechRecognition`, `SPEECHRECOGNITION`, the grammar and event classes that go with it.
RECOGNITION = re.compile(r"speech\s*recognition|speechgrammar|speechrecognitionevent|webkitspeech", re.IGNORECASE)
IDENTIFIER = re.compile(r"speechrecognition|speechgrammar|webkitspeech", re.IGNORECASE)  # no whitespace: a name, even in a comment


def code_without_comments(js: str) -> str:
    """The script without ``/* */`` and ``//`` comments (so a sentence in a comment is not mistaken for code)."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    return "\n".join(re.sub(r"(?<![:'\"\\])//.*$", "", line) for line in js.splitlines())


VOICE_CODE = code_without_comments(VOICE_JS)


# --------------------------------------------------------------------------- #
# The files are in the shell, in the right order, with only two hooks in ask.js
# --------------------------------------------------------------------------- #


def test_the_files_are_in_the_shell_and_load_after_ask_js_and_before_main_js():
    assert '<link rel="stylesheet" href="css/ask-voice.css">' in INDEX
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/ask-voice.js") == scripts.index("js/views/ask.js") + 1
    assert scripts.index("js/views/ask-voice.js") < scripts.index("js/main.js")
    assert "'/js/views/ask-voice.js'," in SW and "'/css/ask-voice.css'," in SW  # the offline shell holds them too


def test_ask_js_has_only_the_two_hook_lines():
    hooks = [line.strip() for line in ASK_JS.splitlines() if "askVoice" in line]
    assert len(hooks) == 2, hooks
    assert hooks[0].startswith("if (KH.askVoice) KH.askVoice.sync(available);")
    assert hooks[1].startswith("if (KH.askVoice) KH.askVoice.speak(answer);")
    assert "speechSynthesis" not in ASK_JS and "MediaRecorder" not in ASK_JS


# --------------------------------------------------------------------------- #
# Never the browser's speech recognition
# --------------------------------------------------------------------------- #


def test_the_browsers_speech_recognition_is_never_referenced_anywhere_in_the_shipped_page():
    offenders = []
    for path in sorted(STATIC.rglob("*")):
        if not (path.is_file() and path.suffix in {".js", ".mjs", ".html", ".css", ".json", ".webmanifest", ".svg"}):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # the identifier, in code or in a comment, in any case; and the words themselves anywhere outside a comment
        for match in IDENTIFIER.finditer(text):
            offenders.append(f"{path.relative_to(STATIC)}:{text[: match.start()].count(chr(10)) + 1}: {match.group(0)}")
        code = code_without_comments(text) if path.suffix in {".js", ".mjs"} else text
        for match in RECOGNITION.finditer(code):
            offenders.append(f"{path.relative_to(STATIC)}:{code[: match.start()].count(chr(10)) + 1}: {match.group(0)}")
    assert not offenders, offenders


def test_the_recognition_pattern_catches_every_spelling_it_must():
    for spelled in ("SpeechRecognition", "webkitSpeechRecognition", "WEBKITSPEECHRECOGNITION", "new window.SpeechRecognition()",
                    "window['webkitSpeechRecognition']", "speechrecognition", "SpeechGrammarList", "webkitSpeechGrammar",
                    "SpeechRecognitionEvent", "Speech Recognition"):
        assert RECOGNITION.search(spelled), spelled
    assert not RECOGNITION.search("speechSynthesis.speak(new SpeechSynthesisUtterance(text))")


def test_the_voice_code_has_no_recognition_even_split_across_strings():
    squashed = re.sub(r"['\"`\s+]", "", VOICE_CODE).lower()
    assert "speechrecognition" not in squashed and "webkitspeech" not in squashed
    assert "window[" not in VOICE_CODE and "globalThis[" not in VOICE_CODE  # no computed lookups on the window


# --------------------------------------------------------------------------- #
# The transcript goes into the box; the person sends
# --------------------------------------------------------------------------- #


def test_the_transcript_goes_into_the_input_and_is_never_sent_by_the_code():
    put = VOICE_CODE[VOICE_CODE.index("function put(text)"):VOICE_CODE.index("// Read aloud")] if "// Read aloud" in VOICE_CODE else VOICE_CODE[VOICE_CODE.index("function put(text)"):]
    assert "els.input.value =" in put
    # nothing in the file presses Send, calls the chat, or triggers the Ask view's send
    only_refresh = VOICE_CODE.replace("if (KH.views.ask) KH.views.ask.refreshTab();", "")
    for banned in (".click()", "KH.views.ask", "ask.send", "api.chat", "withConsent", "requestSubmit", ".submit(", "dispatchEvent(new KeyboardEvent", "new MouseEvent"):
        assert banned not in only_refresh, banned
    assert "if (KH.views.ask) KH.views.ask.refreshTab();" in VOICE_CODE  # the only use of the Ask view: re-read what the server offers
    assert "Nothing has been sent to the AI." in VOICE_JS and "then press Send" in VOICE_JS
    # the new text is added after what is already typed, within the box's limit
    assert "const MAX_CHARS = 2000;" in VOICE_JS and ".slice(0, MAX_CHARS)" in VOICE_JS and "replace(/\\s+$/, '')" in VOICE_JS


def test_the_only_request_is_the_transcription_and_it_stays_on_this_server():
    assert len(re.findall(r"\bfetch\(", VOICE_CODE)) == 1
    assert "`/api/ai/transcribe?seconds=${seconds}`" in VOICE_CODE and "credentials: 'same-origin'" in VOICE_CODE
    assert "'X-Requested-With': KH.brand.csrfHeaderValue" in VOICE_CODE
    for banned in ("XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "importScripts", "import(", "RTCPeerConnection", "<script", "http://", "mode: 'no-cors'"):
        assert banned not in VOICE_CODE, banned
    assert not re.search(r"https://[a-z0-9.-]+", VOICE_CODE, re.IGNORECASE)  # no host is named (the link pattern is a regex)


def test_the_recording_is_never_kept_played_or_stored():
    for banned in ("createObjectURL", "FileReader", "new Audio", "<audio", "audioContext", "AudioContext", "indexedDB", "sessionStorage",
                   "caches.", "navigator.storage", "download", "saveAs", ".src =", "readAsDataURL", "btoa("):
        assert banned not in VOICE_CODE, banned
    stores = re.findall(r"localStorage\.(?:set|get|remove)Item\(([^,)]*)", VOICE_CODE)
    assert stores and set(stores) == {"READ_KEY"}  # the one thing kept: whether answers are read aloud
    assert "const READ_KEY = 'kh.ask.readAloud';" in VOICE_JS
    for use in re.finditer(r"localStorage", VOICE_CODE):  # every use sits in a try block
        before = VOICE_CODE[max(0, use.start() - 80):use.start()]
        assert "try {" in before, before
    assert "blob = null; // the recording is not kept" in VOICE_JS and "mine.chunks.length = 0;" in VOICE_JS


def test_the_microphone_is_released_and_the_recording_stops_by_itself():
    assert "track.stop()" in VOICE_CODE and "releaseStream(mine.stream)" in VOICE_CODE
    assert "const MAX_MS = 60000;" in VOICE_JS and "if (elapsed >= MAX_MS) stopRecording();" in VOICE_JS
    assert "document.hidden" in VOICE_CODE and "attributeFilter: ['hidden']" in VOICE_CODE  # leaving the page discards the recording
    assert "'pagehide'" in VOICE_CODE and "e.key === 'Escape'" in VOICE_CODE
    assert "audioBitsPerSecond: BITRATE" in VOICE_CODE and "const BITRATE = 32000;" in VOICE_JS  # a minute stays far under the size limit
    # only the four containers the server takes
    assert "new Set(['audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav'])" in VOICE_JS


def test_a_recording_row_shows_the_time_and_a_way_out():
    for text in ("Recording. Tap the microphone to stop.", "Turning your recording into text…", "'Discard'", "'Cancel'", "ask-rec-time",
                 "of ${clock(MAX_MS)}", "Stop recording", "Record your question"):
        assert text in VOICE_JS, text
    assert "role: 'status'" in VOICE_JS  # the line under the input is announced
    assert "aria-pressed" not in VOICE_JS  # the button's name changes instead (a toggle would say it twice)


def test_the_microphone_button_follows_the_server_and_the_browsers_limits_are_explained_in_one_line():
    assert "status.features.voice" in VOICE_CODE and "els.mic.hidden = !voiceOn;" in VOICE_CODE
    assert "navigator.mediaDevices.getUserMedia" in VOICE_CODE and "typeof window.MediaRecorder === 'function'" in VOICE_CODE
    assert "This browser cannot record audio. Type your question instead." in VOICE_JS
    assert "Voice input needs a secure (https) connection. Type your question instead." in VOICE_JS
    assert "The microphone is blocked for this site. Allow it in your browser\\'s settings, or type your question." in VOICE_JS
    assert "No microphone was found." in VOICE_JS


def test_consent_is_asked_before_the_microphone_is_opened():
    body = VOICE_CODE[VOICE_CODE.index("async function onMic()"):VOICE_CODE.index("function micProblem")]
    assert body.index("KH.ai.askConsent(info.request") < body.index("getUserMedia({ audio: true })")
    assert "if (!info.consent)" in body and "Nothing was recorded. You can still type your question." in body
    # a 409 at the upload (the host changed) asks again and sends the same recording once more
    assert "err.data.consent_required" in VOICE_CODE and "KH.ai.askConsent(err.data.consent" in VOICE_CODE
    assert "askConsent, cardEl" in AI_JS or "askConsent," in AI_JS  # exported by ai.js


def test_the_consent_sheet_says_where_a_recording_goes_and_what_comes_back():
    assert "voice: 'your voice recording (up to a minute)'," in AI_JS
    never = AI_JS[AI_JS.index("const NEVER_SENT_TEXT"):AI_JS.index("const FEATURE_TEXT")]
    for phrase in ("Nothing but the recording is sent", "nothing goes to the AI until you press Send", "not kept on this device or on the server"):
        assert phrase in never, phrase
    assert "voice ? 'Before your recording is sent' : 'Before anything is sent'" in AI_JS
    assert "voice ? null : check('Show me the request before every AI call to this server'" in AI_JS  # there is no request to preview first
    assert "voice: 'Voice recordings'" in AI_JS and "voice: 'your voice recordings'" in AI_JS and "voice: 'Voice'" in AI_JS
    assert "u.provider_id === 0 ? 'speech to text'" in AI_JS
    assert "if (ev.feature === 'voice') return voiceRow(ev, when);" in AI_JS
    assert "Your recording and its words are not kept anywhere" in AI_JS


# --------------------------------------------------------------------------- #
# Read aloud: voices on the device only
# --------------------------------------------------------------------------- #


def test_read_aloud_uses_only_voices_built_into_the_device():
    assert VOICE_CODE.count("getVoices()") == 1
    assert "all.filter((v) => v && v.localService === true)" in VOICE_CODE
    assert "utterance.voice = voice;" in VOICE_CODE and "pickVoice()" in VOICE_CODE
    assert "voices.find(" in VOICE_CODE and "voices[0]" in VOICE_CODE  # the choice is made among the filtered list
    # nothing is spoken without a voice of the device's own, and the browser's default voice is never left to choose
    assert "if (!engine || !voice || !text) return;" in VOICE_CODE
    assert "localService === false" not in VOICE_CODE and "localService !== true" not in VOICE_CODE
    assert "speechSynthesis" in VOICE_CODE and "SpeechSynthesisUtterance" in VOICE_CODE


def test_without_a_device_voice_the_switch_is_hidden_with_a_note():
    assert "els.readLabel.hidden = !has;" in VOICE_CODE and "els.readNote.hidden = has;" in VOICE_CODE
    assert "this device has no voice of its own, and the app will not use an online one." in VOICE_JS
    assert "Read answers aloud" in VOICE_JS and "Uses a voice built into this device. Nothing is sent anywhere." in VOICE_JS
    assert "voiceschanged" in VOICE_CODE  # browsers that list their voices late are waited for


def test_only_the_checked_answer_text_is_read_and_never_links_or_cards():
    assert "const SPOKEN_KINDS = new Set(['answer', 'confirm_save', 'treat_low', 'get_help_now']);" in VOICE_JS
    speak = VOICE_CODE[VOICE_CODE.index("function spokenText"):VOICE_CODE.index("function speak(")]
    assert "answer.text" in speak and "answer.cards" not in VOICE_CODE and "answer.numbers" not in VOICE_CODE and "answer.notes" not in VOICE_CODE
    assert "LINK_TEXT" in speak
    pattern = re.search(r"const LINK_TEXT = /(.*)/gi;", VOICE_JS)
    assert pattern and "https?:" in pattern.group(1) and "\\/learn\\/" in pattern.group(1) and "@" in pattern.group(1)
    assert "if (MOCK || !built || !els.readInput.checked) return;" in VOICE_CODE  # off until the person switches it on, never in the demo
    assert "const READ_KEY = 'kh.ask.readAloud';" in VOICE_JS and "localStorage.getItem(READ_KEY) === '1'" in VOICE_CODE


def test_speech_stops_when_the_person_acts_elsewhere():
    for trigger in ("els.send.addEventListener('click', () => stopSpeaking())", "e.key === 'Enter' && !e.shiftKey && !e.isComposing) stopSpeaking()",
                    "fresh.addEventListener('click', () => stopSpeaking())", "window.addEventListener('pagehide'"):
        assert trigger in VOICE_CODE, trigger
    assert "'Stop reading'" in VOICE_JS and "engine.cancel()" in VOICE_CODE


# --------------------------------------------------------------------------- #
# Page rules: no inline script or style, text only, tokens for colour
# --------------------------------------------------------------------------- #


def test_no_inline_script_style_or_html_from_text():
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute('on", "setAttribute('style'",
                   'setAttribute("style"', "style:", "srcdoc", "javascript:"):
        assert banned.lower() not in VOICE_CODE.lower(), banned
    assert "textContent" in VOICE_CODE and "createTextNode" not in VOICE_CODE  # strings go through textContent and h() children
    assert not re.search(r"\bon[a-z]+\s*=\s*['\"]", VOICE_CODE)  # no on...="" handler strings


def test_the_stylesheet_uses_the_apps_tokens_and_respects_reduced_motion():
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", VOICE_CSS), "colours come from the app's tokens (light and dark)"
    assert "@import" not in VOICE_CSS and "url(" not in VOICE_CSS
    assert "prefers-reduced-motion: reduce" in VOICE_CSS and "var(--over-text)" in VOICE_CSS
    assert "overflow-wrap: anywhere" in VOICE_CSS and "flex-wrap: wrap" in VOICE_CSS and "overflow-x" not in VOICE_CSS
    assert "min-height: var(--tap)" in VOICE_CSS


def test_the_demo_and_the_preview_never_record_or_speak():
    assert "const { MOCK } = KH.flags;" in VOICE_JS
    assert "if (MOCK || !build()) return;" in VOICE_CODE  # the demo's Ask screen has no input; sync() does nothing there


# --------------------------------------------------------------------------- #
# The header that lets the page use the microphone
# --------------------------------------------------------------------------- #


def test_the_microphone_is_allowed_for_this_origin_only_and_everything_else_is_unchanged():
    from app.security import STATIC_HEADERS

    policy = dict(STATIC_HEADERS)["Permissions-Policy"]
    assert policy == "camera=(self), microphone=(self), geolocation=(), payment=(), usb=(), browsing-topics=()"
    assert "microphone=*" not in policy and "microphone=()" not in policy


def test_the_page_and_the_deploy_files_do_not_override_the_header():
    for path in (REPO / "deploy").rglob("*"):
        if path.is_file() and path.suffix in {".yaml", ".yml", ".conf", ".container", ".caddyfile", ""}:
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "microphone=()" not in text, path
    assert "Permissions-Policy" not in INDEX
