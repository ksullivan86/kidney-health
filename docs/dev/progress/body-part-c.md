Status: in progress (first half of note 10 Part C: the Apple Health export.xml reader; no UI, no server)

# Part C, first half: js/engine/apple_health.js

Worktree branch `worktree-agent-af14ab5cd82f7905f`, based on `0cd8344` (note 10 merged by fast-forward from `f3d2049`).
Local commits only: never push, never open a PR, never touch another branch. This file is deleted in the last commit.

## Done (verified how)
* Step 0: `git merge --ff-only 0cd8344` ok, note present.
* `app/static/js/engine/apple_health.js` (KH.appleHealth): streaming scanner, rows, summary, helpers, SHA-256 (subtle or plain JS).
  Verified by the vectors below and `node --check`.
* `tests/js/gen_apple_health_vectors.mjs` -> `tests/data/apple_health_vectors.json`: 43 hand-written cases at chunk sizes 1, 7, 64, whole.
  Verified: the generator stops on any disagreement (tried a deliberately wrong expectation: it fails); five source_keys re-checked with sha256sum.
* New async group in `tests/js/run_vectors.mjs` ("apple health", 1085 checks): `node tests/js/run_vectors.mjs` passes, all groups.

## Next
1. `tests/js/apple_health_large.mjs` (about 200 MB synthetic, streamed, heap bound; hostile shapes) and `tests/test_apple_health.py`
   (runs run_vectors and the large script, hashlib cross-check of the keys, the preview builder picks the file up once index.html lists it).
2. Note 10 section 4.8: small additions for the details decided here.
3. Full checks: `python -m pytest -q` (no network), `ruff check .`, `node --check`.
4. Delete this file in the last commit; report.

## Decisions (reasons)
* Not in index.html / sw.js yet (test_frontend_shell keeps them in step; the sheet adds both).
* Header comment must not contain the words the shell test greps for (the XML parser class name, innerHTML, eval).
* Pure-JS SHA-256 fallback when crypto.subtle is missing (plain-HTTP LAN installs have no subtle crypto; the repo handles that elsewhere).
* Hand-written linear attribute scanner instead of one regex (a regex with free name starts is quadratic on a hostile 8 KiB tag).
* A "<" inside a start tag ends it (unreadable); the scanner goes on at that "<".
* Pairing: identical startDate and sourceName; two different systolic (or diastolic) values in one group are ambiguous -> all halves skipped as halfPair.
* Extra skip reason `unreadable` (bad date/value, missing sourceName, tag cut by "<" or by the end of the file).
* The key text has no unit (the note's format); value is the attribute as written.
* The batch rows carry no `source`; the server sets apple_health. `forUpload` drops sourceName.

## Reproduce
* `node tests/js/gen_apple_health_vectors.mjs` (rewrites the vectors; stops if the module disagrees)
* `node tests/js/run_vectors.mjs`
* `python -m pytest -q tests/test_apple_health.py`
