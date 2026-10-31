# 28 · Whoop, the Activity and recovery card, and the active-day calorie extra

| | |
|---|---|
| Status | Accepted and built for 0.17, 2026-10-31. Schema step **30**. |
| Owner's words | "Whoop: sleep, recovery, strain, HRV, workouts, calories burned, an Activity and recovery card in Trends, a Care team share area for it, and the active-day calorie extra." The extra is "what Whoop says was burned above the usual quiet-day level, updated through the day. Counts all of it by default; a per-person share and an optional daily ceiling. Only calories rise. No insulin advice; never block or warn against treating a low. HRV is shown, never acted on." (docs/dev/progress/0.14-plan.md, "Owner decisions (2026-10-31, devices)") |
| Builds on | Note 27 (connected devices: connections, the import ledger, the sync loop, the consent sheet), note 05 (targets: E-1 to E-4), note 25 (Care team areas). |
| Out of scope | Whoop webhooks, Whoop's body measurements and profile (name, email), heart-rate zones, changing any target other than calories, anything about insulin. |

## 1. What the WHOOP developer API offers (checked 2026-10-31)

Sources, all read on 2026-10-31:
the OAuth guide, [developer.whoop.com/docs/developing/oauth](https://developer.whoop.com/docs/developing/oauth);
the API reference, [developer.whoop.com/api](https://developer.whoop.com/api);
the refresh tutorial, [developer.whoop.com/docs/tutorials/refresh-token-javascript](https://developer.whoop.com/docs/tutorials/refresh-token-javascript);
rate limits, [developer.whoop.com/docs/developing/rate-limiting](https://developer.whoop.com/docs/developing/rate-limiting);
webhooks, [developer.whoop.com/docs/developing/webhooks](https://developer.whoop.com/docs/developing/webhooks);
the cycle page, [developer.whoop.com/docs/developing/user-data/cycle](https://developer.whoop.com/docs/developing/user-data/cycle);
app approval, [developer.whoop.com/docs/developing/app-approval](https://developer.whoop.com/docs/developing/app-approval);
the v1 to v2 migration page, [developer.whoop.com/docs/developing/v1-v2-migration](https://developer.whoop.com/docs/developing/v1-v2-migration);
and the Open Wearables provider notes, [openwearables.io/docs/providers/whoop-api-integration](https://openwearables.io/docs/providers/whoop-api-integration).

| Question | Answer |
|---|---|
| Sign-in | OAuth 2 authorization code. The browser goes to `https://api.prod.whoop.com/oauth/oauth2/auth?response_type=code&client_id=…&redirect_uri=…&scope=…&state=…`. The redirect address must be registered in the developer dashboard exactly. The state must be at least eight characters (ours is 43). |
| Token endpoint | `POST https://api.prod.whoop.com/oauth/oauth2/token`, form-encoded: `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`, `client_secret`. Refresh: `grant_type=refresh_token`, `refresh_token`, `client_id`, `client_secret`, `scope=offline`. The answer is `{access_token, refresh_token, expires_in, scope, token_type}`; the example shows `expires_in` 3600 (one hour). There is no user id in the answer. |
| Refresh tokens | Only with the `offline` scope. **Rotation**: each refresh returns a new refresh token, and the old one stops working at once ("the first request invalidates the refresh token"). So the new pair is saved before anything else, as for Withings. |
| Scopes | `read:recovery` (score, HRV, resting heart rate), `read:cycles` (day strain, average heart rate, energy), `read:workout`, `read:sleep`, `read:profile` (name and email), `read:body_measurement` (height, weight, max heart rate), `offline`. We ask for `offline read:cycles read:recovery read:sleep read:workout` and **not** profile or body measurements: we do not need a name or an email, and weights come from Withings or the person. |
| Base address | `https://api.prod.whoop.com/developer/v2/…` (v2 since 2025-07-01; WHOOP asks every app to move off v1, and v1 webhooks stopped on 2025-11-01). |
| Collections | `GET /v2/cycle`, `/v2/recovery`, `/v2/activity/sleep`, `/v2/activity/workout`. Query: `limit` (at most 25), `start` (inclusive), `end` (exclusive, default now), `nextToken`. Answer: `{records, next_token}`. |
| Cycle | A physiological day, from falling asleep to the next sleep (not midnight to midnight). `id` (whole number), `user_id`, `start`, `end` (**missing for the cycle the person is in now**), `timezone_offset` (`+hh:mm`, `-hh:mm` or `Z`), `score_state` (`SCORED`, `PENDING_SCORE`, `UNSCORABLE`), `score.strain`, `score.kilojoule`, `score.average_heart_rate`, `score.max_heart_rate`. |
| Recovery | Keyed by `cycle_id`: `score.recovery_score` (%), `score.resting_heart_rate`, `score.hrv_rmssd_milli`, `score.spo2_percentage`, `score.skin_temp_celsius`, `score.user_calibrating`. |
| Sleep | `id` (UUID), `cycle_id`, `nap`, `score.stage_summary` (light, slow wave, REM, awake, in bed, in milliseconds), `score.sleep_performance_percentage`. |
| Workout | `id` (UUID), `start`, `end`, `timezone_offset`, `sport_name`, `score.strain`, `score.kilojoule`, `score.average_heart_rate`. |
| Units | Energy is in **kilojoules**; 1 kcal = 4.184 kJ, so kcal = kJ ÷ 4.184. The cycle's figure is the whole day's energy, resting energy included (the example is 8288 kJ, about 1981 kcal). |
| Revoke | `DELETE /v2/user/access` with the person's access token; 204 when done. |
| Errors | 400 bad request, 401 token refused, 429 too many requests. |
| Rate limits | **100 requests a minute and 10,000 a day per app**, not per person (headers `X-RateLimit-*`). One sync of ours is 4 to 8 requests. |
| Webhooks | `recovery`, `sleep` and `workout` updated or deleted; **none for cycles** (energy and strain). They need an HTTPS address WHOOP can reach and may be missed. We **poll**, like Withings: a home server may not be reachable, and cycles have no webhook anyway. |
| Registering an app | In the WHOOP developer dashboard ([developer-dashboard.whoop.com](https://developer-dashboard.whoop.com)), signed in with a WHOOP account. No fee is mentioned. Every new app starts on the **Sandbox tier: up to 10 WHOOP members**, with no approval. More members need an approval request (a privacy policy, a test with at least one member, WHOOP's brand rules); community threads from 2026 report waits of weeks or months. A home server with a family needs no approval. |
| Test data | WHOOP has no test accounts: trying it needs a real member with a strap. |

Uncertain, and what we do about it:

* Whether the token endpoint also accepts HTTP Basic. The tutorials send `client_id` and `client_secret` in the form; we do the same.
* Whether a refused refresh is 400 or 401. Both mean "connect again" after one try.
* `score_state` of the current cycle: the reference shows only `SCORED`. We take a cycle's numbers when its state is `SCORED`
  and skip `PENDING_SCORE` and `UNSCORABLE` (the next sync looks again).

## 2. How good are tracker calories? (checked 2026-10-31)

* **O'Driscoll R, et al. How well do activity monitors estimate energy expenditure? A systematic review and meta-analysis of the
  validity of current technologies. Br J Sports Med 2020;54(6):332–340.** [doi:10.1136/bjsports-2018-099643](https://bjsm.bmj.com/content/54/6/332).
  60 studies, 41 devices: on average the devices **under**-estimated energy expenditure (Hedges' g −0.23), accuracy depended on
  the activity, and the spread between studies was large (I² > 75 % for many devices). The NASEM 2023 energy report lists the
  monitor-versus-calorimetry differences in this review as running from about −41 % to +116 %
  ([NASEM 2023, chapter 21 table](https://www.nationalacademies.org/read/26818/chapter/21)).
* **Germini F, et al. Accuracy and acceptability of wrist-wearable activity-tracking devices: systematic review of the literature.
  J Med Internet Res 2022;24(1):e30791.** [doi:10.2196/30791](https://www.jmir.org/2022/1/e30791). 65 studies: for energy
  expenditure the mean absolute percentage error was **over 30 % for every brand**; "none of the tested devices proved to be
  accurate in measuring energy expenditure".
* We found **no peer-reviewed study of WHOOP's calories** against calorimetry or doubly labelled water. WHOOP's energy is worked
  out from heart rate.

So the docs and the screen say plainly: **tracker calories can be off, by a lot, in either direction.**

## 3. The energy range the base target keeps to

KDOQI 2020 guideline 3.1.1: 25–35 kcal/kg/day for adults with CKD 1–5D or a transplant, chosen by age, sex, activity, body
composition and weight goals ([Ikizler et al., AJKD 2020;76(3 Suppl 1):S1–S107](https://doi.org/10.1053/j.ajkd.2020.05.006)).
The app's base target (rules E-1 to E-4, `app/target_rules.py`) is the NASEM 2023 estimated energy requirement at the person's
chosen activity level, kept inside that range. **That rule does not change.** The extra is added on top, only on days Whoop counts
more than a usual quiet day; the base stays the planning number on every other day.

## 4. Decisions

### 4.1 The usual quiet-day level (the baseline the extra is measured from)

The owner offered two choices: the energy the base target assumes (the EER at the chosen activity level), or a low percentile of
the person's own Whoop days. **We use the person's own Whoop days**:

> **Usual quiet-day level** = the lower quartile (25th percentile, nearest rank) of Whoop's calories on the person's finished
> Whoop days in the 28 days before the day, when there are at least 14 such days. With fewer, there is no extra yet.

Why:

1. **The same tracker on both sides.** Tracker calories are often off by a third or more (§2), and the error is mostly the same
   person-to-person and device-to-device bias every day. Comparing Whoop with Whoop cancels a constant error. Comparing Whoop with
   the EER does not: a strap that reads 15 % high would add about 300 kcal on *every* day, and one that reads low (the pooled
   finding in O'Driscoll 2020) would never add anything.
2. **It does not depend on profile fields.** The EER needs age, sex, height and weight, and the stored calorie target may be one the
   person typed. The quartile needs nothing but Whoop's own numbers.
3. **"Quiet" means quiet.** The lower quartile is a typical rest day of this person, not their average day, so a normal active
   day already counts.
4. **Enough days to mean something.** 14 finished days of the last 28 (two weeks of wear) before the first extra; the first sync
   reaches back 90 days, so a person who has worn the strap for a while gets the extra at once.

The trade-off: if the person's base target already counts regular exercise (activity level "active"), a usual active day gets a
small extra on top. The share and the ceiling exist for that, and the docs say so.

### 4.2 The extra

For a day *D* with the setting on, a base calorie target, and a Whoop figure for *D*:

```
burned  = Whoop calories so far on D (kJ ÷ 4.184, whole kcal)
quiet   = lower quartile of the finished Whoop days D−28 … D−1 (at least 14), else no extra
above   = max(0, burned − quiet)
extra   = round half up to 10 kcal of (above × share% ÷ 100)       (integer: ((above × share + 500) div 1000) × 10)
extra   = min(extra, ceiling)                                       (when a ceiling is set)
target  = base + extra                                              (both ends of a range move by the same amount)
```

* "Updated through the day": the cycle the person is in now grows with every sync, so the extra starts once the day's calories
  pass a whole quiet day and grows from there. Early in the day it is 0.
* **Only calories rise.** Protein, potassium, phosphorus, sodium, fluid and carbohydrate targets stay as they are. The extra is
  never negative: the target is never below the base.
* Defaults: off; share 100 %; no ceiling. The share is 10–100 %, the ceiling 50–3000 kcal.
* Days without a Whoop figure, days before 14 finished days exist, and people without a calorie target get the base.
* Where it counts: the day on Today (`GET /api/log`), the assistant's `get_today` (same function) and every guidance answer for that
  day ("What fits now", the planner, swaps), because they read the same targets. Trends' averages and the period summary compare
  with the base target.
* What the screen says: "Base target" and "Active-day extra (from Whoop)" as separate lines; "Why this number" names Whoop, the
  quiet-day level and the share; on a day with an extra one plain line: "Extra calories on active days change your carbs; your
  care team can help you plan insulin for exercise." No insulin advice, nothing about lows, no warning.
* HRV, recovery, sleep and strain are shown in the card and **never** change a target, a suggestion or a message.
* The JS twin (`js/engine/activity.js`) computes the same numbers; `tests/data/activity_vectors.json` pins both.

### 4.3 Days, times and what is imported

* **A Whoop day** belongs to the date 12 hours after its cycle starts, on the person's clock (`timezone_offset`). A cycle starts
  when the person falls asleep, so a night that begins at 23:00 on Monday is Tuesday's day, and one that begins at 01:00 on
  Tuesday is Tuesday's day too. When two cycles land on one date (an odd night), the one that started later is kept.
* Day row: calories burned (kcal), strain, recovery %, resting heart rate, HRV (ms, RMSSD), sleep (minutes asleep: light + slow
  wave + REM of the night's main sleeps, naps left out) and sleep performance %. Workouts: start and end, sport, kcal, strain.
* Plausibility: kcal 1–15,000; strain 0–21; recovery and sleep performance 0–100; resting heart rate 20–250; HRV 1–500 ms; sleep
  0–1440 minutes; a workout up to 24 hours. A value outside is left empty.
* **Ledger and updates**: `device_imports` has one row per cycle (`cycle:<id>`) and workout (`workout:<uuid>`). The cycle the
  person is in changes all day, so a later sync **replaces** the values of that day's row (it is Whoop's row; a person cannot
  type activity). A row the person deleted (Disconnect with "also delete") does not come back unless they connect again.
* Each sync asks for everything that started from 3 days before the last sync (the first time: 90 days), so late scores and
  recoveries are picked up.
* Whoop's id for the person comes from the first record (`user_id`); the token answer has none and we do not ask for the profile.
  One Whoop account can be connected to one person here.

### 4.4 Care team

A fifth area, **"activity and recovery"** (`activity`). A Viewer or Care helper with it sees the card on the shared Trends page.
Without it, shared days use the **base** calorie target (the extra would tell them how active the person was). `shares.areas` and
`care_invites.areas` had `CHECK (json_array_length(areas) BETWEEN 1 AND 4)`; step 30 rebuilds both tables with 5 (as step 14
did for `ai_consents`), keeping every row and the link from an invite to its share.

## 5. Data (schema step 30)

```
activity_days(id, user_id → users ON DELETE CASCADE, date, source, source_key, kcal, strain, recovery_pct, resting_hr, hrv_ms,
              sleep_minutes, sleep_performance_pct, finished, started_at, created_at, updated_at)
  UNIQUE (user_id, date, source); UNIQUE (user_id, source_key)
activity_workouts(id, user_id → users ON DELETE CASCADE, date, start_time, end_time, minutes, sport, kcal, strain, source,
                  source_key, created_at, updated_at)
  UNIQUE (user_id, source_key); INDEX (user_id, date)
activity_extra(user_id PRIMARY KEY → users ON DELETE CASCADE, enabled, share_pct, ceiling_kcal, updated_at)
```

## 6. API

| Route | What |
|---|---|
| `GET /api/activity?start=&end=` | The person's Whoop days and workouts in the range, and their extra setting. Always 200 (Trends asks on every open). |
| `PUT /api/activity/extra` | `{enabled, share_pct, ceiling_kcal}`. The Activity list records turning it on or off. |
| `GET /api/shared/{id}/activity` | The same days and workouts for a Viewer or Care helper with the `activity` area; 404 otherwise. |
| `GET /api/log` | Gains `calorie_extra` (`null` or `{base_kcal, extra_kcal, burned_kcal, quiet_kcal, share_pct, ceiling_kcal}`); `targets.calories_kcal` is the raised target. |
| `/api/devices/whoop/…` | As for Withings (note 27 §4). |
