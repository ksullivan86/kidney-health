Status: in progress

# Menu-plan sheet audit

Branch: `audit/menu-plan-editor-lifecycle`, main `01f5298`.
Worktree: `/workspace/work/menu-plan-audit-src`.

- Resumed the remaining menu-plan lead in the durable handoff (PR #168).
- Read repository instructions, architecture's menu-day section, design note 08 and existing menu tests/harness.
- Confirmed `openLink` resets `busy` during a batch write, so reopening can send a second batch. Late success clears
  and closes the new draft and navigates away; a late error fills its error box. Submitted date/choices also stayed editable.
- Nine initial Node cases execute the real menu reader/view: **unchanged main fails 6 and passes 3**.
  The additional cases cover an old day reply while the next link loads and closing during that load.
- Fix: preserve busy across openings, capture each write's opening, freeze only the submitted draft, invalidate old reads
  on open/close, and let only the submitting opening close/clear/navigate. Announce a stale failure separately. Client IDs,
  planned status, built-in-only parsing and all low-treatment logic stay as before.
- Initial focused pytest: 67 pass; expanded menu/tool/handbook checks: **697 pass**, two existing citation warnings.
  **58 Chromium checks pass** at 375 light / 1280 dark in `/workspace/work/menu-plan-browser-verified/report.json`.
  Chromium's queued close event exposed a flaw in the first fix: it could cancel a deliberate reopening. The handler now
  distinguishes a load begun after closing and ignores old close events after reopening. Two added Node cases cover it;
  **all 11 final Node cases pass**, final wrapper/tool checks pass (50), and the final Chromium rerun passes all 58 checks
  in `/workspace/work/menu-plan-browser-last/report.json`.
- The browser harness initially removed its route handler before fulfilling the held
  route, causing `Route is already handled`; corrected the order. This was a harness failure.
- Ruff, whitespace, JS parity, OpenAPI, generated handbook and strict MkDocs checks pass. The existing full menu-plan
  browser walk is running; CI's full suite will be checked on the published PR. Logs are `/workspace/work/menu-plan-*.log`.

## Reproduce

```sh
node tests/js/menu_plan_lifecycle.test.mjs
TMPDIR=/workspace/work/pytest-scratch /workspace/kidney-health/.venv/bin/python -m pytest tests/test_menu_plan.py tests/test_menu_plan_lifecycle.py tests/test_e2e_tools.py -o addopts='' -q
python tools/e2e/menu_plan_late_replies.py --out /tmp/kh-menu-late
```

Unchanged comparison tree: `/workspace/work/menu-plan-baseline-src` (detached `01f5298` with only the new Node file copied).
Keep the PR unmerged for the user's other session.
