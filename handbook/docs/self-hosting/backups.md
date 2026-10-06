---
title: Backups
description: "Back up the database while the app runs, keep the secret key separately, check a backup, and restore it."
slug: backups
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
sources: [DEPLOY, NOTE07, NOTE01, SECDOC, SQLITE-BACKUP, GDPR]
---

# Backups

Everything kidney-health knows is in one SQLite file, `kidney.db`: every person's log, password hashes,
encrypted API keys and the activity log. A backup is a consistent copy of that file, taken with the
app's own command while it keeps running ([deployment guide][DEPLOY]).

## Take a backup

The built-in command uses SQLite's online backup API, which copies a database in use and leaves a
consistent snapshot ([SQLite][SQLITE-BACKUP]). It needs no shell in the container and never overwrites a
file.

```bash
# Quadlet, compose or Docker (use docker instead of podman as needed)
podman exec kidney-health python -m app.admin backup - > "kidney-$(date +%F).db"
# Kubernetes
kubectl -n kidney-health exec deploy/kidney-health -- python -m app.admin backup - > "kidney-$(date +%F).db"
chmod 0600 kidney-*.db
```

Then, every time:

- [ ] **Encrypt** the copy (restic, borg or age). It holds health data for everyone on the server.
- [ ] Keep it `0600`, and keep more than one generation, off this machine.
- [ ] Note where the backups go and how long you keep them: people who delete their account are still in
      older backups until those expire ([design note 07][NOTE07]).

Run it daily from a systemd user timer or cron on the host.

## The secret key is separate

`SECRET_KEY` encrypts the stored API keys. A `python -m app.admin backup` copy does **not** contain it.
A **volume-level** backup (restic of the volume directory, a PVC snapshot, `podman volume export`)
**does**, if the key was auto-generated as `/data/secret.key`, and then anyone holding that backup can
read the keys. That is why every shipped profile mounts `SECRET_KEY_FILE` from the engine's secret
store, outside `/data` ([operator security guide][SECDOC]).

- [ ] Keep a copy of the secret key in a password manager.
- [ ] Restoring without it loses **only** the stored API keys; people re-enter them. Health data and
      passwords are not affected.

## Check a backup

```bash
podman run --rm --user 10001:10001 --entrypoint python \
  -v "$PWD/kidney-2026-10-01.db:/restore/kidney.db:ro,Z" \
  ghcr.io/ksullivan86/kidney-health:0.3 -m app.admin restore-check /restore/kidney.db
```

`restore-check` reports integrity, the schema version, the number of users, and whether stored keys
decrypt with the current key. Do it now and then, not only when you need the backup
([deployment guide][DEPLOY]).

## Restore

1. **Stop the app** so nothing writes during the copy (`systemctl --user stop kidney-health`; compose:
   `podman-compose -f deploy/compose.yaml stop`; Kubernetes: scale to 0).
2. Make the backup readable for UID 10001: `podman unshare chown 10001:0 FILE` (rootless Podman), or
   `chmod 0644` inside a `0700` directory (rootless Docker).
3. Copy it **into** the volume through SQLite, which also handles the `-wal` and `-shm` files. The exact
   one-off command for each engine is in the [deployment guide][DEPLOY].
4. Start the app. Migrations run on start, so a backup restores into the **same or a newer** version,
   never an older one.
5. Optional: `restore-check FILE --revoke-sessions` signs everyone out after a restore.

## The automatic pre-v0.3 backup

Before the accounts migration, the upgrade copies the database to `/data/kidney.db.pre-v3.bak`. It is
the rollback path and is deleted automatically 30 days later (or at once with
`python -m app.admin purge-pre-v3-backup`). **Settings → Admin → About** shows it while it exists
([Upgrades](upgrades.md)).

## Export is not a backup

Each person can export their own data as a `.zip` (v0.3). That is for moving data or keeping a personal
copy, and for the right to take your data with you on a shared server ([GDPR][GDPR], Article 20). It is
not a server backup: it has no passwords, keys or other people's data ([design note 07][NOTE07]).

## Replication is not a backup either

A replicated volume (Longhorn, Ceph) faithfully copies a corrupted file. Keep real, dated backups
([deployment guide][DEPLOY]).

## If something goes wrong

- **`restore-check` reports keys "unreadable"**: the current `SECRET_KEY` is not the one the backup used.
  Restore the old key, or have people re-enter their keys.
- **`attempt to write a readonly database` after a restore**: fix the owner (UID 10001) of the files in
  the volume.
- **The app will not start after restoring an older backup into an older version**: restore into the
  version that made it, or newer.

## Related pages

- [Upgrades](upgrades.md) · [Security](security.md) · [Users and keys](users-and-keys.md)

## Sources

- [Deployment guide][DEPLOY], "Backups and restore"; [operator security guide][SECDOC], section 6.
- [Design note 07][NOTE07] §4.15 and the security review; [design note 01][NOTE01].
- [SQLite: online backup API][SQLITE-BACKUP]; [GDPR][GDPR], Article 20.
