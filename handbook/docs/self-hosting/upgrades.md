---
title: Upgrades
description: "Which image tag to follow, tags versus pinned digests, automatic updates, database migrations, and moving from v0.12 or v0.10 to v0.12, from v0.9, v0.8, v0.7, v0.6, v0.5, v0.4, v0.3 or v0.2."
slug: upgrades
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-29
fact_checked: 2026-10-05
sources: [DEPLOY, NOTE01, NOTE07, SECDOC, SECURITYMD, PODMAN-QUADLET, ARCH]
---

# Upgrades

Upgrading means running a newer image on the same data volume. The app upgrades its database by itself
at start-up, so the work is choosing **what to follow** and **keeping a backup** first
([deployment guide][DEPLOY]).

## Tags: which one to follow

| Tag | Moves when | Use it for |
|---|---|---|
| `0.13` | every 0.13.x patch release | **most homes**: security fixes, no breaking changes |
| `0.21.0` | never | a fixed release |
| `latest` | every release, including a new minor version | not on a machine you care about |
| `edge`, `sha-<short>` | every merge to `main` | testing only |

Tags move only after the image passed a vulnerability scan; pushes to `main` publish only `edge` and
`sha-<short>` ([architecture contract][ARCH], v0.3 item 7; [operator security guide][SECDOC]).

## Tag or digest?

- **Track `:0.21` with auto-update** (simplest). Quadlet's `AutoUpdate=registry` plus
  `podman-auto-update.timer` pulls new patch releases daily and restarts the service
  ([Podman: Quadlet][PODMAN-QUADLET]).
- **Pin a digest** (`…:0.21.0@sha256:…`) that you verified with `scripts/verify-image.sh`, and change it on
  purpose ([security policy][SECURITYMD]). This is the default on Kubernetes, with
  `imagePullPolicy: IfNotPresent`.

Auto-update trusts whoever controls the tag you follow. Signing and the `:0.21` advice reduce that risk
but do not remove it.

!!! warning "Never mount the container engine's socket into an updater"
    Watchtower-style updaters need `podman.sock` or `docker.sock`, which hands that container your whole
    account on the host (or root, with a rootful socket). Use Quadlet auto-update or pinned digests
    instead ([operator security guide][SECDOC]).

## Before a minor upgrade (for example 0.20 to 0.21)

- [ ] Take a backup and check it ([Backups](backups.md)).
- [ ] Read the release notes for changed settings and removed features.
- [ ] Replace your deployment files if the notes say so.
- [ ] Change the tag (or digest), start, and watch the log. The minor tag does not move to the next minor on its own: a host
      that tracks `:0.20` stays on 0.20.x until you change it to `:0.21`.
- [ ] Open the app, check **Server administration → About this server** for the version and schema.

## Database migrations

Schema changes are numbered, append-only steps that run in order at start-up and are recorded in the
database. Each step checks before it changes anything, so a restart in the middle is safe
([architecture contract][ARCH]). A backup restores into the same or a newer version, never an older one.

## From v0.20 to v0.21

1. **Back up first.** The first start runs schema step 33. It adds one column for the new AI choice and changes nothing that is
   there.
2. **Change the tag** to `:0.21` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.21`) or to a digest
   you verified.
3. **Nothing new is switched on.** People choose the server's local or cloud AI only after you set
   `AI_PERSON_ROUTE_CHOICE_ENABLED` and tick them in Server administration → Users.
4. **Coming from 0.19 or older**, also follow the next sections.

## From v0.19 to v0.20

1. **Back up first.** There is no database change in this release.
2. **Change the tag** to `:0.20` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.20`) or to a digest
   you verified.
3. **The privacy filter is on by itself** for every request to a cloud AI. Requests to a local AI are unchanged.
4. **Coming from 0.18 or older**, also follow the next sections.

## From v0.18 to v0.19

1. **Back up first.** The first start runs schema step 32. It adds one table for sending the shopping list to a list app and
   changes nothing that is there.
2. **Change the tag** to `:0.19` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.19`) or to a digest
   you verified.
3. **Nothing new is switched on.** Sending the list stays off until you set `LIST_SYNC_ENABLED`; reading recipe pages stays off
   until `RECIPE_IMPORT_ENABLED` ([Users and keys](users-and-keys.md)).
4. **Coming from 0.17 or older**, also follow the next sections.

## From v0.17 to v0.18

1. **Back up first.** The first start runs schema step 31. It adds the Care team switches and a table for meal suggestions; every
   row stays, and every Care helper and Viewer keeps exactly what they had.
2. **Change the tag** to `:0.18` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.18`) or to a digest
   you verified.
3. **Nothing new is switched on.** The new switches start off for everyone.
4. **Coming from 0.16 or older**, also follow the next sections.

## From v0.16 to v0.17

1. **Back up first.** The first start runs schema step 30. It adds the Whoop and activity tables and rebuilds the Care team tables
   so a fifth area fits; every row stays, and the server keeps a copy of the database from before the step.
2. **Change the tag** to `:0.17` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.17`) or to a digest
   you verified.
3. **Nothing new is switched on.** Whoop stays off until you register a Whoop app and set its variables
   ([Users and keys](users-and-keys.md)).
4. **Coming from 0.15 or older**, also follow the next sections.

## From v0.15 to v0.16

1. **Back up first.** The first start runs schema step 29. It adds the tables for connected devices and changes nothing that is there.
2. **Change the tag** to `:0.16` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.16`) or to a digest
   you verified.
3. **Nothing new is switched on.** Withings stays off until you register a Withings app and set its variables
   ([Users and keys](users-and-keys.md)).
4. **Coming from 0.14 or older**, also follow the next sections.

## From v0.14 to v0.15

1. **Back up first.** There is no schema step.
2. **Change the tag** to `:0.15` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.15`) or to a digest
   you verified.
3. **Nothing new is switched on.** Your sign-in provider keeps working. Two providers at once, provider-only sign-in and tokens
   that never expire are off until you set them ([Users and keys](users-and-keys.md)).
4. **Coming from 0.13 or older**, also follow the next sections.

## From v0.13 to v0.14

1. **Back up first.** The first start runs schema steps 27 and 28. They add the Care team roles and invites, and the test
   accounts and feedback. Every existing share becomes a Viewer. Nothing that is there changes.
2. **Change the tag** to `:0.14` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.14`) or to a digest
   you verified.
3. **Nothing new is switched on.** The Care team still needs sharing turned on, and the test accounts need their switch and a
   password file ([Users and keys](users-and-keys.md)).
4. **Coming from 0.12 or older**, also follow the next sections.

## From v0.12 to v0.13

1. **Back up first.** The first start runs schema step 26. It adds a table for linked sign-ins and changes nothing that is there.
2. **Change the tag** to `:0.13` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.13`) or to a digest
   you verified.
3. **Nothing new is switched on.** Sign-in with Authentik, Google or another provider stays off until you set it up
   ([Users and keys](users-and-keys.md)).
4. **Coming from 0.11 or 0.10**, also follow the next sections.

## From v0.11 to v0.12

1. **Back up first.** 0.12 has no schema step. Coming from 0.10, step 25 from the next section runs at the first start.
2. **Change the tag** to `:0.12` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.12`) or to a
   digest you verified.
3. **Nothing new is switched on.** Planning several days at once uses the app's own rules and needs no setting.
4. **If you use AI**, run `scripts/ai_eval.py` again for each model: the prompt changed (`PROMPT_VERSION` `2026-10-29.1`).
5. **If you reach the server over a VPN** and only the header shows, see [Troubleshooting](troubleshooting.md).

## From v0.10 to v0.11

1. **Back up first.** The first start runs schema step 25. It adds a share's end date; shares made before last until someone
   stops them.
2. **Change the tag** from `:0.10` to `:0.11` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.11`) or to
   a digest you verified.
3. **Nothing new is switched on.** New settings: `BACKUP_REMINDER_DAYS` (7 by default, `0` for none). If your backups run outside
   the app, end the job with `python -m app.admin record-backup` ([Backups](backups.md)).

## From v0.9 to v0.10

1. **Back up first.** The first start runs schema step 24 (sharing). It adds a table and changes nothing that is there.
2. **Change the tag** from `:0.9` to `:0.10` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.10`) or to
   a digest you verified.
3. **Nothing new is switched on.** Sharing is off until you turn it on (`SHARING_ENABLED=true`, or the switch in Server
   settings). A setting you set in the environment still locks it, as before; to give only a first value, see
   [Set it up by code](configuration.md#set-it-up-by-code).
4. **The iPhone QR code needs HTTPS.** It uses `PUBLIC_URL`, or else the address the page was opened at.

## From v0.8 to v0.9

A host on 0.8 goes straight to the current release: back up, change the tag to `:0.21` and follow this section and
"From v0.9 to v0.10", "From v0.10 to v0.11", "From v0.11 to v0.12" and "From v0.12 to v0.13" above. Schema steps 22 to 26 run at the first start.

1. **Back up first.** The first start runs schema steps 22 (two-step sign-in) and 23 (passkeys). They add tables and change
   nothing that is there.
2. **Change the tag** from `:0.8` to the current one (`:0.21`), as above.
3. **Nothing new is switched on.** Two-step sign-in and passkeys are each person's choice. "Admins must use two-step sign-in"
   is off until you turn it on (`AUTH_REQUIRE_TWO_STEP_ADMINS=true`, or the switch in Server settings).
4. **For passkeys, set `PUBLIC_URL`** to the address people open. Browsers make passkeys only for a name over HTTPS, never for an
   IP address.
5. **`SECRET_KEY` now also protects the two-step secrets.** Keep backing it up apart from the database.

## From v0.7 to v0.8

A host on 0.7 goes straight to the current release: back up, change the tag to `:0.21` and follow this section and
the newer sections above. Schema steps 22 to 26 run at the first start.

1. **Back up first.** This release has no schema step, but a backup before every upgrade is the habit to keep.
2. **Change the tag** from `:0.7` to the current one (`:0.21`), as above.
3. **Nothing new is switched on.** AI recipes run on the local AI by default (`AI_ROUTE_RECIPES=local`) and only for people who
   agree to Meal data. Cooking steps written by AI stay off until you set `AI_RECIPE_STEPS=true`, after a live run of
   `scripts/ai_eval.py`.
4. **Everyone who uses AI is asked to agree to Meal data again**, because it now covers a recipe's foods and amounts.
5. **New `PROMPT_VERSION` (`2026-10-27.2`).** Run `scripts/ai_eval.py` again for each model you use.

## From v0.6 to v0.7

A host on 0.6 goes straight to the current release: back up, change the tag to `:0.21` and follow this section and
"From v0.7 to v0.8" above. Schema step 21 runs at the first start.

1. **Back up first.** The first start runs schema step 21: three columns on saved meals for recipes. A recipe that Ask or an
   assistant saved gets its servings and link copied from its note; no note changes.
2. **Change the tag** from `:0.6` to the current one (`:0.21`), as above.
3. **Nothing new is switched on.** Recipes and "Fit to my targets" need no setting and send nothing to an AI.

## From v0.5 to v0.6

A host on 0.5 goes straight to the current release: back up, change the tag to `:0.21` and follow this section and
the newer sections above. Schema steps 20 and 21 run in one start.

1. **Back up first.** The first start runs schema step 20: two columns on the AI provider list. The provider you have now keeps
   every setting.
2. **Change the tag** from `:0.5` to the current one (`:0.21`), as above.
3. **Nothing new is switched on.** A second AI from the environment (`AI_CLOUD_PROVIDER`) and the folder of AI test reports
   (`AI_EVAL_REPORTS_DIR`) do nothing until you set them.
4. **Changing `AUTH_MODE`** now ends every assistant and phone-shortcut token. People make new ones in Settings.
5. **Outside a container**, the app makes its data folder `0770` and the database files `0600`. A backup tool that reads
   `kidney.db` as another user needs the app's user, or use `python -m app.admin backup`.

## From v0.4 to v0.5

A host on 0.4 goes straight to the current release: back up, change the tag to `:0.21` and follow this section and
the newer sections above. The schema steps of both upgrades run in one start.

1. **Back up first.** The first start runs schema steps 18 and 19, each in its own transaction: two new tables for weights and
   blood pressure readings, then a column that says which phone-shortcut token sent a row. There is no automatic copy, and a
   backup restores into the same or a newer version, never an older one.
2. **Change the tag** from `:0.4` to `:0.5` (the shipped Quadlet unit, compose file and Kubernetes base already say `:0.5`) or to
   a digest you verified.
3. **Nothing new is switched on.** Phone shortcuts are off until an admin turns them on, and a token that lets an assistant
   remember tastes exists only when a person ticks the box for it. The weight and blood pressure card on Today shows for
   everyone, and nothing it holds leaves the server. The release notes list every new setting.
4. **Your own Content-Security-Policy?** If a reverse proxy sets it instead of the app, add the Trusted Types policy name
   `kh-pdf` (`trusted-types kh-sw kh-xml kh-pdf`), or choosing a PDF lab report says "This browser cannot read a PDF here". If
   your proxy lists the paths it passes on and you want phone shortcuts, add `/push/v1/` next to `/mcp`.

## From v0.3 to v0.4

A host on 0.3 goes straight to the current release: back up, change the tag to the current one (`:0.21`) and follow this
section and the newer ones above. The schema steps of both upgrades run in one start.

1. **Back up first.** The first start runs schema steps 8 to 17, each in its own transaction. There is no automatic copy as
   there was for 0.3, and a backup restores into the same or a newer version, never an older one.
2. **Change the tag** from `:0.3` to the current one (the shipped Quadlet unit, compose file and Kubernetes base say `:0.21`)
   or to a digest you verified. The image now runs Python 3.15 on the same Chainguard base.
3. **Nothing new is switched on.** Assistant access, Ask, voice input, trusted saves and the cloud fallback are off until an
   admin turns them on. The release notes list every new setting.
4. **Your own Content-Security-Policy?** If a reverse proxy sets it instead of the app, add the Trusted Types policy name
   `kh-xml` (`trusted-types kh-sw kh-xml`), or the patient-portal lab import cannot read a file. 0.5 adds `kh-pdf` (reading a PDF
   lab report), see "From v0.4 to v0.5" above.
5. **Kubernetes:** the base in `deploy/k8s` is cluster-neutral now; copy the example overlay and move your values into it.

## From v0.2 to v0.3

Upgrading from v0.2 now goes straight to the current release: do these steps with the current deployment files, then follow
"From v0.3 to v0.4" and the newer sections above.

1. **Back up first.** v0.2 has no `app.admin backup`; the guide's
   [v0.2 to v0.3 steps](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#from-v02-to-v03) have a one-line SQLite copy for the old image, and what to
   do first on a host that auto-updates `:latest`.
2. **The upgrade makes its own backup** too, `/data/kidney.db.pre-v3.bak`, before the accounts migration.
   It is deleted automatically after 30 days ([design note 07][NOTE07]).
3. **Replace your deployment files** with the v0.3 ones. What changed:
   - the image has no shell; backups and health checks use `python -m app…`;
   - secrets are files: move `USDA_API_KEY` into a secret file, and add `SECRET_KEY_FILE`;
   - the port is published on `127.0.0.1`; reach the app through your HTTPS proxy;
   - set `PUBLIC_URL` (or `ALLOWED_HOSTS`) if people use a host name: unknown names now get
     `400 Unknown host`;
   - `--forwarded-allow-ips=*` is gone: list your proxy in `TRUSTED_PROXIES`;
   - `:latest` now means "newest release", not `main`; track the minor tag (`:0.21` now);
   - `--userns=keep-id` is no longer recommended ([design note 01][NOTE01]).
4. **Accounts.** On first start the existing log becomes the admin's. A v0.2 `APP_PASSWORD` becomes the
   admin's password once (you are asked to change it if it is shorter than 15 characters); otherwise
   use the setup code from the log ([Users and keys](users-and-keys.md)).
5. **Rolling back:** stop v0.3, restore `kidney.db.pre-v3.bak` as `kidney.db`, and start the old image.
   **Do not roll back after a second person has signed up**: v0.2 has no accounts and would mix
   everyone's log together.

## If something goes wrong

- **`400 Unknown host` after the upgrade**: set `PUBLIC_URL`.
- **The health check fails**: an old string-form health command runs through `/bin/sh`, which the image
  no longer has. Use the exec form `["python", "-m", "app.healthcheck"]`.
- **Which version is running?** **Server administration → About this server** shows the version and schema; the engine
  shows the image digest ([Troubleshooting](troubleshooting.md#which-version-is-running)).
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [Backups](backups.md) · [Security](security.md) (verifying images) · [Rootless Podman](podman-rootless.md) · [Kubernetes](kubernetes.md)

## Sources

- [Deployment guide: upgrades](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#upgrades); [operator security guide][SECDOC], sections 7 and 9; [security policy][SECURITYMD].
- [Design note 01][NOTE01]; [design note 07][NOTE07] §4.15; [architecture contract][ARCH], v0.3 contract.
- [Podman: Quadlet units][PODMAN-QUADLET].
