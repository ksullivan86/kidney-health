Status: in progress (2026-10-30)

# Tester role, clear AI naming, full-install walk-through

Three jobs, in this order: (1) make it obvious the AI features are an AI language model; (2) a tester role with
Send feedback, admin Feedback page and a tester checklist (migration step 28, note 26); (3) docs/test-the-full-app.md.

Branch: `worktree-agent-a43b8fd15b9a5572f` (commit locally, no push; the owner merges).

## Done

(nothing yet)

## In progress

Job 1: naming.

## Decisions

* One term set: "AI" everywhere. The chat is the **AI assistant** (tab **Ask AI**). Settings "AI ideas" becomes
  **AI features**. Settings "Assistant access" (MCP tokens for a chat app the person runs elsewhere) becomes
  **Outside AI apps**.

## Commands

* `PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python`
* `$PY -m pytest -p no:cacheprovider --basetemp=<scratchpad>/pt-x tests/<file>`
* `node tests/js/run_vectors.mjs`
