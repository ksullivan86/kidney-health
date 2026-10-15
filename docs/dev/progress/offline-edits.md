Status: complete

# Offline edits and deletes (ROADMAP "Offline edits and deletes of entries already on the server")

Role: `offline-edits`. Worktree branch `worktree-agent-a02e89855299dd980`, base `2d081a1`. Report due 14:45 UTC
(started 11:23 UTC, finished 12:25 UTC). No push, no PR. Schema: no migration (the version is computed, not stored).

## Plan / state

- [x] 1 Server: `version` in the entry JSON, `If-Match` on `PUT`/`DELETE /api/log/{id}`, 412 with the current entry
      (`app/log.py`, `app/models.py`), export drops `version`, import tolerates it; tests (`tests/test_log_if_match.py`,
      isolation matrix entry). Verified: `python -m pytest -q tests/test_log_if_match.py tests/test_isolation_v03.py`
- [x] 2 Demo twin: `js/mock/log.js` (`entryVersion`, `If-Match`, 412), `js/mock/core.js` + `mock/auth.js` pass request headers,
      vectors (`tests/data/entry_version_vectors.json`, generator, `run_vectors.mjs`, `tests/test_entry_version_vectors.py`).
      Verified: `node tests/js/run_vectors.mjs` (entry version vectors: 71 checks)
- [x] 3 Front end: `core.js` (`ifMatch`/`base` options, `intercept` + `onConflict` hooks, `api.updateEntry(id, body, base)`,
      `api.deleteEntry(id, base)`), `offline.js` (queue edit/delete, one item per entry, rewrite a queued create, remove a queued
      create on delete, replay with `If-Match`, 412 -> silent resend only when the server's entry equals the one the change was
      made on, else a conflict card; 404 -> "This entry no longer exists", dropped), `today.js` / `add.js` (versions; waiting
      entries are editable; "needs review" opens Settings -> This device), `css/device.css` (card). Verified:
      `node tests/js/outbox_changes.mjs` (77 checks, mutation-checked), `tests/test_offline_edits_ui.py`, the existing
      front-end static tests
- [x] 4 Tests: static (`tests/test_offline_edits_ui.py`), Node queue logic (`tests/js/outbox_changes.mjs`, 77 checks),
      Chromium (`python tools/e2e/device.py --only changes`: 31 checks; `--only demo`: 17 checks, 5 of them new; `--only
      outbox` still 19/19), parity harness (`python tools/e2e/parity.py`: 6575 comparisons, 0 mismatches; section 5 has the
      new If-Match steps)
- [x] 5 Docs: ARCHITECTURE ("Offline edits and deletes" at the end, plus the log routes, outbox, export, ownership table),
      CHANGELOG (Unreleased, three audiences), ROADMAP (marked done, profile stays online-only), `docs/install-on-your-phone.md`,
      handbook `app/install.md` and `app/logging.md`, note 02 R5 (update paragraph), `tools/e2e/README.md`
- [x] 6 Verification (final tree): `tests/test_log_if_match.py`, `tests/test_entry_version_vectors.py`,
      `tests/test_offline_edits_ui.py`, `tests/test_device_ui.py`, `tests/test_isolation.py`, `tests/test_isolation_v03.py`;
      `node tests/js/run_vectors.mjs` (entry version vectors: 71 checks); `node tests/js/outbox_changes.mjs` (77 checks); the full
      suite in 4 parallel shards over all 112 test files, each `timeout 900 python -m pytest -q -x -p no:cacheprovider <files>`:
      exit 0 for all four; Chromium: `device.py --only changes,outbox,demo,firstvisit,shots` all pass (changes 32, outbox 19,
      demo 17), `parity.py` 6575/6575

## Decisions and why

- The version is FNV-1a (64 bit, 16 hex digits) over a canonical text of the entry JSON's date, meal, food_name, servings,
  grams, note, status, purpose and the 12 nutrient values. Why a hash of content and not `updated_at`: an edit undone on
  another device gives the same content, so no false conflict; and the demo can compute the same without Web Crypto
  (async, secure contexts only). Why FNV and not SHA: it must be identical in Python and in a browser script with no
  library, synchronously, and a change token needs no cryptographic strength.
- `id` and `food_id` are left out of the hash: `id` is the address, and `food_id` never changes for an entry and differs
  between servers (`tests/test_data_import.py` compares an import with its source after dropping both).
- The numbers hashed are the entry JSON's rounded values (servings 3 decimals, grams 1, nutrients as shown), so both sides
  start from the same already-rounded numbers; whole numbers are written without a point.
- 412 body is `{"detail": "This entry was changed on another device", "current": <Entry>}` (an `ApiProblem`, like
  `reauth_required`). `If-Match` accepts a quoted tag, a bare tag, a list, `*`; a weak tag or an empty value never matches.
- With `If-Match` the write is `... AND updated_at = <the row checked>`, so a request that slips in between the check and
  the write also gets a 412 (race test in `tests/test_log_if_match.py`). Without the header the statements are unchanged.
- The export (`export.json`) leaves `version` out (derived, so older servers can still import a new export); the importer
  accepts and ignores a `version` key.

- One outbox item per entry: a second edit joins the first (bodies merged, original version kept, moved to the end of the queue
  so it still goes after a "mark eaten" queued in between), a delete replaces an edit. Why: two items for one entry would make
  the second one a false conflict (its version is the one before the first was applied).
- A 412 whose `current` equals the entry the change was made on (the compared fields are exactly the version's fields) is sent
  again once with the new version: that is our own queued "mark eaten" getting there first, not another device. Queueing a mark
  also marks the waiting changes' expected entries as eaten. Anything else is a conflict and nothing is sent.
- Edit/delete need the entry the person saw (`opts.base`, from `api.updateEntry(id, body, entry)`); without it nothing is queued
  and the old "needs a connection" message stays (no version to check). Profile, targets, labs, foods, settings are not in any
  queue pattern.
- Ask's "Undo" calls `deleteEntry(id)` with no entry, so it is never queued (its test pins the exact text of that API line).
- `intercept` (core.js hook): a change to an entry that already has a change waiting goes into the queue even when online
  (order), and `pending:<client_id>` entries are handled locally whether online or not.
- Online 412: `onConflict` stores the person's change as a conflict item (card in Settings -> This device) and the sheet closes
  with a message; the same card as offline.

- A copy saved before this version (no `version` on its entries) still queues; at replay the app reads the day first and compares
  (equal -> send the server's version, different -> conflict, gone -> dropped, read failed -> not saved). The sync's own
  `GET /api/log?date=` is answered raw (`afterResponse` skips the waiting-items overlay for `noQueue`), otherwise the person's own
  queued edit would look like a foreign change.
- The queued edit body is cut to the fields that differ from the entry the person saw (`changedFields`): the entry sheet always
  sends meal, day, status and note, and sending them all would let "Use mine" erase a note another device wrote. The card's
  "Your change" side is the server's entry with those changes on top, i.e. what "Use mine" leaves.
- Online edits send `If-Match` too (the sheet and the Eaten button pass the entry), so a stale tab or a second device gets the
  same conflict card instead of last-write-wins. Existing clients without the header are unchanged.
- The e2e/Node checks were mutation-checked: dropping the silent resend or `If-Match` from the replay makes them fail.

## Commands that reproduce the checks

- `python -m pytest -q -x -p no:cacheprovider tests/test_log_if_match.py tests/test_entry_version_vectors.py tests/test_isolation_v03.py`
- `node tests/js/run_vectors.mjs` and `node tests/js/outbox_changes.mjs`
- `python -m pytest -q -p no:cacheprovider tests/test_offline_edits_ui.py tests/test_device_ui.py tests/test_frontend_shell.py`
- `python tools/e2e/device.py --only changes,outbox,demo` (Chromium; ports 8066/8067 by default)
- `python tools/e2e/parity.py` (the demo against a real server, about 2 minutes)
- `python tests/data/gen_entry_version_vectors.py` rewrites the vectors (then re-run the Node runner).

## What is left

Nothing in the task. For a maintainer: the manual phone matrix in `docs/ROADMAP.md` ("Manual checks on real devices") now also
means one edit and one delete made offline and one conflict made from a second device; remove the "Done, unreleased" ROADMAP
line and this note when the release is tagged.
