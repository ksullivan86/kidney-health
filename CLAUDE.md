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
