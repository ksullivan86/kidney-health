# Notes for AI coding agents

This repository is a self-hosted food log for people with chronic kidney disease and type 1 diabetes.
Before you change anything, read:

1. [`CLAUDE.md`](CLAUDE.md): the rules every change keeps, and how to checkpoint long work.
2. [`ARCHITECTURE.md`](ARCHITECTURE.md): the contract (API shapes, data model, rules, file ownership,
   the v0.3 decisions). Change it first when a change needs it.
3. [`docs/dev/research/`](docs/dev/research/): the design notes behind the contract. Their "Security
   review" and "Fact-check" sections override their earlier text.

Then [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, tests and the how-tos.

## The key rules

* **Safety.** Never add insulin or medication dosing; never block, delay or warn against treating a low
  blood sugar; every clinical number is traceable to a cited source. Targets come from the person's
  care team.
* **Security.** Every `/api` route except the public auth routes depends on `current_user`; every query
  is scoped by `user.id`; another person's data answers 404. Secrets are write-only in the API. No
  inline scripts or styles (CSP). Outbound HTTP only through the SSRF-checked transports. Configuration
  only through `app/config.py` and the settings registry.
* **No network from the browser.** Nothing from a CDN; vendored files live in `app/static/vendor/` with
  SHA-256 pins in its README.
* **Parity.** The demo's JavaScript twins of server logic must match the server: regenerate
  `tests/data/*.json` with their generators and run `node tests/js/run_vectors.mjs` alongside pytest.
* **Tests.** `python -m pytest` passes with no network. Add tests with every behaviour change, including
  failure paths and limits.
* **Migrations** are append-only steps in `app/migrations/`; never edit a released step.
* **Docs.** When behaviour a person can see changes, update `ARCHITECTURE.md`, the relevant page in
  `docs/` and the handbook (`handbook/docs/app/`).
* **Shared tree.** Other agents may work in the same checkout: commit only the paths you changed (never
  `git add -A` or `git commit -a`), never rewrite history, and keep a progress note in
  `docs/dev/progress/<role>.md` as `CLAUDE.md` describes.
