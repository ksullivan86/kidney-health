Status: in progress

Branch `audit/ai-probe-settings-lifecycle`, main `cea3c94`. Keep PR unmerged.

Confirmed: manual AI probes save replies to the provider id after a network wait without checking the tested
settings. Daily probes compare base_url/model only, ignoring the key, vision model and other settings.
A manual shared probe also tries to render a deleted provider. Reproduce with real API settings changes
from a second TestClient portal inside the awaited probe (no real egress). Sixteen cases cover own/shared
manual probes and daily shared probes, with model/vision/key/deletion/normal flows. AI provider ids already
use AUTOINCREMENT; do not invent an id-reuse issue or change allocation. Clean main (final 16 cases): 10 failed, 6 passed.
All 16 pass after the fix. A background test also allows a completed manual probe receipt
when the settings themselves stayed unchanged. The per-person gate correctly rejects two concurrent
manual probes (429); no gate change was needed. Store results only if the provider row still matches the tested settings, excluding
probe receipts. Check and save under BEGIN IMMEDIATE with no network inside. Manual stale tests return 409;
daily tests discard the stale result. The admin response also uses the existing not-found guard when reading
its final view. Current-setting probe usage still counts the actual requests. Docs/handbook/changelog updated.
Focused AI route/routing/cloud suite: 188 passed (before the extra daily-receipt positive case).
Ruff, OpenAPI, generated handbook, Node parity and strict handbook pass. Full pytest session7480 is running,
started with the original 15 lifecycle cases; the 16th positive case passes separately. Next: finish full
checks, finalize PR and mark ready without merging.
Logs: `/workspace/work/ai-probe-audit/`.
