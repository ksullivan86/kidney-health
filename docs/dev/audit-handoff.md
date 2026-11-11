# Kidney Health audit handoff

Status: this audit batch is verified and published; open follow-ups are recorded for continued auditing.

Original snapshot: 2026-11-06; follow-ups refreshed 2026-11-11. The user asked to continue auditing bugs and improvements, create PRs, and **leave every PR unmerged** for another session. An earlier message asked to keep auditing until "tomorrow at 3pm PST"; its original message timestamp is not recorded here, so do not infer a new absolute deadline from this snapshot date. No scheduled or unattended runner was installed.

This is the durable index. Per-fix progress notes are linked to saved commits so they remain readable if branches are updated or progress files are pruned during a release. Refresh the PR status before acting: this is a checkpoint, not a live dashboard.

## Start here

1. Read `AGENTS.md`, `CLAUDE.md`, the relevant parts of `ARCHITECTURE.md`, and the design notes before editing.
2. Review the completed checkpoints and unresolved follow-ups below, then open the relevant PR and saved progress note. The source and regression tests are pushed.
3. Reuse the indicated worktree when present. `/workspace/kidney-health` is an older device-fix checkout, **not the current audit branch**.
4. Verification for the original batch is complete. Another session integrated #153–167, then fixed both user-reported follow-ups in #170 (0.23.0). The resumed audit starts at main `01f5298`; see #175 and its progress note below. Keep every new PR unmerged.
5. Continue auditing from the recorded leads only after checking what is already covered. Commit only your own paths.

These branches started from main `cea3c944f5fb80c4110ce60a512b874e6da79d7e` (release 0.22.2). No release, version bump or deployment was made. Earlier fixes #144, #145, #146, #148 and #149 were integrated by another session through releases #151/#152.

## Published changes

The latest refresh shows #153–167 merged by another session. This audit did not merge any PR. The table preserves their verification and saved notes. The full pytest results listed below have two expected skips; the runs that report warnings have the two existing handbook citation warnings. Exact commands and limitations are in each saved note and PR body.

| PR and change | State at snapshot | Verification | Saved progress note |
|---|---|---|---|
| [#153: Recheck assistant and phone access before saving](https://github.com/ksullivan86/kidney-health/pull/153) | Merged by another session; closed | 7,431 pytest; 45 authorization races | [ca2b0ae](https://github.com/ksullivan86/kidney-health/blob/ca2b0aec2cbdedaa324f245eb3e0e52674017563/docs/dev/progress/token-write-audit.md) |
| [#154: Keep Plan sheet replies with their original draft](https://github.com/ksullivan86/kidney-health/pull/154) | Merged by another session; closed | 20 Node cases; 44 browser checks; 59 affected rechecks (see note below) | [bc1b38b](https://github.com/ksullivan86/kidney-health/blob/bc1b38bc856e4ba6a6f4d76b5270bac11c7a9b3d/docs/dev/progress/saved-meal-audit.md) |
| [#155: Keep account imports tied to the reviewed file and choices](https://github.com/ksullivan86/kidney-health/pull/155) | Merged by another session; closed | 7,387 pytest; 113 import browser checks | [d3918fe](https://github.com/ksullivan86/kidney-health/blob/d3918fe9f19061ca774ea5e0c030e858ac74c651/docs/dev/progress/account-import-audit.md) |
| [#156: Keep iPhone sync work with its original server and token](https://github.com/ksullivan86/kidney-health/pull/156) | Merged by another session; closed | 7,386 pytest in CI; native iOS/Swift tests; 17 local policy checks | [c5b6f70](https://github.com/ksullivan86/kidney-health/blob/c5b6f70e6229bedd6ba39e05e63a25991e8bf170/docs/dev/progress/ios-settings-audit.md) |
| [#157: Keep concurrent Care team changes counted once](https://github.com/ksullivan86/kidney-health/pull/157) | Merged by another session; closed | 7,392 pytest; 6 concurrent helper-count cases | [cdcfd2a](https://github.com/ksullivan86/kidney-health/blob/cdcfd2ab655edecdb6985de0f1d820c33cbd491e/docs/dev/progress/care-change-accounting-audit.md) |
| [#158: Correct stale security support and upgrade guidance](https://github.com/ksullivan86/kidney-health/pull/158) | Merged by another session; closed | 100 deployment/documentation checks; documentation only | [c5d7eb4](https://github.com/ksullivan86/kidney-health/blob/c5d7eb414c0e913f7fb63e48482933ee5e6dde8f/docs/dev/progress/security-support-docs-audit.md) |
| [#159: Recheck Ask trust before each automatic save](https://github.com/ksullivan86/kidney-health/pull/159) | Merged by another session; closed | 7,400 pytest; 210 focused; 144 browser checks | [79d4ab8](https://github.com/ksullivan86/kidney-health/blob/79d4ab8e12d0e9e5aa8ca5e498d6dd8421a4888f/docs/dev/progress/ask-trust-audit.md) |
| [#160: Cancel stale device sign-in callbacks before storing credentials](https://github.com/ksullivan86/kidney-health/pull/160) | Merged by another session; closed | 7,414 pytest; 82 device checks; [complete CI](https://github.com/ksullivan86/kidney-health/actions/runs/42220785538) | [09695ba](https://github.com/ksullivan86/kidney-health/blob/09695ba3a9a8bd646f82cc19651156f69417b22c/docs/dev/progress/device-callback-audit.md) |
| [#161: Apply password-change requirements to pending provider account actions](https://github.com/ksullivan86/kidney-health/pull/161) | Merged by another session; closed | 7,392 pytest; 116 focused; [complete CI](https://github.com/ksullivan86/kidney-health/actions/runs/42221270024) | [2e985e0](https://github.com/ksullivan86/kidney-health/blob/2e985e0e164fdad4ce9376d052fb5828ef50f974/docs/dev/progress/oidc-password-change-audit.md) |
| [#162: Preserve measurement drafts and their displayed units during late saves](https://github.com/ksullivan86/kidney-health/pull/162) | Merged by another session; closed | 7,387 pytest; 414 browser checks; [complete CI](https://github.com/ksullivan86/kidney-health/actions/runs/42223205700) | [c1a6019](https://github.com/ksullivan86/kidney-health/blob/c1a6019baf03aa6da043fd29ae3542beaefd66a2/docs/dev/progress/body-editor-audit.md) |
| [#163: Serialize import duplicate checks and daily measurement limits](https://github.com/ksullivan86/kidney-health/pull/163) | Merged by another session; closed | 7,399 pytest; 270 focused; [complete CI](https://github.com/ksullivan86/kidney-health/actions/runs/42223648313) | [a1e84e9](https://github.com/ksullivan86/kidney-health/blob/a1e84e9c3e2bb441cc587c65d2c1363af6475a60/docs/dev/progress/record-write-transactions-audit.md) |
| [#164: Keep AI connection-test results with the settings they tested](https://github.com/ksullivan86/kidney-health/pull/164) | Merged by another session; closed | 7,402 pytest; 16 lifecycle cases; [complete CI](https://github.com/ksullivan86/kidney-health/actions/runs/42225013275) | [7aebc8c](https://github.com/ksullivan86/kidney-health/blob/7aebc8c4f65dbda9d94e428e950084121e6ef270/docs/dev/progress/ai-probe-audit.md) |
| [#165: Keep newer symptom drafts intact when older saves return](https://github.com/ksullivan86/kidney-health/pull/165) | Merged by another session; closed | 7,387 pytest; 65 focused; 87 browser checks; [complete CI](https://github.com/ksullivan86/kidney-health/actions/runs/42225683694) | [36077d1](https://github.com/ksullivan86/kidney-health/blob/36077d1eb059329d6e37a8ac5e9d8ff072e610f0/docs/dev/progress/symptom-editor-audit.md) |
| [#166: Reuse the shared USDA food during simultaneous imports](https://github.com/ksullivan86/kidney-health/pull/166) | Merged by another session; closed | 7,392 local pytest; 6 concurrency/rollback cases; 200 + 77 focused; complete CI | [0be5d56](https://github.com/ksullivan86/kidney-health/blob/0be5d5698d699700f15b379659fee597534c7a51/docs/dev/progress/usda-import-audit.md) |
| [#167: Preserve food entry and Quick add drafts across delayed requests](https://github.com/ksullivan86/kidney-health/pull/167) | Merged by another session; closed | 7,388 pytest; 23 Node cases; 62 focused; 78 new + 87 reliability browser checks; complete CI | [374c40a](https://github.com/ksullivan86/kidney-health/blob/374c40adb3a3a18b46c1e91528b0d6d3e28272ef/docs/dev/progress/food-entry-audit.md) |

For #154, the first full run had 7,386 passes and two failures in test-maintenance assertions. Those assertions were corrected and all 59 affected tests passed afterward. All 7,388 unique cases were checked; do not describe that as a second all-green local full run. Follow the PR checks for any later CI run.

The complete CI links for #160–165 passed Python 3.12/3.14/3.15, native iOS/Swift, handbook, lint and image checks at their tested commits. Later progress-note-only commits may have started fresh runs. Check the current head and current checks before integration.

## Resume details

### #166: simultaneous USDA imports — complete

- Branch: `audit/usda-import-concurrency`; saved head `0be5d5698d699700f15b379659fee597534c7a51`.
- Worktree: `/workspace/work/usda-import-audit-src`.
- Full local result: **7,392 passed, 2 skipped, 2 existing warnings**. All six new cases pass; unchanged main fails four actual duplicate-ID cases and passes two rollback cases. An earlier test harness needed HTTPS setup correction; its setup failures are not product evidence.
- Broader API/isolation/MCP/Ask suite: 200 passed. Separate MCP transactional-write suite: 77 passed. Ruff, OpenAPI, generated pages, parity and strict handbook pass.
- CI run: [42279711531](https://github.com/ksullivan86/kidney-health/actions/runs/42279711531), complete and successful.
- Complete: progress note and validation finalized; another session has merged #166. No code work remains for this fix.
- Logs: `/workspace/work/usda-import-audit/`, especially `baseline-final.log`, `lifecycle-verified.log`, `focused.log`, `mcp-write.log`, `full-pytest.log` and `handbook.log`.
- Preserve the transaction contract: `upsert_usda_food` must not commit an existing assistant write. It starts `BEGIN IMMEDIATE` only when the caller has no transaction. Do not replace this with the committing `begin_immediate` wrapper inside a wider save.

### #167: food-entry and Quick add request ownership — complete

- Branch: `audit/food-entry-editor-lifecycle`; saved head `374c40adb3a3a18b46c1e91528b0d6d3e28272ef`.
- Worktree: `/workspace/work/food-entry-audit-src`.
- Source: `app/static/js/views/add.js`; regression cases: `tests/js/food_entry_lifecycle.test.mjs` and its Python wrapper.
- **23 Node cases pass; unchanged main fails 17 and passes six.** These cover saves/deletes after reopen, duplicate prevention, stale metadata for the same entry object, frozen submitted entry controls, deferred metadata, current versus stale offline conflicts, base versions, untouched quantities, date navigation and low-treatment purpose.
- **62 focused checks and all 78 new Chromium checks pass** at 375 light / 1280 dark. Browser harness: `tools/e2e/food_entry_late_replies.py`, registered in the tool index/tests. The first browser run used a duplicate fixture name across viewports; distinct names fixed that harness issue and the complete rerun passed.
- Ruff, OpenAPI, generated pages, all 30 direct Node regression files, parity and strict handbook pass. The existing reliability browser walk also passed all 87 checks (exit 0; Playwright emitted teardown cancellation diagnostics). **Full local pytest: 7,388 passed, 2 skipped, 2 existing warnings.** Complete CI also passes. CI run: [42283407355](https://github.com/ksullivan86/kidney-health/actions/runs/42283407355).
- Complete: full verification passed. Another session merged #167 while its final documentation checkpoint was being pushed. This audit did not merge it. The saved note links to the final checkpoint on the original branch. Inspect main before further code changes; continue with the unresolved follow-ups below.
- Logs: `/workspace/work/food-entry-audit/`; browser result: `browser-final/report.json`.
- Keep existing offline behavior: send the entry's base/version, omit untouched amounts, let current conflicts open review, and preserve the low-treatment purpose. Quick add's new guard preserves reopened drafts; this change does not freeze its fields or alter photo handling.

## How to resume elsewhere

The existing worktrees are easiest on this machine. In another checkout, fetch the branch or check out its PR; the implementation, tests and per-fix note are committed. For example:

```bash
git fetch origin audit/food-entry-editor-lifecycle
git worktree add --detach /workspace/work/food-entry-resume origin/audit/food-entry-editor-lifecycle
cd /workspace/work/food-entry-resume
git switch -c resume/food-entry-checks
```

Do not overwrite an existing checkout or rewrite published history. A continuation that updates the original PR should push a normal fast-forward commit to its existing head branch after checking for intervening work.

The detached `/workspace/work/assistant-audit-base` contains copied regression files used only to compare against unchanged main. Their deliverable copies are in the PR branches. Do not commit the baseline checkout.

## Reproducing checks in this workspace

Use the pinned Python environment at `/workspace/kidney-health/.venv/bin/python`; fresh machines should follow `CONTRIBUTING.md` and the locked dependencies. Node is required for the browser-rule twins and live-view regressions.

```bash
mkdir -p /workspace/work/pytest-scratch
TMPDIR=/workspace/work/pytest-scratch /workspace/kidney-health/.venv/bin/python -m pytest -o addopts='' -q
node tests/js/run_vectors.mjs
/workspace/kidney-health/.venv/bin/python scripts/gen_openapi.py --check
/workspace/kidney-health/.venv/bin/python scripts/build_handbook.py --check
```

Locally available tooling:

```bash
PYTHONPATH=/workspace/work/shopping-audit/lint /workspace/kidney-health/.venv/bin/python -m ruff check .
PYTHONPATH=/workspace/work/shopping-audit/tooling /workspace/kidney-health/.venv/bin/python -m mkdocs build --strict -f handbook/mkdocs.yml -d /workspace/work/audit-handbook-check
PYTHONPATH=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages PLAYWRIGHT_CHROMIUM=/usr/bin/chromium TMPDIR=/workspace/work/pytest-scratch /workspace/kidney-health/.venv/bin/python tools/e2e/food_entry_late_replies.py --out /workspace/work/food-entry-resume-browser
```

Tests and browser walks use fake external services or a fresh local server. This execution environment needs the network-capable sandbox for TestClient/local sockets; otherwise event loops can hang. Read `/etc/codex/network-policy.json` before shell network use.

Concurrent earlier local full suites exhausted the separate 4.9 GiB `/tmp` disk and produced infrastructure errors. The isolated CI runs listed above verify those changes. Completed failed-run scratch roots were removed; do not count their failed local logs as passing suites. Use the workspace scratch directory above and run local full suites one at a time. Leave active pytest lock directories alone.

GitHub tooling notes: authenticated bounded `git push` and `gh pr create --body-file` work. Old `gh pr edit` fails on deprecated Projects fields; use the GitHub connector to update PR metadata/readiness. Avoid large GitHub tree uploads (a previous attempt stalled). Download job logs through the GitHub connector and inspect only relevant summaries; do not print signed log redirect URLs.

## Combining changes

The user's other session handled integration of #153–167. Refresh main before further work; these original feature branches are historical checkpoints. For any future integration, combine independent Unreleased entries and run required checks on the combined changes.

- A `git merge-tree` simulation of #153 + #159 auto-merged `app/mcp/tools.py`; the independent changelog entries conflicted.
- A simulation of #162 + #163 auto-merged source changes; `CHANGELOG.md` and `docs/body.md` conflicted. Keep both behavior notes.
- These were tree comparisons only. No branch or PR was merged by this audit; merged states above were observed from integration by another session.

## Coverage and leads

Both user-reported follow-ups were fixed by another session in [#170](https://github.com/ksullivan86/kidney-health/pull/170), released as 0.23.0:

- **Ask retry while a save is in progress:** `app/ai/chat_save.py` checks the earlier save again under the write lock before offering confirmation. This is the follow-up to #159, not part of its original fix. The new cases in `tests/test_ask_trust_lifecycle.py` pass in the resumed audit.
- **Device session-check duplication:** the read-only `sessions.is_live` helper now supplies the time-limit rule to session validation and device sign-in. `tests/test_session_is_live.py` passes in the resumed audit.

The resumed audit found a new email reset race, fixed in [#175](https://github.com/ksullivan86/kidney-health/pull/175) (leave unmerged). A forgot request could read an address, then issue a live link after a concurrent request removed/changed it or revoked earlier links. Account deletion could cause a 500. The fix reads the target and creates the link in one write transaction; SMTP starts after commit. See [the resumable progress note](https://github.com/ksullivan86/kidney-health/blob/audit/password-reset-review/docs/dev/progress/password-reset-audit.md) for baseline failures, current verification and commands. Full verification was still running when this link was added; use that note and CI for final results.

- Every fix has a per-branch note with its reproduction and verification. Do not repeat completed baseline runs merely to recover context.
- Remaining lead: menu-plan submission also awaits a write before closing its dialog. It has not yet been reproduced or fixed; inspect its opening/busy behavior before declaring a bug.
- Users and AI provider IDs already use `AUTOINCREMENT`. Do not invent a user-ID reuse issue or add an allocator migration.
- Ordinary food-entry edits intentionally recompute nutrients from the current food in `app/log.py`; the preview's use of fresh food data alone is not proof of a snapshot bug.
- Activity/workout sections not imported from an account export are explicitly skipped by the existing contract, not a newly confirmed data-loss bug.
- Shared USDA quota increments already use a conditional atomic UPSERT. Egress readers already count decoded bytes, have gzip tests, and recipe reads check their total deadline. No additional response-handling bug was confirmed in that review.
- The Ask fix rechecks stored trust/admin switches. It does not claim to cancel an in-flight request solely because an ephemeral browser conversation grant is closed.

## Maintaining this handoff

Update this file when pending PRs finish or new work is published. Keep each PR's own progress note and body current. Push a verification checkpoint after the checks finish; unnecessary intermediate docs-only pushes cancel expensive in-progress CI runs. Keep the handoff outside `docs/dev/progress/`, whose files can be pruned at a release.

