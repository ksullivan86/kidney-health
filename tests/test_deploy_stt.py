"""The speech-to-text overlay (``deploy/compose.stt-whisper.yaml``) keeps the container isolated: an internal network
with no way out, an image pinned by digest (or the clearly marked placeholder, never a tag alone), a read-only root, no
capabilities, no privilege gain, a non-root user, limits, a healthcheck, no published port, and the app pointed at it
under the same address rules as an AI provider. Static checks, no network, no container runtime."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / "deploy" / "compose.stt-whisper.yaml"
TEXT = PATH.read_text(encoding="utf-8")
FLAT = re.sub(r"\s*\n#\s*", " ", TEXT)  # the header comment with its line breaks joined
DOC = yaml.safe_load(TEXT)
STT = DOC["services"]["stt"]
APP = DOC["services"]["kidney-health"]
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
PLACEHOLDER = "@sha256:<pin-the-digest-you-verified>"


def active_lines() -> str:
    return "\n".join(line for line in TEXT.splitlines() if not line.lstrip().startswith("#"))


def test_the_image_is_pinned_by_digest_or_carries_the_marked_placeholder_and_never_a_floating_tag():
    image = STT["image"]
    assert DIGEST.search(image) or image.endswith(PLACEHOLDER), image
    name = image.split("@", 1)[0]
    assert ":" in name.rsplit("/", 1)[-1], "a version tag names the pin"
    assert not re.search(r":(latest|main|master|edge|nightly|stable)\b", image), image
    if image.endswith(PLACEHOLDER):  # the placeholder must say how to replace it
        for phrase in ("pin-the-digest-you-verified", "crane digest", "will not start with the placeholder", "bump the pin by hand"):
            assert phrase in FLAT, phrase


def test_the_container_is_hardened():
    assert STT["read_only"] is True
    assert STT["cap_drop"] == ["ALL"] and "cap_add" not in STT
    assert "no-new-privileges:true" in STT["security_opt"]
    user = str(STT["user"])
    assert re.fullmatch(r"\d+:\d+", user) and not user.startswith("0:") and user != "0:0", user  # not root
    for key in ("pids_limit", "mem_limit", "cpus", "healthcheck", "tmpfs"):
        assert key in STT, key
    assert any(str(t).startswith("/tmp:") and "noexec" in t and "nosuid" in t and "nodev" in t for t in STT["tmpfs"])
    assert STT["healthcheck"]["test"][0] == "CMD" and "/health" in " ".join(STT["healthcheck"]["test"])
    for banned in ("privileged", "network_mode", "pid", "ipc", "devices", "sysctls", "extra_hosts", "dns"):
        assert banned not in STT, banned


def test_nothing_is_published_and_no_socket_or_host_path_is_mounted():
    assert "ports" not in STT and "expose" not in STT
    assert "ports:" not in active_lines()
    assert not re.search(r"podman\.sock|docker\.sock|/var/run", active_lines())
    for volume in STT["volumes"]:
        assert re.fullmatch(r"stt-models:/[^:]+:ro", volume), volume  # a named volume, read-only while running
    assert DOC["volumes"] == {"stt-models": {}}


def test_the_container_has_no_way_out_and_only_the_app_can_reach_it():
    assert STT["networks"] == ["stt"]  # not the default network: it has the internet
    assert DOC["networks"]["stt"] == {"internal": True}
    assert APP["networks"] == ["default", "stt"]
    assert STT["environment"]["HF_HUB_OFFLINE"] == "1" and STT["environment"]["ENABLE_UI"] == "false"


def test_the_app_points_at_it_under_the_ai_address_rules_and_holds_no_secret_in_the_environment():
    env = APP["environment"]
    assert env["STT_BASE_URL"] == "http://stt:8000/v1" and env["STT_MODEL"]
    assert env["AI_PRIVATE_HOSTS"] == "stt:8000"  # the same allowlist an Ollama host needs; no wildcard
    assert "*" not in env["AI_PRIVATE_HOSTS"] and "/0" not in env["AI_PRIVATE_HOSTS"]
    assert not any(re.search(r"(KEY|SECRET|PASSWORD|TOKEN)$", name) for name in env), sorted(env)  # a key is a file secret
    assert "AI_VOICE_ENABLED" not in env  # the admin's switch stays off until the admin turns it on


def test_the_header_explains_the_model_download_and_that_the_container_must_not_reach_the_internet():
    for phrase in ("MUST NOT REACH THE INTERNET", "ONCE, before the first start", "snapshot_download", "HF_HUB_OFFLINE", "internal",
                   "Never mount podman.sock", "Test transcription", "AI_PRIVATE_HOSTS", "STT_API_KEY_FILE"):
        assert phrase in FLAT, phrase


@pytest.mark.parametrize("name", ["deploy/README.md", "docs/deployment.md", "docs/ai.md"])
def test_the_overlay_is_documented(name):
    assert "compose.stt-whisper.yaml" in (REPO / name).read_text(encoding="utf-8"), name
