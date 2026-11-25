"""The person's own AI key on the iPhone app (the owner, 2026-11-25; design note 39 §6.5).

* tests/js/own_key.mjs drives the page with a stand-in app and provider: no server, the order, the tasks, the photo switch, never a
  lab task, never the name or birth month, the prefilter, the checks on every answer.
* The app's providers are the server's presets a person may use with their own key, with the same hosts and quirks.
* ``ai-prompts.json`` "own_key" holds the server's own messages and schemas for exactly the three tasks.
* The Swift side (read as text): fixed HTTPS hosts only, the key in the Keychain and in a header, no logging, no lab task.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.ai import config, presets, prompts, schemas

pytestmark = pytest.mark.safety

ROOT = Path(__file__).resolve().parents[1]
OWN = (ROOT / "ios" / "KidneyHealth" / "Services" / "OwnAI.swift").read_text(encoding="utf-8")
CODE = re.sub(r"//[^\n]*", "", OWN)
PAGE = (ROOT / "app" / "static" / "js" / "mock" / "ai.js").read_text(encoding="utf-8")


def test_the_page_with_a_stand_in_app_and_provider() -> None:
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "own_key.mjs")], capture_output=True, text=True, timeout=300, check=False)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-4000:]
    assert "checks passed" in done.stdout


def _swift_case(provider: str, prop: str) -> str:
    """The value a computed property of OwnAIProvider gives for one case (`case .openai: "x"`)."""
    block = CODE[CODE.index(f"var {prop}:"):]
    block = block[: block.index("\n    }\n") + 6]
    m = re.search(rf"case \.{provider}: \"([^\"]*)\"", block)
    assert m, (provider, prop)
    return m.group(1)


def test_the_providers_are_the_servers_own_key_presets() -> None:
    cases = dict(re.findall(r"case (\w+)(?: = \"(\w+)\")?\n", CODE[CODE.index("enum OwnAIProvider"):CODE.index("var id: String")]))
    names = {swift: (raw or swift) for swift, raw in cases.items()}
    assert set(names.values()) == set(presets.USER_PRESETS) == {"openai", "openrouter", "nous_portal"}
    for swift, name in names.items():
        p = presets.get(name)
        assert p.user_allowed and p.kind == "cloud"
        assert p.base_url is not None
        base = p.base_url.removeprefix("https://")
        host, _, path = base.partition("/")
        assert _swift_case(swift, "host") == host
        assert _swift_case(swift, "path") == f"/{path}/chat/completions"
        assert _swift_case(swift, "label") == p.label
        assert _swift_case(swift, "policy") == presets.POLICY_LINES[p.policy_key]
        assert f"{name}: '{presets.POLICY_LINES[p.policy_key]}'".replace("'s ", "\\'s ") in PAGE  # the page's copy for the consent sheet
    # the quirks, as presets.py has them
    assert 'var tokenField: String { self == .openai ? "max_completion_tokens" : "max_tokens" }' in CODE
    assert presets.get("openai").token_field == "max_completion_tokens"
    assert {n for n in presets.USER_PRESETS if presets.get(n).token_field == "max_tokens"} == {"openrouter", "nous_portal"}
    assert "var schemaInRequest: Bool { self != .nousPortal }" in CODE
    assert presets.get("nous_portal").default_structured == "prompt"
    assert all(presets.get(n).default_structured == "json_schema" for n in ("openai", "openrouter"))
    assert 'var temperature: Double? { self == .openai ? nil : 0.2 }' in CODE
    assert presets.get("openai").temperature is None and presets.get("openrouter").temperature == presets.get("nous_portal").temperature == 0.2
    assert 'var reasoningEffort: String? { self == .openai ? "low" : nil }' in CODE
    assert f'var defaultModel: String? {{ self == .openai ? "{presets.get("openai").default_model}" : nil }}' in CODE
    assert 'case .openai: ["store": false]' in CODE and dict(presets.get("openai").extra_body) == {"store": False}
    assert 'case .openrouter: ["provider": ["data_collection": "deny", "require_parameters": true]]' in CODE
    assert dict(presets.get("openrouter").extra_body) == {"provider": {"data_collection": "deny", "require_parameters": True}}


def test_the_committed_own_key_prompts_are_current() -> None:
    """scripts/build_preview.py packs app/ai/own_key_prompts.json with plain Python; this keeps it equal to the server's code."""
    spec = importlib.util.spec_from_file_location("gen_own_key_prompts", ROOT / "scripts" / "gen_own_key_prompts.py")
    gen = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(gen)
    committed = (ROOT / "app" / "ai" / "own_key_prompts.json").read_text(encoding="utf-8")
    assert committed == gen.render(), "app/ai/own_key_prompts.json is stale: run python3 scripts/gen_own_key_prompts.py"


def test_the_pack_step_needs_no_app_dependencies() -> None:
    """The macOS jobs run scripts/build_preview.py --device with plain Python (2026-11-25: an import of app.ai.config there broke
    the iOS build). It may import only app.ai.prompts, whose imports are the standard library and app.textclean."""
    tree = ast.parse((ROOT / "scripts" / "build_preview.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    app_modules = {m for m in modules if m.startswith("app.")}
    assert app_modules == {"app.ai.prompts", "app.guidance.topics.APP_LINKS"}, app_modules  # both need only the standard library


def test_the_own_key_prompts_are_the_servers(tmp_path) -> None:
    spec = importlib.util.spec_from_file_location("build_preview", ROOT / "scripts" / "build_preview.py")
    builder = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(builder)
    builder.build_device(tmp_path)
    own = json.loads((tmp_path / "ai-prompts.json").read_text(encoding="utf-8"))["own_key"]
    assert own["system"] == prompts.TASK_SYSTEM_PROMPT and own["prompt_version"] == prompts.PROMPT_VERSION
    assert own["max_tokens"] == config.DEFAULT_MAX_TOKENS
    assert set(own["tasks"]) == {"parse_meal", "read_label", "plate"}  # never a lab report task
    data = prompts.parse_meal_data("2 eggs & <toast>")
    payload = prompts.data_block(data)[len("<data>\n"):-len("\n</data>")]
    for mode in ("json_schema", "prompt"):
        task = own["tasks"]["parse_meal"]
        assert task["schema"] == schemas.parse_meal_schema() and task["schema_name"] == "kidney_parse_meal" and task["image"] is False
        assert task[mode].replace("{text}", payload) == prompts.user_message("parse_meal", data, mode=mode, schema=schemas.parse_meal_schema())
        for name, key, schema, schema_name in (("read_label", "read_label", schemas.read_label_schema(), "nutrition_label"),
                                               ("plate", "plate", schemas.plate_schema(), "plate_photo")):
            t = own["tasks"][name]
            assert t["schema"] == schema and t["schema_name"] == schema_name and t["image"] is True
            assert t[mode] == prompts.user_message(key, None, mode=mode, schema=schema) and "{text}" not in t[mode]
    assert "Never give, calculate or adjust insulin doses" in own["system"]


def test_the_app_talks_only_to_the_fixed_hosts_with_the_keychain_key_and_logs_nothing() -> None:
    assert 'static let tasks: Set<String> = ["parse_meal", "read_label", "plate"]' in CODE
    assert 'static let photoTasks: Set<String> = ["read_label", "plate"]' in CODE
    for word in ("lab_report", "read_lab_", "lab report", "transcri", "chat"):
        assert word not in CODE.lower().replace("/chat/completions", ""), word  # no lab task, no Ask, no voice
    assert "http://" not in OWN and 'parts.scheme = "https"' in CODE and "parts.host = provider.host" in CODE
    assert "http.url?.host == provider.host" in CODE  # the answer came from the fixed host
    assert "URLSessionTransport.makeSession(" in CODE and "URLSession(" not in CODE  # no cookies, no cache, no redirects
    assert "Keychain.read(.ownAIKey)" in CODE and 'forHTTPHeaderField: "Authorization"' in CODE
    assert re.search(r"defaults\.set\([^)]*key\b", CODE) is None  # the key never goes to UserDefaults
    for word in ("print(", "NSLog", "os_log", "Logger(", "debugPrint", "dump(", ".write(to:", "FileManager"):
        assert word not in CODE, word
    # the page never sees the key: status names only these
    status = CODE[CODE.index("func status()"):CODE.index("static func isPlausibleKey")]
    assert set(re.findall(r'"(\w+)": ', status)) == {"ok", "set", "provider", "label", "host", "model", "photos"}
    # photos only with the switch on, and the switch is off until the person turns it on
    assert 'guard !photo || photosOn else { return Self.problem("photos_off") }' in CODE
    assert 'photosOn = defaults.bool(forKey: "ownAI.photos")' in CODE
    assert "count <= Self.maxPhoto" in CODE and "count <= Self.maxText" in CODE and "reply.count <= Self.maxAnswer" in CODE
    for word in ("insulin", "dose", "dosing", "bolus"):
        assert word not in CODE.lower(), word
    keychain = (ROOT / "ios" / "KidneyHealth" / "Keychain.swift").read_text(encoding="utf-8")
    assert "case ownAIKey" in keychain
    services = (ROOT / "ios" / "KidneyHealth" / "Services" / "FoodServices.swift").read_text(encoding="utf-8")
    assert 'case "ownAIStatus":' in services and "OwnAI.shared.answer(request)" in services
    keys = (ROOT / "ios" / "KidneyHealth" / "Services" / "KeysView.swift").read_text(encoding="utf-8")
    assert 'Toggle("Also send meal and label photos to this AI"' in keys and "SecureField(" in keys
    assert "Lab reports, and anything with your name or date of birth, are never sent to it." in keys


def test_the_page_never_sends_a_lab_report_to_the_own_key() -> None:
    tasks = set(re.findall(r"viaOwnKey\([^,]+, '[a-z_]+', '([a-z_]+)'", PAGE)) | set(re.findall(r"'/api/vision/\w+': \['([a-z_]+)'", PAGE))
    assert tasks == {"parse_meal", "read_label", "plate"}
    assert "'/api/ai/read-lab-report'" not in PAGE[PAGE.index("const OWN_PHOTO"):PAGE.index("for (const [path, featureRoute]")]
    lab = PAGE[PAGE.index("route('POST', '/api/ai/read-lab-report-text'"):]
    assert "viaOwnKey" not in lab[: lab.index("route('*'")]
