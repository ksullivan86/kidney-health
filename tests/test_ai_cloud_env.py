"""A second AI provider from the environment: ``AI_CLOUD_PROVIDER`` and its ``AI_CLOUD_*`` siblings (docs/ai.md, "A local AI and a
cloud AI, both from the environment").

What is pinned down here: how the values are read, defaulted and checked (every start-up error and warning); that the start-up
sync keeps two locked rows in step with the environment (consents dropped when the host or the company changes, the connection test
cleared on a new URL, model or key, the row deleted when the variable is unset); the consent line for a proxy that forwards to a
company, and that no existing line changed; that both rows are locked and their roles fixed in the admin API; the prompt budget of
the cloud slot. Routing and the lab report guarantee are in ``tests/test_ai_cloud_routing.py``. No network."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from ai_support import FakeProvider, attach_routed, chat
from conftest import HTTPS_URL, TestClient, make_settings, sign_in
from test_ai_routing import IDEAS, db, next_meal, ready, route, turn_on
from app import security
from app.ai import config as K
from app.ai import presets as P
from app.config import AiCloudEnv, AiEnv, ConfigError, load_ai_env, load_settings
from app.main import create_app

LOCAL_KEY = "sk-local-0123456789abcdefghijklmn"
CLOUD_KEY = "sk-cloud-9876543210zyxwvutsrqponm"
GPU_URL = "http://gpu.lan:4000/v1"  # a LiteLLM proxy with the key that can only call models on the home GPU
CLOUD_URL = "http://litellm.lan:4000/v1"  # a LiteLLM proxy with the key that can only call cloud models
HOSTS = ("gpu.lan:4000", "litellm.lan:4000")
PROXY_LINE = ("Goes through your admin's LiteLLM proxy to Anthropic. Anthropic receives what is sent, under its own terms; "
              "your admin can read it too.")
SELF_HOSTED_LINE = "Runs on your admin's hardware; your admin can read what is sent."


def cloud_env(**over: Any) -> AiCloudEnv:
    values: dict[str, Any] = dict(provider="litellm", base_url=CLOUD_URL, api_key=CLOUD_KEY, model="claude-sonnet",
                                  vision_model="claude-sonnet", upstream="Anthropic")
    values.update(over)
    return AiCloudEnv(**values)


def local_env(**over: Any) -> dict[str, Any]:
    values: dict[str, Any] = dict(provider="litellm", base_url=GPU_URL, api_key=LOCAL_KEY, model="gemma", vision_model="gemma-vision",
                                  provider_role="local", private_hosts=HOSTS)
    values.update(over)
    return values


def both(tmp_path, foods_json, *, cloud: AiCloudEnv | None = None, **main: Any):
    """Settings with the home GPU as ``AI_PROVIDER`` (role local) and the cloud models as ``AI_CLOUD_PROVIDER``."""
    return make_settings(tmp_path, foods_json, ai=AiEnv(**local_env(**main), cloud=cloud or cloud_env()))


def cloud_only(tmp_path, foods_json, *, cloud: AiCloudEnv | None = None, **ai: Any):
    return make_settings(tmp_path, foods_json, ai=AiEnv(private_hosts=HOSTS, cloud=cloud or cloud_env(), **ai))


def check(tmp_path, foods_json, **kw: Any) -> list[str]:
    return K.check_env(both(tmp_path, foods_json, **kw))


def start(settings) -> None:
    """One start of the app (the start-up sync runs), then stop."""
    with TestClient(create_app(settings), base_url=HTTPS_URL):
        pass


def rows(settings) -> dict[str, sqlite3.Row]:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        return {r["env_slot"]: r for r in conn.execute("SELECT * FROM ai_providers WHERE locked = 1")}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Reading the values
# --------------------------------------------------------------------------- #


def test_nothing_set_means_no_cloud_provider_and_the_defaults_are_unset():
    c = load_ai_env({}).cloud
    assert c == AiCloudEnv() and c.stray() == []
    assert load_ai_env({"AI_CLOUD_PROVIDER": "", "AI_CLOUD_MODEL": "  ", "AI_CLOUD_UPSTREAM": ""}).cloud == AiCloudEnv()  # blank is unset


def test_every_value_is_read_like_its_ai_twin(tmp_path):
    key_file = tmp_path / "cloud-key"
    key_file.write_text(CLOUD_KEY + "\n")
    env = {"AI_CLOUD_PROVIDER": "LiteLLM", "AI_CLOUD_BASE_URL": CLOUD_URL, "AI_CLOUD_API_KEY_FILE": str(key_file),
           "AI_CLOUD_MODEL": "claude-sonnet", "AI_CLOUD_VISION_MODEL": "claude-sonnet", "AI_CLOUD_TIMEOUT_S": "90",
           "AI_CLOUD_MAX_TOKENS": "2_000", "AI_CLOUD_CONTEXT_TOKENS": "65536", "AI_CLOUD_STRUCTURED_OUTPUT": "JSON_Schema",
           "AI_CLOUD_REASONING_EFFORT": "Low", "AI_CLOUD_UPSTREAM": "Anthropic"}
    c = load_ai_env(env).cloud
    assert c == AiCloudEnv(provider="litellm", base_url=CLOUD_URL, api_key=CLOUD_KEY, model="claude-sonnet", vision_model="claude-sonnet",
                           timeout_s=90.0, max_tokens=2000, structured="json_schema", reasoning_effort="low", context_tokens=65536,
                           upstream="Anthropic")
    assert load_ai_env({**{k: v for k, v in env.items() if k != "AI_CLOUD_API_KEY_FILE"}, "AI_CLOUD_API_KEY": CLOUD_KEY}).cloud.api_key == CLOUD_KEY
    assert load_ai_env(env).api_key is None and load_ai_env(env).provider is None  # the first provider's values are not touched


@pytest.mark.parametrize("name, value, message", [
    ("AI_CLOUD_TIMEOUT_S", "4", "AI_CLOUD_TIMEOUT_S must be between 5 and 600"),
    ("AI_CLOUD_TIMEOUT_S", "soon", "AI_CLOUD_TIMEOUT_S must be a number of seconds"),
    ("AI_CLOUD_MAX_TOKENS", "63", "AI_CLOUD_MAX_TOKENS must be between 64 and 32768"),
    ("AI_CLOUD_MAX_TOKENS", "many", "AI_CLOUD_MAX_TOKENS must be a whole number"),
    ("AI_CLOUD_CONTEXT_TOKENS", "1000", "AI_CLOUD_CONTEXT_TOKENS must be between 1024 and 2000000"),
    ("AI_CLOUD_STRUCTURED_OUTPUT", "yaml", "AI_CLOUD_STRUCTURED_OUTPUT must be one of auto, json_schema, json_object, prompt"),
])
def test_a_bad_value_names_its_variable(name, value, message):
    with pytest.raises(ConfigError, match=message):
        load_ai_env({name: value})


def test_the_key_comes_from_a_file_or_a_variable_never_both_and_a_missing_file_is_named(tmp_path):
    with pytest.raises(ConfigError, match="Set either AI_CLOUD_API_KEY or AI_CLOUD_API_KEY_FILE, not both"):
        load_ai_env({"AI_CLOUD_API_KEY": CLOUD_KEY, "AI_CLOUD_API_KEY_FILE": str(tmp_path / "k")})
    with pytest.raises(ConfigError, match="AI_CLOUD_API_KEY_FILE points to .*does not exist"):
        load_ai_env({"AI_CLOUD_API_KEY_FILE": str(tmp_path / "missing")})
    empty = tmp_path / "empty"
    empty.write_text("\n")
    assert load_ai_env({"AI_CLOUD_API_KEY_FILE": str(empty)}).cloud.api_key is None  # an empty file is an unset key
    assert load_ai_env({"AI_API_KEY": LOCAL_KEY, "AI_CLOUD_API_KEY": CLOUD_KEY}).api_key == LOCAL_KEY  # two keys, side by side


@pytest.mark.parametrize("name", ["Anthropic", "OpenAI", "Mistral AI", "Z.ai", "Hugging Face & Partners", "Group-1", "a" * 60, "7 Labs"])
def test_a_plain_company_name_is_accepted(name):
    assert load_ai_env({"AI_CLOUD_UPSTREAM": name}).cloud.upstream == name


@pytest.mark.parametrize("name", ["<b>Anthropic</b>", "Anthropic!", "Anth_ropic", "a" * 61, "-Anthropic", ".Anthropic", "Anthropic\nOpenAI",
                                  "Anthropic (US)", "Antropic‮evil", "https://example.com", "Ünicode"])
def test_anything_else_is_refused_before_it_can_reach_a_screen(name):
    with pytest.raises(ConfigError, match="AI_CLOUD_UPSTREAM must be the company's plain name"):
        load_ai_env({"AI_CLOUD_UPSTREAM": name})


def test_the_cloud_key_is_kept_out_of_logs_like_the_first_key(tmp_path, foods_json):
    settings = both(tmp_path, foods_json)
    assert {LOCAL_KEY, CLOUD_KEY} <= set(settings.secret_values())
    assert CLOUD_KEY not in repr(settings) and CLOUD_KEY not in repr(settings.ai.cloud)
    security.install_log_redaction(settings.secret_values())
    assert CLOUD_KEY not in security.redact(f"sending with {CLOUD_KEY} now")
    assert load_settings({"DATA_DIR": str(tmp_path / "d"), "AI_CLOUD_PROVIDER": "openai", "AI_CLOUD_API_KEY": "sk-from-env-0123456789"}
                         ).secret_values().count("sk-from-env-0123456789") == 1


# --------------------------------------------------------------------------- #
# Start-up checks: every error and warning
# --------------------------------------------------------------------------- #


def test_a_cloud_only_server_is_allowed(tmp_path, foods_json):
    assert K.check_env(cloud_only(tmp_path, foods_json)) == []
    start(cloud_only(tmp_path, foods_json))
    assert list(rows(cloud_only(tmp_path, foods_json))) == ["cloud"]


def test_both_providers_with_the_first_one_local_are_allowed(tmp_path, foods_json):
    assert check(tmp_path, foods_json) == []


def test_two_cloud_providers_stop_the_start(tmp_path, foods_json):
    with pytest.raises(ConfigError, match=r"Two cloud providers.*AI_CLOUD_PROVIDER is always the cloud AI.*AI_PROVIDER_ROLE=local"):
        check(tmp_path, foods_json, provider_role="cloud")
    with pytest.raises(ConfigError, match="Two cloud providers"):  # also with a role and no provider, a mistake worth stopping on
        K.check_env(cloud_only(tmp_path, foods_json, provider_role="cloud"))
    with pytest.raises(ConfigError, match="Two cloud providers"):
        start(both(tmp_path, foods_json, provider_role="cloud"))


def test_the_first_provider_needs_the_local_role_when_a_cloud_provider_is_set(tmp_path, foods_json):
    with pytest.raises(ConfigError, match=r"AI_PROVIDER needs a role: set AI_PROVIDER_ROLE=local"):
        check(tmp_path, foods_json, provider_role=None)
    # without AI_CLOUD_PROVIDER the first provider needs no role, as before
    assert K.check_env(make_settings(tmp_path, foods_json, ai=AiEnv(**local_env(provider_role=None)))) == []


def test_the_first_providers_own_checks_are_unchanged(tmp_path, foods_json):
    with pytest.raises(ConfigError, match="AI_PROVIDER_ROLE=local needs a private host"):
        check(tmp_path, foods_json, private_hosts=("litellm.lan:4000",))
    with pytest.raises(ConfigError, match="AI_PROVIDER=litellm needs AI_API_KEY_FILE"):
        check(tmp_path, foods_json, api_key=None)


def test_hermes_is_refused_for_the_cloud_slot(tmp_path, foods_json):
    with pytest.raises(ConfigError, match=r"AI_CLOUD_PROVIDER=hermes is refused.*use AI_PROVIDER"):
        check(tmp_path, foods_json, cloud=cloud_env(provider="hermes", base_url="http://host.containers.internal:8643/v1"))
    ai = AiEnv(provider="hermes", base_url="http://host.containers.internal:8643/v1", model="kidney", api_key=LOCAL_KEY, provider_role="local",
               private_hosts=("host.containers.internal:8643", *HOSTS), cloud=cloud_env())
    assert any("tool-free" in w for w in K.check_env(make_settings(tmp_path, foods_json, ai=ai)))  # hermes stays fine as the first provider


@pytest.mark.parametrize("cloud, message", [
    (dict(provider="skynet"), "AI_CLOUD_PROVIDER: unknown AI preset"),
    (dict(provider="openai_compatible", base_url=None), "AI_CLOUD_PROVIDER=openai_compatible needs AI_CLOUD_BASE_URL"),
    (dict(base_url="http://litellm.lan:4000/api"), "AI_CLOUD_BASE_URL"),
    (dict(model=None), "AI_CLOUD_PROVIDER=litellm needs AI_CLOUD_MODEL"),
    (dict(api_key=None), "AI_CLOUD_PROVIDER=litellm needs AI_CLOUD_API_KEY_FILE"),
    (dict(structured="yaml"), "AI_CLOUD_STRUCTURED_OUTPUT must be one of"),
    (dict(reasoning_effort="loud"), "AI_CLOUD_REASONING_EFFORT must be one of"),
])
def test_a_bad_cloud_provider_stops_the_start_with_its_own_names(tmp_path, foods_json, cloud, message):
    with pytest.raises(ConfigError, match=message):
        check(tmp_path, foods_json, cloud=cloud_env(**cloud))


def test_a_cloud_preset_needs_a_model_only_when_it_has_no_default(tmp_path, foods_json):
    ok = cloud_env(provider="openai", base_url=None, model=None, upstream=None)
    assert check(tmp_path, foods_json, cloud=ok) == []  # openai names gpt-6-luna
    with pytest.raises(ConfigError, match="AI_CLOUD_PROVIDER=openrouter needs AI_CLOUD_MODEL"):
        check(tmp_path, foods_json, cloud=cloud_env(provider="openrouter", base_url=None, model=None, upstream=None))


def test_a_private_cloud_provider_must_be_listed_in_ai_private_hosts_and_the_message_says_so(tmp_path, foods_json):
    with pytest.raises(ConfigError, match=r"AI_CLOUD_BASE_URL: http:// is only allowed for hosts in AI_PRIVATE_HOSTS"):
        check(tmp_path, foods_json, private_hosts=("gpu.lan:4000",))
    with pytest.raises(ConfigError, match=r"AI_CLOUD_BASE_URL: 10\.0\.0\.7:4000 is private; add it to AI_PRIVATE_HOSTS"):
        check(tmp_path, foods_json, cloud=cloud_env(base_url="https://10.0.0.7:4000/v1"))
    listed = ("gpu.lan:4000", "10.0.0.7:4000")
    assert check(tmp_path, foods_json, private_hosts=listed, cloud=cloud_env(base_url="https://10.0.0.7:4000/v1")) == []
    assert check(tmp_path, foods_json, private_hosts=("gpu.lan:4000", "10.0.0.0/8"), cloud=cloud_env(base_url="http://10.0.0.7:4000/v1")) == []
    assert check(tmp_path, foods_json, cloud=cloud_env(provider="openai", base_url=None, upstream=None)) == []  # a public host needs no listing


def test_the_cloud_provider_is_not_made_local_by_being_listed(tmp_path, foods_json):
    """Listing its host lets a shared provider reach it; it does not give the cloud AI the local role."""
    assert check(tmp_path, foods_json) == []
    with TestClient(create_app(both(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        roles = c.get("/api/admin/ai-routing").json()["roles"]
        assert roles["cloud"]["private"] is True and roles["local"]["host"] == "gpu.lan:4000"


def test_an_address_in_ai_deny_cidrs_stops_the_start(tmp_path, foods_json):
    with pytest.raises(ConfigError, match="AI_CLOUD_BASE_URL: this address is never contacted"):
        check(tmp_path, foods_json, private_hosts=(*HOSTS, "10.0.0.7:4000"), deny_cidrs=("10.0.0.0/24",),
              cloud=cloud_env(base_url="http://10.0.0.7:4000/v1"))


@pytest.mark.parametrize("preset", ["litellm", "vllm", "openai_compatible", "ollama", "lmstudio", "llamacpp"])
def test_a_server_the_admin_runs_needs_the_company_it_forwards_to(tmp_path, foods_json, preset):
    base = "http://litellm.lan:4000/v1"
    with pytest.raises(ConfigError, match=rf"AI_CLOUD_PROVIDER={preset} is a server your admin runs.*set AI_CLOUD_UPSTREAM"):
        check(tmp_path, foods_json, cloud=cloud_env(provider=preset, base_url=base, upstream=None))
    assert check(tmp_path, foods_json, cloud=cloud_env(provider=preset, base_url=base, upstream="Anthropic")) == []


@pytest.mark.parametrize("preset", ["openai", "openrouter", "nous_portal"])
def test_a_cloud_preset_ignores_the_company_and_warns(tmp_path, foods_json, preset):
    warnings = check(tmp_path, foods_json, cloud=cloud_env(provider=preset, base_url=None, model="m", upstream="Anthropic"))
    assert warnings == [f"AI_CLOUD_UPSTREAM is ignored: AI_CLOUD_PROVIDER={preset} is the company's own service, and its consent line names it."]
    assert check(tmp_path, foods_json, cloud=cloud_env(provider=preset, base_url=None, model="m", upstream=None)) == []


def test_stray_cloud_values_without_the_provider_give_a_warning(tmp_path, foods_json):
    stray = cloud_env(provider=None, timeout_s=30.0, max_tokens=900, structured="prompt", reasoning_effort="low", context_tokens=9000)
    [warning] = K.check_env(make_settings(tmp_path, foods_json, ai=AiEnv(cloud=stray)))
    assert warning.endswith("are set but AI_CLOUD_PROVIDER is not, so no server cloud AI provider is defined.")
    for name in ("AI_CLOUD_BASE_URL", "AI_CLOUD_API_KEY", "AI_CLOUD_MODEL", "AI_CLOUD_VISION_MODEL", "AI_CLOUD_TIMEOUT_S", "AI_CLOUD_MAX_TOKENS",
                 "AI_CLOUD_CONTEXT_TOKENS", "AI_CLOUD_STRUCTURED_OUTPUT", "AI_CLOUD_REASONING_EFFORT", "AI_CLOUD_UPSTREAM"):
        assert name in warning
    one = K.check_env(make_settings(tmp_path, foods_json, ai=AiEnv(cloud=AiCloudEnv(model="m"))))
    assert one == ["AI_CLOUD_MODEL is set but AI_CLOUD_PROVIDER is not, so no server cloud AI provider is defined."]
    assert K.check_env(make_settings(tmp_path, foods_json, ai=AiEnv())) == []
    start(make_settings(tmp_path, foods_json, ai=AiEnv(cloud=stray)))  # a warning, not a stop
    assert rows(make_settings(tmp_path, foods_json)) == {}


def test_a_stray_value_set_through_the_environment_is_seen(tmp_path, foods_json):
    ai = load_ai_env({"AI_CLOUD_MODEL": "m", "AI_CLOUD_UPSTREAM": "Anthropic"})
    [warning] = K.check_env(make_settings(tmp_path, foods_json, ai=ai))
    assert warning == "AI_CLOUD_MODEL, AI_CLOUD_UPSTREAM are set but AI_CLOUD_PROVIDER is not, so no server cloud AI provider is defined."


def test_a_bad_environment_stops_the_start_through_load_settings(tmp_path):
    env = {"DATA_DIR": str(tmp_path / "d"), "AI_PROVIDER": "litellm", "AI_CLOUD_PROVIDER": "litellm"}
    with pytest.raises(ConfigError, match="AI_PROVIDER needs a role"):
        create_app(load_settings(env))
    with pytest.raises(ConfigError, match="AI_CLOUD_UPSTREAM must be"):
        load_settings({**env, "AI_CLOUD_UPSTREAM": "<script>"})


# --------------------------------------------------------------------------- #
# The start-up sync: two locked rows
# --------------------------------------------------------------------------- #


def test_two_locked_rows_are_made_one_for_each_variable(tmp_path, foods_json):
    settings = both(tmp_path, foods_json)
    start(settings)
    r = rows(settings)
    assert set(r) == {"main", "cloud"} and r["main"]["id"] != r["cloud"]["id"]
    main, cloud = r["main"], r["cloud"]
    assert (main["preset"], main["base_url"], main["model"], main["vision_model"], main["upstream"]) == (
        "litellm", GPU_URL, "gemma", "gemma-vision", None)
    assert (cloud["preset"], cloud["base_url"], cloud["model"], cloud["vision_model"], cloud["upstream"]) == (
        "litellm", CLOUD_URL, "claude-sonnet", "claude-sonnet", "Anthropic")
    for row in (main, cloud):
        assert row["scope"] == "shared" and row["locked"] == 1 and row["enabled"] == 1 and row["owner_user_id"] is None
        assert row["api_key_enc"] is None and row["api_key_hint"] is None  # a key from the environment is never stored
        assert (row["max_tokens"], row["structured"], row["reasoning_effort"], row["timeout_s"]) == (1500, "auto", None, None)
    assert main["context_tokens"] is None and cloud["context_tokens"] == 32_768  # the cloud slot's own default
    con = sqlite3.connect(settings.db_path)
    stored = "".join(str(v) for v in con.execute("SELECT * FROM ai_providers").fetchall())
    con.close()
    assert LOCAL_KEY not in stored and CLOUD_KEY not in stored


def test_the_cloud_values_are_the_ones_written(tmp_path, foods_json):
    cloud = cloud_env(timeout_s=90.0, max_tokens=2000, context_tokens=65536, structured="json_object", reasoning_effort="low", vision_model=None)
    settings = both(tmp_path, foods_json, cloud=cloud)
    start(settings)
    row = rows(settings)["cloud"]
    assert (row["timeout_s"], row["max_tokens"], row["context_tokens"], row["structured"], row["reasoning_effort"], row["vision_model"]) == (
        90.0, 2000, 65536, "json_object", "low", None)


def test_a_restart_with_the_same_environment_changes_nothing(tmp_path, foods_json):
    settings = both(tmp_path, foods_json)
    start(settings)
    first = {k: dict(v) for k, v in rows(settings).items()}
    start(settings)
    assert {k: dict(v) for k, v in rows(settings).items()} == first  # same ids, same timestamps


def fingerprint(settings, key: str) -> str | None:
    """What the sync compares a key against (an HMAC under this data directory's secret key)."""
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        return K.key_fingerprint(c.app.state.keyring, key)


def seed(settings, *, probe: bool = True, consent: bool = True) -> dict[str, int]:
    """Give both locked rows a stored connection test (for their current key) and a consent from the admin."""
    keys = {"main": settings.ai.api_key, "cloud": settings.ai.cloud.api_key}
    prints = {slot: fingerprint(settings, key) for slot, key in keys.items()}
    conn = sqlite3.connect(settings.db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    ids = {r["env_slot"]: int(r["id"]) for r in conn.execute("SELECT id, env_slot FROM ai_providers WHERE locked = 1")}
    for slot, pid in ids.items():
        if probe:
            conn.execute("UPDATE ai_providers SET probe_json = ?, probed_at = '2026-10-20T10:00:00Z' WHERE id = ?",
                         (json.dumps({"ok": True, "key_fp": prints[slot]}), pid))
        if consent:
            conn.execute("INSERT INTO ai_consents VALUES (1, ?, 'text', 'x', ?, 0, 'now')", (pid, P.POLICY_VERSION))
    conn.commit()
    conn.close()
    return ids


def consents(settings) -> dict[int, int]:
    conn = sqlite3.connect(settings.db_path)
    try:
        return {int(p): int(n) for p, n in conn.execute("SELECT provider_id, COUNT(*) FROM ai_consents GROUP BY provider_id")}
    finally:
        conn.close()


def probe_of(settings, slot: str) -> Any:
    return rows(settings)[slot]["probe_json"]


def test_a_new_cloud_host_asks_everyone_again_for_the_cloud_provider_only(tmp_path, foods_json):
    start(both(tmp_path, foods_json))
    ids = seed(both(tmp_path, foods_json))
    assert consents(both(tmp_path, foods_json)) == {ids["main"]: 1, ids["cloud"]: 1}
    moved = both(tmp_path, foods_json, private_hosts=(*HOSTS, "litellm2.lan:4000"), cloud=cloud_env(base_url="http://litellm2.lan:4000/v1"))
    start(moved)
    assert consents(moved) == {ids["main"]: 1}  # the cloud provider's consents are gone, the first provider's are kept
    assert probe_of(moved, "cloud") is None and probe_of(moved, "main") is not None
    assert rows(moved)["cloud"]["id"] == ids["cloud"] and rows(moved)["cloud"]["base_url"] == "http://litellm2.lan:4000/v1"


def test_the_same_host_on_another_path_keeps_the_consents_but_clears_the_test(tmp_path, foods_json):
    start(both(tmp_path, foods_json))
    ids = seed(both(tmp_path, foods_json))
    other = both(tmp_path, foods_json, cloud=cloud_env(base_url="http://litellm.lan:4000/cloud/v1"))
    start(other)
    assert consents(other) == {ids["main"]: 1, ids["cloud"]: 1} and probe_of(other, "cloud") is None and probe_of(other, "main") is not None


def test_a_new_company_asks_everyone_again_and_the_same_company_does_not(tmp_path, foods_json):
    start(both(tmp_path, foods_json))
    ids = seed(both(tmp_path, foods_json))
    start(both(tmp_path, foods_json))  # unchanged
    assert consents(both(tmp_path, foods_json)) == {ids["main"]: 1, ids["cloud"]: 1}
    changed = both(tmp_path, foods_json, cloud=cloud_env(upstream="Mistral AI"))
    start(changed)
    assert consents(changed) == {ids["main"]: 1}  # nobody has agreed to Mistral AI yet
    assert rows(changed)["cloud"]["upstream"] == "Mistral AI" and probe_of(changed, "cloud") is None
    assert rows(changed)["cloud"]["id"] == ids["cloud"]  # the same row throughout


def test_the_cloud_provider_can_become_a_cloud_preset_and_the_company_is_dropped(tmp_path, foods_json):
    start(both(tmp_path, foods_json))
    ids = seed(both(tmp_path, foods_json), probe=False)
    openai = both(tmp_path, foods_json, cloud=cloud_env(provider="openai", base_url=None, model="gpt-6-luna", upstream=None))
    start(openai)
    row = rows(openai)["cloud"]
    assert (row["preset"], row["upstream"], row["base_url"]) == ("openai", None, "https://api.openai.com/v1")
    assert consents(openai) == {ids["main"]: 1}  # a different host, and no company any more


def test_a_new_model_or_key_clears_the_connection_test_of_that_provider_only(tmp_path, foods_json):
    settings = both(tmp_path, foods_json)
    start(settings)
    seed(settings, consent=False)
    start(settings)
    assert probe_of(settings, "main") and probe_of(settings, "cloud")  # nothing changed: both tests are kept
    newer = both(tmp_path, foods_json, cloud=cloud_env(model="claude-opus"))
    start(newer)  # a new model
    assert probe_of(newer, "cloud") is None and probe_of(newer, "main")
    seed(newer, consent=False)
    start(newer)
    assert probe_of(newer, "cloud") and probe_of(newer, "main")
    rotated = both(tmp_path, foods_json, cloud=cloud_env(model="claude-opus", api_key="sk-cloud-rotated-0123456789abcdef"))
    start(rotated)  # a new key, same URL and model: the stored test was for the old key
    assert probe_of(rotated, "cloud") is None and probe_of(rotated, "main")
    seed(rotated, consent=False)
    both_rotated = both(tmp_path, foods_json, api_key="sk-local-rotated-0123456789abcdef", cloud=cloud_env(model="claude-opus", api_key="sk-cloud-rotated-0123456789abcdef"))
    start(both_rotated)
    assert probe_of(both_rotated, "main") is None and probe_of(both_rotated, "cloud")  # each key counts for its own provider only
    seed(both_rotated, consent=False)
    start(both(tmp_path, foods_json, api_key="sk-local-rotated-0123456789abcdef", cloud=cloud_env(model="claude-opus", vision_model=None,
                                                                                                api_key="sk-cloud-rotated-0123456789abcdef")))
    assert probe_of(both_rotated, "cloud") is None and probe_of(both_rotated, "main")  # a new vision model is a change too


def test_unsetting_a_variable_deletes_only_its_row_and_its_consents(tmp_path, foods_json):
    start(both(tmp_path, foods_json))
    ids = seed(both(tmp_path, foods_json))
    only_main = make_settings(tmp_path, foods_json, ai=AiEnv(**local_env()))
    start(only_main)
    assert set(rows(only_main)) == {"main"} and rows(only_main)["main"]["id"] == ids["main"]
    assert consents(only_main) == {ids["main"]: 1}
    start(both(tmp_path, foods_json))  # set again: a new row, and nobody has agreed to it
    assert rows(only_main)["cloud"]["id"] != ids["cloud"] and consents(only_main) == {ids["main"]: 1}
    only_cloud = cloud_only(tmp_path, foods_json)
    start(only_cloud)
    assert set(rows(only_cloud)) == {"cloud"}
    start(make_settings(tmp_path, foods_json))
    assert rows(only_cloud) == {}
    conn = sqlite3.connect(only_cloud.db_path)
    assert conn.execute("SELECT COUNT(*) FROM ai_providers").fetchone()[0] == 0
    conn.close()


def test_an_admins_own_provider_is_left_alone_by_the_sync(tmp_path, foods_json):
    settings = both(tmp_path, foods_json)
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        r = c.post("/api/admin/ai-providers", json={"preset": "ollama", "model": "gemma", "base_url": GPU_URL.replace("gpu.lan:4000", "gpu.lan:4000")})
        assert r.status_code == 201, r.text
        own = r.json()["id"]
    start(make_settings(tmp_path, foods_json))  # both variables unset
    conn = sqlite3.connect(settings.db_path)
    assert [tuple(x) for x in conn.execute("SELECT id, locked, env_slot FROM ai_providers")] == [(own, 0, None)]
    conn.close()


# --------------------------------------------------------------------------- #
# The consent line
# --------------------------------------------------------------------------- #


def test_no_existing_policy_line_or_version_changed():
    """Changing a line would ask everyone again (docs/ai.md "What is sent"); the proxy line is new."""
    assert P.POLICY_VERSION == "2026-10-06.1"
    assert dict(P.POLICY_LINES) == {
        "openai": "OpenAI does not use API data for training; it keeps abuse-monitoring logs for up to 30 days.",
        "openrouter": "OpenRouter routes the request only to model providers that do not collect data.",
        "nous_portal": "Nous Research's API receives the request; read their privacy policy before agreeing.",
        "self_hosted": SELF_HOSTED_LINE,
        "agent": ("Your admin's Hermes agent keeps a transcript and forwards the request to the model provider it is set up with; "
                  "your admin can read what is sent."),
        "custom": "Goes to a server your admin chose; whoever runs that server can read what is sent.",
        "user_custom": "Goes to the server you entered; whoever runs that server can read what is sent.",
    }
    for name, preset in P.PRESETS.items():  # with no company named, every preset says what it always said
        assert P.policy_line(preset, scope="shared") == P.POLICY_LINES[preset.policy_key], name
        assert P.policy_line(preset, scope="shared", upstream=None) == P.POLICY_LINES[preset.policy_key], name


def test_a_proxy_to_a_company_says_so_in_the_existing_style():
    litellm = P.get("litellm")
    assert P.policy_line(litellm, scope="shared", upstream="Anthropic") == PROXY_LINE
    assert P.policy_line(P.get("openai_compatible"), scope="shared", upstream="Mistral AI") == (
        "Goes through your admin's proxy to Mistral AI. Mistral AI receives what is sent, under its own terms; your admin can read it too.")
    assert P.policy_line(P.get("vllm"), scope="shared", upstream="Z.ai").startswith("Goes through your admin's proxy to Z.ai.")
    # the company is named only for a shared server that can forward; nothing else changes
    assert P.policy_line(P.get("openai"), scope="shared", upstream="Anthropic") == P.POLICY_LINES["openai"]
    assert P.policy_line(P.get("hermes"), scope="shared", upstream="Anthropic") == P.POLICY_LINES["agent"]
    assert P.policy_line(P.get("openai_compatible"), scope="user", upstream="Anthropic") == P.POLICY_LINES["user_custom"]


def test_the_cloud_provider_asks_for_consent_with_the_proxy_line_and_the_first_one_keeps_its_line(tmp_path, foods_json):
    with TestClient(create_app(both(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        assert route(c, meal_ideas="cloud", photos="local").status_code == 200
        ready(c, {})
        providers = {p["env"]: p for p in c.get("/api/admin/ai-providers").json()["providers"]}
        assert providers["AI_CLOUD_PROVIDER"]["policy"] == PROXY_LINE and providers["AI_CLOUD_PROVIDER"]["upstream"] == "Anthropic"
        assert providers["AI_PROVIDER"]["policy"] == SELF_HOSTED_LINE and providers["AI_PROVIDER"]["upstream"] is None
        local, cloud = FakeProvider(address="10.0.0.5"), FakeProvider(address="10.0.0.5")
        with attach_routed(c.app, local=local, cloud=cloud, local_host="gpu.lan"):
            ask = next_meal(c)
        assert ask.status_code == 409 and ask.json()["consent_required"] is True
        sheet = ask.json()["consent"]
        assert sheet["policy"] == PROXY_LINE and sheet["upstream"] == "Anthropic" and sheet["host"] == "litellm.lan:4000"
        assert sheet["provider_id"] == providers["AI_CLOUD_PROVIDER"]["id"] and sheet["policy_version"] == P.POLICY_VERSION
        assert local.requests == [] and cloud.requests == []
        status = c.get("/api/ai/status").json()
        assert status["routes"]["meal_ideas"]["runs_on"]["policy"] == PROXY_LINE  # what "Runs on ..." carries
        assert status["routes"]["photos"]["runs_on"]["policy"] == SELF_HOSTED_LINE
        shared = {p["id"]: p["policy"] for p in c.get("/api/me/ai").json()["shared"]}  # what a person is shown
        assert shared == {providers["AI_CLOUD_PROVIDER"]["id"]: PROXY_LINE, providers["AI_PROVIDER"]["id"]: SELF_HOSTED_LINE}


def test_without_a_company_a_cloud_preset_keeps_its_own_line(tmp_path, foods_json):
    settings = both(tmp_path, foods_json, cloud=cloud_env(provider="openai", base_url=None, model="gpt-6-luna", upstream=None, api_key=CLOUD_KEY))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        providers = {p["env"]: p for p in c.get("/api/admin/ai-providers").json()["providers"]}
        assert providers["AI_CLOUD_PROVIDER"]["policy"] == P.POLICY_LINES["openai"] and providers["AI_CLOUD_PROVIDER"]["upstream"] is None


def test_the_company_name_is_shown_as_text_by_the_provider_row():
    ai_js = open("app/static/js/views/ai.js", encoding="utf-8").read()
    assert "p.upstream ? h('p', { class: 'muted small' }, p.policy) : null" in ai_js  # h() sets textContent: a name cannot add markup


def test_a_person_who_agreed_must_agree_again_when_the_company_changes(tmp_path, foods_json):
    settings = both(tmp_path, foods_json)
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        assert route(c, meal_ideas="cloud").status_code == 200
        cloud_id = next(p["id"] for p in c.get("/api/admin/ai-providers").json()["providers"] if p["env"] == "AI_CLOUD_PROVIDER")
        local_id = next(p["id"] for p in c.get("/api/admin/ai-providers").json()["providers"] if p["env"] == "AI_PROVIDER")
        ready(c, {cloud_id: ("text",), local_id: ("photos",)})
        assert {x["provider_id"] for x in c.get("/api/me/ai").json()["consents"]} == {cloud_id, local_id}
    changed = both(tmp_path, foods_json, cloud=cloud_env(upstream="OpenAI"))
    with TestClient(create_app(changed), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert {x["provider_id"] for x in c.get("/api/me/ai").json()["consents"]} == {local_id}
        r = next_meal(c)
        assert r.status_code == 409 and r.json()["consent"]["policy"].startswith("Goes through your admin's LiteLLM proxy to OpenAI. OpenAI receives")


# --------------------------------------------------------------------------- #
# The prompt budget follows the role
# --------------------------------------------------------------------------- #


def config_of(settings, slot: str):
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        state = c.app.state
        conn = sqlite3.connect(settings.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return K.to_config(K.env_row(conn, slot), state.keyring, settings, user_id=1)
        finally:
            conn.close()


def test_the_cloud_slot_gets_the_cloud_budget_even_for_a_self_hosted_preset(tmp_path, foods_json):
    cloud = config_of(both(tmp_path, foods_json), "cloud")
    assert cloud.context_tokens == 32_768 and cloud.preset == "litellm" and cloud.upstream == "Anthropic"
    assert cloud.api_key == CLOUD_KEY and cloud.local_only is False and cloud.key_scope == "shared" and cloud.net_scope == "shared"


def test_the_first_provider_keeps_the_budget_of_its_preset(tmp_path, foods_json):
    settings = both(tmp_path, foods_json)
    main = config_of(settings, "main")
    assert main.context_tokens == 8_192 and main.upstream is None and main.api_key == LOCAL_KEY
    explicit = both(tmp_path, foods_json, context_tokens=12_000)
    assert config_of(explicit, "main").context_tokens == 12_000


def test_the_cloud_budget_can_be_set_and_a_cloud_preset_keeps_its_default(tmp_path, foods_json):
    assert config_of(both(tmp_path, foods_json, cloud=cloud_env(context_tokens=50_000)), "cloud").context_tokens == 50_000
    assert config_of(both(tmp_path, foods_json, cloud=cloud_env(provider="openrouter", base_url=None, model="m", upstream=None)),
                     "cloud").context_tokens == 32_768


# --------------------------------------------------------------------------- #
# The admin API: both rows are locked, the roles are fixed
# --------------------------------------------------------------------------- #


def test_both_rows_are_listed_locked_with_their_variable_and_a_write_only_key(tmp_path, foods_json):
    with TestClient(create_app(both(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        listing = c.get("/api/admin/ai-providers")
        assert listing.status_code == 200 and LOCAL_KEY not in listing.text and CLOUD_KEY not in listing.text
        data = listing.json()
        assert data["env_provider"] is True and data["env_cloud_provider"] is True
        by_env = {p["env"]: p for p in data["providers"]}
        assert set(by_env) == {"AI_PROVIDER", "AI_CLOUD_PROVIDER"}
        assert [p["env"] for p in data["providers"]] == ["AI_PROVIDER", "AI_CLOUD_PROVIDER"]  # the first provider first
        for p in by_env.values():
            assert p["locked"] is True and p["scope"] == "shared" and p["key"] == {"set": True, "source": "env", "locked": True}
        assert by_env["AI_PROVIDER"]["role"] == "local" and by_env["AI_CLOUD_PROVIDER"]["role"] == "cloud"
        assert by_env["AI_PROVIDER"]["private_host"] is True and by_env["AI_CLOUD_PROVIDER"]["private_host"] is True
        assert by_env["AI_CLOUD_PROVIDER"]["context_tokens"] == 32_768 and by_env["AI_PROVIDER"]["context_tokens"] is None


def test_the_overview_shows_the_roles_as_set_by_the_environment(tmp_path, foods_json):
    with TestClient(create_app(both(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        o = c.get("/api/admin/ai-routing").json()
        assert o["env_role"] == "local" and o["env_cloud"] is True
        by_env = {p["env"]: p for p in o["providers"]}
        assert o["roles"]["local"]["id"] == by_env["AI_PROVIDER"]["id"] and o["roles"]["cloud"]["id"] == by_env["AI_CLOUD_PROVIDER"]["id"]
        assert by_env["AI_PROVIDER"]["role"] == "local" and by_env["AI_CLOUD_PROVIDER"]["role"] == "cloud"
        assert all(p["locked"] for p in o["providers"]) and o["writable"] is True
    with TestClient(create_app(cloud_only(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        o = c.get("/api/admin/ai-routing").json()
        assert o["env_role"] is None and o["env_cloud"] is True and o["roles"]["local"] is None and o["roles"]["cloud"]["host"] == "litellm.lan:4000"
    with TestClient(create_app(make_settings(tmp_path / "plain", foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert c.get("/api/admin/ai-routing").json()["env_cloud"] is False


def test_neither_row_can_be_edited_or_deleted_and_the_message_names_the_variable(tmp_path, foods_json):
    with TestClient(create_app(both(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        by_env = {p["env"]: p["id"] for p in c.get("/api/admin/ai-providers").json()["providers"]}
        body = {"preset": "litellm", "model": "other", "base_url": CLOUD_URL}
        for var, pid in by_env.items():
            r = c.put(f"/api/admin/ai-providers/{pid}", json=body)
            assert r.status_code == 409 and r.json()["locked"] is True and f"({var})" in r.json()["detail"], r.text
            r = c.delete(f"/api/admin/ai-providers/{pid}")
            assert r.status_code == 409 and r.json()["locked"] is True and f"({var})" in r.json()["detail"] and "unset it there" in r.json()["detail"]
        assert len(c.get("/api/admin/ai-providers").json()["providers"]) == 2
        assert {r["id"] for r in db(c, "SELECT id FROM ai_providers WHERE locked = 1")} == set(by_env.values())


def test_the_cloud_role_cannot_be_changed_here_and_the_message_names_ai_cloud_provider(tmp_path, foods_json):
    with TestClient(create_app(both(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        by_env = {p["env"]: p["id"] for p in c.get("/api/admin/ai-providers").json()["providers"]}
        extra = c.post("/api/admin/ai-providers", json={"preset": "openai", "model": "gpt-6-luna", "api_key": "sk-spare-0123456789abcdefghijk"})
        spare = extra.json()["id"]
        for body in ({"cloud_provider": spare}, {"cloud_provider": 0}, {"cloud_provider": by_env["AI_CLOUD_PROVIDER"]}):
            r = route(c, **body)
            assert r.status_code == 409 and r.json()["locked"] is True and r.json()["field"] == "cloud_provider", (body, r.text)
            assert "AI_CLOUD_PROVIDER" in r.json()["detail"]
        r = route(c, local_provider=spare)  # the local role is the first provider's, from AI_PROVIDER_ROLE
        assert r.status_code == 409 and r.json()["locked"] is True and "AI_PROVIDER_ROLE=local" in r.json()["detail"]
        r = route(c, local_provider=by_env["AI_CLOUD_PROVIDER"])
        assert r.status_code == 409 and r.json()["locked"] is True and r.json()["field"] == "local_provider"
        r = route(c, local_provider=by_env["AI_PROVIDER"], photos="off")
        assert r.status_code == 409 and "AI_PROVIDER_ROLE=local" in r.json()["detail"]
        o = c.get("/api/admin/ai-routing").json()
        assert o["roles"]["cloud"]["id"] == by_env["AI_CLOUD_PROVIDER"] and o["roles"]["local"]["id"] == by_env["AI_PROVIDER"]
        assert [f["route"] for f in o["features"] if f["feature"] == "photos"] == ["local"]  # a refused change applied nothing
        assert route(c, meal_ideas="cloud", chat="cloud").status_code == 200  # the features stay the admin's to route


def test_a_cloud_only_server_leaves_the_local_role_to_the_admin(tmp_path, foods_json):
    with TestClient(create_app(cloud_only(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        cloud_id = next(p["id"] for p in c.get("/api/admin/ai-providers").json()["providers"] if p["locked"])
        r = c.post("/api/admin/ai-providers", json={"preset": "ollama", "model": "gemma", "base_url": GPU_URL})
        assert r.status_code == 201, r.text
        ollama = r.json()["id"]
        assert route(c, local_provider=ollama).status_code == 200
        r = route(c, local_provider=cloud_id)  # the cloud provider is never the local AI
        assert r.status_code == 409 and r.json()["locked"] is True and r.json()["field"] == "local_provider"
        assert "AI_CLOUD_PROVIDER" in r.json()["detail"] and "cannot hold another role" in r.json()["detail"]
        r = route(c, cloud_provider=ollama)
        assert r.status_code == 409 and "AI_CLOUD_PROVIDER" in r.json()["detail"]
        roles = c.get("/api/admin/ai-routing").json()["roles"]
        assert roles["local"]["id"] == ollama and roles["cloud"]["id"] == cloud_id


def test_the_setting_that_names_the_roles_cannot_make_the_cloud_provider_local_either(tmp_path, foods_json):
    """Not even a value written straight into the settings: the environment's role wins in ``role_row``."""
    from app.ai import routing as R

    with TestClient(create_app(cloud_only(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        state = c.app.state
        conn = sqlite3.connect(state.settings.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cloud = K.env_row(conn, "cloud")
            state.ai.store.set_instance(conn, "ai.route.local_provider", int(cloud["id"]), updated_by=None)
            conn.commit()
            assert R.role_row(conn, state.ai.store, state.settings, "local") is None
            assert int(R.role_row(conn, state.ai.store, state.settings, "cloud")["id"]) == int(cloud["id"])
            assert R.role_of(conn, state.ai.store, state.settings, cloud) == "cloud"
        finally:
            conn.close()


def test_a_connection_test_of_each_row_uses_its_own_key(tmp_path, foods_json):
    with TestClient(create_app(both(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        by_env = {p["env"]: p["id"] for p in c.get("/api/admin/ai-providers").json()["providers"]}
        models = {"status": 200, "headers": {"Content-Type": "application/json"}, "body": {"data": [{"id": "m"}]}}

        def answer(request):  # the model list, and a reply to every test question
            return models if request.url.path.endswith("/models") else chat({"ok": "yes"})

        local, cloud = FakeProvider(route=answer, address="10.0.0.5"), FakeProvider(route=answer, address="10.0.0.5")
        with attach_routed(c.app, local=local, cloud=cloud, local_host="gpu.lan"):
            for var in ("AI_PROVIDER", "AI_CLOUD_PROVIDER"):
                c.post(f"/api/admin/ai-providers/{by_env[var]}/probe")
        assert local.requests and cloud.requests
        assert {r.headers["authorization"] for r in local.requests} == {f"Bearer {LOCAL_KEY}"}
        assert {r.headers["authorization"] for r in cloud.requests} == {f"Bearer {CLOUD_KEY}"}
        stored = {r["id"]: json.loads(r["probe_json"]) for r in db(c, "SELECT id, probe_json FROM ai_providers WHERE locked = 1")}
        keyring = c.app.state.keyring
        assert stored[by_env["AI_PROVIDER"]]["key_fp"] == K.key_fingerprint(keyring, LOCAL_KEY)
        assert stored[by_env["AI_CLOUD_PROVIDER"]]["key_fp"] == K.key_fingerprint(keyring, CLOUD_KEY)
        assert LOCAL_KEY not in json.dumps(stored) and CLOUD_KEY not in json.dumps(stored)
