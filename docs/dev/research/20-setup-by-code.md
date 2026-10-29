# 20 · Set the server up by code

| | |
|---|---|
| Status | Accepted and built, 2026-10-29. The owner asked for it: "admins don't like to click through a bunch of menus to bootstrap … some settings will want the option to change from the app UI, so maybe those can only be set on first pull, so that if someone wants to deploy kidney health it can mostly be set up by an AI." |
| Scope | Every server setting can be given in the environment, either as a **lock** (as before) or as a **first value** that the server writes once and an admin can change in the app afterwards. With the first admin from `ADMIN_USERNAME` + `ADMIN_PASSWORD_FILE` and the AI providers from `AI_*`, a server can be set up from one `.env` file and a few secret files, with no clicks. |
| Out of scope | People's own settings (their targets, theme choice, AI consent): those are theirs to make. Accounts other than the first admin (people are invited). A settings file in another format: `deploy/.env` already is one file. |
| Builds on | Note 07 §4.3 and §4.11 (settings registry, env locks, `ADMIN_USERNAME`), `app/settings_store.py`, `app/admin.py check`. |

## 1. Why

Until now a value in the environment **locked** its setting: the app showed it as "Set by the server" and nobody could change
it there. That suits a setting the admin wants fixed (a demo server's `REGISTRATION_MODE=closed`). It does not suit a setting
the admin wants to start somewhere and adjust later, so they had to click through Server administration after the first start.
A person or an AI agent setting a server up should be able to write every choice down once.

## 2. How it works

* `SETTINGS_INITIAL_ONLY` is a comma list of setting variables, or `*` for all of them. A variable on the list is a **first
  value**, not a lock.
* On every start, before anything else reads the settings, the server looks at each first value. If it has never looked at
  that setting before, it writes the value as the server's setting, adds a `settings.changed` row to the activity log (no
  person, `env` names the variable) and remembers that it did (a `meta` row `settings_initial:<key>`). If an admin had already
  chosen a value in the app, that value stays; the setting is still remembered.
* After that, the app owns the value. An admin can change it or put it back to the default, and a restart keeps that. Changing
  the variable later does nothing; the log says so once per start. A variable added to the list later is written on the next
  start.
* A variable not on the list keeps locking its setting, as before.
* A wrong name in the list, `*` mixed with names, or a value of the wrong type stops the start with a message naming the
  variable, as a wrong lock does. `python -m app.admin check` lists the locked settings and the first values.

For theme and units (scope `user_default`) the first value is the default for everyone; each person can still pick their
own. A lock on them would stop people choosing, so the docs advise listing them in `SETTINGS_INITIAL_ONLY`.

## 3. A variable for every server setting

Twelve settings had no variable. They have one now:

| Setting | Variable |
|---|---|
| `registration.invite_ttl_days` | `INVITE_TTL_DAYS` |
| `providers.usda.shared_enabled` | `USDA_SHARED_ENABLED` |
| `providers.usda.user_keys_allowed` | `USDA_ALLOW_USER_KEYS` |
| `targets.lab_rules_enabled` | `LAB_RULES_ENABLED` |
| `targets.lab_fresh_days.potassium`, `.phosphate`, `.albumin`, `.bicarbonate` | `LAB_FRESH_DAYS_POTASSIUM`, `_PHOSPHATE`, `_ALBUMIN`, `_BICARBONATE` |
| `targets.default_activity` | `DEFAULT_ACTIVITY` |
| `ui.theme` | `UI_THEME` |
| `user.units.labs`, `user.units.weight` | `LAB_UNITS`, `WEIGHT_UNITS` |

The only two without one are `ai.route.local_provider` and `ai.route.cloud_provider`. They hold the id of a provider row made
in the app. A provider from the environment gets its role from `AI_PROVIDER_ROLE` and `AI_CLOUD_PROVIDER` instead
(`app/ai/routing.py`). A test keeps this true for every setting added later.

## 4. Setting a server up without clicks

1. Secret files: `secret_key` (one line, 32 characters or more), `admin_password`, and any API keys.
2. `deploy/.env` (or Quadlet `Environment=`, or Kubernetes `env:`): `PUBLIC_URL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD_FILE`,
   the features to turn on, and `SETTINGS_INITIAL_ONLY` naming the ones the admin may change later.
3. `python -m app.admin check` inside the container: it stops on any mistake and lists what is locked and what is a first value.
4. Start the server. The log shows `setting …: first value from …` for each first value.

## 5. Tests

`tests/test_settings_initial.py`: a listed variable is not a lock and the others still are; `*`; each start-up mistake; written
once with an audit row; an admin's change and an admin's reset survive a restart; a value chosen before is kept; a variable
added later; the whole server through the admin page; `admin check`; the activity text. The settings parity vectors include two
cases with `SETTINGS_INITIAL_ONLY`, and the JavaScript twin treats a listed variable as no lock.

## 6. Choices taken (the owner can change any of them)

1. One list variable, not a second name per setting (`NAME_INITIAL`): `deploy/compose.yaml` passes each variable by name, so a
   second name would double that list, and the same `.env` line can move between lock and first value by editing one list.
2. Locks stay the default, so existing servers behave exactly as before.
3. A first value never overwrites a value chosen in the app, even on the first start that sees it.
