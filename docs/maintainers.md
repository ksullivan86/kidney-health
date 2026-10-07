# Maintainer guide: releases and repository settings

For the people who can merge to `main`, push tags and change the repository's settings. Contributors
start with [CONTRIBUTING.md](../CONTRIBUTING.md); the security background is in
[SECURITY.md](../SECURITY.md) and [docs/security.md §9](security.md#9-supply-chain-what-ci-guarantees).

## Contents

* [Image tags](#image-tags)
* [Release process](#release-process)
* [What `release.yml` does](#what-releaseyml-does)
* [Verify the published image, its signature and SBOM](#verify-the-published-image-its-signature-and-sbom)
* [`HOLD_LATEST`: keeping `:latest` back](#hold_latest-keeping-latest-back)
* [Repository settings to turn on](#repository-settings-to-turn-on)
* [Refreshing the lock files](#refreshing-the-lock-files)
* [Scheduled jobs and what to do when they fail](#scheduled-jobs-and-what-to-do-when-they-fail)

## Image tags

ARCHITECTURE.md decision 7, implemented by [`.github/workflows/release.yml`](../.github/workflows/release.yml):

| Git event | Image tags |
|---|---|
| push to `main` | `:edge`, `:sha-<short>` |
| tag `vX.Y.Z` | `:X.Y.Z`, `:X.Y`, `:latest` (unless `HOLD_LATEST` is `true`) |
| tag `vX.Y.Z-rc1` (anything with `-`) | only `:X.Y.Z-rc1` |

Tags move only after the Grype gate passed for both platforms, and (on a public repository) after the
index was signed and attested. Users are told to track `:X.Y` or a verified digest.

## Release process

1. **Prepare on a branch and merge it** (pull request, green CI):
   * the version in `pyproject.toml`, `APP_VERSION` in `app/main.py` and `APP_VERSION` in
     `app/static/js/views/settings.js` (`tests/test_settings_ui.py` keeps the last two equal); the
     service worker's cache version is a content hash and changes by itself;
   * `CHANGELOG.md`: rename `## Unreleased` to `## X.Y.Z — YYYY-MM-DD` (UTC) with highlights, upgrade
     notes, security fixes and known limitations; `docs/ROADMAP.md`: move shipped items out;
   * `ARCHITECTURE.md`, `docs/` and the handbook's "Using the app" pages describe what ships.
2. **Checks before the tag** (the ones CI cannot do):
   * the browser harnesses: `python tools/e2e/parity.py`, `regress.py --no-pytest`, `sandbox.py`,
     `device.py`, `guidance_perf.py` and `learn.py` ([tools/e2e/README.md](../tools/e2e/README.md));
   * the manual device matrix of note 02 ("Manual device test matrix"): an iPhone, an iPad, an Android
     phone with Chrome, desktop Chrome and Safari, over HTTPS (live camera, install, offline outbox) and
     plain HTTP (barcode photo, typed digits);
   * `python3 scripts/bench_guidance.py --max-p95 200` on a Raspberry Pi 4 and 5 with the image's
     Python, results recorded in [docs/guidance.md](guidance.md#performance);
   * for a release that changes the upgrade path: decide whether to hold `:latest` (below).
3. **Tag `main`** with an annotated (preferably signed) tag and push it:

   ```bash
   git switch main && git pull --ff-only
   git tag -s vX.Y.Z -m "vX.Y.Z"        # or -a without a signing key
   git push origin vX.Y.Z
   ```

4. **Watch `Release image`** in the Actions tab (build → two Grype gates → sign, attest, tag). If the
   `release` environment has required reviewers, approve the publish job there.
5. **Verify** the published image (next sections) before announcing it.
6. **Publish the GitHub release** from the tag with the changelog section as its notes:

   ```bash
   awk '/^## X\.Y\.Z /{p=1; next} /^## /{p=0} p' CHANGELOG.md > /tmp/notes.md
   gh release create vX.Y.Z --verify-tag --title "X.Y.Z" --notes-file /tmp/notes.md
   ```

7. **Afterwards**: open `## Unreleased` in `CHANGELOG.md`; watch the next weekly image scan.

**Patch releases of an older minor version** (for example 0.3.4 after 0.4.0 shipped): branch
`release/0.3` from the last `v0.3.*` tag, fix, and tag from that branch. `release.yml` moves `:latest`
on *every* non-pre-release tag, so set `HOLD_LATEST=true` before pushing such a tag and remove it
afterwards; otherwise `:latest` would go back to 0.3.

**If the release workflow fails:** no tag moved (tags move last). Fix the cause on `main`, then either
re-run the failed jobs (same digest) or, if the code had to change, delete the unreleased git tag and
tag again, or tag the next patch version. Never move a tag that has already published an image.

## What `release.yml` does

1. **build** (amd64 + arm64): builds `deploy/Containerfile` with buildx and pushes it **by digest
   only** (no tag yet), with buildx provenance (`mode=max`) and an SBOM stored in the image index.
2. **scan** (one job per platform, read-only permissions, no secrets): Grype fails the release on any
   High or Critical vulnerability that has a fix.
3. **publish** (environment `release`): on a public repository, `cosign sign` keylessly signs the index
   digest (the certificate names `release.yml` and the git ref; the signature is a Sigstore bundle
   stored as an OCI 1.1 referrer), then GitHub artifact attestations record SLSA build provenance and an
   SPDX SBOM made by Syft from the published index. **Last**, `docker buildx imagetools create` points
   the tags at the scanned (and signed) digest. On a private repository the signing and attestation
   steps are skipped (GitHub offers them to private repositories only on Enterprise Cloud).

## Verify the published image, its signature and SBOM

```bash
scripts/verify-image.sh X.Y.Z      # resolves the digest, checks the signature and both attestations
```

It needs cosign 3.0 or later, a current `gh` and one of crane, skopeo or `docker buildx`; the manual
commands are in [SECURITY.md](../SECURITY.md#verifying-the-image-before-you-run-it). To read the SBOM
itself:

```bash
D=$(crane digest ghcr.io/ksullivan86/kidney-health:X.Y.Z)
gh attestation verify "oci://ghcr.io/ksullivan86/kidney-health@$D" --repo ksullivan86/kidney-health \
  --signer-workflow ksullivan86/kidney-health/.github/workflows/release.yml \
  --predicate-type https://spdx.dev/Document/v2.3 --format json \
  | jq '.[0].verificationResult.statement.predicate.packages | length'   # number of packages
docker buildx imagetools inspect "ghcr.io/ksullivan86/kidney-health@$D" --format '{{ json .SBOM }}'  # buildx's in-index SBOM
```

Check that the SBOM lists the Python packages of `requirements.lock` at their locked versions and no
package manager or shell.

## `HOLD_LATEST`: keeping `:latest` back

A repository variable (Settings → Secrets and variables → Actions → Variables). When it is `true`, a
`v*` tag publishes `:X.Y.Z` and `:X.Y` but leaves `:latest` on the previous release.

* **v0.3.0: not used.** Owner decision (2026-10-06): `:latest` moves to v0.3.0 when it is tagged and
  `HOLD_LATEST` stays unset; v0.2 hosts are warned in CHANGELOG.md, README.md and
  [docs/deployment.md](deployment.md#from-v02-to-v03) (ARCHITECTURE.md decision 7).
* Use it for a release that would break hosts that auto-update `:latest` until they change their
  deployment files, and for patch tags of an older minor version (above). Remove it again (or set it
  to anything but `true`) when the hold should end; the next `v*` tag then moves `:latest`, or move it
  by hand: `docker buildx imagetools create --tag ghcr.io/ksullivan86/kidney-health:latest
  ghcr.io/ksullivan86/kidney-health:X.Y.Z`.

## Repository settings to turn on

Once, when the repository is created or made public (Settings unless noted):

* **Code security → Dependency graph**: on (public repositories have it by default). Dependency review
  in CI and the SBOM view need it.
* **Code security → Dependabot alerts** and **Dependabot security updates**: on. Version updates come
  from [`.github/dependabot.yml`](../.github/dependabot.yml) (Actions, base images, the lint tools) with a
  7-day cooldown; Dependabot cannot update the `*.lock` files (below).
* **Code security → Code scanning → CodeQL**: use the repository's workflow
  ([`.github/workflows/codeql.yml`](../.github/workflows/codeql.yml), Python, JavaScript and the
  workflows with `security-extended`; it runs only while the repository is public), not "default setup",
  so the two do not run twice. **Dismiss a false positive** in Security → Code scanning with the matching
  reason ("False positive", "Used in tests" or "Won't fix") **and a comment saying why** (the code path,
  the check that makes it safe, a link to the test); never dismiss without a reason, and prefer fixing
  the code when the alert has a point.
* **Code security → Private vulnerability reporting**: on. [SECURITY.md](../SECURITY.md) and the issue
  form's contact link send reporters there.
* **Rules → Rulesets**:
  * a branch ruleset for `main`: require a pull request (at least one approval when there is a second
    maintainer; dismiss stale approvals), require status checks to pass and the branch to be up to date
    (`pytest (Python 3.12)`, `pytest (Python 3.14)`, `JS parity vectors (Node)`,
    `lint (workflows, Containerfiles, manifests, scripts)`, `zizmor (workflow security audit)`,
    `image (chainguard) build + smoke test`, `image (debian) build + smoke test`,
    `handbook (build, content, links, /learn in Chromium)`; once public also `dependency review` and the
    three `CodeQL (…)` checks), block force pushes and deletion;
  * a tag ruleset for `v*`: only maintainers may create them; block updates (moving a tag), deletion
    and force pushes.
* **Actions → General**: "Require actions to be pinned to a full-length commit SHA"; workflow
  permissions "Read repository contents" by default; **allow GitHub Actions to create pull requests**
  (the lock refresh opens one); require approval for workflows from outside collaborators.
* **Issues → Labels**: make sure `bug`, `enhancement` and `clinical-content` exist (the issue forms in
  `.github/ISSUE_TEMPLATE/` apply them; a missing label is silently skipped). Route `clinical-content`
  issues to a clinician reviewer ([CONTRIBUTING.md](../CONTRIBUTING.md#clinical-content-policy-and-sign-off)).
* **Environments → `release`** (optional): required reviewers and a deployment rule for `main` and `v*`
  tags, so a person approves every publish.
* **Releases → Immutable releases**: on, so a published release's tag and assets cannot change.
* **GHCR package** (your profile → Packages → `kidney-health` → Package settings): **visibility
  public** once the repository is public (people pull without logging in, and verification needs it);
  "Manage Actions access" limited to this repository with write access.
* **Pages** (the public handbook, optional): Settings → Pages → Build and deployment → Source **"GitHub
  Actions"**; Environments → `github-pages` deployments from `main` only; then the repository variable
  **`HANDBOOK_PAGES=true`** turns on [`handbook-pages.yml`](../.github/workflows/handbook-pages.yml).
  Afterwards set `HANDBOOK_PUBLIC_URL` on servers that should link to it and point the image's
  `org.opencontainers.image.documentation` label at it (note 08 §4.8 "Owner setup"). A Pages site
  built from a private repository on GitHub Pro or Team is public on the internet.

## Refreshing the lock files

Python dependencies are hash-locked: `requirements.lock`, `requirements-dev.lock`,
`handbook/requirements.lock`, `handbook/requirements-zensical.lock` and `tools/e2e/requirements.lock`,
all generated by [`scripts/lock.sh`](../scripts/lock.sh) (pip-tools under Python 3.14, inside the
pinned `python:3.14-slim` image when Podman or Docker is available).

* **Weekly:** [`refresh-locks.yml`](../.github/workflows/refresh-locks.yml) runs
  `PIP_UPLOADED_PRIOR_TO=P7D scripts/lock.sh --upgrade` (only releases at least 7 days old) and opens or
  updates the pull request `deps/refresh-locks`. A pull request opened by the workflow token does not
  start CI: **close and reopen it** to run CI, review the version changes (changelogs, new
  dependencies, licences), then merge.
* **A security fix that cannot wait:** run the workflow by hand with `cooldown_days` 0, or locally
  `scripts/lock.sh --upgrade-package NAME`, and open a pull request.
* **By hand:** `scripts/lock.sh` (no upgrade: only re-resolves after a change to an `.in` file) or
  `scripts/lock.sh --upgrade`. Never edit a `.lock` file by hand. A new runtime dependency needs a
  decision in `ARCHITECTURE.md` first.

## Scheduled jobs and what to do when they fail

| Workflow | When | On failure |
|---|---|---|
| [`scheduled-scan.yml`](../.github/workflows/scheduled-scan.yml) | Mondays | Opens or comments on a tracking issue. Refresh the locks or the base image (Dependabot), release a patch version. |
| [`refresh-locks.yml`](../.github/workflows/refresh-locks.yml) | Mondays | Opens a pull request (see above). |
| [`codeql.yml`](../.github/workflows/codeql.yml) | Mondays and every push | Alerts in Security → Code scanning: fix, or dismiss with a reason and a comment. |
| [`handbook-links.yml`](../.github/workflows/handbook-links.yml) | Mondays | Opens or comments on an issue labelled `handbook-links`. Update the source in `handbook/sources.yml` (and `checked`), rebuild. |
| [`vendor-check.yml`](../.github/workflows/vendor-check.yml) | Mondays | A warning when the vendored barcode decoder has a newer release: update it with `scripts/vendor_barcode.py` ([app/static/vendor/README.md](../app/static/vendor/README.md)). A failure means the committed files no longer match their pins. |
| [`off-live-check.yml`](../.github/workflows/off-live-check.yml) | Wednesdays | A warning when Open Food Facts' answers no longer map: compare with the recorded fixtures (`tests/fixtures/off/`), adapt `app/off.py`. |
