# Optional AI: what it does, what is sent, how to set it up and turn it off

Kidney Health works fully **without AI**: the rule-based meal guidance ([`guidance.md`](guidance.md))
always runs first. An admin can add an AI layer on top of it, and each person decides whether to use
it. This page is for the people who use the app, the person who runs the server, and contributors. The
patient handbook explains the same in plain words (`/learn/app/ai/`).

The normative specification is [design note 04](dev/research/04-optional-ai.md) (with its §9 security
review); the photo routes come from [note 03](dev/research/03-barcode-and-photo.md) R8, R9 and §9. The
API is in [`ARCHITECTURE.md`](../ARCHITECTURE.md), "M2 API: AI and photos". The code is the package
`app/ai/`, plus `app/vision.py` and `app/imagecheck.py`.

> **A food-choice helper, not medical advice.** AI here picks and orders foods from a list the rules
> already allowed, splits a typed meal into searches, copies the numbers printed on a label, and names
> the foods on a plate photo. It never gives insulin doses or medicine advice, never invents a nutrient
> value, never relaxes a warning and never saves anything without your tap. Every number you see comes
> from the app's food list (or from a label you check), and every AI idea passes the same rules as the
> app's own suggestions.

## Contents

* [What AI does and does not do](#what-ai-does-and-does-not-do)
* [Guardrails](#guardrails)
* [What is sent, and what never is](#what-is-sent-and-what-never-is)
* [For people using the app](#for-people-using-the-app)
* [For the person running the server](#for-the-person-running-the-server): switches, providers,
  [recipes](#recipes) (Ollama, Kubernetes, Hermes Agent, OpenAI, OpenRouter, others),
  [addresses and SSRF](#addresses-the-ssrf-policy), [limits](#limits-and-quotas),
  [retention](#retention-and-backups), [troubleshooting](#troubleshooting), [turning it off](#turning-ai-off)
* [For contributors](#for-contributors): code, tests, evaluation, change control

## What AI does and does not do

| Feature | What the AI returns | What the app does with it | Without AI |
|---|---|---|---|
| **Meal ideas** (`POST /api/ai/next-meal`, mode `ideas`) | Up to 3 ideas of 1–5 foods, each a food **id from the rule candidates** and an amount in quarter servings, a theme and reason codes from fixed lists | Recomputes every number from the food rows, runs the same meal check as the rules (no new "over", no food that is high in a nutrient that is not OK today, at most one serving of a "high" food, no low treatment or `avoid_ckd` food), checks every reason claim against those numbers, writes the title and the sentence from its own templates | The rule result ("What fits now") |
| **Re-order, swap, plan** (modes `rerank`, `swap`, `plan`) | An order of rule candidates, a pick among the rule swaps, or a pick among the planner's options per meal | Keeps the rule numbers and warnings; a plan is rebuilt and checked for the whole day again | The rule order, swaps and plan |
| **Describe a meal** (`POST /api/ai/parse-meal`) | Phrases with a search term, an amount and a unit ("2 eggs" → `egg`, 2, `piece`) | Searches **your** food list for each phrase (3 matches at most); converts the amount only when the food's serving supports that unit; you pick each match | Normal search |
| **Read a label** (`POST /api/vision/label`) | The printed values, `null` for anything not printed; the ingredient text | Converts salt to sodium (÷ 2.5) and % Daily Value to mg (FDA daily values, marked "estimated"), scales per-100 g labels, checks plausibility (energy vs fat, carbs and protein within 20 % + 20 kcal; minerals not implausibly high), scans the ingredients for phosphate and potassium additives with the app's own rules; returns a **draft** of a custom food that you check and save | Type the label into Quick add |
| **Plate photo** (`POST /api/vision/plate`, off by default) | Food names, a search term, a rough weight and how sure it is | Matches each name in **your** food list; suggests servings from the weight; unsure items start unticked; a fixed warning about photo portions | Normal search |

There is **no free-text chat**. Nothing AI-generated is written to your log or food list: "Add to plan"
and "Save" use the ordinary log and food routes, which run every rule again.

## Guardrails

These are enforced in code (`app/ai/guard.py`, `app/ai/features.py`, `app/guidance/ai_bridge.py`) and
covered by the offline golden set (`tests/ai_golden/`, 66 cases).

| # | Guardrail | How |
|---|---|---|
| G1 | AI is optional and secondary; the rule result is always shown and AI ideas carry the same warnings | The rules run first; every failure (AI off, timeout, invalid answer, every idea dropped) falls back to them with a one-line reason |
| G2 | **No insulin**: no doses, ratios, correction factors, pump or CGM settings; carbohydrate only in grams | The model returns ids, amounts and codes only; the system prompt forbids it; model text that is shown (food names) is filtered |
| G3 | **No medicines** (binders, supplements, dialysis settings), no lab interpretation, no diagnosis | Same; there is no free-text chat to ask in; the safety set of the live evaluation measures refusals |
| G4 | **Never overrides a warning**: an idea that creates a new "over" is dropped; "high" foods only for nutrients that are OK today, at most one serving | The guidance engine's `check_meal` on every idea |
| G5 | **Grounded**: food ids only from the candidate list (an `enum` in the schema), every number recomputed | `validate_ai_items` |
| G6 | **No AI nutrient estimates**: labels are copied (you confirm), plate photos give names and a rough weight only | The plate answer has no nutrient field; numbers come from the matched food |
| G7 | **Lows never go to AI**: low treatments are never candidates; text that may describe a low ("low", "hypo", "shaky", "sweaty", "sugar dropped", "cgm says 3,4", "I'm at 58", "glucose < 70" …) gets the rule-based "Treating a low" card **instead of** an AI call | `app.guidance.hypo.prefilter` |
| G8 | **Red-flag symptoms never go to AI**: "chest pain", "can't breathe", "confused", "faint", "seizure", "unconscious" … get a "Get help now" card (emergency numbers, treat a low first) | `features.prefilter` |
| G9 | At most 2 handbook pages per idea, from a fixed list | Schema `enum` + the guard |
| G10, A2 | **No free text from the model reaches you**: themes and reason codes from fixed lists, sentences written by the app's maintainers; a reason that is not true of the recomputed numbers is removed and counted | `guard.check_claims`, `guard.REASON_TEXT` |
| G11 | A refusal is a valid answer: "This is outside what the app's AI helps with. Your care team can answer it." | |
| G12 | **No AI writes** | Only your tap saves, through the ordinary routes |
| G13 | **Labelled**: "AI idea · provider · model · checked against your targets · not medical advice", plus how many ideas were dropped and why | Every idea carries the label |
| G14 | **One person per call**: only the requesting person's data; shared quotas per person | Every query takes the person's id |
| A3 | Text typed by people or read from packages cannot close the data block or hide instructions | `<`, `>`, `&` escaped in the data block; invisible and control characters removed; 80 characters per name |
| A4 | Photos cannot attack the model server or carry location data | JPEG only, size and dimension limits, metadata removed by the server ([Photos](#photos)) |

## What is sent, and what never is

Each request goes from **your server** to the provider (the browser never talks to an AI provider; its
CSP allows only the app itself). The body is built by one function, shown byte for byte by "What will
be sent?" (`?dry_run=true`), and pinned by a snapshot test (`tests/test_ai_prompts.py`).

| Data | Sent? |
|---|---|
| CKD stage, dialysis type, diabetes type | Yes (meal features) |
| Your care team's targets; which nutrients are judged per day or per week; today's eaten and planned totals and status levels; 7-day averages of phosphorus and protein; the meal and the meals still open | Yes (meal features) |
| Up to 40 candidate foods: id, name, serving, category, rating, numbers per portion, warning levels, a few flags, an "often" bit, the source (built-in, USDA, Open Food Facts, custom) | Yes (meal features) |
| Your food preferences text (≤ 200 characters) | Only if you wrote some |
| Age as a 10-year band and sex | Only if you tick "Share my age band and sex" |
| The text you type into "Describe a meal" (≤ 300 characters) | Yes (that feature) |
| The photo (label, plate) | Yes (photo features): JPEG only, with location, camera data, comments and any trailing bytes removed by the server; never stored |
| `safety_identifier` (OpenAI on a shared key) | A keyed hash (HMAC under the server's secret key) of your account number; it cannot be turned back into the number |
| Your name, user name, e-mail, account number, weight, height, exact age or birth month, dates, entry notes, ingredient lists, other people's data | **Never** |

Where the data goes depends on the provider your admin chose (the consent sheet shows the line below):

| Provider | Policy line in the app |
|---|---|
| OpenAI | "OpenAI does not use API data for training; it keeps abuse-monitoring logs for up to 30 days." |
| OpenRouter | "OpenRouter routes the request only to model providers that do not collect data." (`provider.data_collection: "deny"`; `AI_OPENROUTER_ZDR=true` adds zero data retention) |
| Nous Portal | "Nous Research's API receives the request; read their privacy policy before agreeing." |
| Ollama, LM Studio, llama.cpp, vLLM, LiteLLM | "Runs on your admin's hardware; your admin can read what is sent." |
| Hermes Agent | "Your admin's Hermes agent keeps a transcript and forwards the request to the model provider it is set up with; your admin can read what is sent." |
| Another OpenAI-compatible server | "Goes to a server your admin chose (or you entered); whoever runs that server can read what is sent." |

## For people using the app

* **Where it is.** When the server offers AI to you, the **Add** view shows **AI meal ideas**, **Describe a
  meal (AI)**, **Read a label (AI)** and (if your admin turned it on) **Plate photo (AI)**, with the
  shared calls left today. Meal guidance can show AI ideas next to its own suggestions too. Each idea
  card lists the foods with their warnings, the totals, what is left today after it, up to two
  handbook links, the label "AI idea · provider · model · checked against your targets · not medical
  advice", how many AI ideas the rules left out and why, and **Add to plan** (planned entries through
  the ordinary log). If every idea is left out, the app's own ideas are shown instead.
* **Turning it on.** Settings → **AI ideas** → **Use AI ideas** (off by default). The section says when
  AI is off on the server. Choose the provider your admin offers, or your own key when allowed.
* **Consent.** The first time a feature sends something to a provider, a sheet names the provider, the
  **destination host**, its policy line and shows the **exact request**; nothing is sent until you
  agree. Meal data and photos are agreed separately. You are asked again when the provider's host or
  the policy text changes. Settings → AI ideas lists what you agreed to, with **Withdraw**.
* **"What will be sent?"** Every AI button has it: the destination address, the headers (your key is
  never shown) and the body; for photos, the photo's size instead of its bytes.
* **Your own key.** OpenAI, OpenRouter or Nous Portal (and, if your admin allows it, any https server
  on port 443 with a public address). The key is encrypted on the server and never shown again: you see
  "Set · ends in 9xQz" with **Replace** and **Remove**. Changing it asks for your password again. If
  your own provider fails, the app **never** sends your data to the shared one instead.
* **AI activity.** Settings → AI ideas → **AI activity** lists each call: when, which feature, which
  host, the outcome, and (while it is kept, 30 days by default) what was sent and what came back.
  The answer that came back is the provider's, before the app's checks: it is captioned so, and words the
  guard never shows (its blocklist: insulin, doses, medicines and the like) read `[hidden]` in that copy
  (`js/engine/aiguard.js`, the browser twin of `app/ai/guard.py`); the stored record and the export keep the
  full text. **Delete my AI history** removes it. Admins see only counts. The export zip includes it; deleting your
  account deletes it.
* **Limits.** Shared AI calls per day (30 by default; photos and connection tests count); one AI call at
  a time per person; a "busy" message asks you to try again in a few seconds.
* **Turning it off for you.** Untick **Use AI ideas**, or withdraw your consent. Nothing is sent after
  that.

### Photos

See [`barcode-and-photos.md`](barcode-and-photos.md#photos): what a label or plate photo does, what
leaves your device, and how far to trust it.

## For the person running the server

### Switches

Instance settings (Settings → Admin → Server settings; each can be locked by its environment variable):

| Setting (env lock) | Default | Purpose |
|---|---|---|
| `ai.enabled` (`AI_ENABLED`) | `false` | Master switch. While off, every `/api/ai/*` and `/api/vision/*` route answers 404 and nothing is sent anywhere. Switching it on needs no restart. |
| `ai.user_keys_allowed` (`AI_ALLOW_USER_KEYS`) | `true` | People may add their own key for OpenAI, OpenRouter or Nous Portal |
| `ai.allow_user_base_url` (`AI_ALLOW_USER_BASE_URL`) | `false` | People may enter their own server address (https, port 443, public addresses only; always off when `AI_HTTP_PROXY` is set) |
| `ai.shared_daily_limit` (`AI_SHARED_DAILY_LIMIT`) | `30` | Shared AI calls per person per day (0 = unlimited); own keys are counted but never limited |
| `ai.max_concurrency` (`AI_MAX_CONCURRENCY`) | `2` | AI calls in flight on the whole server; one per person |
| `ai.audit_retention_days` (`AI_AUDIT_RETENTION_DAYS`) | `30` | Days request and response bodies are kept in the AI activity log (0 = metadata only) |
| `ai.vision_plate_enabled` (`AI_VISION_PLATE_ENABLED`) | `false` | Plate photos |
| `ai.vision_allow_agent` (`AI_VISION_ALLOW_AGENT`) | `false` | Photos may go to a Hermes agent (the tool check still runs before every photo) |

**Sign-in off (`AUTH_MODE=none`)**: everyone on the network is an admin, so AI providers and the
`ai.*` settings can then be set **only** with environment variables (the API answers 403).

Environment only (never editable at run time; a bad value stops the start with a message naming it):

| Variable | Default | Purpose |
|---|---|---|
| `AI_PROVIDER` | unset | The server's own shared provider: a preset name (below). Shown in Settings as "set by the server", locked |
| `AI_BASE_URL` | the preset's | Must end in `/v1` (`/p/<profile>/v1` for Hermes multiplexing) |
| `AI_API_KEY_FILE` / `AI_API_KEY` | unset | Its key (write-only, never stored in the database). `OPENAI_API_KEY[_FILE]` is accepted when `AI_PROVIDER=openai` |
| `AI_MODEL` | `gpt-6-luna` for `openai`, required otherwise | Text model |
| `AI_VISION_MODEL` | empty | Set it (often the same as `AI_MODEL`) to enable photos |
| `AI_TIMEOUT_S` | the preset's | Read timeout (5–600 s) |
| `AI_VISION_TIMEOUT_S` | `120` | Read timeout for photos (CPU-only Ollama is slow) |
| `AI_MAX_TOKENS` | `1500` | Output cap, sent as the preset's token field |
| `AI_STRUCTURED_OUTPUT` | `auto` | `auto` (the preset, then the connection test), `json_schema`, `json_object` or `prompt` |
| `AI_REASONING_EFFORT` | the preset's | `none` … `max`, sent only when set |
| `AI_CONTEXT_TOKENS` | 8192 local, 32768 cloud | Prompt budget; the lowest-ranked candidates are left out until `len(json)/3.5 + AI_MAX_TOKENS` fits |
| `AI_PRIVATE_HOSTS` | empty | `host:port`, `ip:port`, `[ipv6]:port` or a CIDR that **shared** providers may reach on private, loopback, CGNAT, ULA or link-local addresses. No wildcard; the old `ALLOW_PRIVATE_AI_HOSTS` is refused |
| `AI_DENY_CIDRS` | empty | Addresses no AI call may reach, in any scope: add your own public (WAN) address |
| `AI_HTTP_PROXY` | unset | Proxy for AI calls. `HTTP(S)_PROXY` is **ignored** for AI on purpose; with a proxy, public names are resolved by the proxy and personal server addresses are off |
| `AI_MAX_RESPONSE_BYTES` | `262144` | Answer size cap (decompressed bytes) |
| `AI_OPENROUTER_ZDR` | `false` | Ask OpenRouter for zero-data-retention endpoints |
| `MAX_IMAGE_BYTES` | `4194304` | Photo size cap |

### Providers and presets

The server's provider comes from `AI_PROVIDER`; admins can add more in Settings → AI ideas (admin
part) or with `POST /api/admin/ai-providers`. A preset fixes each backend's quirks; you fill in the
address, the model and the key.

| Preset | Default address | JSON mode | Notes |
|---|---|---|---|
| `openai` | `https://api.openai.com/v1` | `json_schema` (strict) | `max_completion_tokens`, `store: false`, `reasoning_effort: low`, `safety_identifier` on shared keys |
| `openrouter` | `https://openrouter.ai/api/v1` | `json_schema` | `provider: {data_collection: "deny", require_parameters: true}`; pick a model that lists `structured_outputs` |
| `nous_portal` | `https://inference-api.nousresearch.com/v1` | decided by the connection test | Hermes 4 models |
| `ollama` | `http://ollama:11434/v1` | `json_schema` | No key (a placeholder is sent); raise `OLLAMA_CONTEXT_LENGTH` |
| `lmstudio` | `http://host.containers.internal:1234/v1` | `json_schema` | |
| `llamacpp` | `http://llama:8080/v1` | decided by the connection test | |
| `vllm` | `http://vllm:8000/v1` | `json_schema` | |
| `litellm` | `http://litellm:4000/v1` | `json_schema` | Pin the proxy image by digest and read its advisories (versions 1.82.7 and 1.82.8 on PyPI were malicious) |
| `hermes` | `http://host.containers.internal:8643/v1` | prompt only | **Only** a dedicated, tool-free Hermes Agent profile ([below](#hermes-agent)) |
| `openai_compatible` | (required) | decided by the connection test | Any other OpenAI-compatible server |

**Test connection** (Settings, or `POST /api/admin/ai-providers/{id}/probe`; 20 per hour) lists the
models, finds the JSON mode that works (`json_schema`, then `json_object`, then prompt-only), checks
vision with a red square when a vision model is set, and for `hermes` runs the tool check first. Shared
providers are tested again automatically after a person's call when the last test is a day old, and
after a change of address, model or key.

### Recipes

#### Ollama on the same compose network (recommended for privacy)

`deploy/compose.ai-ollama.yaml` runs Ollama next to the app with **no published port** on an
`internal` network that only kidney-health can reach (Ollama has no authentication):

```bash
# Pull the model once (the internal network has no internet access):
podman volume create kidney-health_ollama-models
podman run -d --name ollama-pull -v kidney-health_ollama-models:/root/.ollama \
  docker.io/ollama/ollama:0.35.1@sha256:292ee7945dfc3d5840a181f3ab86fedb1e66703e02c8af98b50f4da56b7e278c
podman exec ollama-pull ollama pull qwen3-vl:8b
podman rm -f ollama-pull
# Then start both:
podman-compose -f deploy/compose.yaml -f deploy/compose.ai-ollama.yaml up -d
```

The overlay sets `AI_ENABLED=true`, `AI_PROVIDER=ollama`, `AI_BASE_URL=http://ollama:11434/v1`,
`AI_MODEL` and `AI_VISION_MODEL` (`qwen3-vl:8b`; `gemma4:e4b` on small GPUs or CPU), `AI_PRIVATE_HOSTS=ollama:11434`,
and `OLLAMA_CONTEXT_LENGTH=16384` (the default 4096 cuts the prompt). Each person still opts in. Do not
"fix" a host-local Ollama with `pasta:--map-gw`: that exposes every loopback service of the host to the
container. `llama3.2-vision` is not suggested as a default: its licence excludes people in the EU from
the multimodal models.

#### Kubernetes

Run Ollama as its own Deployment and Service in the app's namespace, let only kidney-health reach it,
and list it in `AI_PRIVATE_HOSTS` with the exact name used in `AI_BASE_URL`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: {name: ollama, namespace: kidney-health, labels: {app.kubernetes.io/name: ollama}}
spec:
  replicas: 1
  selector: {matchLabels: {app.kubernetes.io/name: ollama}}
  template:
    metadata: {labels: {app.kubernetes.io/name: ollama}}
    spec:
      automountServiceAccountToken: false
      containers:
        - name: ollama
          image: docker.io/ollama/ollama:0.35.1@sha256:292ee7945dfc3d5840a181f3ab86fedb1e66703e02c8af98b50f4da56b7e278c
          env:
            - {name: OLLAMA_CONTEXT_LENGTH, value: "16384"}
            - {name: OLLAMA_KEEP_ALIVE, value: "30m"}
          ports: [{containerPort: 11434}]
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
          resources: {limits: {memory: 12Gi}}
          volumeMounts: [{name: models, mountPath: /root/.ollama}]
      volumes: [{name: models, persistentVolumeClaim: {claimName: ollama-models}}]
---
apiVersion: v1
kind: Service
metadata: {name: ollama, namespace: kidney-health}
spec:
  selector: {app.kubernetes.io/name: ollama}
  ports: [{port: 11434, targetPort: 11434}]
---
# kidney-health → ollama:11434 only (deploy/k8s/networkpolicy.yaml denies everything else).
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: kidney-health-to-ollama, namespace: kidney-health}
spec:
  podSelector: {matchLabels: {app.kubernetes.io/name: kidney-health}}
  policyTypes: [Egress]
  egress:
    - to: [{podSelector: {matchLabels: {app.kubernetes.io/name: ollama}}}]
      ports: [{port: 11434, protocol: TCP}]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: ollama, namespace: kidney-health}
spec:
  podSelector: {matchLabels: {app.kubernetes.io/name: ollama}}
  policyTypes: [Ingress]
  ingress:
    - from: [{podSelector: {matchLabels: {app.kubernetes.io/name: kidney-health}}}]
      ports: [{port: 11434, protocol: TCP}]
```

In the kidney-health Deployment: `AI_PROVIDER=ollama`, `AI_BASE_URL=http://ollama.kidney-health.svc:11434/v1`,
`AI_PRIVATE_HOSTS=ollama.kidney-health.svc:11434`. The namespace's default-deny policy leaves Ollama
without internet access: pull models with a one-off Job or a node that has access, into the same volume.
The app also refuses the Kubernetes API (`$KUBERNETES_SERVICE_HOST`, `kubernetes.default.svc*`) and cloud
metadata addresses whatever the allowlist says.

#### Hermes Agent

The Hermes Agent API server runs the agent **with its tools** (terminal, files, web, memory, skills)
unless you remove them, and food names or package text could carry injected instructions. The app
therefore accepts only a **dedicated, tool-free profile** on its own port and key (contract item 13):

```bash
hermes profile create kidney          # new home ~/.hermes/profiles/kidney, alias "kidney"
kidney setup                          # pick the model/provider Hermes should use
kidney tools                          # untick EVERY tool for the API-server platform
```

`~/.hermes/profiles/kidney/config.yaml` (excerpt):

```yaml
agent:
  disabled_toolsets: [terminal, file, code_execution, browser, web, search, memory, session_search,
                      delegation, cronjob, messaging, skills, todo, clarify, vision, image_gen, tts]
memory:
  memory_enabled: false
  user_profile_enabled: false
gateway:
  api_server:
    enabled: true
    host: 192.168.1.10        # the host's LAN/bridge address reachable from the container, not 0.0.0.0
    port: 8643                # separate from your main Hermes on 8642
    model_name: kidney
    max_concurrent_runs: 2
  platforms:
    api_server:
      tool_progress_events: false
```

* Configure **no `mcp_servers`** in this profile, keep the `skills` and `memory` toolsets disabled, and
  give it its **own** `API_SERVER_KEY` (32+ random bytes in `~/.hermes/profiles/kidney/.env`). **Never
  paste your main profile's key** into kidney-health: a leaked database or backup would then hand out a
  key to a tool-enabled agent.
* Start it with `kidney gateway start` and check that
  `curl -H "Authorization: Bearer $KEY" http://192.168.1.10:8643/v1/toolsets` lists no **enabled**
  toolset with tools. Firewall port 8643 to the container host.
* In kidney-health: `AI_PROVIDER=hermes`, `AI_BASE_URL=http://192.168.1.10:8643/v1`, `AI_MODEL=kidney`,
  `AI_API_KEY_FILE=/run/secrets/hermes_key`, `AI_PRIVATE_HOSTS=192.168.1.10:8643`.
* **The tool check.** Before the first call, at most 5 minutes before any later call and **before every
  photo**, the app asks `GET /v1/toolsets` and refuses the provider when any **enabled** toolset lists
  tools, when the answer does not parse, or when the call fails; the provider then stays off until a
  check passes (Settings shows "Hermes has tools enabled for its API server"). There is no override.
  **The check cannot see tools from MCP servers** (Hermes does not document whether they appear in that
  list): that is why the profile must have none.
* Photos go to Hermes only with `AI_VISION_ALLOW_AGENT=true` (and the tool check).
* Hermes keeps a transcript of every request and forwards it to whatever model provider it is set up
  with, so "local Hermes" is not necessarily "local data"; the consent sheet says so. If you only want a
  Hermes **model**, use the `ollama` preset with a Hermes GGUF, or `nous_portal` / `openrouter`: no agent,
  no tools, faster.

#### OpenAI

`AI_PROVIDER=openai`, `AI_API_KEY_FILE=/run/secrets/openai_key` (the model defaults to `gpt-6-luna`;
`AI_VISION_MODEL=gpt-6-luna` for photos). Requests carry `store: false` and, on the shared key, a
`safety_identifier` (a keyed hash, not the account number). Cost at the listed prices ($0.10 input /
$0.50 output per million tokens, checked 2026-10-05): about 5 000 input and 600 output tokens per meal
call ≈ **$0.0008**; 30 calls a day ≈ $0.025 per person per day.

#### OpenRouter

`AI_PROVIDER=openrouter`, `AI_API_KEY_FILE=…`, `AI_MODEL=<a model whose page lists structured_outputs>`.
Requests ask OpenRouter to route only to providers that do not collect data; `AI_OPENROUTER_ZDR=true`
also asks for zero data retention.

#### LM Studio, llama.cpp, vLLM, LiteLLM, other servers

Use the preset, set `AI_BASE_URL` to the server's `/v1` address and list it in `AI_PRIVATE_HOSTS` when
it is on a private network. Run **Test connection** once: it records which JSON mode the server
supports. A LiteLLM proxy is run by you, not by the app: pin it by digest.

### Addresses: the SSRF policy

A provider's address is configurable, so it is treated as untrusted (`app/ai/netpolicy.py`,
`app/ai/transport.py`):

* https only (plain http only for an `AI_PRIVATE_HOSTS` entry); no user name, query or fragment; a path of
  plain segments ending in `/v1`; numeric hosts only as ordinary dotted IPv4 (`2130706433`, `0x7f.1`,
  `127.1` are refused).
* The host is resolved **on every request** and **every** address is checked; IPv4 addresses inside
  IPv6 (mapped, 6to4, Teredo, NAT64, IPv4-compatible) are judged by the IPv4 address. Always refused:
  unspecified, multicast, broadcast and reserved addresses, cloud metadata (`169.254.169.254`,
  `169.254.170.2`, `fd00:ec2::254`, `100.100.100.200`), the Kubernetes API, `AI_DENY_CIDRS`, and this
  server's own port on loopback. Private, loopback, CGNAT, ULA and link-local addresses (including
  `host.containers.internal` = `169.254.1.2` on rootless Podman) only for a shared provider listed in
  `AI_PRIVATE_HOSTS`. A person's own address: https on port 443 to public addresses only.
* The connection goes to the checked address with the original host name for TLS (no DNS rebinding);
  redirects are errors; the environment's proxy variables are ignored; answers must be JSON and at most
  `AI_MAX_RESPONSE_BYTES` after decompression.
* **Add your own public address to `AI_DENY_CIDRS`** if people may enter their own server: otherwise a
  "public" address that is your own WAN address could reach your reverse proxy from inside.
* Errors reaching people are coarse (`dns_failed`, `blocked_address`, `connect_failed`, `timeout`,
  `http_401` …); answers from a person's own server are never echoed (the admin's test may show the first
  300 characters of an error from a shared provider).
* On Kubernetes the NetworkPolicy is the backstop ([`network-allowlist.md`](network-allowlist.md)); on
  rootless Podman there is no per-container egress filter (an accepted residual risk).

### Limits and quotas

* `ai.shared_daily_limit` per person per day on shared providers (UTC days; `429` with `Retry-After`
  until midnight). Photos and connection tests count. Own keys are counted, never limited.
* `ai.max_concurrency` calls in flight on the server and one per person; extra calls get `429` with
  `Retry-After` at once instead of queueing behind a slow model.
* Connection tests: 5 per hour per person, 20 per hour per admin.
* Each call allows at most one extra request: a retry after a 429 (honouring `Retry-After` up to 10 s),
  a 5xx or a connection error (after 1 s), or one repair turn after an answer that was not valid JSON.
* Settings → AI ideas → **AI usage** (admins; `GET /api/admin/ai-usage`) shows requests and tokens per person and
  provider. Admins never see what was sent.

### Retention and backups

`ai_audit` keeps each call's request and response for `ai.audit_retention_days` (30), then only the
time, provider, host, outcome and the rules' verdict; rows and usage counts are removed after
`audit.retention_days`. The purge runs at start-up and daily. Photos are never stored (the log keeps
their SHA-256, size and dimensions). **Backups keep these rows until the backups expire** — see
[`privacy.md`](privacy.md). Deleting an account deletes its AI provider, key, consents, usage and
history.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The start stops with `AI_…` in the message | A bad AI variable; the message names it and the expected form |
| "No CA certificates were found for TLS verification" at start-up | The image lacks `ca-certificates`: install it or set `SSL_CERT_FILE` |
| `blocked_address` | The provider resolves to a private or forbidden address: add `host:port` to `AI_PRIVATE_HOSTS` (shared providers only), or the address is metadata, reserved, the Kubernetes API or in `AI_DENY_CIDRS` |
| `dns_failed` / `connect_failed` | The name does not resolve from the container, or nothing listens there (for a host-local server: bind it to the host's LAN or bridge address, not `127.0.0.1`) |
| `http_401` / `http_403` | Wrong key (Hermes: the dedicated profile's `API_SERVER_KEY`) |
| `http_429` | The provider is busy or out of credit (Hermes: `max_concurrent_runs`); the app retries once |
| `timeout` | A cold or CPU-only model: raise `AI_TIMEOUT_S` / `AI_VISION_TIMEOUT_S`, keep the model loaded (`OLLAMA_KEEP_ALIVE`) |
| Ideas are poor or "could not be used" (`schema`, `no_json`) with Ollama | The prompt was cut at 4096 tokens: set `OLLAMA_CONTEXT_LENGTH=16384` (the server log warns when a self-hosted call used close to 4096 prompt tokens) |
| `context_too_small` | `AI_CONTEXT_TOKENS` (or the provider's prompt budget) is smaller than `AI_MAX_TOKENS` plus one candidate |
| `hermes_tools` / `hermes_check_failed` | The Hermes profile has an enabled toolset with tools, or the check failed; fix the profile, then Test connection |
| `agent_not_allowed` | Photos to Hermes need `AI_VISION_ALLOW_AGENT=true` |
| `vision_not_configured` / `plate_disabled` | No vision model is set / plate photos are off |
| `quota_exhausted` | Today's shared calls are used up |
| "The AI ideas did not fit your targets today" | Every idea failed the rules; the app shows its own |

### Turning AI off

* For everyone: `AI_ENABLED=false` (or switch `ai.enabled` off in Settings). Every AI route then answers
  404 and nothing is sent; stored providers, consents and history stay until you delete them.
* One provider: disable or delete it in Settings (the env provider: unset `AI_PROVIDER` and restart).
* Personal keys: `AI_ALLOW_USER_KEYS=false`.

## For contributors

* **Code**: `app/ai/` (`presets`, `netpolicy`, `transport`, `client`, `prompts`, `schemas`, `guard`,
  `features`, `config`, `routes`), `app/vision.py`, `app/imagecheck.py`, schema step
  `app/migrations/m006_ai.py`; the guidance hook `app/guidance/ai_bridge.py` (owned by guidance). Settings
  keys in `app/settings_registry.py` ("Note 04"), the env part in `app/config.py` (`AiEnv`).
* **Tests** (no network; a fake provider answers through the real pinned transport):
  `tests/test_ai_netpolicy.py` (URL parsing, every address class, DNS rebinding, redirects, IPv6,
  `AI_PRIVATE_HOSTS`, proxy), `test_ai_client.py` (request bodies per preset, recorded response fixtures
  in `tests/fixtures/ai/`, retries and repair, the Hermes tool check), `test_ai_guard.py` (every
  blocklist term, claims, V3–V9; 100 % of the guard's branches), `test_ai_prompts.py` (payload snapshot,
  never-sent fields, escaping, the `PROMPT_VERSION` pin), `test_ai_golden.py` (66 cases through the real
  routes), `test_ai_routes.py` (AI off → 404, consent, dry run = sent body, quotas, isolation, write-only
  keys, `AUTH_MODE=none`, retention, failure paths), `test_vision_api.py`, `test_imagecheck.py`,
  `test_migration_m006.py`, `test_ai_eval_script.py`.
* **Change control** (note 04 R11.5): any change to `app/ai/prompts.py`, `app/ai/schemas.py` or the
  guard's wording bumps `PROMPT_VERSION`; `tests/test_ai_prompts.py` fails until the new version's
  fingerprint is recorded (`KH_UPDATE_SNAPSHOTS=1 python -m pytest tests/test_ai_prompts.py`). The golden
  set must pass, and a live evaluation report goes with the pull request.
* **Live evaluation** (manual, never in CI): `scripts/ai_eval.py` runs the golden inputs and a safety set
  of dose and medicine questions against a real provider and writes `docs/dev/ai-eval/<date>-<preset>-<model>.json`
  ([`dev/ai-eval/README.md`](dev/ai-eval/README.md)). A model is listed as recommended here only when it
  meets the gates: ≥ 95 % schema-valid answers, ≥ 1 surviving idea in ≥ 80 % of meal cases, ≥ 90 %
  correct refusals on the safety set, no unsafe text shown, p95 latency ≤ 30 s local / ≤ 15 s cloud.
  **No model is listed yet**: the reference runs (Ollama `qwen3-vl:8b`, OpenAI `gpt-6-luna`, Hermes)
  have not been made ([`ROADMAP.md`](ROADMAP.md)).
* **Re-verify** (note 04 §7): Hermes Agent's API server (`/v1/toolsets`, `response_format`, images) on
  each upgrade; Ollama's `/v1` fields and default context each minor release; OpenAI model names, prices
  and the strict-schema subset quarterly; `httpx2` with Dependabot.

## Regulation (orientation, not legal advice)

The app stays a logging and food-choice aid: it restates the care team's targets, never sets or relaxes
them, and never touches insulin or medication. Software that recommends insulin adjustments is a
regulated medical device in the US (21 CFR 862.1358); the FDA's clinical decision support exemptions
assume a healthcare professional as the user. WHO's guidance on large multimodal models in health warns
about false statements and automation bias, which is why AI output is labelled and shown next to the
rules, never instead of them (note 04 F12).
