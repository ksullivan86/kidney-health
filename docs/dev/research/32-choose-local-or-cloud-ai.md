# 32 · Chosen people pick the server's local or cloud AI, per feature

| | |
|---|---|
| Status | Accepted and built for 0.21, 2026-10-31. Schema step **33** (one column). |
| Owner's words (2026-10-31) | "I would rather give people the option to use the server's local or cloud [AI] (ideally this can be an extra privilege role for the user and we can have an option check box or something to enable the role users to choose between the server's AIs (local or cloud))." One choice per feature. |
| Standing rules it keeps | Lab reports, and anything showing a name or date of birth, go to the local AI only, never to the cloud and never as a fallback. A feature the admin switched off is off for everyone. Consent is per person, provider and purpose. The privacy filter runs on every request to a cloud AI. Every setting is an environment variable. The AI never gets a dosing task. |
| Builds on | `app/ai/routing.py` (roles `local` and `cloud`, `ai.route.*`, tier 3 `local_then_cloud`), note 31 (the privacy filter), `users.can_use_shared` (the pattern for a per-person tick box an admin sets). |
| Out of scope | Choosing between more than the two shared roles. Choosing a provider for lab report photos. Letting a person choose without the admin's tick. |

## 1. What it does

An admin can let chosen people decide, feature by feature, whether their requests go to the server's **local AI** or the
server's **cloud AI**. Everyone else keeps exactly what the admin set.

Three things must all be true for a person's choice to count:

1. The server switch is on: `AI_PERSON_ROUTE_CHOICE_ENABLED=true` (setting `ai.person_route_choice`, default off).
2. The admin ticked **May choose the server's local or cloud AI** for that person in Server administration → Users
   (`users.can_choose_ai`, default 0).
3. The person picked something other than **Server default** for that feature in Settings → AI features.

The server checks 1 and 2 on every request, from the database, so a change takes effect at once. The browser's choice is
never trusted: the page only shows what the server says and sends the choice to a route that checks it.

## 2. The features

| Feature | Can be chosen | Why |
|---|---|---|
| Photos (labels and plates) | yes | |
| Meal ideas | yes | |
| Describe a meal | yes | |
| Ask | yes | |
| Recipes | yes | |
| Lab report photos | **never** | A report can show a name and date of birth that the app cannot take out of a photo. It stays local or off. It is never offered, never stored and never changed. |

## 3. How a request is resolved

`routing.resolve_feature` is still the one place. The order:

1. AI off, test account without AI, or not opted in: as before.
2. The admin's route is `off`: off for everyone, whatever the person chose.
3. Lab report photos: local or off, as before. The person's choice is never read.
4. The person uses **their own provider**: their own provider, as before. Their own-provider choice wins.
5. **New:** the switch is on, the person has the privilege, and they chose `local` or `cloud` for this feature: the shared
   provider holding that role serves it. No `local_then_cloud` fallback: the person chose one AI.
6. Otherwise the admin's route (`local`, `cloud`, `any`, `local_then_cloud`), exactly as before.

In step 5 the usual checks still apply: `can_use_shared`, the provider is switched on, its key can be read, and a local AI
must still be on a private address (and is pinned to the private network). If the chosen role has no provider any more, the
feature is off for that person with a plain reason (`chosen_role_missing`). It does not move to the other AI on its own: that
would send data somewhere the person did not choose.

Consent, quota, the answer cache, the AI activity row and "What will be sent?" follow the provider the feature resolves to,
as they always have. So the first time a person's feature goes to the cloud AI, the consent sheet names that company and host.
The privacy filter runs for every provider that is not the local AI, so it runs on every request after a person picks cloud.

## 4. Decisions

1. **Server switch.** `AI_PERSON_ROUTE_CHOICE_ENABLED` (setting `ai.person_route_choice`), default off, in the settings
   registry like every server setting, and env-only while sign-in is off. While off nothing changes for anyone: the tick box
   is shown greyed with a hint, Settings shows no choice, and stored choices are ignored.
2. **Per-person privilege.** A column `users.can_choose_ai` (schema step 33, 0 or 1, default 0). Only admins change it
   (`PATCH /api/admin/users/{id}` with `can_choose_ai`, recent password as for every admin write). Each change is in the audit
   log as `user.updated` with `can_choose_ai`. Test accounts may have it: they are a good way to try it. A test account reset
   makes new accounts, so the tick goes with them.
3. **The person's choice.** A personal setting `ai.route_choice`: one of `default`, `local`, `cloud` for each of `photos`,
   `meal_ideas`, `describe`, `chat` and `recipes` (no `labs` field: the model refuses it). It is written only through
   `PUT /api/me/ai/route-choice`, which answers `403` without the switch and the privilege. `PATCH /api/me/settings` refuses
   the key the same way. Each change is in the person's activity list as `ai.route_choice_changed` (feature, old, new).
4. **What the screen offers.** Only the AI that exists: "The server's local AI (host)" only when a provider holds the local
   role, and the same for cloud. The route refuses a missing one (`400`, `no_local_provider` / `no_cloud_provider`) and a
   feature the admin switched off (`409`, `feature_off`). "Server default" is always allowed.
5. **When the privilege or the switch goes.** The choices are **kept and ignored**: from the next request the person is back
   on the admin's routes. If the admin gives the privilege back, the old choices apply again; Settings shows them while they
   apply. Kept, because the switch is an environment variable and can be turned off without any request that could clear
   them, so clearing would happen only some of the time.
6. **Own provider wins.** A person who chose "My own provider" keeps it for every feature; the per-feature choice applies
   again when they switch back to the server's AI. Settings says so.
7. **No fallback on a chosen feature.** "The server's local AI" means only the local AI. "Server default" keeps
   `local_then_cloud` exactly as before.

## 5. API

* `GET /api/me/ai` adds `route_choice`: `null` unless the switch is on and the person has the privilege; otherwise
  `{choices: {feature: default|local|cloud}, features: [{feature, label, choice, admin_off}], local: {label, host}|null,
  cloud: {label, host}|null, own_wins: bool}`.
* `PUT /api/me/ai/route-choice` with any of the five features. Answers the same view as `GET /api/me/ai`.
* `GET /api/ai/status` and `GET /api/me/ai`: each `routes`/`routing` entry adds `chosen` (`local`, `cloud` or null) and the
  "Runs on" line adds "(your choice)".
* `GET /api/admin/users` adds `can_choose_ai`; `PATCH /api/admin/users/{id}` takes it.

## 6. Tests

`tests/test_ai_route_choice.py`: switch off changes nothing; privilege off refuses the choice and ignores a stored one; local
and cloud resolve per feature; admin `off` wins; labs is never offered, never stored and never cloud; a newly chosen cloud
provider asks for consent; the privacy filter runs on a chosen cloud request; own provider unchanged; only admins set the
privilege; audit rows; one person's choice never changes another's. `tests/test_migration_m033.py` for the step.
