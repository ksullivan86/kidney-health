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
     `device.py`, `guidance_perf.py`, `learn.py`, `journey.py` (needs a built handbook) and `upgrade.py`
     (needs a full clone), and the ones that belong to a feature: `prefs.py`, `ask.py`, `ask_voice.py`, `fallback.py`,
     `symptoms.py`, `visitprep.py`, `body.py`, `menuplan.py` (needs a built handbook), `demo_local.py`, `import_walk.py`, `body_import.py`,
     `push.py`, `lab_pdf.py` and `mcp_smoke.py`
     ([tools/e2e/README.md](../tools/e2e/README.md)). Run them one after another on a machine that is busy:
     `ask.py` and `fallback.py` each failed once when run beside a full test run, because they read the server right after a
     click (they pass alone);
   * the workflows that only run on a schedule, on a tag or after an owner setting, the first time they
     matter: `refresh-locks.yml` once by hand (*Run workflow*; review the pull request it opens: its
     `scripts/lock.sh` path was checked only by hand when it was written), `handbook-links.yml` once by
     hand, and `handbook-pages.yml` after setting `HANDBOOK_PAGES`;
   * the live AI evaluations before a model is recommended (`scripts/ai_eval.py`, and `--chat` for Ask, for the current
     `PROMPT_VERSION`; [docs/dev/ai-eval/README.md](dev/ai-eval/README.md)). `ai_eval.py` skips the cases that need the routing,
     so also try, once with a real Ollama and a cloud key: a photo of a real lab report on the local AI (which units and dates a
     vision model misreads), the **PDF** a real portal (Quest, Labcorp, a hospital portal) gives out, chosen in Labs on an iPhone
     (Safari) and on a desktop browser (the pages drawn by the bundled pdf.js, how long a page takes, whether a scanned PDF comes out blank),
     and the route `local_then_cloud` (the cloud AI asked only when the local answer fails the checks);
   * speech to text: pin the image of `deploy/compose.stt-whisper.yaml` by a digest you checked (`crane digest`; the file carries a
     placeholder), start it with a real model in its volume, check its health check and cache path, and talk to Ask from an
     iPhone (Safari) and an Android phone (Chrome): the first tap asks for the consent, then the microphone;
   * the manual device matrix of note 02 ("Manual device test matrix"): an iPhone, an iPad, an Android
     phone with Chrome, desktop Chrome and Safari, over HTTPS (live camera, install, offline outbox) and
     plain HTTP (barcode photo, typed digits), with an entry edited and another deleted while offline and a conflict made from
     a second device (the card in Settings → This device), Settings → Your data → Import from a file with the phone's own file
     picker (choose the export `.zip` kept in the Files app or Android's picker, and an `export.json` from inside it; after closing
     the password prompt, choosing the same file again asks for the password again), and the screen readers (VoiceOver, TalkBack) on Profile, Lab results, the
     entry sheet and Settings;
   * Settings → Account → Your data → **Import from a file** is covered by `import_walk.py` in Chromium (export from one
     account, import the `export.json` into a fresh account with and without "Add to my existing data" and "Also replace
     my profile, targets and settings", the files it refuses and the password prompt); on a phone it is part of the device
     matrix above, because the harness hands the file to the page and only a phone's own file picker shows how a real one
     behaves;
   * Reading the zip in the browser with a real Health `export.zip` from an iPhone (note 11, "Re-verify"): Settings → Your data
     → Import from a file with the app's own export `.zip` in Safari on the phone and in a desktop browser, the Health import
     sheet and Labs → Import from Apple Health, each with the `.zip` itself. The tests build their own archives (`zipfile` and a
     hand-written builder), so this is the only check on what Apple's archiver really writes (its methods, zip64, the
     `__MACOSX` extras); the reader refuses what it does not understand with a plain reason and the old "unzip it" advice;
   * Labs → Import from Apple Health with a real Health export from an iPhone (Safari, the `export.zip` itself and the Files
     app's Select All in `clinical-records`): the sample resources in `tests/data/fhir_labs_vectors.json` are hand-written, so look at the
     headline's counts for tests or units a real export has that the reader skips, and add a LOINC code only after
     the lookup described in [targets-and-labs.md](targets-and-labs.md#in-the-app);
   * Weights and blood pressure from the Health app with a real `export.xml` from an iPhone (the Health app's Export All Health
     Data, `export.zip` chosen as it is and, once, `export.xml` unzipped in the Files app; Safari on the phone, so the file's own picker
     and a file of hundreds of megabytes are read): `body_import.py` and the vectors in `tests/data/apple_health_vectors.json` use hand-written records, so look at
     the review's "Left out" lines for units or records a real export has that the reader skips, check that a watch's readings
     are listed apart and unticked, that the progress line moves and Cancel stops the read, and that importing the same export
     again adds nothing (note 10 §4.8, "Re-verify"). Also an export with a source that has more than 20 weights or 30
     readings in a day: the sheet says how many were left out;
   * Phone shortcuts with a real iPhone (the iOS version noted): follow the handbook's "From a phone shortcut" (Weight and blood pressure)
     step by step, with a token made in Settings → Account → Your data → Phone shortcuts. `push.py` posts from a harness, so it cannot show
     the Shortcuts app: check that the action names and their order match, that **Format Date** gives a time with its zone, that the JSON
     body is what the server accepts (the Show Result answer is counts such as `added` 1), that a personal automation runs without asking
     (or says what to tap), that the phone reaches the server from the place it is used, and that a second run adds nothing; correct the
     handbook where it differs and tick the row in `handbook/REVIEW.md`;
   * Labs → Import from a patient portal file with a real C-CDA download from a patient portal (MyChart and at least one other; the
     "Download" of the health summary or a visit summary, XML or C-CDA format, not the PDF): the documents in
     `tests/data/ccda_labs_vectors.json` and `tools/e2e/regress.py` are hand-written, so look at the headline's counts for
     results a real file has that the reader skips (a code or unit the table lacks, a result only on the organizer's `effectiveTime`,
     a section with other template ids, a file refused for a DOCTYPE), and add a LOINC code only after the lookup described in
     [targets-and-labs.md](targets-and-labs.md#in-the-app). Also check, in Safari on an iPhone and in Chrome, that the page reads the
     file (the Trusted Types policy `kh-xml` is the part only a real browser exercises) and that no console error other than
     Chromium's "Refused to apply inline style" for a malformed file appears;
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
6. **Publish the GitHub release** with the changelog section as its notes. The `release notes (image
   digest)` job of `release.yml` appends an **Image** section (the multi-arch index digest to pin, the
   tags that point at it, and the note that anonymous pulls need a public GHCR package) when the
   release exists by the time the job runs, and it never adds it twice. Paste the section as
   **Markdown** (the file `CHANGELOG.md` itself, or the command below), not copied from the rendered
   page: a copy of the page carries its HTML and styles, and GitHub cuts the notes off at 125,000
   characters. If the notes and the Image section together would pass that limit, the job warns
   ("Release notes too long for the Image block") and prints the block instead of adding it; shorten
   the notes and re-run the job, or paste the block by hand. A long section (0.4.0's is about 94,000
   characters) can be cut to the highlights, upgrade steps, security and known limitations, with a
   link to the full section in `CHANGELOG.md` at the tag.

   * **Release first, tag by GitHub** (the UI's "Publish release" with a new tag, or the command below):
     the release exists before the workflow starts, so the Image section is appended automatically.

     ```bash
     awk '/^## X\.Y\.Z /{p=1; next} /^## /{p=0} p' CHANGELOG.md > /tmp/notes.md
     gh release create vX.Y.Z --target main --title "X.Y.Z" --notes-file /tmp/notes.md
     ```

   * **Signed tag first** (step 3's `git tag -s`): create the release after the workflow finishes and
     paste the Image block the `notes` job printed in its log (Actions → the run → "release notes
     (image digest)"); the build job's summary shows the same digest.

7. **Afterwards**: open `## Unreleased` in `CHANGELOG.md`; watch the next weekly image scan.

**Patch releases of an older minor version** (for example 0.4.4 after 0.5.0 shipped): branch
`release/0.4` from the last `v0.4.*` tag, fix, and tag from that branch. `release.yml` moves `:latest`
on *every* non-pre-release tag, so set `HOLD_LATEST=true` before pushing such a tag and remove it
afterwards; otherwise `:latest` would go back to 0.4.

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
* **The rule from v0.4.0 on (owner, 2026-10-22): `:latest` moves with every release tag.** Leave `HOLD_LATEST` unset when you tag
  `vX.Y.Z`. A test release is a pre-release tag (anything with `-`, such as `v0.5.0-rc1`), which publishes only `:X.Y.Z-rc1` and never
  moves `:latest` on its own. The one remaining use of `HOLD_LATEST` is the patch of an **older** minor version (see "Patch releases of an older minor version" above), where moving
  `:latest` would take it backwards.
* **v0.4.0: not held.** The release runs schema steps 8 to 17 at start without an automatic copy, and moves the shipped files from
  `:0.3` to `:0.4`. A host that auto-updates `:latest` migrates its database at the next pull; one that tracks `:0.3` stays on 0.3.x.
  CHANGELOG.md, "Upgrading from 0.3", says to take a backup first.
* **v0.5.0: not held.** The release runs schema steps 18 and 19 at start without an automatic copy, and moves the shipped files from
  `:0.4` to `:0.5`. A host that auto-updates `:latest` migrates its database at the next pull; one that tracks `:0.4` stays on 0.4.x.
  CHANGELOG.md, "Upgrading from 0.4", says to take a backup first.
* **v0.5.1: not held.** A security release: new base image digests only, no schema step, so `:0.5` and `:latest` move as usual.
* **v0.6.0: not held.** The release runs schema step 20 at start without an automatic copy, and moves the shipped files from
  `:0.5` to `:0.6`. A host that auto-updates `:latest` migrates its database at the next pull; one that tracks `:0.5` stays on 0.5.x.
  CHANGELOG.md, "Upgrading from 0.5", says to take a backup first.
* **v0.7.0: not held.** The release runs schema step 21 at start without an automatic copy, and moves the shipped files from
  `:0.6` to `:0.7`. A host that auto-updates `:latest` migrates its database at the next pull; one that tracks `:0.6` stays on 0.6.x.
  CHANGELOG.md, "Upgrading from 0.6 or 0.5", says to take a backup first. If v0.5.1 and v0.6.0 were never tagged, tag only v0.7.0:
  it carries both.
* Use it for patch tags of an older minor version (above), and only with the owner's say-so for anything else. Remove it again (or set it
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
    (`pytest (Python 3.12)`, `pytest (Python 3.14)`, `pytest (Python 3.15)`, `JS parity vectors (Node)`,
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
pinned `python:3.14-slim-trixie` image when Podman or Docker is available).

The pins must have wheels (the image installs `--only-binary=:all:`) for every Python the project
runs on: 3.12 and 3.14 in CI and 3.15 in the published image. After a refresh, check the app lock for
each (this also verifies the hashes); a package without a wheel for a Python names itself:

```bash
for v in 3.12 3.14 3.15; do
  pip download -r requirements.lock --only-binary=:all: --python-version $v --implementation cp --no-deps \
    --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 -d "$(mktemp -d)"
done
```

Add `aarch64` platforms to check the arm64 image. PyYAML has no Python 3.15 wheel yet, so
`requirements-dev.in` carries `pyyaml>=6,<7; python_version < "3.15"` and the handbook stage of
`deploy/Containerfile` stays on a Python 3.14 digest (the `TEMPORARY SPLIT` comment there). When
PyYAML publishes a cp315 wheel: drop the marker, run `scripts/lock.sh`, make the handbook `FROM` line
identical to the builder's again, remove the comment and the skip in `tests/test_handbook_content.py`
and `tests/test_deploy.py` (`test_every_yaml_file_parses`).

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
| [`vendor-check.yml`](../.github/workflows/vendor-check.yml) | Mondays | A warning when the vendored barcode decoder or pdf.js has a newer release: update it with `scripts/vendor_barcode.py` ([app/static/vendor/README.md](../app/static/vendor/README.md)). A failure means the committed files no longer match their pins. |
| [`off-live-check.yml`](../.github/workflows/off-live-check.yml) | Wednesdays | A warning when Open Food Facts' answers no longer map: compare with the recorded fixtures (`tests/fixtures/off/`), adapt `app/off.py`. |
