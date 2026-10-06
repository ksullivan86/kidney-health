# Working on kidney-health

Read `ARCHITECTURE.md` (the contract, including the v0.3 section) before changing code. The
design notes in `docs/dev/research/` are the specifications behind it.

Rules that every change must keep:

* **Health data and safety.** This app supports people with chronic kidney disease and type 1
  diabetes. Never add insulin or medication dosing, never block or warn against hypoglycaemia
  treatment, and keep every clinical number traceable to a cited source (see
  `docs/research/` and the handbook bibliography).
* **No network from the browser.** The UI loads nothing from a CDN; vendored files live in
  `app/static/vendor/` with hashes in `vendor/README.md`.
* **Security.** Every `/api` route except the public auth routes needs `current_user`; every
  query is scoped by `user.id`; not-yours is 404. Secrets are write-only in the API. No inline
  scripts (CSP). Outbound HTTP goes through the SSRF-checked transport.
* **Parity.** The demo/preview mode's JavaScript twins of server logic must match the server:
  update `tests/data/*.json` vectors and run `node tests/js/run_vectors.mjs` with pytest.
* **Tests.** `python -m pytest` must pass with no network. Add tests with every behaviour change.
* **Migrations** are append-only steps in `app/migrations/`; never edit a released step.
* **Docs.** Update `ARCHITECTURE.md`, the relevant `docs/` page and the handbook when behaviour a
  person can see changes.

## Long-running agent work: checkpoint as you go

Agent runs can be cut off at any moment (usage limits, restarts). Files you wrote survive; your
working memory does not. So, for any task longer than a few minutes:

1. **Progress note.** Keep `docs/dev/progress/<your-role>.md` up to date after every sub-step:
   done (and how it was verified), in progress, next steps, decisions and their reasons, commands
   that reproduce your checks. Write it so a fresh agent could continue without re-reading
   everything.
2. **Checkpoint commits of your own files only.** After each sub-step that leaves the tree in a
   sensible state, commit just the paths you own, then push:
   `git add <your paths> docs/dev/progress/<your-role>.md && git commit -m "WIP(<your-role>): <step>" -- <your paths> docs/dev/progress/<your-role>.md && git push -q origin HEAD`.
   Never `git add -A` or `git commit -a`: other agents work in the same tree at the same time.
   If git reports `index.lock`, wait a few seconds and retry. Never rewrite history.
3. **When you start**, read `docs/dev/progress/<your-role>.md`, `git log --oneline -15` and
   `git status` first: a previous attempt may have left work to continue. If your prompt names a
   previous attempt's transcript (`agent-*.jsonl`), read its last tool calls and messages to see
   where it stopped.
4. When your task is fully done, mark the progress note "Status: complete" in its first line.
