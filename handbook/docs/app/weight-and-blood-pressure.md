---
title: Weight and blood pressure
description: "Write down your weights and blood pressure readings, or send them from an iPhone Shortcut, enter the two numbers your care team gave you, and see what the app shows, what it points to in this handbook and what it leaves to your team."
slug: weight-and-blood-pressure
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-22
fact_checked: 2026-10-22
sources: [NOTE10, NOTE12, APPLE-SHORTCUTS, ARCH, NOTE05, MEDLINE-BPM, NHLBI-BPS, K21BP, AHA25BP, AHA-CUFFLESS, DG28a, NKF-HDaccess]
---

# Weight and blood pressure

The app keeps a log of your weights and your blood pressure readings. It shows them back to you and your
care team, works out a few plain numbers, and points to the warning signs in this handbook. **It does not
say what a weight or a reading means, what causes it or what to do about it, and it never suggests a
medicine** ([design note 10][NOTE10]; [architecture contract][ARCH]).

## What to record and when

Record the weights and readings your care team asks for. Your team also tells you how often. The dialysis
pages say when to weigh yourself: see [In-center hemodialysis](../stages/hemodialysis-in-centre.md) and
[Fluid](../eat/fluid.md).

Open **Today**, find the card **Weight and blood pressure**, and press **Add weight** or **Add blood
pressure**. Nothing is saved until you press **Save**. Each entry has **Edit** and **Delete**.

- **A weight** asks when it was taken: morning, before dialysis, after dialysis or other. The two dialysis
  choices show only when your Profile says you are on dialysis. You type it in pounds or in kilograms, as
  you chose in **Settings → Weight and blood pressure**, and the sheet shows the other unit under the box.
- **A blood pressure reading** has the **top number (systolic)** first and the **bottom number (diastolic)**
  second. The pulse is optional. It also asks when you measured: morning, evening or other, and before or
  after dialysis if you are on dialysis.
- The sheet repeats what you typed, for example "Top 180, bottom 95", so you can see a slip before you save.
  The app refuses a number that cannot be right, such as a top number lower than the bottom one.
- Weights and readings need your connection to the server: if you are offline, the app says so and saves
  nothing ([architecture contract][ARCH]).
- If the server cannot save it, the sheet stays open with what you typed and the message shows on top of
  it. Press **Save** again to try once more.

## How to measure blood pressure at home {#how-to-measure}

- Rest for about 5 minutes in a chair first. Sit up straight with your legs uncrossed and your feet flat.
  Use an upper-arm cuff that fits snugly, and measure at the same time of day each time
  ([MedlinePlus][MEDLINE-BPM]).
- If you have a fistula or a graft for dialysis, never let anyone put a blood pressure cuff on that arm:
  use the other one ([NKF][NKF-HDaccess]; [In-center hemodialysis](../stages/hemodialysis-in-centre.md)).
- Ask your care team how often to measure and which readings to bring to a visit.

## Which device

- **Use a validated upper-arm cuff.** "Validated" means the model was tested against a reference
  measurement and found accurate. Ask your care team or your pharmacy if you are not sure that yours is
  ([2025 AHA/ACC guideline][AHA25BP]; [MedlinePlus][MEDLINE-BPM]).
- **A watch or a ring that estimates blood pressure without a cuff is not a good source for this log.** The
  2025 American Heart Association and American College of Cardiology guideline recommends against using
  cuffless devices to diagnose or treat high blood pressure until they show better precision and
  reliability ([2025 AHA/ACC guideline][AHA25BP]; [American Heart Association][AHA-CUFFLESS]).

## The alarm and the goal are your care team's numbers

In **Settings → Weight and blood pressure** you can enter two numbers. Both come from your care team. The
app has no number of its own for either and never suggests one:

- **Weight-gain alarm:** "Call my team if my weight goes up by more than [ ] kg or lb, between sessions or
  in [n] days". **Between sessions** is offered only if your Profile says hemodialysis. You can choose 1 to 7
  days ([design note 10][NOTE10]).
- **Blood pressure goal:** "My blood pressure goal from my team: under [ ] / [ ]", the top number and
  then the bottom one.

Leave a box empty and the app shows your numbers with no verdict. Why the app has no goal of its own:

- The KDIGO guideline for adults with CKD who are not on dialysis suggests a top-number target of under
  120 *when blood pressure is measured the standard way at the clinic*. It says home or 24-hour readings
  should **add to** clinic readings, not replace them, and that applying the target to readings taken in a
  non-standard way can be hazardous ([KDIGO 2021][K21BP], recommendations 1.2 and 3.1.1, practice point
  3.1.1). So ask your team which number to use for your home readings.
- On hemodialysis, weight gains between sessions above 3.5 % of body weight are linked to death
  ([Cabrera 2015][DG28a]). Your unit sets a limit that fits you; the app does not guess it
  ([Fluid](../eat/fluid.md)).

## What the app shows

When you change the date, the card clears while that day's weights and readings load.
If it cannot load them, press **Try again**.

- **Today** shows the day's weights and readings. When you have set an alarm, a line says how your weight
  changed and names the two weights it compared. When you have set a goal, a line shows your last 7 days'
  average against it. With fewer than 3 readings in those 7 days the app shows the average and says
  there are too few to compare ([design note 10][NOTE10]).
- **"In days" alarm:** the app compares your latest weight with the latest weight of the same kind (a
  morning weight with a morning weight) from that many days to twice that many days earlier. **"Between
  sessions" alarm:** it compares your latest weight with your last weight after a session in the 7 days
  before it; without one, with the dry weight in Profile; without either, it asks you to add a weight after
  a session. The weight is over the alarm only when the gain is **more** than your number
  ([design note 10][NOTE10]).
- **"At or above" the goal:** a goal of "under 130/80" means a top number of 130 is not under it, so an
  average of 130 counts as at or above ([design note 10][NOTE10]).
- **Trends** has a weight chart and a blood pressure chart. On hemodialysis the weight chart also shows the
  dry weight from your Profile as a dashed line, and weights after dialysis have their own marker. The
  blood pressure chart shows the top and bottom numbers as two lines and your goal as dashed lines. Each
  chart has a table under it with every value, so you never need to read the chart.
- **Profile** can show "Latest in your log" under **Weight** (not on dialysis, where Profile holds your dry
  weight) and "In your log" under **Weight 6 months ago**, each with **Use this**. Using one only fills the
  box: nothing changes until you press **Save profile**. Losing more than 5 % in 6 months is a sign of
  malnutrition risk, so that second box matters for your targets ([design note 05][NOTE05], from the GLIM
  criteria; [Eating enough](../eat/eating-enough.md)).
- **Visit prep** (**Trends → Get ready for a visit**) adds your latest weight and the change over six
  months, on hemodialysis the gains between your last sessions, your blood pressure averages for the last
  7 and 30 days, how many readings were at or above your goal, and any reading the handbook points to, with
  its date ([design note 10][NOTE10]; [Reports for your care team](reports-for-your-team.md)).

## When the app points to Get help now

The app never explains a number. It does one thing: when a number is past a limit, it quotes this
handbook's own words and links to [Get help now](../get-help-now.md).

- **A weight over your alarm:** the app quotes the line "weight gain above the alarm number your team gave
  you", which the page lists under **Call your care team today**.
- **A reading with a top number of 180 or more, or a bottom number of 120 or more:** the app shows a red
  block at the top of Today. It quotes the **Call 911 now** line first: a reading of 180/120 or higher
  **with** a sudden severe headache, trouble breathing, sudden severe pain in the chest, belly or back,
  numbness or weakness, a sudden change in vision or problems talking
  ([MedlinePlus][MEDLINE-BPM]; [NHLBI][NHLBI-BPS]). Without those signs, the page says to rest for 5 minutes
  and measure again, and to call your care team today if it is still that high ([NHLBI][NHLBI-BPS]).
  NHLBI does not say whether "180/120" means either number, so the app is careful and points to the page
  when either one is that high. The sheet shows the same block before you save, so you can check that you
  did not mistype.

## From a phone shortcut {#from-a-phone-shortcut}

If you have an iPhone, a **Shortcut** can send your latest weight and your latest blood pressure from the Health app
to your own server each morning, without opening the app and without an export. It is off until your admin turns
it on. If **Settings → Account → Your data → Phone shortcuts** says "Your admin has not turned this on", ask them
([Configuration](../self-hosting/configuration.md); [design note 12][NOTE12]).

**What the token can do.** You make a **token** in **Settings → Account → Your data → Phone shortcuts**: a name, such as "Morning
weight", and when it ends (30 days, 90 days or 1 year). It is shown **once**, with **Copy token** and the address to
send to (this server's address followed by `/push/v1/body`). The token can only **add** weights and blood pressure
readings to your own log. It cannot read your log, change or delete anything, or open any other part of the app.
Treat it like a password: never post it or send it by email.

- A reading from a source with "Watch" in its name is **not saved** (a watch or ring that estimates blood pressure
  without a cuff is not a good source for this log, see
  [Which device](#which-device)). A weight from a watch is saved.
- Only weights and blood pressure are accepted. Nothing else from the Health app is sent or kept.
- Sending the same reading twice, or importing your Health export after the Shortcut has sent it, adds nothing.
  A reading you typed yourself is never counted as the same.
- The app marks each row it received this way, for example "from a shortcut (Morning weight)", on Today and in the
  tables under the Trends charts. Edit one and it becomes yours.

### The phone must reach the server

The Shortcut sends from your phone, so the phone must be able to reach your server: on your home network, or
through the VPN you use to reach it. A server on a private network cannot be reached from mobile data without
one, and the Shortcut will then fail until you are home again ([Install the app](install.md)).

### Make the "latest weight" shortcut

The steps below are for the Shortcuts app on iOS. **Action names and the order of the choices can differ between
iOS versions**, so look for the action that does the same thing. Apple's guide to Shortcuts describes each action
([Apple Shortcuts User Guide][APPLE-SHORTCUTS]).

!!! note "Written from Apple's guide, not yet tried on every iPhone"
    These steps have not been checked on a real iPhone yet (the review log has the check that is still to do). If a step
    does not match your phone, stop, and ask whoever runs your server. Nothing
    breaks: until the token is pasted in, nothing is sent.

1. In **Settings → Account → Your data → Phone shortcuts** make a token and **Copy token**. Keep the page open: you need the
   address too.
2. In the Shortcuts app, tap **+** to make a new shortcut and name it, for example "Send weight".
3. Add **Find Health Samples**. Set **Type** to Weight, **Sort by** Start Date, **Order** Latest First and
   **Limit** to on, with a limit of 1.
4. Add **Get Details of Health Samples** and choose **Value**. Add it three more times for **Unit**, **Start Date**
   and **Source**.
5. Add **Format Date**. Choose the **Start Date**, set the **Date Format** to **ISO 8601** and turn on **Include
   Time**. The result looks like `2026-10-22T07:15:00-04:00`: it must end with the zone (`-04:00`, or `Z`).
6. Add **Dictionary** and give it one key, `weights`, of type **List**. In the list add one **Dictionary** with
   four keys:
   `at` (Text) is the formatted date; `value` (Number) is the Value; `unit` (Text) is the Unit; and
   `source` (Text) is the Source. The unit must be exactly `kg` or `lb`. If your Shortcut shows another word, type
   the unit yourself as Text.
7. Add **Get Contents of URL**. For the URL paste the address from Settings. Open **Show More** and set **Method** to
   **POST**. Under **Headers** add the key `Authorization` with the text `Bearer ` followed by your token (the word
   Bearer, a space, then the token). Set **Request Body** to **JSON** and give it the Dictionary from step 6.
8. Add **Show Result** to see the answer the first time. It is only counts, for example `added` 1 weight, so it
   never shows your numbers back.
9. Run the shortcut once. Open **Today**: the weight is there, marked "from a shortcut".

### Make the "latest blood pressure" shortcut

Make a second shortcut the same way, because a blood pressure reading is two numbers.

1. **Find Health Samples** with **Type** Blood Pressure Systolic (Latest First, limit 1), then **Get Details of
   Health Samples** for its **Value**, **Start Date** and **Source**. Do the same with **Type** Blood Pressure
   Diastolic and get its **Value**. Look at the two Start Dates the first time: they should be the same
   measurement. If your phone shows blood pressure as one item, use its systolic and diastolic values.
2. **Format Date** as in step 5 above.
3. **Dictionary** with the key `readings` (a List) holding one Dictionary with four keys: `at` (Text, the formatted
   date), `systolic` (Number), `diastolic` (Number) and `source` (Text). Whole numbers only.
4. **Get Contents of URL** exactly as in step 7 above.

You can also put both in one shortcut: a Dictionary with a `weights` list and a `readings` list. Send only what you
have.

### Send it every morning

In the Shortcuts app open **Automation**, tap **+**, choose **Time of Day**, set the time and **Daily**, then
choose **Run Shortcut** and pick yours. Choose **Run Immediately** if your iOS offers it, so that the phone does not
ask each time. Whether an automation runs without asking depends on your iOS version.

### If the shortcut shows an error

- **401, "A valid device token is required".** The token is wrong, has ended or was revoked, or your admin has not
  turned phone shortcuts on. Check **Settings → Account → Your data → Phone shortcuts**; make a new token if you need one.
- **400, with a place such as `weights.0.at`.** The server names the field it did not accept: a time without its
  zone, a unit that is not `kg` or `lb`, or a number outside what the log accepts. Nothing from that request is kept.
- **429.** The token has sent more than 60 requests in an hour. Wait and try again.
- **It cannot connect.** The phone cannot reach the server (see above).

### The QR code next to the token

When the server has an `https://` address, the page also shows a **QR code** with the new token. It is for the project's
iPhone app, which sends new weights and readings from Health by itself. The app is not in the App Store yet, and a Shortcut
does not need the code. Point the iPhone Camera at it and tap the link: the app asks "Pair with" and your server's name
before it saves anything. Keep the code private, like the token, and do not photograph it.

### If the phone is lost or the shortcut was shared

Open **Settings → Account → Your data → Phone shortcuts** on another device and **Revoke** the token. The shortcut stops
working at once. Then, if you think someone else sent rows, press **Delete what it sent**: it names how many weights and
readings it will remove, and removes only what that token sent. Your own entries stay. Changing your password also ends
every token.

### The app does not watch these readings

Nothing here sends you an alert. A reading that was sent by a shortcut is checked the same way as one you typed, but
the check happens when you open the app: if a reading is past a limit, the red block appears on **Today** the next
time you open it. If you feel unwell, or a number worries you, do not wait for the app: follow
[Get help now](../get-help-now.md) and call your care team.

## What the app does not do

- It does not say what causes a number, whether a number is good or bad for you, or what medicine to take,
  skip or change. That is for your care team.
- It does not give you an alarm or a goal. It has no alarm for a low blood pressure.
- It never changes your Profile weight by itself. That weight sets your calorie and protein targets, and on
  dialysis it is your dry weight, which your unit sets and a scale reading is not ([First setup](first-setup.md)).
- It does not watch the readings a shortcut sends: nothing alerts you, and a reading past a limit shows its
  warning when you open the app ([From a phone shortcut](#from-a-phone-shortcut)).
- It does not send your weights or readings to an AI provider or to the Ask assistant ([Privacy and your
  data](privacy.md); [architecture contract][ARCH]).
- Your weights and readings are in your data export, and they are deleted with your account
  ([Privacy and your data](privacy.md)).

## If something goes wrong

- **I mistyped a number.** Press **Edit** on the entry, or **Delete** it, and add it again.
- **The alarm says "Not enough weights to compare yet".** For "in days" the app needs an earlier weight of
  the same kind from the right number of days before. A morning weight is not compared with an evening one.
- **The alarm says "Add a weight after a session to compare".** On hemodialysis, add the weight you take
  after a session, or set your dry weight in Profile.
- **The pounds and kilograms look swapped.** Check the unit in **Settings → Weight and blood pressure**.
- **I do not see "between sessions".** It is offered only when your Profile says **Hemodialysis**.
- **A weight or reading I did not type is in the list.** The row says where it came from: "from a shortcut (name)",
  "from the Health app" or "from a file". For a shortcut, see
  [If the phone is lost or the shortcut was shared](#if-the-phone-is-lost-or-the-shortcut-was-shared).

## Ask your care team

1. "What weight gain is too much for me, and over how many days (or between sessions)?"
2. "What is my blood pressure goal, and does it apply to readings I take at home?"
3. "Which blood pressure monitor should I use, and can you check my cuff against yours?"
4. "How often should I weigh myself and measure my blood pressure, and which readings should I bring?"

## Get help now if…

The warning signs, including the ones for a very high blood pressure reading, are on
[Get help now](../get-help-now.md). If you are not sure whether to call, call your care team.

## Related pages

- [Reports for your care team](reports-for-your-team.md) · [First setup](first-setup.md) · [Privacy and your data](privacy.md)
- [Get help now](../get-help-now.md) · [Fluid](../eat/fluid.md) · [In-center hemodialysis](../stages/hemodialysis-in-centre.md)

## Sources

- [Design note 10][NOTE10]: how the alarm, the goal, the averages and the warning lines work;
  [project architecture contract][ARCH]. [Design note 12][NOTE12]: the phone shortcut, its token and what the
  server accepts.
- [Apple Shortcuts User Guide][APPLE-SHORTCUTS]: the Shortcuts actions for Health samples, dates, dictionaries,
  web requests and automations.
- [MedlinePlus: measuring blood pressure][MEDLINE-BPM] and [NHLBI: high blood pressure symptoms][NHLBI-BPS]:
  how to measure at home, and the 180/120 warning lines.
- [KDIGO 2021 blood pressure in CKD guideline][K21BP]: recommendations 1.2 and 3.1.1.
- [2025 AHA/ACC high blood pressure guideline][AHA25BP]; [AHA: cuffless blood pressure devices][AHA-CUFFLESS]:
  validated devices; cuffless devices.
- [Cabrera 2015][DG28a]: weight gain between sessions; [NKF: hemodialysis access][NKF-HDaccess]: no cuff on
  the access arm; [design note 05][NOTE05]: the weight-loss rule.
