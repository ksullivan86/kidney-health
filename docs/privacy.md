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
* the person's **food preferences** (schema steps 5 and 17): for a food, *More like this*, *Less often*, *Not for me* or
  *Stop using what you learned*, with who set it (the person, or the Ask chat after they confirmed) and when, and in their
  settings the food groups they like, want less of or never want, the *Learn from my log* switch and the learned usual
  meals they hid. They shape only the order of meal suggestions, are shown only to that person, are part of the export and
  import, and are deleted with the account. **What the app learns from the log is not stored**: the app's own code works it
  out from the log each time it makes a suggestion, with a plain reason, and it is not a diagnosis or an allergy
  list. **Only the person's own explicit choices can be sent to an AI**, and only to the two features that already send a
  profile: when the optional AI is on, the person opted in and agreed to the destination, **meal ideas and Ask** are told, by
  name, the foods and food groups the person marked *More like this*, *Less often* or *Not for me* (at most 10 of each,
  each name cut to 60 characters, as untrusted data), and "What will be sent?" shows them. **What the app learned from the
  log is never sent**, nor a food the person told the app to stop learning about, nor the hidden usual meals; describe a meal,
  photos, lab report photos and an assistant connected with a token never get any of it (a test checks that the code that
  builds those requests does not read a preference). The Ask chat can also *propose* a change ("I don't really like
  salmon"): the app shows a card and writes nothing until the person presses Remember, whatever they trust;
* the **symptoms** the person chooses to record (schema step 15): which symptom (from a short list, or a name of
  their own up to 60 characters for "other"), the date, how bad (mild, moderate or severe) and an optional note up to
  300 characters. This is a new kind of health data. It is shown only to that person, on Today and Trends; it is part of
  the export (`export.json` and `symptoms.csv`) and of the import; it is never written to the server's log, and it
  is deleted with the account. **It is never sent to an AI provider, the Ask chat or an assistant: the code that builds
  those requests does not read it** (a test checks that), and a later feature must say so here before it does. The app
  records and shows a symptom; it does not say what it means. A symptom that the handbook's Get help now page lists
  as a warning sign shows the handbook's own words and a link to that page; that is computed from the symptom's name
  alone, on the server, and sends nothing anywhere ([Symptoms](../handbook/docs/app/reports-for-your-team.md));
* the **weights and blood pressure readings** the person chooses to record (schema step 18; design note 10): the date, an optional time,
  the weight in kilograms (or the top and bottom blood pressure number and an optional pulse), when it was taken (morning, before or after
  dialysis, other) and an optional note up to 200 characters, and where a row came from (typed, or imported with a key that stops a second
  import adding it twice). Two numbers the person's **care team** gave them are kept as personal settings: a weight-gain alarm and a blood
  pressure goal (the app never suggests either). This is health data. It is shown only to that person; it is part of the export
  (`export.json`, `weights.csv` and `blood_pressure.csv`) and of the import; it is never written to the server's log or the activity list,
  and it is deleted with the account. **It is never sent to an AI provider, the Ask chat or an assistant: the code that builds those
  requests does not read it** (a test checks that), and a later feature must say so here before it does. The app records and shows
  numbers; it does not say what they mean. A weight past the person's alarm, or a reading with a top number of 180 or more or a bottom
  number of 120 or more, shows the handbook's own words from its Get help now page and a link to it; that is computed on the server from the
  numbers alone and sends nothing anywhere ([the design](body.md));
* **Visit prep** (Trends → Get ready for a visit) stores nothing and sends nothing: it is drawn in the browser from the summary, lab results and symptoms the person already has, with the person's own questions kept in the open page's memory only (not in the browser's storage, not on the server, never sent to an AI); it is printed or saved as a PDF by the browser. The code that builds requests to an AI provider or an assistant does not read it ([Reports for your care team](../handbook/docs/app/reports-for-your-team.md));
* **Lab results from Apple Health clinical records** (Labs → Import from Apple Health, [Personalised targets and labs](targets-and-labs.md))
  are read **in the browser, on the device, and nothing is uploaded**. The person chooses the Health app's `export.zip` (or, if it was
  already unzipped in the Files app, the `clinical-records` JSON files); the page opens the zip itself with the browser's own
  decompression (the archive never leaves the device) and reads only the `clinical-records` entries, or opens each picked file with the
  browser's file reader (a file over 1 MB is not even opened), parses it there, shows the lab results it recognises, and lets go of the file. Only the rows the person keeps (the test,
  the value, the unit and the day) are sent, to the person's own server, through the same `POST /api/labs/import` as a typed or
  spreadsheet result, and are then stored and exported like any lab result. The files' other contents (the patient's name and ids,
  providers, notes, every other record) and the file names are not read, kept or sent, nothing is kept in the browser's storage,
  and the code makes no other network request (a test checks that). The files are not sent to an AI provider, the Ask chat or an
  assistant either;
* **Weights and blood pressure from the Apple Health export** (Import from Apple Health, [Weight and blood pressure](body.md#import-from-the-iphone-health-app))
  are read **in the browser, on the device, and nothing is uploaded while the file is read**. The person chooses the Health app's `export.zip`
  (or `export.xml`, if it was already unzipped in the Files app); the page opens the zip itself and reads only `export.xml` out of it,
  streaming it as text (it can be hundreds of megabytes, so it is never held whole and never given
  to an XML parser), keeps only weights and blood pressure readings and shows what it found. Only the rows the person keeps (the date and time,
  the value or values, when it was taken, the source `apple_health` and a key that stops a second import adding it twice) are sent, to the
  person's own server, through `POST /api/body/weights/batch` and `/blood-pressure/batch`. The name of the app or device that wrote a reading,
  the file name and every other record in the file (heart rate, steps, blood glucose, insulin, workouts, the person's name) are not kept or
  sent, nothing is kept in the browser's storage, and the code makes no other network request (a test checks that). Readings from a watch are
  not ticked until the person ticks them. Nothing from the file reaches an AI provider, the Ask chat or an assistant;
* **Lab results from a patient-portal C-CDA file** (Labs → Import from a patient portal file, [Personalised targets and labs](targets-and-labs.md))
  are read and **parsed in the browser, on the device, and nothing is uploaded**, so the server never sees the XML and has no XML parser.
  The person downloads the health summary from the portal and chooses the `.xml` file (up to 20 files of 5 MB; a larger one is not
  even opened); the page parses each with the browser's own parser, reads only the lab results of the Results section, shows the
  ones it recognises and lets go of the file. A file with a DOCTYPE or ENTITY declaration is refused before it is parsed. Only the
  rows the person keeps (the test, the value, the unit and the day) are sent, to the person's own server, through the same
  `POST /api/labs/import`. A portal summary also holds the patient's name, address, ids, doctors, medicines and notes: none of
  that is read, kept or sent, nothing is kept in the browser's storage, and the code makes no other network request (a test checks
  that). The files are not sent to an AI provider, the Ask chat or an assistant either;
* API keys the person chose to store, encrypted;
* assistant access tokens the person made, when the admin has turned assistant access on
  ([assistant.md](assistant.md)): a name, the first 12 characters, the scopes (read only, or also save food and
  recipes), the dates and a one-way hash of each token, never the token itself;
* phone-shortcut tokens the person made, when the admin has turned phone shortcuts on ([push.md](push.md)): the same (a name, the
  first 12 characters, the dates, a one-way hash), and the one scope that lets a token add weights and blood pressure readings. A
  weight or reading such a token adds is ordinary data of the account (marked as sent by that token, with its name shown while the token
  exists, in the export without the token, deleted with the account); the server logs only counts, never a value;
* a per-day count of lookups made with a shared key (counts only, not what was looked up);
* entries in the activity log about their account: sign-ins, failed sign-ins, password and key
  changes, assistant and phone-shortcut tokens made or revoked, a phone-shortcut token's rows deleted (counts only), food or recipes an assistant saved (with the token's name and
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
so it can open without a connection, and entries logged, edited or deleted while offline until the server has them
([Offline](install-on-your-phone.md#offline)). Signing out, **Clear offline data on this device** and
the server's sign-out answer (`Clear-Site-Data`) remove all of it. Photos of barcodes and labels are
read on the device; a barcode photo is never uploaded, and a label photo only when the person asks AI
to read it (resized, without location data).

Nothing is sent anywhere unless a feature that needs the internet is used (USDA lookups, barcode
lookups or the optional AI the admin turns on), and then only what that feature needs. The AI sends
nothing until the person opts in and agrees to the destination shown, and never sends their name,
account, weight, height, exact age, dates or notes ([ai.md](ai.md#what-is-sent-and-what-never-is)). Meal ideas and Ask
word the person's condition from the profile in one sentence (kidney stage or "not chosen yet", dialysis, and a diabetes
type only if there is one); describe-a-meal and photo requests carry no profile data
([ai.md](ai.md#the-instructions-follow-your-profile)).

If the admin turns on the **Ask** chat ([assistant.md](assistant.md#the-ask-screen-the-chat-inside-the-app)) and a
person agrees to it (its own consent, separate from meal data and photos), each question sends the AI provider the
person's messages in that conversation (the last 20, kept in the page only, never on the server) and the app's own
numbers the assistant looks up with its read-only tools: targets, a day's totals, food names and nutrients, plus the
same stage, dialysis, diabetes and preferences block as the other AI features (the preferences text and the foods and food
groups the person marked Like, Less often or Not for me, never what the app learned from the log). Never the name, user name,
e-mail, weight, height, exact age or notes. A message that sounds like a low or an emergency is answered by the app and
never sent. A question can take up to seven calls to the provider. What the provider does with it follows the
policy line the consent sheet shows ([ai.md](ai.md#what-is-sent-and-what-never-is)).

**Where each AI feature runs.** An admin who runs a model at home (Ollama on a GPU) can keep two shared AI providers
at once, a **local** one on the home network and a **cloud** one, and choose per feature which it uses
([ai.md](ai.md#which-ai-does-each-feature-use)). The default is the least-trusting one: **photos** (a kitchen photo can show
more than a label), **meal ideas**, **describing a meal** and **Ask** all go to the local AI, and are **off** if there is
none; a feature goes to a cloud company only when the admin pins it there, and the admin screen then says what it sends and
where. What the local AI receives never leaves the home network (the server refuses to connect to it on a public
address). Settings → AI features tells each person, per feature, where it runs, and a feature that moves to another provider asks
for the person's consent again. A person's own key is their own choice and goes to that company; the admin can switch
personal keys off. A server that already used one provider before this existed keeps using it for everything until the admin
chooses.

**Local first, cloud only when the local answer fails.** For photos, meal ideas and describing a meal an admin can choose
*Local, then cloud* ([ai.md](ai.md#local-first-cloud-only-when-the-local-answer-fails)). The request goes to the local AI
first, and the cloud company sees it **only if** the local AI's answer fails the app's checks (it is not usable, or the app's
rules throw it all out) **and** the person has agreed to send that kind of data to that cloud host. It does not go to the
cloud when the local AI is unreachable, slow, over its limit or declines the question. The consent sheet names both hosts and
has a separate tick box for the cloud one; "What will be sent?" shows both requests and says the second goes only if the
first fails the checks; every answer says which AI gave it, and the AI activity list records both calls. What is sent to the
cloud is exactly what a feature pinned to the cloud would send, no more, and never to a person's own provider. Ask is not
offered this way (it is several calls in a row) and **lab report photos never are**: they stay on the local AI only.

**A person who may choose** ([ai.md](ai.md#choosing-the-servers-local-or-cloud-ai-yourself)). An admin can turn on
`AI_PERSON_ROUTE_CHOICE_ENABLED` and tick chosen people in Server administration → Users. Those people pick, per feature, the
server's local AI or its cloud AI instead of the admin's choice. Picking the cloud AI sends that feature's data to the cloud
company, after the consent sheet and through the privacy filter below. A feature the admin switched off stays off, lab report
photos stay on the local AI, and nobody else's routing changes. The server checks the switch and the tick on every request.

**The privacy filter** ([ai.md](ai.md#the-privacy-filter)). Before any request goes to a cloud AI (the shared cloud AI, a
person's own provider, or a shared provider without the local role), the server replaces names, places, dates, addresses,
phone numbers, e-mail addresses, web addresses with a query and record numbers in its text with labels such as `[PERSON_1]`,
and puts the words back into the answer. The person's own names and their Care team's names are always among them. The list
that links labels to words lives in memory for that one request: it is not stored, logged or sent. The AI activity row keeps
the filtered request and the count of replaced details, never which words they were. It is always on and has no switch. It
never runs for the local AI, and it does not change where anything goes: lab report photos still go only to the local AI. It
reads text only, not photos or voice recordings, and it hides who is asking, not the health question.

**A photo of a lab report, or a PDF** (Labs → Read a lab report photo or PDF, [ai.md](ai.md#lab-report-photos)) can show a person's name,
date of birth, record numbers and clinic, and the app cannot take them out of an image. So it is read **only by the local
AI**: never by a cloud AI and never by a provider the person added themselves, whatever the admin's routing says (the setting
accepts only `local` and `off`), and with no local AI the feature is off and says so. It has its own consent
("Lab report photos"), whose sheet says where the photo goes, that the report may show a name, a date of birth and record
numbers, that the photo is not kept, and to crop it to the results table. The photo is checked and stripped of camera and
location data like every AI photo, never written to disk or logged, and not kept by the server: the AI activity row holds its
fingerprint and size and **none** of what the AI copied. The AI only copies printed results; the app keeps the tests and
units it knows and shows them as rows that start unticked; nothing is saved to the person's lab results until they tick a
row and press Save, and then it is stored like any lab result they typed (in their export, deleted with their account).

**A PDF lab report** is opened **in the person's browser** (the bundled pdf.js, in a worker the page makes itself: no eval, no scripting, no
forms, nothing fetched). **The PDF file is never sent to the server or anywhere else**; only the pages the person ticks (at most 10) are drawn
in the browser and sent, each as a JPEG, through the same route, local AI, consent and checks as a photo, and the drawn pages and the PDF are let
go when the person saves, discards, picks another file or cancels. A password-protected PDF is refused (the app never asks for the password).

When the assistant in Ask saves food or a recipe, what it saves is stored like anything else the person logs (their own
entries and saved meals, in their export and deleted with their account). By default it only saves when the person presses
Save on a card; the person can instead choose to trust it for a conversation or always (Settings → AI features, only while the
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
data of the person's account, in the export and deleted with it. A recipe's source link is kept as text. The
server opens it only when the person imports a recipe from that page (see below). A token made with "Also let it remember tastes" lets that assistant also change the person's own food
preferences (a like, "less often" or "not for me" for a food or a food group, or forgetting one; it reads and returns nothing
else of them), limited to 30 changes a day per token; each change is in the person's activity list with the token's name, the
food row is marked "from your assistant", and it is in the export and deleted with the account like any preference.

If the admin sets up Withings and a person connects their Withings account ([devices.md](devices.md)), the server keeps that
person's Withings sign-in, encrypted with the server's secret key, and fetches their weight, blood pressure and pulse every few
hours. The server sends Withings nothing but the sign-in and the request for measurements. The readings are ordinary weights and
readings marked "from Withings": in the export, deleted with the account, never sent to an AI provider. The server also keeps a
list of which Withings measures it has already looked at, so none is fetched twice; it holds no values and is deleted with the
account. Disconnect deletes the sign-in at once.

Whoop works the same way. The server keeps the person's Whoop sign-in, encrypted, and fetches their calories burned, strain,
recovery, resting heart rate, heart rate variability, sleep and workouts every few hours. It never asks Whoop for the person's
name, email or body measurements, and sends Whoop nothing but the sign-in and the requests. Whoop's member number for the person
is kept so one Whoop account is connected to one person here. The days and workouts are in the export, deleted with the account
and never sent to an AI provider. A Care team member sees them only if the person shares "activity and recovery". The person's
choice to add active-day calories to their target is kept with their other settings.

If the admin turns on the shopping list app and a person sets one up ([list-sync.md](list-sync.md)), the server keeps the
address of that person's own Grocy, KitchenOwl or Mealie, the list they chose, and their key, encrypted with the server's secret
key. When the person presses Send, the server sends that app the lines they ticked: each food's name and amount. Nothing else:
no dates, targets, readings or name. The key is never shown again, logged or exported; the address and key are deleted with the
account or with Remove. The activity list records each send with the app's name and the number of items.

If the admin turns on recipe pages and a person imports a recipe from a link ([recipe-import.md](recipe-import.md)), the
server opens that one page, reads its recipe data and forgets the page; only the link is kept, with the recipe. The site sees a
request from the server, not from the person's phone, with no cookie and nothing about the person. Pasted ingredients never
leave the server.

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
  * the **How well each AI is doing** section in Server administration counts everyone's AI calls together. It shows
    no names and no contents. On a server with only two or three people, an admin may still guess whose calls they were.

## Moving your data to another server

Settings → Account → Your data → **Import from a file** reads the `export.json` of an export of yours into
your account on the server you are signed in to. Your browser reads the file and sends it to your own
server over the same connection as everything else; nothing is sent anywhere else. Before anything changes
the server checks the file and shows what would be added and what would be left out.

* **Carried over:** your log entries, foods you made, saved meals, lab results, symptoms, weights and blood pressure readings and
  food preferences (More like this, Less often, Not for me); the
  shared USDA and Open Food Facts foods you used (linked if the new server has them, otherwise kept as your
  own copies, with their licence note). If you also tick *Also replace my profile, targets and settings*: your
  profile, targets, meal-guidance settings, display settings and the weight alarm and blood pressure goal. That box is off by default because your
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
* After importing, Profile and saved-meal lists reload from the server. A slow request that started before the import
  cannot put the old data back on screen.
* **No double counting.** An account that already has entries, foods, saved meals, lab results, symptoms, weights or blood pressure readings refuses
  an import unless you tick *Add to my existing data*; then whatever is already there is left out, so
  importing the same file twice adds nothing. A food that is neither in the file nor built in is listed as
  left out, never guessed; a saved meal that loses a food that way says so in its note.
* The server writes one line to your activity list ("Data imported", with counts and no content). Importing
  is limited to 20 requests an hour and needs your password again; the file may be up to 16 MiB (the
  person running the server can change that with `MAX_IMPORT_BYTES`).
* The `.zip` also holds spreadsheets (CSV) for reading; only `export.json` is imported.

## The online demo: data kept in your browser (only if you choose)

The online demo (the GitHub Pages build) runs entirely in your browser with sample data and has no server, so it stores nothing
by default. If you press **Keep my data in this browser** and tick *I understand*, the demo keeps its data in **this browser's
IndexedDB, on this device only**. **Nothing is sent anywhere**: the page makes no request for it, and there is no account and no
server to hold a copy. What that means for you:

* it is **not backed up**: clearing site data, private browsing, or the browser deciding to free up space can delete it, so export
  it regularly (**Settings → Your data → Export my data (export.json)**) and keep the file somewhere private, since it holds
  your health data;
* anyone who can use this browser on this device can open the demo and see it (the demo has no real sign-in);
* **Stop keeping data here** deletes the stored copy; the demo then starts again with its sample data;
* the file is the same `export.json` a server writes, so you can move to a real server with **Import from a file** (above);
* the installed app never does any of this: it keeps your data on your server only (its offline queue stores unsent entries
  on the device, see [Install on your phone](install-on-your-phone.md#offline)).

See [The online demo](demo.md).

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
  yourself (Ollama) keeps it in the house, and you can read it. The AI activity log keeps no request or reply text
  by default (`ai.audit_retention_days` 0); if you raise it, keep it short when your backups are kept long. Mark that model as the local AI (`AI_PROVIDER_ROLE=local`, or Server administration →
  AI providers → Which AI does each feature use?; a cloud AI from the environment is `AI_CLOUD_PROVIDER`) so photos, meal ideas, describing a meal and Ask use it by default, and
  pin a feature to a cloud provider only on purpose ([ai.md](ai.md#which-ai-does-each-feature-use)); *Local, then cloud* is the
  middle way (the cloud company sees a request only when the local answer fails the app's checks and the person agreed).
  Reading a photo of a lab report works only with a local AI (it cannot be pinned to a cloud provider, or to *Local, then
  cloud*).
* Use HTTPS once more than one person has an account ([https.md](https.md)).
