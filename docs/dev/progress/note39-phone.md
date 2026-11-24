Status: in progress (step 1)

# note39-phone: the phone side of design note 39 (steps 1, 3, 4)

Role: `note39-phone`. Branch: `worktree-agent-a1f6012ad3f84dd14` (fast-forwarded to c7337a6, which has note 39).
Commit own paths only, trailers per the prompt. No push, no PR. Do not edit app/*.py or app/migrations.
Venv: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python

## Plan
1. Step 1: `_serverSync` rows record `v` (version when sent) and `d` (deleted on the phone after sending); status counts them;
   Settings says how many. Tests in tests/js/server_sync.mjs.
2. Bridge `serverApi` (ServerSync.swift + allow-list in KidneyHealthCore), `GET /push/v1/about` reading, token kind on the
   pairing screen (SyncModel/ContentView).
3. Page: js/mock/server_api.js (about cache, call through the bridge); foods.js / barcode.js use the server when both ways.
4. Page: ai.js choice rule (server, iPhone, none), "Use only this iPhone's AI".
5. Tests, docs.

## Done
- nothing yet

## Next
- step 1
