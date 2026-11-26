"""Speaking a question for Ask in the iPhone app (owner, 2026-11-26): the words are worked out on the iPhone.

The Swift code only compiles in CI (macOS); these tests pin what it must keep: the two bridge kinds and their answers, recognition
on the device only, the two permission sentences in the app's Info.plist settings, no file, no network and no storage, and the page
side (``js/views/ask-voice.js``) asking only those two kinds and hiding the microphone otherwise.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "ios"
DICTATION = (IOS / "KidneyHealth" / "Phone" / "Dictation.swift").read_text(encoding="utf-8")
SERVICES = (IOS / "KidneyHealth" / "Services" / "FoodServices.swift").read_text(encoding="utf-8")
PROJECT = (IOS / "KidneyHealth.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
VOICE_JS = (ROOT / "app" / "static" / "js" / "views" / "ask-voice.js").read_text(encoding="utf-8")


def code(swift: str) -> str:
    """The Swift source without ``//`` comments."""
    return "\n".join(re.sub(r"(?<![:\"])//.*$", "", line) for line in swift.splitlines())


def test_the_bridge_answers_the_two_kinds():
    assert 'case "speechStatus":' in SERVICES and "return Dictation.status()" in SERVICES
    assert 'case "dictate":' in SERVICES and "return await Dictation.shared.dictate()" in SERVICES


def test_recognition_runs_on_the_iphone_only():
    body = code(DICTATION)
    assert "request.requiresOnDeviceRecognition = true" in body
    assert "recognizer.supportsOnDeviceRecognition" in body  # a language the phone cannot do on the device is "not_on_device"
    assert '"reason": "not_on_device"' in body and '"reason": "not_allowed"' in body and '"reason": "not_ready"' in body
    for word in ("URLSession", "URLRequest", "Keychain", "UserDefaults", "FileManager", "AVAudioRecorder", "AVAudioFile", "write(to", "print(", "Logger", "os_log"):
        assert word not in body, word


def test_the_answers_are_the_ones_the_page_reads():
    body = code(DICTATION)
    for error in ("cancelled", "not_allowed", "unavailable", "busy", "failed"):
        assert f'"error": "{error}"' in body, error
    assert 'next.resume(returning: ["ok": true, "text": String(heard.prefix(2000))])' in body  # the question box's limit
    assert "static let maxSeconds = 60" in body  # the web app's limit
    assert "UIApplication.willResignActiveNotification" in body  # leaving the app keeps nothing
    for kind in ("cancelled", "not_allowed"):
        assert f"error === '{kind}'" in VOICE_JS, kind


def test_the_app_says_why_it_asks_for_the_microphone_and_speech():
    for key in ("NSMicrophoneUsageDescription", "NSSpeechRecognitionUsageDescription"):
        sentences = re.findall(rf'INFOPLIST_KEY_{key} = "([^"]*)";', PROJECT)
        assert len(sentences) == 2 and sentences[0] == sentences[1], key  # Debug and Release
        assert "this iPhone" in sentences[0] and "Ask" in sentences[0], key


def test_the_microphone_is_hidden_unless_ask_runs_and_the_phone_can_listen():
    assert "phoneVoice = !!(chatAvailable && status && status.ok && status.available);" in VOICE_JS
    assert "els.mic.hidden = !phoneVoice;" in VOICE_JS
    # the status is asked only while Ask can run
    assert "if (chatAvailable && KH.mock && KH.mock.device) {" in VOICE_JS
