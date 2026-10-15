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
* the **symptoms** the person chooses to record (schema step 15): which symptom (from a short list, or a name of
  their own up to 60 characters for "other"), the date, how bad (mild, moderate or severe) and an optional note up to
  300 characters. This is a new kind of health data. It is shown only to that person, on Today and Trends; it is part of
  the export (`export.json` and `symptoms.csv`) and of the import; it is never written to the server's log, and it
  is deleted with the account. **It is never sent to an AI provider, the Ask chat or an assistant: the code that builds
  those requests does not read it** (a test checks that), and a later feature must say so here before it does. The app
  records and shows a symptom; it does not say what it means. A symptom that the handbook's Get help now page lists
  as a warning sign shows the handbook's own words and a link to that page; that is computed from the symptom's name
  alone, on the server, and sends nothing anywhere ([Symptoms](../handbook/docs/app/reports-for-your-team.md));
* API keys the person chose to store, encrypted;
* assistant access tokens the person made, when the admin has turned assistant access on
  ([assistant.md](assistant.md)): a name, the first 12 characters, the scopes (read only, or also save food and
  recipes), the dates and a one-way hash of each token, never the token itself;
* a per-day count of lookups made with a shared key (counts only, not what was looked up);
* entries in the activity log about their account: sign-ins, failed sign-ins, password and key
  changes, assistant tokens made or revoked, food or recipes an assistant saved (with the token's name and
  how many entries, or the recipe's name), exports;
* if the optional AI is on and the person uses it ([ai.md](ai.md)): the providers they agreed to send
  data to, their own AI provider (its key encrypted), a per-day count of AI calls and tokens, and their
  **AI activity**: what each call sent and received (kept 30 days by default, then only the time,
  provider and outcome; photos are never stored, only their fingerprint and size). The person sees and
  can delete their AI activity in Settings; admins see only the counts. The **Ask** chat is the exception:
  its calls keep no request, answer or message text, only the time, provider, model, the step and tool name and
  the outcome, and the conversation is not stored on the server at all. **Voice input** is another exception: the
  recording and its words are never stored; the activity list gets one row per recording with the transcription host, the
  model, a length bucket ("under 10 s") and the outcome, and the person's agreement to send recordings to that host is
  kept like the other consents;

**On the person's own device** (the browser's storage for the app's address, never on another
device): the app's offline copy, the days, foods and settings it last showed (13 days back to 7 ahead)
so it can open without a connection, and entries logged while offline until the server has them
([Offline](install-on-your-phone.md#offline)). Signing out, **Clear offline data on this device** and
the server's sign-out answer (`Clear-Site-Data`) remove all of it. Photos of barcodes and labels are
read on the device; a barcode photo is never uploaded, and a label photo only when the person asks AI
to read it (resized, without location data).

Nothing is sent anywhere unless a feature that needs the internet is used (USDA lookups, barcode
lookups or the optional AI the admin turns on), and then only what that feature needs. The AI sends
nothing until the person opts in and agrees to the destination shown, and never sends their name,
account, weight, height, exact age, dates or notes ([ai.md](ai.md#what-is-sent-and-what-never-is)).

If the admin turns on the **Ask** chat ([assistant.md](assistant.md#the-ask-screen-the-chat-inside-the-app)) and a
person agrees to it (its own consent, separate from meal data and photos), each question sends the AI provider the
person's messages in that conversation (the last 20, kept in the page only, never on the server) and the app's own
numbers the assistant looks up with its read-only tools: targets, a day's totals, food names and nutrients, plus the
same stage, dialysis, diabetes and preferences block as the other AI features. Never the name, user name, e-mail,
weight, height, exact age or notes. A message that sounds like a low or an emergency is answered by the app and
never sent. A question can take up to seven calls to the provider. What the provider does with it follows the
policy line the consent sheet shows ([ai.md](ai.md#what-is-sent-and-what-never-is)).

**Where each AI feature runs.** An admin who runs a model at home (Ollama on a GPU) can keep two shared AI providers
at once, a **local** one on the home network and a **cloud** one, and choose per feature which it uses
([ai.md](ai.md#which-ai-does-each-feature-use)). The default is the least-trusting one: **photos** (a kitchen photo can show
more than a label), **meal ideas**, **describing a meal** and **Ask** all go to the local AI, and are **off** if there is
none; a feature goes to a cloud company only when the admin pins it there, and the admin screen then says what it sends and
where. What the local AI receives never leaves the home network (the server refuses to connect to it on a public
address). Settings → AI ideas tells each person, per feature, where it runs, and a feature that moves to another provider asks
for the person's consent again. A person's own key is their own choice and goes to that company; the admin can switch
personal keys off. A server that already used one provider before this existed keeps using it for everything until the admin
chooses.

When the assistant in Ask saves food or a recipe, what it saves is stored like anything else the person logs (their own
entries and saved meals, in their export and deleted with their account). By default it only saves when the person presses
Save on a card; the person can instead choose to trust it for a conversation or always (Settings → AI ideas, only while the
admin allows it). The server then keeps three small things: the person's choice (with their other AI settings), a row in
their activity list for every change of the choice and for every save ("with Ask"; no food names, only how many entries,
the meal and the day, or the recipe's name), and, for 24 hours, a remembered key (a hash, never the key itself) with the ids
of what that chat request saved, so a request sent twice saves once. None of this is sent to the AI provider, and Ask's
conversation is still not stored.

If the admin turns on **voice input** for Ask ([ai.md](ai.md#voice-input-speech-to-text)) and a person agrees to it (its own
consent), tapping the microphone sends that **one recording** (a minute at most) to the speech-to-text server the admin
chose, and nothing else: no name, account details or cookie. That server turns it into text, which comes back into the
person's question box; the recording is deleted at once and the server keeps neither it nor the text (not on disk, not
in the database, not in the log). If the transcription server is on the admin's own network the audio does not leave it;
if it is an online service, it receives the audio under its own terms, which the consent sheet says. The browser's own
speech recognition is never used (Chrome would send the audio to Google, Safari to Apple). Only what the person then
chooses to send with **Send** goes to the AI, as above.

If the admin turns on assistant access and a person connects a chat assistant with their own token
([assistant.md](assistant.md)), the server answers that assistant's questions with the person's own numbers:
targets, the day's totals, food values and checked meals. Those answers go to the chat client the person
connected (and to the AI model it uses; a company's model sees them) and stay under that client's own settings.
The server keeps no copy of the questions or answers; Settings shows when each token was last used.
A token made with "Can also save food and recipes" lets that assistant also write to the person's own log and
saved meals (and add a USDA food the person chose to their food list, which looks the food up at USDA FoodData
Central as the Food screen's import does, sending only the food's number and the key); what it saved is ordinary
data of the person's account, in the export and deleted with it. A recipe's source link is kept as text and the
server never opens it.

## Who can see it

* **You** see everything of yours, and can download it all (Settings → Account → Export) as a
  `.zip` with a JSON file and CSV files your dietitian or a spreadsheet can open, and bring the JSON file
  into another server (see "Moving your data to another server" below).
* **Other people on the same server** cannot see any of it.
* **Admins** manage accounts but have no screen or API that shows another person's log, foods or
  profile. However:
  * the person who runs the server can technically read the database file and its backups;
  * an admin can create a password-reset link for any account. If that happens, you are told at
    your next sign-in, and it appears in your activity list.

## Moving your data to another server

Settings → Account → Your data → **Import from a file** reads the `export.json` of an export of yours into
your account on the server you are signed in to. Your browser reads the file and sends it to your own
server over the same connection as everything else; nothing is sent anywhere else. Before anything changes
the server checks the file and shows what would be added and what would be left out.

* **Carried over:** your log entries, foods you made, saved meals, lab results, symptoms and "Not for me" foods; the
  shared USDA and Open Food Facts foods you used (linked if the new server has them, otherwise kept as your
  own copies, with their licence note). If you also tick *Also replace my profile, targets and settings*: your
  profile, targets, meal-guidance settings and display settings. That box is off by default because your
  targets may have been agreed with your care team on the server you are importing into.
* **Not carried over, even if a file has them:** your username, password and sign-in sessions; assistant
  access tokens and every API key; your AI activity, AI call counts, the AI providers you agreed to send
  data to and your own AI provider (you agree again, on the new server); your Open Food Facts barcode
  choice; your sign-in activity list; anything about other people. An export never holds the first group
  and the importer ignores them if someone adds them to a file.
* **Only your own account is changed.** The file cannot reach another person's data, and it cannot make
  anything shared: a USDA or Open Food Facts food the new server lacks is never created from a file for
  everyone, only for you.
* **The numbers of an entry are recalculated** from its food and amount, as for any entry you log, so they
  follow the foods on the new server.
* **No double counting.** An account that already has entries, foods, saved meals, lab results or symptoms refuses
  an import unless you tick *Add to my existing data*; then whatever is already there is left out, so
  importing the same file twice adds nothing. A food that is neither in the file nor built in is listed as
  left out, never guessed; a saved meal that loses a food that way says so in its note.
* The server writes one line to your activity list ("Data imported", with counts and no content). Importing
  is limited to 20 requests an hour and needs your password again; the file may be up to 16 MiB (the
  person running the server can change that with `MAX_IMPORT_BYTES`).
* The `.zip` also holds spreadsheets (CSV) for reading; only `export.json` is imported.

## Deleting your account

Settings → Account → Delete account removes your account and everything that belongs to it from the
database at once (log, foods, saved meals, profile, settings, keys, sessions, assistant tokens, usage
counts, AI provider, consents and AI activity). The
database overwrites deleted records where it can. What deletion cannot reach:

* **backups** made before the deletion keep your data until they expire (ask the person running the
  server how long they keep them); that includes AI activity that was still kept when the backup was
  made;
* the one-time copy made when the server was upgraded to version 0.3 (`kidney.db.pre-v3.bak`), which
  holds the data logged before that upgrade and is deleted automatically 30 days after it;
* the activity log keeps a line saying that account number N was deleted (no name, no health data).

Export your data first if you want to keep it.

## For the person running the server

* Encrypt and rotate backups (restic, borg or age), keep them private (`0600`), and keep
  `SECRET_KEY` outside the data volume and its backups (see [accounts.md](accounts.md)).
* Tell the people you invite what this page says, especially the two points under "Admins".
* If you turn the optional AI on, what people send goes to the provider you chose; a model you run
  yourself (Ollama) keeps it in the house, and you can read it. Keep `ai.audit_retention_days` short if
  your backups are kept long. Mark that model as the local AI (`AI_PROVIDER_ROLE=local`, or Server administration →
  AI providers → Which AI does each feature use?) so photos, meal ideas, describing a meal and Ask use it by default, and
  pin a feature to a cloud provider only on purpose ([ai.md](ai.md#which-ai-does-each-feature-use)).
* Use HTTPS once more than one person has an account ([https.md](https.md)).
