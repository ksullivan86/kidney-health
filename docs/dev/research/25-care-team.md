# 25 · Care team: invite by user name, and a Care helper who plans meals

| | |
|---|---|
| Status | Accepted and built, 2026-10-30 (the smaller first version). Schema step **27**. §10's "later" items are built by [note 29](29-full-care-team.md) (schema step 31). |
| Owner's words | "is it set so someone who already has an account can easily be invited as a caregiver or care helper (family member) can help meal plan. I didnt see where this is setup at all". The owner chose the smaller first version and the name **Care team** for every screen. |
| Builds on | Note 19 (read-only sharing: the `shares` table, the one check `shared_owner`, links, the switch), note 22 (the shopping list), note 23 (Plan several days, Clear planned days). |
| Scope | Settings → Care team as its own section; inviting someone who already has an account by user name (pending until they accept); two roles, **Viewer** and **Care helper**; a Care helper plans meals for the person and uses their shopping list; "Planning for" on the Plan tab. |
| Out of scope (later, §10) | Per-permission switches, a Caregiver role, logging eaten food for someone, sharing saved meals, notes from a clinician. |

## 1. What a person sees

* **Settings → Care team** is its own section, second after Account. Profile links to it. Every screen says "Care team"; the
  word "Sharing" is gone from the screens (the API keeps its route names).
* With the server switch off, a person sees one line: "Your admin can turn on the Care team for this server." An admin sees
  where: Server administration → Server settings → Care team, or `SHARING_ENABLED=true`, with a button that opens it.
* **Your Care team**: each person with their role, what they see, since when, when they last looked and when they last changed
  your plan. **Role** (Viewer / Care helper) changes in place. **Remove** ends it.
* **Invite someone**: their user name on this server, the role, what they may see, for how long. **Make a link instead** keeps the
  old link for anyone else.
* **Waiting for an answer**: invites you sent (by the user name you typed) and unused links, each with **Cancel**.
* **Invites for you**: who invited you, the role and what you would see, with **Accept** and **Decline**.
* **Care teams you are on**: each person, your role, **Open**, **Trends**, **Plan meals** (Care helper only) and **Leave**.

## 2. Roles

| | Viewer | Care helper |
|---|---|---|
| See what was shared (food, labs, weight and blood pressure, symptoms) | yes | yes |
| Plan meals on the person's days | no | yes |
| Use the person's shopping list (see, tick, copy, share) | no | yes |
| Eaten food, targets, profile, labs, weight, symptoms, preferences, AI settings, keys | read only, if shared | read only, if shared |

* Existing shares become **Viewer** (the column's default).
* A Care helper must see the food log. Choosing Care helper adds "food log" to what is shared, and the screen says so first.
* The person changes the role at any time, in one place (their Care team list). The next request the helper makes uses it.

## 3. Inviting by user name

* `POST /api/me/shares/invite {username, role, areas, days}` with a recent password, like making a link.
* **The same answer either way.** Whether or not an active account has that user name, the answer is `201` with the invite as the
  inviter's list shows it: the user name as typed, the role, the areas and the date it lapses. The inviter's list shows it under
  "Waiting for an answer" in both cases. An invite to a name nobody has simply lapses after 7 days. Inviting your own user name is
  `400` (it reveals nothing).
* Limits: 20 tries an hour per account and per address (`care_invite`, as share links), at most 5 waiting invites, and the 10-person
  cap of note 19. A second invite to the same name replaces the first.
* The invited person sees it in **Settings → Care team → Invites for you** and answers **Accept** or **Decline**. Accepting makes a
  share (a newer one from the same person replaces the old, as links do). Declining tells the inviter "declined"; it is not
  hidden, since they chose to answer. Nothing happens until they press a button.

## 4. Storage (schema step 27)

```sql
ALTER TABLE shares ADD COLUMN role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer', 'care_helper'));
ALTER TABLE shares ADD COLUMN helper_changes TEXT;   -- JSON {day, added, changed, removed}: the helper's changes on the latest day
CREATE TABLE care_invites (
  id INTEGER PRIMARY KEY,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  invitee_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,   -- NULL when no active account had the name
  username TEXT NOT NULL,                                            -- as typed (normalized), for the inviter's list
  areas TEXT NOT NULL, role TEXT NOT NULL, lasts_days INTEGER,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  answered_at TEXT, answer TEXT CHECK (answer IN ('accepted', 'declined', 'cancelled', 'replaced')),
  share_id INTEGER REFERENCES shares(id) ON DELETE SET NULL
);
ALTER TABLE log_entries ADD COLUMN added_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
```

`added_by_user_id` is set only when a Care helper adds an entry. The API shows it as `added_by` (the helper's name) on every
entry; the entry's `version` does not include it. It is not in the export (it points at another account).

## 5. Routes

All need a session; all answer `404` while the switch is off and in `AUTH_MODE=none`.

| Route | Who | Does |
|---|---|---|
| `GET /api/me/shares` | person | adds `role` to each share, `helper_changes`, and `invites` (waiting username invites) |
| `POST /api/me/shares` | person *(re-auth)* | takes `role` too (default `viewer`) |
| `POST /api/me/shares/invite` | person *(re-auth)* | §3 |
| `DELETE /api/me/shares/invites/{id}` | person | cancels a waiting invite |
| `PUT /api/me/shares/{id}/role` | person | `{role}` → the share; Care helper adds `food` |
| `GET /api/shared` | helper | adds `role` to each person, and `invites` (invites for you) |
| `POST /api/shared/invites/{id}/accept` / `decline` | invited | `201` the share / `204` |
| `GET /api/shared/{id}/foods?q=` | Care helper | food search as the person sees it (their own foods too), so a planned food is one they can use |
| `GET /api/shared/{id}/plan/shopping` | Care helper | the person's shopping list, as `GET /api/plan/shopping` |
| `POST /api/shared/{id}/log`, `/log/batch` | Care helper | add **planned** entries (an eaten one is `400`); each records the helper |
| `PUT`, `DELETE /api/shared/{id}/log/{entry}` | Care helper | change the amount, meal, day or note of a planned entry, or remove it |
| `POST /api/shared/{id}/log/clear-planned` | Care helper | as the person's own route: eaten food and planned low treatments stay |
| `POST /api/shared/{id}/guidance/plan-days` | Care helper | Plan several days for the person (computes only; saved meals off, §7) |

**One check for every write, on every request** (`care_helper_owner`): the share is the signed-in person's, accepted, not
stopped, not past its end date, its role is Care helper now, both accounts are active, the food log is shared and the switch is
on. Anything else is the same `404 "Not shared with you."`. Entries are looked up in the person's log only, so a helper cannot
reach their own log or anyone else's through a share. An eaten entry or a planned low treatment is `404` to a helper's change or
removal: a helper never changes or removes a low treatment, and Clear planned days leaves it, as it does for the person.
Adding a planned low treatment is allowed. Nothing in the app blocks or warns against treating a low.

## 6. Activity

The person's activity gets: `care.invited` (a user name invite, no name of the invited person in it), `care.invite_answered`
(accepted or declined), `care.invite_cancelled`, `care.role_changed`, `share.ended` (as before), and **once a day per helper**
`care.plan_changed` at the helper's first change of the day. The Care team list shows that day's count (added, changed,
removed), kept on the share (`helper_changes`). Audit rows are append-only, so the count lives on the share, not in the row.

## 7. Saved meals: not in this version

Saved meals were never shared (note 19 §2). A Care helper cannot list, apply or edit the person's saved meals, and **Plan several
days for the person runs with saved meals off**, so a plan never shows them. The planner still honours the person's targets,
dialysis days, "not for me" foods and what may repeat, because those shape what is safe to suggest; the helper does not see
those settings, only the plan. Letting a Care helper use saved meals is a later choice for the person (§10).

## 8. Planning for someone (the screens)

* The Plan tab shows **Planning for: Me / <person>** when the signed-in person is a Care helper for anyone. Choosing a person
  hides their own Plan and shows the person's week with a banner: "You are planning for Ana. Changes go to Ana's plan, not
  yours." and **Back to my own plan**. The choice is kept in memory only.
* Their week: projected totals per day. A day opens its entries: eaten food read-only, planned food with an amount to change
  and **Remove** (a low treatment says only the person changes it), and "Added by <name>". **Add food** searches the person's
  foods. **Plan several days** previews a plan and **Add to Ana's plan**. **Clear planned days** asks first.
* Their shopping list: ticks kept on this device under a key with the share's id, so they never mix with your own list.
  Copy and Share as for your own.
* Writes go to `/api/shared/{id}/…` only. The offline outbox and the saved copies for offline use match the person's own
  routes (`/api/log…`) exactly, so a write for someone else is never queued, never replayed to your own log, and their days
  are never saved as yours. Offline, a change for someone else says it needs a connection.
* On Today, an entry a helper added says "Added by Sam".

## 9. Risks

* **A helper changes the plan in a way the person does not want.** The person sees "Added by", the daily activity row and the
  counts, can change the role back to Viewer or remove the helper at once.
* **Finding out who has an account.** The invite answers the same either way and is rate-limited; the inviter sees names only
  after acceptance.
* **Too much shown through the planner.** Saved meals are off; the plan's foods are ones the person can already see in their
  log or the shared food list.
* **A stale screen.** Every write is checked against the share as it is now, so a role changed to Viewer or a removed helper
  gets `404` on the next tap, and the screen goes back to the helper's own plan.

## 10. Later

Per-permission switches; a **Caregiver** role (log eaten food for someone); letting a Care helper use the person's saved meals
(a switch the person turns on); the person's own approval of changes; a clinician role with notes.
