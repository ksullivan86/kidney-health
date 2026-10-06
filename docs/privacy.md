# Privacy: what the server stores and who can see it

This page explains, in plain words, what a Kidney Health server keeps about the people who use it.
It is written for the person who runs the server and for the people they invite. It is not legal
advice. If you offer the app to people outside your household (a clinic, a support group), health
data is a special category under data-protection law (for example GDPR Article 9) and you should
take advice.

## What is stored

For each account, on the server's disk in one SQLite database (`kidney.db`):

* the username, display name, role and when the account was created and last used;
* a hash of the password (Argon2id), never the password itself;
* the devices that are signed in (when, a shortened browser name and the first part of the network
  address), so people can sign out a lost phone;
* everything the person enters: food log entries (eaten and planned), their own foods, saved meals,
  their profile (weight, height, kidney stage, dialysis, diabetes type, targets) and settings;
* if the person chooses to add them (all optional): birth month (not the full date), the sex used in
  medical formulas, activity level, transplant date, pregnancy or breastfeeding, frailty, past weight,
  urine and dialysis volumes, and the lab results they type in (with the date taken). They are used
  only to work out suggested targets and the kidney-function card, are never written to the server's
  log, are part of the export, and are deleted with the account
  ([Personalised targets and labs](targets-and-labs.md));
* API keys the person chose to store, encrypted;
* a per-day count of lookups made with a shared key (counts only, not what was looked up);
* entries in the activity log about their account: sign-ins, failed sign-ins, password and key
  changes, exports.

Nothing is sent anywhere unless a feature that needs the internet is used (USDA lookups, and later
barcode or AI features the admin turns on), and then only what that lookup needs.

## Who can see it

* **You** see everything of yours, and can download it all (Settings → Account → Export) as a
  `.zip` with a JSON file and CSV files your dietitian or a spreadsheet can open.
* **Other people on the same server** cannot see any of it.
* **Admins** manage accounts but have no screen or API that shows another person's log, foods or
  profile. However:
  * the person who runs the server can technically read the database file and its backups;
  * an admin can create a password-reset link for any account. If that happens, you are told at
    your next sign-in, and it appears in your activity list.

## Deleting your account

Settings → Account → Delete account removes your account and everything that belongs to it from the
database at once (log, foods, saved meals, profile, settings, keys, sessions, usage counts). The
database overwrites deleted records where it can. What deletion cannot reach:

* **backups** made before the deletion keep your data until they expire (ask the person running the
  server how long they keep them);
* the one-time copy made when the server was upgraded to version 0.3 (`kidney.db.pre-v3.bak`), which
  holds the data logged before that upgrade and is deleted automatically 30 days after it;
* the activity log keeps a line saying that account number N was deleted (no name, no health data).

Export your data first if you want to keep it.

## For the person running the server

* Encrypt and rotate backups (restic, borg or age), keep them private (`0600`), and keep
  `SECRET_KEY` outside the data volume and its backups (see [accounts.md](accounts.md)).
* Tell the people you invite what this page says, especially the two points under "Admins".
* Use HTTPS once more than one person has an account ([https.md](https.md)).
