"""Provider presets (note 04 R4, F4; §9 A1 for ``hermes``). Pure data.

A preset fixes one backend's quirks (token field, structured-output mode, temperature, timeouts, extra
body fields) so an admin or a person only picks the preset and fills in the blanks (base URL, model,
key). Every call uses the OpenAI Chat Completions wire format (``POST {base}/chat/completions``,
``stream: false``, no ``tools``, no ``n``), which every backend here implements (F3).

``kind`` decides the consent policy line (note 04 R9) and the default prompt budget
(``AI_CONTEXT_TOKENS``: 8,192 tokens for self-hosted backends, 32,768 for cloud ones):

* ``cloud``: a company's API (OpenAI, OpenRouter, Nous Portal);
* ``self_hosted``: a model server on the admin's hardware (Ollama, LM Studio, llama.cpp, vLLM, LiteLLM);
* ``agent``: the admin's Hermes Agent (keeps transcripts; **only** a dedicated, tool-free profile,
  checked with ``GET {base}/toolsets`` before use: contract item 13, §9 A1);
* ``custom``: any other OpenAI-compatible server the admin names.

``user_allowed``: presets a person may choose for their **own** key (``ai.user_keys_allowed``). A
person's own custom URL (``openai_compatible``) needs ``ai.allow_user_base_url`` too, and is then
https on port 443 to public addresses only (R5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping

Kind = Literal["cloud", "self_hosted", "agent", "custom"]
StructuredMode = Literal["json_schema", "json_object", "prompt"]
PresetStructured = Literal["json_schema", "json_object", "prompt", "probe"]
STRUCTURED_MODES: tuple[str, ...] = ("json_schema", "json_object", "prompt")
STRUCTURED_SETTINGS: tuple[str, ...] = ("auto", *STRUCTURED_MODES)
REASONING_EFFORTS: tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

# Consent policy lines (R9). Changing one bumps POLICY_VERSION, so everybody is asked again.
POLICY_VERSION = "2026-10-27.1"  # 2026-10-27.1: "Meal data" also covers the foods and amounts of a recipe (AI recipes)
POLICY_LINES: Mapping[str, str] = MappingProxyType({
    "openai": "OpenAI does not use API data for training; it keeps abuse-monitoring logs for up to 30 days.",
    "openrouter": "OpenRouter routes the request only to model providers that do not collect data.",
    "nous_portal": "Nous Research's API receives the request; read their privacy policy before agreeing.",
    "self_hosted": "Runs on your admin's hardware; your admin can read what is sent.",
    "agent": (
        "Your admin's Hermes agent keeps a transcript and forwards the request to the model provider it is "
        "set up with; your admin can read what is sent."
    ),
    "custom": "Goes to a server your admin chose; whoever runs that server can read what is sent.",
    "user_custom": "Goes to the server you entered; whoever runs that server can read what is sent.",
})

# A server your admin runs that forwards to a company (a LiteLLM proxy in front of a cloud model) is the cloud AI, whatever its preset:
# "Runs on your admin's hardware" would be false for it. ``AI_CLOUD_UPSTREAM`` names the company, and the consent sheet says so. This
# is a new line built from that name; none of the lines above changes, so nobody is asked again for a provider they already agreed to.
PROXY_POLICY = "Goes through your admin's {proxy} to {upstream}. {upstream} receives what is sent, under its own terms; your admin can read it too."
PROXY_NAMES: Mapping[str, str] = MappingProxyType({"litellm": "LiteLLM proxy"})  # any other preset: "proxy"
UPSTREAM_KINDS: tuple[str, ...] = ("self_hosted", "custom")

DEFAULT_CONTEXT_TOKENS: Mapping[str, int] = MappingProxyType({"cloud": 32_768, "self_hosted": 8_192, "agent": 8_192, "custom": 8_192})


@dataclass(frozen=True)
class Preset:
    """One backend's defaults (R4 table)."""

    name: str
    label: str
    kind: Kind
    base_url: str | None  # None = the admin must enter one
    token_field: Literal["max_completion_tokens", "max_tokens"]
    structured: PresetStructured  # "probe": decided by "Test connection"; "prompt" until then
    temperature: float | None
    reasoning_effort: str | None
    timeout_s: float  # read timeout
    extra_body: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    default_model: str | None = None
    user_allowed: bool = False  # a person may pick it with their own key
    key_required: bool = True
    placeholder_key: str | None = None  # sent as the bearer value when no key is set (Ollama ignores it)
    tool_check: bool = False  # hermes: refuse unless GET {base}/toolsets shows no enabled tools
    photos_by_default: bool = True  # hermes: photo features only with ai.vision_allow_agent (note 03 B10)

    @property
    def policy_key(self) -> str:
        if self.kind in ("self_hosted", "agent", "custom"):
            return self.kind
        return self.name

    @property
    def default_structured(self) -> StructuredMode:
        """The mode used before a probe has decided (``probe`` presets start with prompt-only JSON)."""
        return "prompt" if self.structured == "probe" else self.structured

    @property
    def context_tokens(self) -> int:
        return DEFAULT_CONTEXT_TOKENS[self.kind]

    @property
    def can_proxy(self) -> bool:
        """A self-hosted or custom server can sit in front of a company's model (``AI_CLOUD_UPSTREAM`` then names it)."""
        return self.kind in UPSTREAM_KINDS


def _frozen(d: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(d))


PRESETS: Mapping[str, Preset] = MappingProxyType({p.name: p for p in (
    Preset(
        name="openai", label="OpenAI", kind="cloud", base_url="https://api.openai.com/v1",
        token_field="max_completion_tokens", structured="json_schema", temperature=None, reasoning_effort="low",
        timeout_s=45.0, extra_body=_frozen({"store": False}), default_model="gpt-6-luna", user_allowed=True,
    ),
    Preset(
        name="openrouter", label="OpenRouter", kind="cloud", base_url="https://openrouter.ai/api/v1",
        token_field="max_tokens", structured="json_schema", temperature=0.2, reasoning_effort=None, timeout_s=60.0,
        extra_body=_frozen({"provider": {"data_collection": "deny", "require_parameters": True}}), user_allowed=True,
    ),
    Preset(
        name="nous_portal", label="Nous Portal", kind="cloud", base_url="https://inference-api.nousresearch.com/v1",
        token_field="max_tokens", structured="probe", temperature=0.2, reasoning_effort=None, timeout_s=60.0,
        user_allowed=True,
    ),
    Preset(
        name="ollama", label="Ollama", kind="self_hosted", base_url="http://ollama:11434/v1",
        token_field="max_tokens", structured="json_schema", temperature=0.2, reasoning_effort="none", timeout_s=120.0,
        key_required=False, placeholder_key="ollama",
    ),
    Preset(
        name="lmstudio", label="LM Studio", kind="self_hosted", base_url="http://host.containers.internal:1234/v1",
        token_field="max_tokens", structured="json_schema", temperature=0.2, reasoning_effort=None, timeout_s=120.0,
        key_required=False, placeholder_key="lm-studio",
    ),
    Preset(
        name="llamacpp", label="llama.cpp server", kind="self_hosted", base_url="http://llama:8080/v1",
        token_field="max_tokens", structured="probe", temperature=0.2, reasoning_effort="none", timeout_s=120.0,
        key_required=False,
    ),
    Preset(
        name="vllm", label="vLLM", kind="self_hosted", base_url="http://vllm:8000/v1",
        token_field="max_tokens", structured="json_schema", temperature=0.2, reasoning_effort=None, timeout_s=60.0,
        key_required=False,
    ),
    Preset(
        name="litellm", label="LiteLLM proxy", kind="self_hosted", base_url="http://litellm:4000/v1",
        token_field="max_tokens", structured="json_schema", temperature=0.2, reasoning_effort=None, timeout_s=60.0,
    ),
    Preset(
        # The dedicated tool-less "kidney" profile on its own port (R10), never the main profile on 8642.
        name="hermes", label="Hermes Agent (tool-free profile)", kind="agent",
        base_url="http://host.containers.internal:8643/v1", token_field="max_tokens", structured="prompt",
        temperature=None, reasoning_effort=None, timeout_s=180.0, tool_check=True, photos_by_default=False,
    ),
    Preset(
        name="openai_compatible", label="Other OpenAI-compatible server", kind="custom", base_url=None,
        token_field="max_tokens", structured="probe", temperature=0.2, reasoning_effort=None, timeout_s=60.0,
        key_required=False,
    ),
)})

# Presets a person may use with their own key when ai.user_keys_allowed is on (R4).
USER_PRESETS: tuple[str, ...] = tuple(name for name, p in PRESETS.items() if p.user_allowed)
# ... plus this one when ai.allow_user_base_url is on (https:443 to public addresses only).
USER_CUSTOM_PRESET = "openai_compatible"


def get(name: str) -> Preset:
    """The preset called ``name`` (``KeyError`` with the known names otherwise)."""
    try:
        return PRESETS[name]
    except KeyError:
        raise KeyError(f"unknown AI preset {name!r}; use one of {', '.join(PRESETS)}") from None


PROXY_CHAIN_POLICY = ("Goes through your admin's {proxy} to {first}{rest}. Each company receives what is sent to it, under its own "
                      "terms; your admin can read it too.")


def proxy_line(preset: Preset, upstream: str) -> str:
    """The consent line for a server your admin runs that forwards to ``upstream``: one company's plain name, or several separated by
    ";" in the order the proxy tries them (the next only when the one before is busy or down)."""
    proxy = PROXY_NAMES.get(preset.name, "proxy")
    names = [n.strip() for n in upstream.split(";") if n.strip()]
    if len(names) <= 1:
        return PROXY_POLICY.format(proxy=proxy, upstream=upstream.strip())
    rest = "".join(f", or to {n} when the one before is busy or down" for n in names[1:])
    return PROXY_CHAIN_POLICY.format(proxy=proxy, first=names[0], rest=rest)


def policy_line(preset: Preset, *, scope: str, upstream: str | None = None) -> str:
    """The consent sheet's line for ``preset`` (a person's own custom server gets its own wording).

    ``upstream``: the company a shared self-hosted or custom server forwards to (``AI_CLOUD_UPSTREAM``). It replaces "Runs on your
    admin's hardware", which would be untrue; it is ignored for every other preset and for a person's own server."""
    if scope == "user" and preset.kind == "custom":
        return POLICY_LINES["user_custom"]
    if upstream and scope == "shared" and preset.can_proxy:
        return proxy_line(preset, upstream)
    return POLICY_LINES[preset.policy_key]
