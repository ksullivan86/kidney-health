"""deploy/compose.yaml passes the v0.3 settings through as ``${NAME:-}``, so an operator who leaves
``deploy/.env`` alone sends every one of them to the app as an EMPTY string. These tests keep three
things true together: every pass-through is explained in ``deploy/.env.example``, no secret travels
as an environment variable, and an empty value means "unset" to the app (nothing locked in Settings →
Admin, AI and Open Food Facts stay off, guidance keeps its default, no outbound feature starts).
"""
from __future__ import annotations

import re
from pathlib import Path

from app import config
from app.settings_registry import REGISTRY
from app.settings_store import SettingsStore

REPO = Path(__file__).resolve().parent.parent
COMPOSE = (REPO / "deploy" / "compose.yaml").read_text(encoding="utf-8")
ENV_EXAMPLE = (REPO / "deploy" / ".env.example").read_text(encoding="utf-8")
QUADLET = (REPO / "deploy" / "quadlet" / "kidney-health.container").read_text(encoding="utf-8")
K8S = (REPO / "deploy" / "k8s" / "deployment.yaml").read_text(encoding="utf-8")

PASSTHROUGH = re.compile(r"^ {6}([A-Z][A-Z0-9_]*): \$\{\1:-\}$", re.M)
V03_KEYS = {
    "OFF_ENABLED", "OFF_CONTACT", "GUIDANCE_ENABLED", "AI_ENABLED", "AI_PROVIDER", "AI_BASE_URL", "AI_MODEL",
    "AI_VISION_MODEL", "AI_PRIVATE_HOSTS", "HANDBOOK_PUBLIC_URL", "PASSWORD_BREACH_CHECK",
}
EGRESS_HOSTS = ("api.nal.usda.gov", "world.openfoodfacts.org", "api.pwnedpasswords.com")


def passthrough_names() -> list[str]:
    return PASSTHROUGH.findall(COMPOSE)


def test_compose_passes_the_v03_settings_through_and_env_example_explains_each():
    names = passthrough_names()
    assert V03_KEYS <= set(names), sorted(V03_KEYS - set(names))
    for name in names:
        assert re.search(rf"^{name}=", ENV_EXAMPLE, re.M), f"{name} is passed through by compose.yaml but not in .env.example"


def test_no_secret_is_passed_as_an_environment_variable():
    for name in passthrough_names():
        assert not re.search(r"(KEY|SECRET|PASSWORD|TOKEN)$", name), name
    for text in (COMPOSE, ENV_EXAMPLE, QUADLET, K8S):
        active = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        assert not re.search(r"\bAI_API_KEY\s*[:=]", active)
    # The cloud AI key is shown only as a file secret, the way SECRET_KEY and the USDA key are given.
    assert "# AI_API_KEY_FILE: /run/secrets/ai_api_key" in COMPOSE and "#   file: ./secrets/ai_api_key" in COMPOSE
    assert "# Environment=AI_API_KEY_FILE=/run/secrets/ai_api_key" in QUADLET
    assert "value: /run/secrets/kidney-health/ai_api_key" in K8S


def test_every_deploy_profile_names_the_optional_egress():
    for label, text in (("compose", COMPOSE), ("quadlet", QUADLET), (".env.example", ENV_EXAMPLE)):
        for host in EGRESS_HOSTS:
            if label == ".env.example" and host == "api.nal.usda.gov":
                continue  # the USDA key is a file secret, explained in compose.yaml's header
            assert host in text, (label, host)
        assert "docs/network-allowlist.md" in text, label
    networkpolicy = (REPO / "deploy" / "k8s" / "networkpolicy.yaml").read_text(encoding="utf-8")
    for needle in ("USDA", "Open Food Facts", "AI"):
        assert needle in networkpolicy, needle


def test_blank_pass_through_values_mean_unset(tmp_path):
    env = {name: "" for name in passthrough_names()}
    env["DATA_DIR"] = str(tmp_path / "data")

    settings = config.load_settings(env)
    assert settings.handbook_public_url is None
    assert settings.password_breach_check is False

    ai = config.load_ai_env(env)
    assert (ai.provider, ai.base_url, ai.model, ai.vision_model, ai.private_hosts) == (None, None, None, None, ())

    store = SettingsStore(env=env)
    assert store.validate_env_locks() == []
    for definition in REGISTRY.values():
        assert store.env_value(definition) == (False, None), definition.key
    assert REGISTRY["food.off_enabled"].default is False
    assert REGISTRY["ai.enabled"].default is False
    assert REGISTRY["guidance.enabled"].default is True


def test_a_set_pass_through_value_locks_the_setting(tmp_path):
    env = {name: "" for name in passthrough_names()}
    env.update(OFF_ENABLED="true", GUIDANCE_ENABLED="false", OFF_CONTACT="admin@example.net")
    store = SettingsStore(env=env)
    assert sorted(store.validate_env_locks()) == ["food.off_contact", "food.off_enabled", "guidance.enabled"]
    assert store.env_value(REGISTRY["guidance.enabled"]) == (True, False)
