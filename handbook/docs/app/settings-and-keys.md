---
title: Settings and keys
description: "The Settings menu, shared and private API keys, daily limits, and settings that the server locks."
slug: settings-and-keys
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-14
fact_checked: 2026-10-05
sources: [NOTE07, NOTE03, NOTE04, NOTE06, NOTE02, FDC-API, NOTE17, NOTE18, NOTE19, NOTE25]
---

# Settings and keys

**Settings** (the gear icon at the top, or **Profile → Open Settings**) holds everything that is not about your body or your targets; those stay in **Profile**.
Some features need a **key**: a password-like code from an outside service such as USDA or OpenAI. Keys
can be shared by your admin or added by you ([design note 07][NOTE07]).

## What is in Settings

| Section | What you find there |
|---|---|
| **Account** | your name, user name, **Change password**, **Two-step sign-in**, **Passkeys**, **Signed-in devices**, **Your data** (export, import, **Phone shortcuts** for an iPhone Shortcut that sends your weight and blood pressure: [Weight and blood pressure](weight-and-blood-pressure.md#from-a-phone-shortcut); delete account), your recent sign-in activity, **Sign out** |
| **Care team** | family, a caregiver or a dietitian on your server who can look at your log (**Viewer**) or also plan your meals and use your shopping list (**Care helper**); invites for you; the Care teams you are on ([Care team](#sharing)) |
| **Connected devices** (when your admin sets it up) | **Connect Withings** so the server fetches your weight, blood pressure and pulse; **Sync now**; **Disconnect** ([Weight and blood pressure](weight-and-blood-pressure.md#from-withings)) |
| **Preferences** | theme (match device, light, dark), the day your week starts on, **Units for lab results** (US or SI: the unit offered first) |
| **Meal guidance** | on or off, carbohydrate tolerance, low-treatment amount, foods to leave out, your "Not for me" foods ([Meal guidance](guidance.md)) |
| **Food data** | your own USDA key, the shared key's status and today's remaining lookups, **Send barcodes I scan to Open Food Facts** ([Barcodes and label photos](barcode-and-photo.md)) |
| **AI ideas** | opt in, provider, your own AI provider and key, what you agreed to send, AI activity ([Optional AI](ai.md)) |
| **Assistant access** (when your admin turns it on) | personal tokens for a chat assistant you connect: make one, copy it once, see when it was last used, revoke it ([below](#assistant-access)) |
| **This device** | installed or not, "Offline ready", storage used, entries waiting to sync with **Sync now**, **Retry** and **Discard**, **Clear offline data on this device** ([Install the app](install.md)) |
| **Admin** (admins only) | a button that opens **Server administration** (below) |
| **About & privacy** | what is stored, who can see it, disclaimers, **Learn** (this handbook), data sources and licences ([Privacy and your data](privacy.md)) |

**Bigger text.** The app has no text size setting of its own. It follows the text size you choose in your browser's settings,
and zoom works too. At twice the normal size, the screens still fit without scrolling sideways.

## Server administration (admins only)

Admins see a **shield button** next to the gear. It opens **Server administration**, a page of its own
with **People** (accounts, invites, reset links), **Server settings** (sign-in and registration, food
data, AI and the other server-wide switches), **Shared keys**, **Usage**, the **Activity log**, **About
this server** and **AI providers**. Members never see the button or the page, and the server refuses
every admin request from a member anyway. There is no page where an admin can read anyone else's log,
foods or keys.

**AI providers** is where an admin adds the shared AI and chooses which one each feature uses. Under that choice, **How well each AI
is doing** shows, for every feature that is on, how its latest calls went and whether the model passed the live evaluation. It shows
counts only, never what anyone asked. A caution there means most recent calls gave no usable result, or the model has no passing
evaluation report for the current prompts ([setup](../self-hosting/configuration.md#ai)).

## Shared keys and your own keys

| | Shared key (from your admin) | Your own key |
|---|---|---|
| Who pays or signs up | the admin | you |
| Daily limit in the app | yes: by default 200 USDA lookups and 30 AI calls per person per day | no app limit (the service's own limit still applies) |
| Who can read it back in the app | nobody, once saved | nobody, once saved, the admin included |
| If it stops working | ask the admin | replace it; the app **never** switches you to the shared key without asking |

The app uses **your own key first**. If you have none, it uses the shared key while your admin allows it
and today's limit is not used up. Otherwise the feature says what to do: "Add your own key in Settings →
Food data", or "Today's shared lookups are used up" ([design note 07][NOTE07]).

For AI, a failing own key is never replaced by the shared provider, because that would send your data
somewhere you did not agree to ([design note 04][NOTE04]).

## Add your own USDA key

A USDA FoodData Central key is free. It allows 1,000 requests an hour; USDA's public `DEMO_KEY` allows
only 30 an hour and 50 a day ([USDA API guide][FDC-API]).

1. Sign up at the USDA "Get an API key" page (linked from the [API guide][FDC-API]) with your email.
2. Copy the key from the email.
3. In the app: **Settings → Food data → USDA key → Replace** (or **Add**).
4. Paste the key, tap **Test**, then **Save**. The app asks for your password again if you have not
   entered it in the last 10 minutes.

## How keys are shown

Keys are **write-only**: after you save one, the app never shows it again, to you or anyone else.

- **Set**: "Set · ends in 9xQz · updated 3 Oct", with **Replace** and **Remove**.
- **Replacing**: an empty box (never pre-filled), **Test** and **Save**.
- **Set by the server**: the admin fixed it in the server's configuration. You see no buttons and
  cannot change it.
- **"Please enter your key again"**: the server can no longer read the stored key (for example after a
  restore without its encryption key). Add it again.

Keys are stored encrypted on the server. They are not included in your data export or in log files.

## Settings the server locks

Each setting comes from the first of these that has a value ([design note 07][NOTE07]):

1. **The server's configuration** (an environment variable). Shown as "Set by the server" and read-only.
2. **Your own choice**, for settings you are allowed to change.
3. **The admin's choice** for everyone on this server.
4. **The app's default.**

So if a switch is grayed out with "Set by the server", only the person who runs the server can change it
([Configuration](../self-hosting/configuration.md)).

## Password and devices

- **Change password**: needs your current password; at least 15 characters (unless your admin chose
  another minimum). Your other devices are signed out.
- **Signed-in devices**: lists your sessions. **Sign out** one you do not recognize, or
  **Sign out everywhere else**.
- Sensitive actions (changing a password or key, turning two-step sign-in on or off, adding or removing a passkey, making an assistant token,
  exporting, deleting your account) ask for your password again if you entered it more than 10 minutes ago. If you have a
  passkey, **Use a passkey instead** answers with your fingerprint, face or PIN.

## Two-step sign-in

Two-step sign-in means a password alone is not enough to get into your account. After your password, the app asks
for a 6-digit code from an **authenticator app** on your phone, such as Aegis, 2FAS, Google Authenticator,
Microsoft Authenticator, 1Password or Bitwarden. The code changes every 30 seconds and works only once. Someone who
learns your password still cannot sign in. It is off until you turn it on ([design note 17][NOTE17]).

To turn it on:

1. **Settings → Account → Two-step sign-in → Turn on two-step sign-in**. The app asks for your password again.
2. In your authenticator app, add an account and scan the QR code. On the phone you are using, tap
   **Open it in your authenticator app** instead. If neither works, type the key shown under the QR code.
3. Type the 6-digit code the app shows, and tap **Turn on**.
4. The app shows **ten recovery codes**, once. Tap **Download**, or copy them into a password manager, and keep them
   away from your phone. Each one works once instead of a code, if you lose your phone.

Your other devices are signed out, and you sign in on them again with your password and a code. Phone shortcut and
assistant tokens keep working.

- **New phone:** turn two-step sign-in off and on again, and scan the new QR code with the new phone.
- **Lost phone:** sign in with a recovery code, then turn it off and on again with your new phone.
- **Running low on codes:** **Make new recovery codes**. The old ones stop working.
- **No phone and no recovery codes:** ask your admin. They can remove two-step sign-in from your account, and you
  then sign in with your password alone.
- A password reset link from your admin sets a new password but does not sign you in: you still need a code.
- **Admins:** your server can ask every admin to use two-step sign-in. Until you turn it on, Server administration shows only a
  note that sends you here.

## Passkeys

A passkey lets you sign in with your fingerprint, your face or your phone's PIN, with no password and no code to type. The
passkey stays on your phone or computer, and it only works on your own server's address, so nobody can guess it or trick you
into typing it on a fake page ([design note 18][NOTE18]). Your password keeps working too.

To add one:

1. **Settings → Account → Passkeys**. Give it a name if you like, such as "My phone", and tap **Add a passkey**. The app may ask
   for your password again.
2. Your phone or computer asks to save a passkey. Confirm with your fingerprint, face or PIN.

To sign in with it, tap **Sign in with a passkey** under the sign-in form and confirm on your device. On many phones and
computers you can also tap the user name box: your passkey is listed there, and picking it signs you in.

- Add one on each phone or computer you use. A passkey saved to iCloud Keychain or Google Password Manager also works on your
  other devices signed in to that account; the list then says "synced".
- **Lost or stolen device:** sign in with your password and **Remove** its passkey. If you cannot, ask your admin to remove your
  passkeys.
- Passkeys need your server's name, like `kidney.example.org`. If you open the app by a number address, Settings says so; ask
  your admin.

## Care team {#sharing}

Your **Care team** is family, a caregiver or a dietitian who has their own account on your server. You choose what each person
can do, and you can change it or stop it at any time ([design notes 19][NOTE19] and [25][NOTE25]). Your admin turns the Care
team on first; until then, Settings says so. **Profile → Open Care team** takes you there too.

There are two roles:

- A **Viewer** can look at the parts you tick: your food log, lab results, weight and blood pressure, symptoms. They never change
  anything.
- A **Care helper** can also plan your meals and use your shopping list. They see your food log so they can plan. They never
  change what you ate, your targets, your profile, your labs, your weight, your symptoms or your settings.

To add someone:

1. **Settings → Care team → Add someone**. Type their user name on this server, pick **Viewer** or **Care helper**, tick what
   they can see and pick how long: until you stop it, a week, 30 days, 90 days or a year. Tap **Send invite**. The app may ask
   for your password again.
2. They see your invite in their own **Settings → Care team** and tap **Accept** or **Decline**. Nothing changes until they do.
   Your invite waits 7 days under **Waiting for an answer**, where you can cancel it.
3. If you do not know their user name, open **Make a link instead**, make a link and send it to them. It works once, for 7 days.
   Send it only to them: whoever opens it first can accept it.

They never see your saved meals, your recipes, your food preferences, your AI settings, your keys or your sign-in activity. They
see the weight in your profile only if you shared weight and blood pressure.

- **Your Care team** lists each person, their role, until when, when they last looked, and what a Care helper changed in your
  plan that day. Change the role in the list. **Remove** ends it at once.
- Food a Care helper planned for you says **Added by** and their name on your Today. You can change or remove it like any
  planned food.
- Your activity shows invites, answers, role changes, and once a day that a Care helper changed your plan.
- A share with an end date stops by itself on that day.

**When you are on someone's Care team**, they are under **Care teams you are on**. **Open** shows their summary page, **Trends**
their charts; **Leave** ends it. Their weight chart uses their dry weight, never yours. If a part cannot load, tap **Retry**.

**Planning meals for someone (Care helper).** Tap **Plan meals**, or choose their name under **Planning for** at the top of the
Plan tab. A banner says whose plan you are changing. **Back to my own plan** takes you back; your own plan is never mixed with
theirs.

- Pick a day to see what they ate and what is planned. Change an amount and tap **Save**, or **Remove** a planned food.
- **Add food** searches the foods they can use.
- **Plan several days** makes a plan that follows their targets. Look it over, then tap **Add to their plan**. Their saved meals
  are not used.
- **Clear planned days** takes planned food off. Eaten food and a planned low treatment always stay. Only the person changes a
  planned low treatment, and nothing in the app ever warns against treating a low.
- Their **shopping list** works like yours: tick items, **Copy list** or **Share list**. Ticks stay on your device, apart from
  your own list.
- Planning for someone needs a connection to your server. Changes for them never wait on your phone.

## Assistant access

When your admin turns assistant access on, **Settings → Outside AI apps** makes personal **tokens** for a chat
assistant you connect. A token lets that assistant read your own food log and targets; it cannot change
anything, and it never sees anyone else's data, unless you tick **Can also save food and recipes** when you make
it. Then the assistant can also add food to your log and save recipes as saved meals (it still cannot edit or
delete anything). The box is off by default, and a token's choice cannot be changed later: make a new token. The
list says **Read only**, **Read and save**, **Read and tastes** or **Read, save and tastes** for each token, and your
activity lists what an assistant saved.

A second box, **Also let it remember tastes (likes and dislikes)**, is separate and also off by default. Ticked, the
assistant can remember that you like a food or a kind of food, want it less often or do not want it, or forget one of
these, after it asks you. It cannot do anything else with that box, and it never changes **Treating a low**. Each
change is listed in your activity, and a food it set shows in **Settings → Meal guidance → Your food preferences** as
"from your assistant", where you can remove or change it.

- Give the token a name (the app or device it is for) and choose when it expires: 30 days, 90 days or 1 year.
- The token is shown **once**, with **Copy token**. Paste it into the assistant straight away: it is not shown
  again. If it is lost, **Revoke** it and make a new one.
- You can have 5 at a time. **Revoke** ends one at once. Changing your password, a password reset, or your
  account being disabled revokes all of them, and so does an admin who uses **Revoke tokens** on your
  account (your activity says so). That ends your phone shortcut tokens too. If your admin changes how the
  server signs people in, every token ends and you make new ones.
- If an assistant retries a save, it is not saved twice: the app answers the repeat with what was saved the first time.
- Treat a token like a password: never send it by text message or email.

## What to do

- [ ] Check **Food data**: do you have shared lookups, or do you need your own USDA key?
- [ ] Look at **Signed-in devices** after you get a new phone, and sign out the old one.
- [ ] Turn on **Two-step sign-in**, and keep the recovery codes somewhere safe.
- [ ] Add a **passkey** on the phone you use most, so signing in is a fingerprint or a glance.
- [ ] Never send a key by text message or email to anyone; paste it only into the app.

## If something goes wrong

- **"Key rejected" after Test.** Copy it again, without spaces, and check you used the right service.
- **"Today's shared lookups are used up."** Wait until tomorrow, use the builtin foods and Quick add, or
  add your own key.
- **"Please enter your password again."** This is normal for sensitive actions; enter it and the app
  carries on.
- **"That code is not right."** The codes depend on the phone's clock. Set the phone's date and time to set
  automatically, wait for a new code, and try again. Or type a recovery code.

## Related pages

- [Privacy and your data](privacy.md) · [Optional AI](ai.md) · [Logging food](logging.md)
- For admins: [Users and keys](../self-hosting/users-and-keys.md) · [Configuration](../self-hosting/configuration.md)

## Sources

- [Design note 07: accounts, settings and secrets][NOTE07], sections 4.11, 4.12 and 4.17.
- [Design note 02][NOTE02] (This device); [design note 03][NOTE03] (barcode settings); [design note 04][NOTE04] (AI keys);
  [design note 06][NOTE06] (guidance settings).
- [Design note 19][NOTE19]: read-only sharing. [Design note 25][NOTE25]: the Care team.
- [USDA FoodData Central API guide][FDC-API]: free keys and rate limits.
