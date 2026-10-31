# 26 · Test accounts: `tester`, `tester-helper` and Send feedback

| | |
|---|---|
| Status | Accepted and built, 2026-10-31. Schema step **28**. Replaces the "tester role" of the 0.14 plan. |
| Owner's words | "what about a test account I can enable on the server and have a tester login with the testing account?" and "its going to be hard to test the care giver without a caregiver test account that can be added to the test accounts care team". |
| Builds on | Note 07 (accounts, settings, secrets as files), note 19 and note 25 (the Care team), note 04 (optional AI), the demo's sample person (`app/static/js/mock/seed.js`). |
| Scope | One server switch that makes two test accounts with one password from a file; rules that keep them apart from real accounts; Reset; Send feedback and Server administration → Feedback; a walk-through for testers. |
| Out of scope | Several sets of test accounts, a tester role on real accounts, screenshots or logs attached to feedback, test accounts in the demo. |

## 1. What the owner gets

* `TEST_ACCOUNT_ENABLED` (off). Also **Server administration → Server settings → Test accounts**, like every other setting.
* When on, the server makes two accounts if they are missing:
  * **`tester`**, display name Sam: the patient. Starts with the demo's sample person: CKD stage 4, type 1 diabetes, 70 kg,
    170 cm; about 30 days of renal-diet meals with a few higher days, two treated lows and three empty days; today partly eaten
    with dinner planned; three days ahead planned; three saved meals (one is the hypo kit); 11 lab results; two weeks of
    weights and blood pressure; a sample weight-gain alarm and blood pressure goal; targets from the app's own suggestion. Dates
    count from the day the account is made.
  * **`tester-helper`**, display name Jo: a family member, already a **Care helper** on Sam's Care team, seeing all four areas.
* One password for both, read from `TEST_ACCOUNT_PASSWORD_FILE` (a Podman or compose secret). Never an environment variable:
  `TEST_ACCOUNT_PASSWORD` stops the start, as `OIDC_CLIENT_SECRET` does.
* **Reset test accounts** in Server administration, and `python -m app.admin reset-test-accounts`.
* **Send feedback** for test accounts, and **Server administration → Feedback** for admins.
* The walk-through [docs/test-the-full-app.md](../../test-the-full-app.md).

## 2. Making them (`app/test_accounts.py`)

`sync()` runs at start-up, right after the first-run setup, and whenever an admin changes the switch.

* **On**, with `AUTH_MODE=local` and the first admin set up: make each missing account, seed `tester`, add the Care team link,
  enable a disabled or locked test account, and set the password again when the file changed.
* **Off**: disable both (not delete), sign them out, revoke their tokens. Turned on again, they work again with their data.
* It never stops the start. A problem is logged as a warning and shown in Server administration → Test accounts:
  * `TEST_ACCOUNT_PASSWORD_FILE` not set, missing, unreadable or empty;
  * the password fails the password policy (checked for both names, with `PASSWORD_MIN_LENGTH`);
  * a real account already uses `tester` or `tester-helper` (it is never taken over);
  * `AUTH_MODE` is not `local` (then existing test accounts are disabled).

The seed is a port of `seedSampleData` in `app/static/js/mock/seed.js` (the non-dialysis person): the same foods (by USDA FDC id,
with the same name fallback), the same meal lists and special days, and the same random numbers (mulberry32 with the same seed),
so the tester sees the plan the demo shows. A test checks that the food table and the key texts still match the demo's file, and
that every food of the seed is in `data/foods.json`. Entries go in through the server's own `insert_entry` (so a low treatment is
marked as one), labs through `units.convert`, the profile through `ProfileUpdate`, the targets through the suggestion code.

## 3. Rules (each where the feature decides)

| Rule | Where |
|---|---|
| Never an admin | People refuses **Make admin** (409); single sign-on groups are ignored for them; two triggers of step 28 refuse any row with `role = 'admin'` and `is_test_account = 1`. |
| Care team only between test accounts | `app/sharing.py`: an invite by name between a test and a real account answers exactly as for a name nobody has (note 25 §3); a link between them is the generic 404 (`info` and `accept`); the share check and both lists leave such a row out. Both directions. |
| Never in a real person's lists | Follows from the row above: the Care team is the only place one person sees another. |
| The server's AI off unless `TEST_ACCOUNT_AI` | `app/ai/config.py` `resolve` and `app/ai/routing.py` `resolve_feature` answer "disabled"; `/api/ai/*` and `/api/vision/*` are 404; Settings → AI features and `/api/meta` say off. |
| One shared password | No password change, no two-step sign-in (it would lock the others out), no deleting the account, no admin reset link or "must change password" for a test account (409 with a plain reason). |

Test accounts can use everything else, including a passkey or an Outside AI app token; Reset removes those.

## 4. Storage (schema step 28)

```sql
ALTER TABLE users ADD COLUMN is_test_account INTEGER NOT NULL DEFAULT 0 CHECK (is_test_account IN (0, 1));
CREATE TRIGGER users_test_account_never_admin_insert BEFORE INSERT ON users
  WHEN NEW.role = 'admin' AND NEW.is_test_account = 1 BEGIN SELECT RAISE(ABORT, 'a test account cannot be an admin'); END;
CREATE TRIGGER users_test_account_never_admin_update BEFORE UPDATE ON users
  WHEN NEW.role = 'admin' AND NEW.is_test_account = 1 BEGIN SELECT RAISE(ABORT, 'a test account cannot be an admin'); END;
CREATE TABLE feedback (
  id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- the tester; NULL after a reset
  username TEXT NOT NULL,                                    -- kept, so the admin still knows who sent it
  screen TEXT NOT NULL,                                      -- 1 to 60 characters
  trying TEXT NOT NULL, happened TEXT NOT NULL,              -- at most 2,000 characters each
  useful TEXT,                                               -- yes, somewhat, no or NULL
  unsafe INTEGER NOT NULL DEFAULT 0,
  app_version TEXT NOT NULL, created_at TEXT NOT NULL,
  done_at TEXT, done_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
```

Every existing account is a real account. Nothing else changes.

## 5. Reset

Refused (409) while the switch is off or the accounts could not be made again (the password file is checked first, so nothing
is deleted when it would fail). Otherwise it deletes both accounts, which deletes everything they made (log, foods, saved meals,
profile, settings, labs, weights, symptoms, sessions, tokens, passkeys, Care team rows) as deleting any account does, and makes
them again as in §2. New account ids; both are signed out. One activity row, `test_accounts.reset`, with the two names. The
feedback stays: its `user_id` becomes NULL and `username` keeps the name, so the fresh accounts see none of it and the admin
still has all of it.

## 6. Send feedback (`app/feedback.py`, `js/views/feedback.js`)

* A test account sees a **Send feedback** button in the header of every screen (an icon with that name). Real accounts, admins
  included, never see it, and `/api/feedback` is 404 for them.
* The sheet: **What were you trying to do?** (started with the screen's name, such as "Today: "), **What happened?**, **Was this
  screen useful?** (Useful, A little, Not useful), and **This looked wrong or unsafe**, with a line saying to tick it if anything
  blocked or warned against treating a low, or if the AI gave an insulin or medicine dose. Below: **What you sent**, with "done"
  once the admin marked it.
* Only what was typed is sent, with the screen's name. The server adds the app version and the time. Nothing is copied in: no
  screenshot, no numbers from the log, no health data. The body is checked (`extra="forbid"`): any other field is refused.
* Limits: 2,000 characters a box, 20 an hour, 50 a day for each account, 5,000 kept on the server (then 409 until an admin deletes
  what is done).
* **Server administration → Feedback**: open, done or all; only "wrong or unsafe"; **Mark done** / **Open again**; **Export CSV**
  (cells a spreadsheet would run as a formula are escaped); **Delete done**. **Server administration → Test accounts**: each
  account's state and last sign-in, the problem if any, whether the AI is on for them, and **Reset test accounts** (it asks first).

## 7. The demo

The GitHub Pages preview and `?mock=1` need none of this: the demo has no accounts of its own and already starts with Sam. The
script is left out of the preview build (`data-preview="omit"`), and with `?mock=1` the Test accounts settings, the Test accounts
part and the Feedback part are hidden. The demo's settings table still lists the two keys, so the settings parity vectors match.

## 8. Safety

* Nothing here gives or suggests a dose, and nothing blocks or warns against treating a low. The feedback sheet asks testers to
  report it if anything ever does.
* The sample data is the demo's: a made-up person. The weight-gain alarm and blood pressure goal are marked in the demo as sample
  numbers "from the care team"; the app never suggests either (note 10 §2).

## 9. Tests

`tests/test_test_accounts.py` (switch, password file, seeding, never admin, Care team both ways, AI, shared password, Reset from
the page and the command line, feedback routes, limits, CSV, start-up, the seed against the demo's file and the real food list),
`tests/test_test_accounts_ui.py` (the page), `tests/test_isolation_v03.py` (the `feedback` table), the settings parity vectors,
and `tools/e2e/test_accounts.py` (Chromium: a tester sends feedback, the helper is on Sam's Care team, the admin reads, marks
done and resets, and the demo has none of it).
