Status: in progress

Branch `audit/symptom-editor-lifecycle`, main `cea3c94`. Keep PR unmerged.

Confirmed late symptom success/400/500 replies changed a reopened draft. Five live-handler/real-rule cases:
clean main fails4/passes1; fixed5pass. Added per-opening generation, frozen submitted fields, editable new
drafts whose Save waits for the outstanding request, current-error preservation and safe stale-success
refresh of the current day. No symptom/severity rules, handbook flags or text changed.

Focused Python/static/new regressions:65passed. Real Chromium walk:87passed at phone/desktop plus demo,
including held committed saves, intact new drafts and server-side once-only counts. Architecture, symptom
guide, handbook and e2e README updated. Full pytest session31417 is running; lint, vectors, OpenAPI, generated
pages and strict handbook started. Next: finish checks, checkpoint/push,draft PR,complete validation,readyunmerged. Logs: `/workspace/work/symptom-editor-audit/`.
