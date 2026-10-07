# fixer-frontend-docs progress

Status: in progress (started 2026-10-07)

Role: v0.3.0 review fixer for app/static, tools/e2e, tests/js, scripts/build_preview.py, handbook/, docs/,
README/CHANGELOG/CONTRIBUTING/AGENTS and the GitHub templates. Ports 8620-8639. Scratch:
`/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/fixer-frontend-docs/`.
Another fixer works on the backend half at the same time: commit only my paths, re-read shared files
before editing them.

## Findings

CONFIRMED (fix with root cause and a test):

| id | finding | status |
|---|---|---|
| C1 | unknown K/P counted as 0 (today.js:147 and every total) | pending |
| C2 | handbook light-scheme links/header fail WCAG AA | done |
| C3 | Settings → This device renders twice on first visit | done |
| C4 | DG47 dead citation on 13 handbook pages | pending |
| C5 | guidance never shows which targets it used / when saved | pending |

LOW (apply or justify): see the table below as each is done.

## Done

* **C3** (settings.js `renderDevice`, offline.js `renderDevice`): each render builds into a detached fragment;
  only the newest (ticket) replaces `#set-device-body` after its last await; the outbox list's `draw()` builds
  its parts and `replaceChildren`s (ticket too), and `renderDevice(container)` now returns a stop function
  that Settings calls when a newer render replaces the list. Verified: `tools/e2e/device.py --only firstvisit`
  (new section: three fresh profiles at `/#settings` with the service worker allowed) fails 6/9 on HEAD's code
  (copy via `git archive`) with exactly the review's symptoms and passes 9/9 after; `outbox` and `demo`
  sections still pass (36/36). Static guard: `tests/test_device_ui.py::test_settings_device_section_is_drawn_once_when_renders_overlap`.

* **C2** (`handbook/docs/stylesheets/extra.css`): teal primary → teal 800 `#00695c` (white on it and it on
  white 6.61:1; the header in both schemes and light links), light accent `#004d40` (hover/focus 9.8:1),
  inactive tabs 85 % opacity (5.2:1) with the current tab underlined, the phone drawer's section title at full
  foreground colour (was 4.4:1 light / 4.1:1 dark). The probe found more than the review: tabs 2.59:1 and the
  drawer title. `tools/e2e/learn.py` now measures every visible text run (colour alpha, opacity, stacked
  backgrounds; waits for transitions to end) on 5 pages in both schemes: 60/60 pass on a build with
  `HANDBOOK_APP_LINK=/` (the image's flags). Before the CSS the same probe found 6 failing groups per page.

## Coordination

* The backend fixer (`fixer-backend-ops`) owns the server half of C1 (their C8: unknown K/P counted as 0 in
  `app/log.py`; their C6: insights). I build the UI on the shape they add to DaySummary / range / summary and
  update the mock twin (`js/mock/log.js`) to match. If their shape is not there when I reach C1, I add the
  smallest server change myself and say so here.

## Next steps

Work order: C3, C2, C4, C5, C1 (largest), then the LOW list, then final checks.

## Commands

* `python -m pytest -q` ; `node tests/js/run_vectors.mjs`
* handbook: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook/venv/bin/mkdocs build --strict -f handbook/mkdocs.yml -d <scratch>/site`
