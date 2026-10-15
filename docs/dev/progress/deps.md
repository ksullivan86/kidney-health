# Progress: Python 3.15 readiness (role: deps)

Status: complete (2026-10-15). Worktree branch `worktree-agent-ac8612635844bcb6c`, based on `main`; not pushed, no PR.

Why: Chainguard's free `python:latest` / `:latest-dev` moved from 3.14 to 3.15, so the pinned 3.14 digests get no
security updates. Dependabot's grouped PR (#32) bumps the digests but the image build fails: PyYAML has no cp315
wheel (handbook stage) and `pydantic-core==2.46.5` has none either (app lock).

## Done

* Locks: `scripts/lock.sh --upgrade-package pydantic==2.14.0 --upgrade-package pydantic-core==2.50.0` (no container
  engine here, so its local python3.14 path). Only `requirements.lock` and `requirements-dev.lock` changed in content;
  the handbook, Zensical and e2e locks came out with comment-only differences (header text) and were reverted.
  * pydantic 2.13.5 -> 2.14.0, pydantic-core 2.46.5 -> 2.50.0. 2.14.0 is the oldest pydantic whose core has cp315
    wheels (it pins core 2.50.0); 2.14.1 (2026-10-11) is under the 7-day cooldown, the weekly refresh takes it.
  * `requirements.in`: floor `pydantic>=2.14,<3`. A plain `scripts/lock.sh` afterwards leaves both locks unchanged.
  * `requirements-dev.in`: `pyyaml>=6,<7; python_version < "3.15"` (PyYAML has no cp315 wheel; wheels-only install).
* Images: `deploy/Containerfile` builder `latest-dev@e8e6a6f7...` and runtime `latest@1c4deeea...` (3.15); handbook
  stage kept on the 3.14 `latest-dev@630df1be...` with a TEMPORARY SPLIT comment; `deploy/Containerfile.debian` three
  FROM lines and `scripts/lock.sh` IMAGE on `python:3.14-slim-trixie@a2b82f3c...`. All digests resolve on the registries.
* CI: matrix `["3.12", "3.14", "3.15"]` (setup-python's manifest has stable 3.15.0, so the plain version works).
* Tests: PyYAML-dependent modules skip on 3.15 only; FROM-line test allows the one documented split;
  `test_dependencies.py` checks pydantic-core >= 2.48.0 and the marker; CI matrix assertion updated.
* Docs: CHANGELOG (one entry, server section), maintainers (required check, wheel check, when to undo the split),
  deployment, deploy/README, CONTRIBUTING, ARCHITECTURE, note 01 risk R1, `.github/dependabot.yml` comment.

## Verified (all offline-reproducible from the lock; commands below)

* `pip download -r requirements.lock --only-binary=:all: --python-version {3.15,3.14,3.12} --platform
  manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 --implementation cp --no-deps`
  succeeds on all three (hashes checked), also on aarch64 for 3.15 and 3.14 (the release image is amd64 + arm64).
  `requirements-dev.lock`: succeeds on 3.14 and 3.12; on 3.15 everything but the marked PyYAML has a wheel.
* Full suite with the CI install command (`pip install --no-deps --require-hashes --only-binary=:all: -r
  requirements-dev.lock`): Python 3.12.3 (host venv): 3653 passed. CPython 3.14.8 and 3.15.0 from the real Chainguard
  `latest-dev` images (unpacked from cgr.dev into a chroot under the scratchpad, Node 22 copied in): 3.14.8 3652 passed;
  3.15.0 3064 passed, 2 skipped (the PyYAML modules). One test is deselected in the chroots
  (`test_upgrade_starting_points_exist` needs the repository history, which the copy lacks); it passes in the worktree.
* zizmor 1.30.1 offline on `.github/workflows`: no findings. `.github/scripts/yaml_parse.py`: 38 files, 0 problems.
  Not run: actionlint, hadolint, kubeconform (not installed, no GitHub downloads here), the container build and
  smoke test (no container daemon here); CI runs them.

## Open / for the owner

* `latest-dev` has already moved on (`733f745e...`, built 2026-10-14); the digests here are the ones in #32, a
  matching pair built 2026-10-11. Dependabot will propose the newer pair, and (see the comment in
  `.github/dependabot.yml`) its bump of the handbook line to a 3.15 digest fails the image build until PyYAML
  publishes a cp315 wheel.
* pydantic 2.14 behaviour changes worth a look on the next release: enum constructors are called in both
  validation modes, `multiple_of` must be positive, `NameEmail` rejects newlines. The suite passes unchanged.
* Python 3.14.0rc2 (the only 3.14 `uv` offers here) lacks `typing._eval_type(prefer_fwd_module=...)`, which pydantic
  2.14 uses on 3.14; final 3.14.x has it (CI's setup-python serves a final release; 3.14.8 above passed).

## Commands that reproduce the checks

* `scripts/lock.sh --upgrade-package pydantic==2.14.0 --upgrade-package pydantic-core==2.50.0`
* `pip download -r requirements.lock --only-binary=:all: --python-version 3.15 --platform manylinux_2_28_x86_64
  --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 --implementation cp --no-deps -d <tmp>`
* `python -m pytest -q -x -p no:cacheprovider` and `node tests/js/run_vectors.mjs`
* `zizmor --offline --persona regular .github/workflows`
