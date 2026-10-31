# 29 · The full Care team: switches, a Caregiver who logs eaten food, saved meals and suggestions

| | |
|---|---|
| Status | Accepted and built, 2026-10-31. Schema step **31**. |
| Owner's words | "0.18 full Care team: Caregiver role that logs eaten food, per-person permission switches, helpers using saved meals, fold in note 21 coach suggestions." Roles are **presets over switches**. Writes are checked on the server, entries say "Added by <name>", a helper never changes targets, labs, profile or medicines, and never touches a low treatment. The name is **Care team** everywhere. |
| Builds on | Note 19 (shares, `shared_owner`), note 25 (the Care team, Viewer and Care helper, `care_helper`, "Planning for"), note 21 (suggestions; its §8 defaults are taken as they are). |
| Scope | Switches per person; a third preset, **Caregiver**, who logs eaten food; saved meals for helpers when the person allows it; suggestions from anyone on the Care team the person allows. |
| Out of scope | The person approving each change before it lands; notes from a clinician; suggestions sent to several people at once (note 21 §6); templates of suggestions. |

## 1. What a person sees

* **Settings → Care team → Your Care team**: each person has a **Role** (Viewer, Care helper, Caregiver, or Custom when the
  switches match no role) and **What they may do**, a short list of switches:
  * See: my food log, lab results, weight and blood pressure, symptoms, activity and recovery.
  * Do: plan my meals and use my shopping list; log food I ate; use my saved meals; suggest meals.
  Each switch saves at once. Turning on any "Do" switch while the food log is not shared first says "Planning, logging, saved
  meals and suggestions need your food log. Share your food log with Jo?" and shares it when the person says yes.
* **Planning for** on the Plan tab (note 25 §8) now shows what the switches allow: a Caregiver also sees **Add as eaten** and,
  on a planned food, **Mark eaten**; with saved meals on, **Saved meals** lists the person's meals with **Add to plan** and
  **Add as eaten**; with suggestions on, **Suggest a meal** builds a suggestion and **Sent suggestions** shows the answers.
  A person who only suggests (a coach) gets the same "Planning for" screen with only the suggestion parts.
* **Plan tab, the person's side**: "Suggestions for you" with one card per suggestion: who sent it, the day and meal, the foods,
  what it adds to the day against their targets, the note, **Add to my plan** and **No thanks**.
* **Today**: an entry a helper added says "Added by Jo", eaten or planned.

## 2. Roles are presets

| Switch | Viewer | Care helper | Caregiver |
|---|---|---|---|
| See what was shared | yes | yes | yes |
| `may_plan`: plan meals, use the shopping list, Plan several days, Clear planned days | no | yes | yes |
| `may_log`: log eaten food, mark a planned food eaten, fix eaten food they added | no | no | yes |
| `may_use_saved_meals` | no | no | no |
| `may_suggest` | no | no | no |

* The role shown is worked out from the four "Do" switches: none is Viewer, plan only is Care helper, plan and log is Caregiver,
  anything else is **Custom**. Areas never change the role.
* Choosing a role sets the four switches to that row. What the person shares stays, and food is added when a "Do" switch needs it.
* Any "Do" switch needs the food log: turning one on adds `food` (the screen asks first).
* Invites and links take a role (`viewer`, `care_helper`, `caregiver`). The switches are changed after the person joins.

## 3. Rules every write keeps

* **One check, every request.** Each `/api/shared/{id}/…` write loads the share as it is now: the signed-in person's, accepted,
  not stopped or past its end, both accounts active, the switch on, the food log shared and the switch named by that write on.
  Anything else is the one `404 "Not shared with you."`.
* **Low treatments.** A Caregiver may add a low treatment as eaten: recording what happened is never blocked. No helper changes,
  removes, moves or marks eaten any entry that treats a low, whoever logged it. The server answers `403` with one sentence:
  "Only Ana can change or remove a low treatment." Clear planned days leaves them, as before. Nothing warns against treating a low.
* **Eaten food.** A Caregiver changes or removes only the eaten food they added themselves (to fix a mistake). The person's own
  eaten food, and food another helper logged, is `403` "You can change only the eaten food you added." A planned food may become
  eaten (`status: "eaten"` on `PUT`); nothing goes back from eaten to planned.
* **Never touched by a helper:** targets, labs, profile, medicines, preferences, AI settings, keys, saved meals themselves.
  There are no routes for them. No insulin or medicine dosing anywhere.
* **Added by.** Every entry a helper adds, planned or eaten, records them (`added_by_user_id`), shown as "Added by <name>".
  Marking a planned food eaten does not change who added it.

## 4. Saved meals

Off by default. With `may_use_saved_meals` on, `GET /api/shared/{id}/meals` lists the person's saved meals as `GET /api/meals`
answers them, and `POST /api/shared/{id}/meals/{meal_id}/apply` adds one to a day, as planned (needs `may_plan`) or eaten (needs
`may_log`), each entry with "Added by". Plan several days for the person uses saved meals when the helper ticks it and the
switch is on; otherwise they stay out as in note 25 §7. A helper never edits, renames or deletes a saved meal.

## 5. Suggestions (note 21, folded in)

* `may_suggest` is off by default. A Viewer may have it (the coach case).
* A suggestion is a day, a meal, 1 to 30 foods the person can use with servings, and a note of up to 280 characters. A food
  that treats a low is refused (`400`): how a low is treated stays the person's choice. The note is checked like AI text: the
  words of `messages.BANNED_PATTERN` and the low-detecting prefilter (`hypo.mentions_low`) are refused with a plain reason.
* Limits: 10 open per share (`409`) and 20 sent per 24 hours per suggester, counted from the table (`429`).
* It waits 14 days, then expires (`suggestion.expired` in the person's activity). Turning `may_suggest` off keeps what was sent
  until the person answers. Ending the share closes its open suggestions.
* **Add to my plan** adds planned entries through the person's own insert, so they are the person's (no "Added by"). A food the
  person can no longer use is left out and the answer says how many; if none is left the answer is `409`.
* The suggester sees each suggestion and its answer (`open`, `accepted`, `declined`, `expired`, `ended`), never a reason.
* **The fit.** When sending, and on the person's card, the app adds the suggestion to that day's projected food and compares it
  with the person's targets the way Today does (`unknown` counted, "≥" and "not listed" on screen). It never stops the suggester.

## 6. Storage (schema step 31)

```sql
ALTER TABLE shares ADD COLUMN may_plan INTEGER NOT NULL DEFAULT 0 CHECK (may_plan IN (0, 1));   -- and may_log,
ALTER TABLE care_invites ADD COLUMN may_plan ...                                              -- may_use_saved_meals, may_suggest
UPDATE shares SET may_plan = 1 WHERE role = 'care_helper';          -- every existing share keeps its meaning exactly
UPDATE care_invites SET may_plan = 1 WHERE role = 'care_helper';
CREATE TABLE care_suggestions (
  id INTEGER PRIMARY KEY,
  share_id INTEGER NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- the person it is for
  from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,    -- the suggester
  date TEXT NOT NULL, meal TEXT NOT NULL CHECK (meal IN ('breakfast','lunch','dinner','snack')),
  items_json TEXT NOT NULL,              -- [{food_id, servings}], 1 to 30
  note TEXT CHECK (note IS NULL OR length(note) <= 280),
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  answered_at TEXT, answer TEXT CHECK (answer IN ('accepted','declined','expired','ended')),
  CHECK ((answered_at IS NULL) = (answer IS NULL)), CHECK (from_user_id != owner_user_id)
);
```

The `role` column of step 27 stays and keeps its `CHECK`. It is written as `care_helper` exactly when `may_plan` is on, so an
older build reading the same database still lets that person plan and nothing more.

## 7. Routes

All need a session and answer `404` while the switch is off and in `AUTH_MODE=none`, except `GET /api/me/suggestions`, which
answers `200 {enabled: false, suggestions: []}` so the Plan tab never sees a failed request.

| Route | Who | Does |
|---|---|---|
| `GET /api/me/shares` | person | each share adds the four switches; `role` is worked out (§2) |
| `PUT /api/me/shares/{id}/role` | person | `{role}` sets the four switches to the preset |
| `PUT /api/me/shares/{id}/switches` | person | `{areas?, may_plan?, may_log?, may_use_saved_meals?, may_suggest?}`; a "Do" switch adds `food` |
| `GET /api/shared` | helper | each person adds the four switches |
| `GET /api/shared/{id}/foods` | `may_plan`, `may_log` or `may_suggest` | as before |
| `POST /api/shared/{id}/log`, `/log/batch` | `may_plan` (planned) / `may_log` (eaten) | each entry records the helper |
| `PUT`, `DELETE /api/shared/{id}/log/{entry}` | as §3 | |
| `GET /api/shared/{id}/meals` | `may_use_saved_meals` | the person's saved meals |
| `POST /api/shared/{id}/meals/{meal_id}/apply` | saved meals and `may_plan` / `may_log` | as `POST /api/meals/{id}/apply`, with "Added by" |
| `POST /api/shared/{id}/guidance/plan-days` | `may_plan` | `use_saved_meals` honoured only with the switch on |
| `POST /api/shared/{id}/suggestions` | `may_suggest` | `{date, meal, items, note?}` → `201` the suggestion with its fit |
| `GET /api/shared/{id}/suggestions` | any active share | what you sent to this person and the answers |
| `GET /api/me/suggestions` | person | open suggestions, each with its fit worked out now |
| `POST /api/me/suggestions/{id}/accept` | person | planned entries, `200 {entries, skipped}` |
| `POST /api/me/suggestions/{id}/decline` | person | `204` |

## 8. Activity

The person's activity gets `care.switches_changed` (which switches, and whether food was added), `care.role_changed` (as
before, now with the switches), `care.food_logged` once a day per helper at their first eaten entry of the day (UTC), and
`suggestion.sent`, `suggestion.accepted`, `suggestion.declined`, `suggestion.expired`. `helper_changes` on the share also counts
`logged` (eaten entries added or marked eaten that day).

## 9. Export

`care_suggestions` in the person's export: each suggestion's date, meal, foods (names and servings), note, who sent it (their
name at export time), when, and the answer. The import reads nothing from it (it is a record of other people's messages).

## 10. Risks

* **A Caregiver logs something wrong.** "Added by" on every entry, the daily activity row and the count; the Caregiver can fix
  what they added; the person can change anything and turn logging off at once.
* **A stale screen.** Every write checks the share as it is now: a switch turned off is a `404` on the next tap and the screen
  goes back to the helper's own plan.
* **A note that gives medical advice.** The note uses the AI text checks and is short; targets never come from a suggester.

## Decisions (the owner can change any of them)

1. Switches live on the share (four columns); the role is worked out from the "Do" switches, and saved meals or suggestions on
   top of a role show it as **Custom**.
2. Choosing a role sets all four "Do" switches; what is shared stays (food is added when needed).
3. The old `role` column is written `care_helper` exactly when planning is on, so going back to 0.17 keeps planning and drops
   the rest.
4. A Caregiver may mark a planned food eaten and fix or remove eaten food they added; never the person's own eaten food or
   another helper's.
5. Low treatments: a Caregiver may add one as eaten; no helper changes, removes, moves or marks one eaten (`403`, one sentence).
6. Invites and links carry a role only; switches are changed after joining.
7. Saved meals are off by default and only listed and applied, never changed. Plan several days uses them only when the helper
   asks and the switch is on.
8. Suggestions follow note 21 §8: off by default, planned only and only by the person's tap, 14 days, a 280-character note
   checked like AI text, no targets from the suggester, 10 open per share and 20 a day per suggester.
9. An accepted suggestion's entries are the person's own (no "Added by"); the card names who suggested it.
10. Turning suggestions off keeps the open ones; ending the share closes them.
11. `care.food_logged` is written once a day per helper, like `care.plan_changed`.
12. The export holds the person's suggestions with the suggester's name; the import skips them.
13. The test accounts stay as they were: Jo is Sam's Care helper. The walkthrough has Sam turn on the other switches.
