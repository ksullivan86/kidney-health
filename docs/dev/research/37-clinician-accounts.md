# 37 · Clinician accounts with notes

| | |
|---|---|
| Status | Proposed 2026-11-12. Phase 1 built 2026-11-12 (unreleased) with the defaults of §12, schema step 36. Phase 2 (§11) is not built. |
| Owner's words | ROADMAP "Clinician accounts with notes (large)": "a `clinician` role that a person invites (and can revoke) to see their log, labs, symptoms and visit summaries read-only, and to add notes the person can read. Every view by a clinician goes to the person's activity log. … wording about what the app is not: a self-hosted personal tool, not part of a clinic's medical record." |
| Builds on | [Note 19](19-sharing.md) (shares, `shared_owner`, links, the switch, `share.viewed`), [note 25](25-care-team.md) (the Care team, invites by user name, Viewer), [note 29](29-full-care-team.md) (switches on the share, roles as presets, suggestions and their note checks), [note 21](21-suggestions-from-a-caregiver.md) §6 ("coach mode later"), [note 07](07-accounts-settings-secrets.md) (accounts, audit, the isolation matrix), [note 34](34-password-reset-by-email.md) (email), the Visit prep page ([`ARCHITECTURE.md`](../../../ARCHITECTURE.md#visit-prep)), [`accounts.md`](../../accounts.md#care-team). |
| Scope | One more switch on a Care team share, **May write notes**, and a role preset over it, **Clinician**. Notes a Care team member writes for the person, which the person reads in their own app. Finer view logging for those shares. |
| Out of scope | Replies, attachments and notifications (phase 2, §11). Any link to a clinic's record system. Orders, prescriptions, dosing, targets or lab entries from anyone but the person. Checking that someone really is a clinician. |

## 1. What it is for

Ana has kidney disease and type 1 diabetes. Her dietitian, Dee, has an account on the same server. Ana adds Dee to her Care
team as a **Clinician**. Dee can then:

* read the parts Ana chose (food log, labs, weight and blood pressure, symptoms, activity), as a Viewer does today, through
  **Open** (the Visit prep page) and **Trends**;
* write a short note for Ana, such as "Your potassium was lower on the days you swapped the potato for rice. Keep that up.",
  tied to a day or an area if she wants;
* see which of her notes Ana has read.

Ana reads the notes in her own app, can delete any of them, and sees every time Dee looked in her activity.

## 2. What it is not

These sentences, or shorter ones that say the same, appear where a person picks the role, on the clinician's invite question
and under every note (§7):

* It is **not a medical record** and not part of a clinic's record system. A clinician keeps their own record as their clinic
  requires. Ana can delete a note at any time.
* It gives **no orders**. A note never changes targets, labs, medicines, profile, preferences or the log. Nothing a clinician
  does in the app changes Ana's data.
* There is **no dosing**: no insulin or medicine amounts in the app, from anyone.
* Nothing in the app warns against or blocks **treating a low**. A note never touches a low treatment.
* The app **does not check who someone is**. "Clinician" is what Ana chose to call this person, not a checked credential.
* It is not for urgent questions. Notes are read when Ana opens the app.

## 3. What already exists and is reused

| Piece | From | Used as it is |
|---|---|---|
| The share row, areas, end dates, Stop sharing and Leave | note 19, step 24 and 25 | yes |
| Invite by user name, links, the same answer either way, limits | note 25 | yes; invites and links take the new role |
| Viewer reads (`/api/shared/{id}/…`), Visit prep and Trends in shared mode | note 19 | yes, unchanged |
| Switches on the share, roles as presets, `role_of`, Custom | note 29 | one more switch and one more preset |
| One check per request (`_check_share`), one 404 "Not shared with you." | notes 19, 29 | one more check, `care_noter` |
| The server switch `sharing.enabled` | note 19 | yes, plus a second switch for notes (§12 decision 2) |
| Admin's End Care team, account deletion cascades | note 19 | yes; notes stay with the person (§8) |
| Activity rows that concern the person target the person, no `ip_prefix` for the other side | note 19, 0.22.2 | yes |
| Note text checks from suggestions | note 29 §5 | a narrower version (§7) |
| Email sending (`app/mail.py`) | note 34 | later, for an optional "you have a note" letter (§11) |

What is new: the switch `may_note`, the preset `clinician`, the table `care_notes`, eight routes, finer view rows for these
shares, the person's Notes list and its Today card, and "Write a note" in the shared views.

## 4. A new account kind, or a switch on the share?

| | A. `clinician` as an account role (`users.role`) | B. A switch on the share, `may_note`, and a preset **Clinician** |
|---|---|---|
| Who decides | The admin marks an account as a clinician | The person, per share, as for every other switch |
| Fits note 29 | No: roles there are presets over switches on the share | Yes: one more column, one more row in `PRESETS` |
| Admin risk | Touches `users.role` (`admin`/`user` today, with triggers for test accounts) | Never touches `users.role`; nothing to do with admin rights |
| A dietitian who is also someone's partner | Needs two accounts | One account, a different switch per person |
| "Verified clinician" | Suggests a check the app cannot make | Says plainly it is the person's choice |
| Older build reading the database | Unknown role value breaks `CHECK` | `role` column stays `viewer`; an old build sees a Viewer and has no note routes |
| Cost | More: admin screens, CLI, OIDC group mapping | Less |

**Recommended: B.** A clinician is any account the person gives the notes switch. The preset **Clinician** is Viewer plus
`may_note`. Notes plus any other "Do" switch shows as **Custom**, as today. `may_note` does not add `food`: a note may be about
labs only. Choosing Clinician keeps the areas the person shared.

## 5. What a person sees

**The person (Ana)**

* **Settings → Care team → Invite someone**: the role list gains **Clinician: can look and write notes for you**. Under it:
  "Notes are messages for you. They are not a medical record and never change your targets, labs or medicines. The app does
  not check who someone is."
* **What they may see and do** gains one switch: **Write notes for me**.
* **Today**: when there are unread notes, a small card at the top: "1 new note from Dee", with **Read**. It never hides or
  moves the low-treatment button or anything else.
* **Notes** (`#notes`, no new tab): newest first. Each note shows who wrote it, when, what it is about ("About Tuesday 10
  November, food log" with a link to that day, or "About your lab results" with a link to Labs), the text, "edited" if it was,
  and **Delete**. Showing a note on screen marks it read. Reached from the Today card, from Settings → Care team ("Notes from
  your Care team") and from Visit prep.
* **Visit prep**: one screen-only line, "2 notes from your Care team in this period", linking to Notes. Notes are not printed
  (§12 decision 8).
* **Activity**: each note written, edited or withdrawn, and each look by a clinician (§6).

**The clinician (Dee)**

* The invite question: "Ana invites you to her Care team as a Clinician. You can look at her food log and lab results and
  write notes she can read. This is Ana's personal app, not part of a clinic's record. Keep your own record as your clinic
  requires." **Accept** / **Decline**, as today.
* **Care teams you are on** shows Ana with **Open**, **Trends** and **Notes**.
* In Open (Visit prep, the day card) and Trends, a **Write a note** button. It fills in the day or area being viewed, which Dee
  can change or clear. A box of up to 1,000 characters, a counter, **Send to Ana**.
* **Notes** for Ana: what Dee wrote, newest first, each with "Read on 12 Nov" or "Not read yet". **Edit** and **Withdraw** show
  only while unread.

## 6. Every look is logged

Today a share writes one `share.viewed` row a day (UTC). For a share with `may_note` on, the person sees more:

* `share.viewed` is written at the first read of **each area in each hour**, with `{area}` in the details. An hour of reading
  four areas makes four rows, not hundreds.
* `last_viewed_at` is set on every such row, as now.
* The person's Care team list shows "last looked today 14:05 at lab results".
* Shares without `may_note` keep one row a day. Making it finer for every share is §12 decision 5.

## 7. Notes: rules

* **Who can see a note.** The person it is for and its author. No one else: not other Care team members, not admins (there is
  no admin route), not the AI, not the assistant.
* **The author's access ends with the share.** Once the share is stopped, ends or the author leaves, the author can no longer
  read, edit or withdraw their notes. The person keeps them.
* **Editing.** The author may edit or withdraw a note **only while it is unread**. After Ana has read it, a correction is a new
  note. So a note Ana read is always the note she read, and no edit history is needed. Edits use `If-Match` (the note's
  `version`), and marking read uses it too: if Dee edits while Ana's screen shows the old text, Ana's read is `412` and her
  list reloads, so `read_at` always belongs to the text she saw.
* **The person may delete** any note. It is gone for both sides. The author's list simply no longer has it.
* **Text checks.** A note goes through `hypo.mentions_low` and a short dosing list (insulin, bolus, basal, units, dose,
  dosing, correction, ratio, pump). Refused with: "Notes cannot be about lows, insulin or doses. Talk to Ana directly about
  those." This is narrower than the suggestion check (`messages.BANNED_PATTERN`), which also refuses "lab results",
  "supplements" and "safe", words a dietitian needs. §12 decision 6.
* **Plain text only.** Shown through `textContent`; no links made clickable, no HTML, no markdown.
* **Limits.** 1,000 characters (at least 1 after trimming). 10 notes in 24 hours per author per person (`429`). 500 notes
  kept per person (`409`: "Ana has 500 notes. Ask her to delete old ones."). A note's `date` is a real date no more than one
  year back and not in the future. `area` is one of the share's areas now, or none.
* **No AI.** `app/ai/`, `app/mcp/`, `app/guidance/` and Ask never read `care_notes`. No summaries of notes, no replies drafted
  by AI, no AI check of note text. A test reads those packages' sources and fails if one names the table (as for symptoms).
* **No admin through this.** `may_note` grants nothing outside the share. It never changes `users.role`, and single sign-on
  group mapping never sets it. An admin can be on someone's Care team like anyone else, with no extra reach into notes.

## 8. Storage (schema step: next free)

```sql
ALTER TABLE shares ADD COLUMN may_note INTEGER NOT NULL DEFAULT 0 CHECK (may_note IN (0, 1));
ALTER TABLE care_invites ADD COLUMN may_note INTEGER NOT NULL DEFAULT 0 CHECK (may_note IN (0, 1));
CREATE TABLE care_notes (
  id INTEGER PRIMARY KEY,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,  -- the person it is for
  author_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,         -- NULL once the author's account is deleted
  share_id INTEGER REFERENCES shares(id) ON DELETE SET NULL,              -- the share it was written through
  author_name TEXT NOT NULL,             -- display name, else user name, when written; kept for the person
  area TEXT CHECK (area IS NULL OR area IN ('food','labs','body','symptoms','activity')),
  about_date TEXT,                       -- YYYY-MM-DD or NULL
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 1000),
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  edited_at TEXT,
  read_at TEXT,
  CHECK (author_user_id IS NULL OR author_user_id != owner_user_id),
  CHECK (edited_at IS NULL OR read_at IS NULL OR edited_at <= read_at)
);
CREATE INDEX care_notes_owner ON care_notes(owner_user_id, created_at);
CREATE INDEX care_notes_share ON care_notes(share_id, created_at);
```

* The step only adds; released steps are not edited. Every existing share gets `may_note = 0`, so nothing changes until a
  person turns it on.
* The `role` column of step 27 keeps its `CHECK` and is written `viewer` for a Clinician. An older build sees a Viewer.
* A note row is deleted, not hidden, when the person deletes it or the author withdraws it. The activity row stays, with no text.
* **Deleting the person's account** deletes their notes (cascade). **Deleting the author's account** keeps the notes for the
  person with `author_name` and "account removed" (§12 decision 4).
* `area` and `about_date` are what the note is about. They are not checked against data (a note about a day with no food is
  fine).

## 9. Routes

All need a session (`current_user`), are scoped by `user.id`, answer `404` while `sharing.enabled` or the notes switch is off
and in `AUTH_MODE=none`, and send the CSRF header on writes. Anything not yours is the one `404`. The exception is
`GET /api/me/notes`, which answers `200 {enabled: false, unread: 0, notes: []}` so Today never shows a failed request.

| Route | Who | Does |
|---|---|---|
| `GET /api/me/shares`, `PUT /api/me/shares/{id}/switches`, `PUT …/role` | person | gain `may_note` and the preset `clinician` |
| `POST /api/me/shares`, `/invite` | person *(re-auth)* | `role` may be `clinician` |
| `GET /api/shared` | member | each person gains `may_note` |
| `GET /api/me/notes?before=&limit=` | person | `{enabled, unread, notes: [{id, from: {name, removed}, area, date, body, version, created_at, edited_at, read_at}]}`, newest first, at most 50 a page; only rows `WHERE owner_user_id = user.id` |
| `POST /api/me/notes/{id}/read` | person | `If-Match: version` → `204`; already read is `204`; edited since is `412` |
| `DELETE /api/me/notes/{id}` | person | `204` |
| `POST /api/shared/{id}/notes` | `may_note` | `{body, area?, date?}` → `201` the note; `400` text check or area not shared; `409` at 500; `429` at 10 a day |
| `GET /api/shared/{id}/notes` | `may_note` | the notes this author wrote for this person through any share, with `read_at` |
| `PUT /api/shared/{id}/notes/{note_id}` | `may_note`, author | `If-Match`; `{body?, area?, date?}` → the note; read is `409` "Ana has read this note. Write a new one instead." |
| `DELETE /api/shared/{id}/notes/{note_id}` | `may_note`, author | unread only → `204`; read is `409` |

* **One check.** `care_noter` runs `_check_share` with `may_note` and no area, on every request. A note is looked up
  `WHERE id = ? AND owner_user_id = <share owner> AND author_user_id = <signed-in person>`; anything else is `404`.
* Writes run under `BEGIN IMMEDIATE`, so a read and an edit at the same moment cannot both win, and the daily count cannot be
  passed by sending many at once.
* No route lets anyone but the author write a note's text, and no route shows a note to a third account.

## 10. Activity, export, admin, tests, demo

* **Audit actions** (all in `USER_VISIBLE_ACTIONS`, never the note text): `care_note.written`, `care_note.edited` and
  `care_note.withdrawn` target the person (written by the author, no `ip_prefix`); `care_note.deleted` is the person's own;
  `share.viewed` gains `{area}` for notes shares (§6); `care.switches_changed` and `care.role_changed` name `may_note`.
  Reading a note writes no row: `read_at` is enough.
* **Export.** `care_notes` in the person's `export.json`: `date, area, from, body, created_at, edited_at, read_at`.
  `data_import.SKIPPED_SECTIONS` and the demo's list skip it: notes are other people's words. The author's export holds
  nothing of them (they are about someone else), as for suggestions.
* **Admin.** End Care team ends the shares; notes stay with the person, and the author loses access with the share. No admin
  route reads notes. `GET /api/admin/users` is unchanged.
* **Test accounts.** The Care team stays between test accounts. The test walkthrough has Sam turn on **Write notes for me** for
  Jo, and Jo writes one. No third test account (§12 decision 9).
* **Isolation matrix** (`tests/test_isolation.py`, `tests/test_sharing_security.py`): A writes a note for B through a share.
  C, on B's Care team without the switch, gets `404` on every note route; C's own share id with A's note id is `404`; A cannot
  reach B's note through another person's share; B cannot edit A's text; after the share ends A gets `404` on all of them and
  B still reads the note; the person's `GET /api/me/notes` never lists another person's notes; the export of A has none of
  them. Plus the method list in `tests/test_sharing.py` gains the four note routes, each checked to go through `care_noter`.
* **Other tests.** The migration (existing shares unchanged), the switches and presets, the text check, the limits, `If-Match`
  on read and edit, the hourly view rows, account deletion of either side, the no-AI source test, the screens in Node and a
  Chromium walk with two people.
* **Demo twin.** `js/mock/care.js` gains a Clinician, Dee, with one unread note on the sample person's food from two days ago,
  and answers every route above. The note limits, the text check's refusals and `role_of` with `may_note` go into
  `tests/data/care_vectors.json` and are replayed by `node tests/js/run_vectors.mjs`.
* **Docs.** `ARCHITECTURE.md` (a section after "The full Care team"), `docs/accounts.md` "Care team", `docs/privacy.md`, and
  the handbook's [Reports for your care team](../../../handbook/docs/app/reports-for-your-team.md) and privacy pages.

## 11. Plan and size

Estimated as in ROADMAP's cost table (one agent in one session, ±50 %; a multi-agent build with review rounds costs 2–3×).
The read-only sharing it builds on is already built, so only the notes part is left.

| Phase | What | Tokens | Agent time |
|---|---|---|---|
| 1 | The switch and preset, `care_notes`, the routes, hourly view rows, Notes list, Today card, Visit prep line, "Write a note" in the shared views, export, demo twin, tests, docs | 3–5M | 1–1.5 days |
| 2a | Replies: the person answers a note (same table with `reply_to`, same limits and checks) | 1–2M | 4–6 h |
| 2b | Notifications by email: off by default, the person opts in, at most one letter a day, generic text ("You have a new note in <instance>"), no name or health data, only with `EMAIL_ENABLED` and a confirmed address | 0.5–1M | 2–3 h |
| 2c | Notifications by Web Push: once the opt-in Web Push reminders are built (ROADMAP "Installable app"), one more opt-in kind, the same generic body, never about lows | 0.3–0.6M | 1–2 h |
| 2d | Attachments (a PDF or photo with a note): storage, size limits, file checks, export. Not recommended until asked | 2–3M | 1 day |

## 12. Risks and decisions for the owner

Each decision has a recommended default in the least-trust style. The owner can change any of them.

1. **Account role or share switch.** Default: a switch on the share (`may_note`) with a **Clinician** preset (§4). No account
   kind, no admin step.
2. **A second server switch.** Default: notes have their own switch, `care_notes.enabled` (`CARE_NOTES_ENABLED`), off, so a
   server with the Care team on does not get notes until the admin chooses.
3. **Who sees a note.** Default: the person and the author only. Other Care team members never see it, even with all areas.
4. **When the author's account is deleted.** Default: the person keeps the note, shown as "from Dee (account removed)". The
   other choice is to delete the author's notes too.
5. **Finer view logging.** Default: one row per area per hour, only for shares with notes on. The other choice is the same for
   every share.
6. **Text check.** Default: refuse lows and dosing words only (§7), so a dietitian can write about labs and food. The other
   choices: the full suggestion check (stricter, blocks "lab results"), or none (a human writes to a person).
7. **Editing.** Default: edit or withdraw only while unread; after that, a new note. No edit history kept.
8. **Notes on paper.** Default: Visit prep shows a screen-only line and does not print notes, so a printed page does not carry
   someone else's words. The other choice: a tick to include them.
9. **Test accounts.** Default: no new test account; Jo gets the switch in the walkthrough.
10. **Notifications.** Default: none in phase 1. Email (2b) and Web Push (2c) are opt-in per person when built.
11. **Name on screens.** Default: "Clinician", with "The app does not check who someone is" beside it. The other choice is a
    neutral name such as "Adviser".
12. **Limits.** Default: 1,000 characters, 10 a day per author per person, 500 kept per person.

**Risks.**

* **Someone pretends to be a clinician.** The app cannot check. The person chooses who gets the switch, the role text says so,
  and the person can delete any note and remove the person at once.
* **A note gives harmful advice.** Lows and dosing are refused; every note says it is not an order and changes nothing; no
  route lets a note change data. The person's real care team stays the source of targets.
* **A clinician's employer does not allow it.** The invite question says this is the person's app, not the clinic's. Whether
  a clinician may use it is for them and their clinic.
* **The person expects a reply or an urgent answer.** The Notes screen says notes are read when people open the app, and to
  contact their care team directly for anything urgent.
* **Too much shown.** Nothing new is shared: a Clinician reads exactly what a Viewer with the same areas reads.
* **Notes treated as a record.** The person can delete them, the author loses them with the share, and the wording in §2 says
  so. A clinic that needs a record keeps its own.
