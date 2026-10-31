# 21 · Suggestions from a caregiver or coach

| | |
|---|---|
| Status | Built 2026-10-31 as part of the full Care team ([note 29](29-full-care-team.md) §5), with the §8 defaults; a suggestion is a meal (foods and a note), not a swap. Proposed 2026-10-29. The owner asked: "is the caregiver able to suggest things?" and "this and that caregiver (coach) will be useful in the diet food log app". The choices in §8 are defaults the owner can change. |
| Scope | Someone a person shares their food log with (note 19) may **suggest** a meal, a food swap or a short note. A suggestion waits in the person's own app until the person adds it to their plan or says no. Nothing is ever written to the person's log, plan, targets or settings by someone else. |
| Out of scope | Writing on someone's behalf. Changing targets (they come from the care team, entered by the person). Messages that are not about food (the app is not a chat app). Suggestions to someone who has not shared with you. Medicines and insulin, always. |
| Builds on | Note 19 (shares, `shared_owner`, the activity log), note 16 (recipes and `fit-recipe`), the guidance engine's checks (`check_meal`, `food_warnings`), "Clinician accounts with notes" in ROADMAP. |

## 1. Why

A parent planning meals for a teenager, a partner who does the shopping, or a dietitian between visits wants to say "try this for
dinner on Thursday" in the app, not in a text message the person has to type in again. Today a share is read-only, so the only
way is to hand over the password, which also hands over everything else.

## 2. What a person sees

1. Ana's share with Sam gets one more tick: **Sam may suggest meals** (off by default). Ana can turn it off at any time; the
   suggestions already sent stay until she deals with them.
2. Sam opens **Shared with you → Ana → Plan** and builds a meal from Ana's own food list (the same picker as Plan), or picks one
   of Ana's saved meals, for a day and a meal. He may add a note of up to 280 characters ("the low-sodium broth is in the
   pantry"). **Send to Ana** sends it.
3. Before it is sent, the app checks the suggestion against **Ana's** targets for that day, the same way "Fit to my targets"
   does, and shows Sam the result ("fits", "over potassium by 150 mg"). It does not stop him: Ana decides.
4. Ana sees a badge on Plan: **1 suggestion from Sam**. The card shows the foods, the numbers for one serving against her day
   (with "≥" and "not listed" as everywhere), the note, and two buttons: **Add to my plan** (planned entries, which she can
   still change) and **No thanks**. Both are one tap. Sam sees which one she chose, never why.
5. A suggestion that is not dealt with in 14 days goes away by itself.

## 3. Rules that keep the person in charge

* **Only planned entries, only by the person's tap.** Accepting calls the person's own `POST /api/log/batch` with
  `status: "planned"`. The suggester has no write route into the person's data at all.
* **The person's food list only.** A suggestion names food ids the person owns or the built-in list; Sam cannot add foods to
  Ana's list. A food that is gone when Ana opens it makes the card say so and **Add** adds the rest.
* **No low treatments, ever.** A suggestion with a food marked as a low treatment is refused (`400`), so nobody else can plan,
  limit or comment on how a person treats a low. The note text is checked the same way as AI text (`messages.BANNED_PATTERN`
  and the hypo prefilter): a note about insulin, doses or treating a low is refused with a plain reason.
* **Rate limits.** At most 10 open suggestions per share and 20 sent per day per suggester.
* **Everything is in the activity log**: `suggestion.sent`, `suggestion.accepted`, `suggestion.declined`, `suggestion.expired`,
  on the person's side.

## 4. Storage (one new schema step)

```sql
CREATE TABLE IF NOT EXISTS suggestions (
  id INTEGER PRIMARY KEY,
  share_id INTEGER NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- the person it is for
  from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,    -- the suggester
  date TEXT NOT NULL, meal TEXT NOT NULL,
  items_json TEXT NOT NULL,              -- [{food_id, servings}], 1-30 items
  note TEXT,                             -- <= 280 characters
  created_at TEXT NOT NULL,
  answered_at TEXT, answer TEXT CHECK (answer IN ('accepted','declined','expired'))
);
```

`shares` gets `may_suggest INTEGER NOT NULL DEFAULT 0`. Suggestions are in the person's export (they are about them). Ending
the share ends its open suggestions.

## 5. Routes

| Route | Who | Does |
|---|---|---|
| `POST /api/shared/{id}/suggestions` | suggester, share with `food` and `may_suggest` | `{date, meal, items, note?}` → `201` with the fit check against the person's targets |
| `GET /api/shared/{id}/suggestions` | suggester | What they sent and the answer (accepted, declined, expired), never more |
| `GET /api/me/suggestions` | person | Open suggestions with the numbers worked out now (`unknown` as in the guidance answers) |
| `POST /api/me/suggestions/{id}/accept` | person | Adds planned entries through the person's own batch route; `200` with the entries |
| `POST /api/me/suggestions/{id}/decline` | person | `204` |

Every `/api/shared/{id}/…` route still goes through `shared_owner(area)`; the new write route also checks `may_suggest` and
returns the same `404 "Not shared with you."` for anything else. The demo answers the same routes with one built-in suggester.

## 6. Coach mode later

A dietitian or coach is the same thing with more people: one account that several people share with. What it adds later, when
the owner wants it: a list of the people who share with you on one screen, and suggestions saved as templates ("low-potassium
breakfast ideas") to send to several people. Notes from a clinician that stay on the record are the separate ROADMAP item.

## 7. Cost

About 2-3M tokens: the schema step, five routes with the share checks, the Plan cards and badge, the share's tick, the demo's
twin of the routes, tests (isolation matrix, the low-treatment refusal, expiry, export, the audit rows), a Chromium walk with two
people, and the docs and handbook page.

## 8. Decisions for the owner

1. **Off by default per share** (the person ticks "may suggest"). The other choice: on whenever food is shared.
2. **Planned entries only.** A suggestion never becomes an eaten entry without the person logging it.
3. **14 days** before an open suggestion expires.
4. **A note of 280 characters**, checked like AI text. The other choice: no free text at all, only foods.
5. **No targets from the suggester.** Targets stay the care team's, entered by the person.
