---
title: Install the app on your phone
description: "Add the app to your Home Screen on iPhone, Android or a computer, why it needs HTTPS, and what works without a connection."
slug: install
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-07
fact_checked: 2026-10-05
sources: [NOTE02, NOTE38, NOTE39, WEBKIT-26, CHROME-PWA, MDN-SECURE]
---

# Install the app on your phone

The app is a web page that you can add to the Home Screen of an iPhone, iPad or Android phone, or
install on a computer. It then opens in its own window with its own icon, like an app from a store,
but nothing comes from a store: it is your own server's page, kept on your device
([design note 02][NOTE02]).

## Before you start

- [ ] Ask your admin for **the address you will keep using**, for example
      `https://food.home.example.net`.
- [ ] Check that the address starts with `https://` and that your browser shows no warning.
- [ ] Install from that exact address. The phone treats another name, another port, or `http`
      instead of `https` as a **different app with empty storage**, so you would have to install it
      again ([design note 02][NOTE02]).

## Why HTTPS matters

Phones only let a web app work offline when the page comes over HTTPS (or from the same computer).
The browser calls this a "secure context", and the offline part of the app (its service worker)
cannot start without one ([MDN][MDN-SECURE]).

| Feature | `https://` address your phone trusts | plain `http://` on your Wi-Fi |
|---|---|---|
| Icon on the Home Screen, opens full screen | yes | yes on iPhone (iOS 26 and later); a shortcut elsewhere |
| Opens without a connection to the server | yes | no |
| Food you log without a connection waits and syncs later | yes | yes, but the app cannot be reopened until the server is back |
| "Update ready" message after an upgrade | yes | no |
| Live barcode scanning with the camera | yes | no (a photo of the barcode or typing the digits still works) |
| **Install app** button on Android and in desktop Chrome | yes | no |
| Your password travels encrypted | yes | **no**: anyone on the Wi-Fi can read it |

Plain HTTP is fine for a first look on a network you trust. For daily use, ask your admin to set up
HTTPS ([HTTPS for phones](../self-hosting/https.md)).

## iPhone and iPad

1. Open the app's address in **Safari**. (Chrome, Edge and Firefox on iOS 16.4 and later can do this
   too.)
2. Sign in if the app asks you to.
3. Tap **Share** (the square with an arrow), then **Add to Home Screen**.
4. Keep **Open as Web App** switched on. On iOS 26 every site added this way opens as a web app
   unless you switch it off ([WebKit][WEBKIT-26]).
5. Check the name ("Kidney Log") and tap **Add**.
6. Open the app from its new icon. It may ask you to sign in once more: an app on the Home Screen keeps
   its own sign-in, separate from Safari's ([design note 02][NOTE02]).

On your third visit in the browser, the app shows these steps once as a tip at the top of the page.
Tap × to close it; it does not come back, and the steps stay in **Settings → This device**.

These steps are written for iOS and iPadOS 26 and 27; installing works from iOS 17. If a button looks
different on your phone, tell your admin so this page can be corrected.

## Android

1. Open the app's address in **Chrome**.
2. Sign in if the app asks you to.
3. Tap **Install app** on the banner, or open the **⋮** menu and choose **Install app** (on some
   phones **Add to Home screen**) ([Chrome Help][CHROME-PWA]).
4. Open the app from its new icon.

In the app, **Settings → This device → Install this app** also shows an **Install app** button when Chrome
allows it.

## Computer

- **Chrome or Edge:** click the install icon at the right end of the address bar, or open the menu and
  choose **Cast, save, and share → Install page as app** ([Chrome Help][CHROME-PWA]).
- **Safari on a Mac (macOS 14 or later):** **File → Add to Dock**.
- **Firefox:** use it in a normal tab.

## What works without a connection

Once the app has been opened online from an `https://` address, it keeps working when the phone cannot
reach your server (no signal, the server is down, a flight) ([design note 02][NOTE02]):

| Works offline | Needs your server |
|---|---|
| The app opens from its icon. | Signing in for the first time on this device. |
| **Add**, **Quick add**, **Mark eaten**, and **editing or deleting** an entry: they wait on the phone with a "waiting to sync" badge and are sent once, in order, when the server is back. | Changing your profile, targets or settings: the app says the change needs a connection. |
| **Today**, the last two weeks and the coming week, from the copy saved the last time you looked (the screen says so). | Barcode lookups, USDA search, AI and new meal suggestions. |
| Search among the foods this phone has seen (the builtin list is checked once a day while connected and downloaded again only when it changed). | |
| The **Treating a low** card. | |
| Handbook pages (**Learn**) you have already opened on this phone. | Handbook pages you have not opened on this phone yet: they say so. Print the ones you need away from home, such as the [Wallet cards](../reference/wallet-card.md). |

A badge at the top shows how many entries and changes are waiting ("Offline · 2 to sync"; on a phone just
the number). Tap it to open **Settings → This device**, where you can **Retry** or **Discard** an entry the
server refused when it arrived (for example because the food was deleted meanwhile)
([Logging food](logging.md#offline)).

A change to an entry that is already on your server is never allowed to overwrite another device's change
without asking. If the same entry was changed somewhere else while your phone was offline, your change is held
back, the badge says "to review", and **Settings → This device** shows what your server has next to your
change, with **Keep the saved one** and **Use mine** ([Logging food](logging.md#offline)).

Your log lives on the server, not on the phone. Removing the icon or getting a new phone does not
delete it. Only entries still "waiting to sync" live on the phone alone, and only for the person who
logged them; the app asks before you sign out if any are left, because signing out removes everything
the app kept on the phone ([design note 02][NOTE02]).

!!! danger "Lows come first, even offline"
    If your glucose is low and the app will not load, treat the low anyway and log it later. Nothing
    in the app has to work before you treat a low ([Treating a low](../t1d/treating-a-low.md)).

## The iPhone app, with no server

There is also a Kidney Health app for iPhone, for now only for testers through TestFlight. It runs the whole app on the
phone and needs no server ([design note 38][NOTE38]):

- It starts empty. Everything you log stays on the iPhone.
- After each change it saves a copy of your data that you can find in the **Files** app, under **On My iPhone**. If you ever
  need your data back, open the app's **Settings → Your data → Import from a file** and choose that copy.
- **Add → Scan a barcode** opens the iPhone's own scanner. Point it at a food barcode and the app looks the code up.
  Tap **Cancel** to type the digits instead.
- Touch and hold the app's icon on the Home Screen for shortcuts: **Scan a barcode**, **Add food** and **Quick add**.
- **Settings → Reminders** gives you a notification at a time you choose, to log a meal, plan tomorrow or log your weight
  ([Reminders in the iPhone app](settings-and-keys.md#reminders-iphone)). They stay on the iPhone.
- Export your data now and then and keep the file somewhere safe. **Settings → Your data → Export my data (.zip)** makes the same
  `.zip` a server gives: `export.json`, spreadsheet (CSV) files and a README. The share sheet opens so you choose where it goes.
  The file is made on the iPhone and nothing is sent.
- **Settings → This device → Apple Health and server** holds the phone's own settings:
  - **Apple Health**: allow weight and blood pressure, and new readings are added to the log on the phone when the app is open.
    Readings from a watch are not added.
  - **Keys and services**: look up more foods with your own free USDA key, or barcodes on Open Food Facts. Each is off until you
    turn it on, and sends only the words you type or the barcode you scan.
  - **Your own AI key**, also in Keys and services: no server is needed. See [Your own AI key](#your-own-ai-key-on-the-iphone).
  - **Lock with Face ID or passcode**: off unless you turn it on.
  - Connecting your own server is optional. With a token made for the iPhone app, the app sends each new row you add to your
    server when it can be reached ([Connect the Kidney Health iPhone app](weight-and-blood-pressure.md#connect-the-kidney-health-iphone-app)).
    You then see it in the web app and on your other devices, and your care team can use it.
  - A token made for **the iPhone app, both ways** does that too. It also keeps the phone and your server in step both ways,
    and lets the app use your server's food services and AI ([design note 39][NOTE39]). The server's address screen says which
    kind of token is saved. An older token keeps working for sending what you add.
- **Settings → This device → Your server** shows how many rows wait to be sent, when the app last synced, and any row your
  server refused. **Sync now** tries at once. With an older token, changes or deletions you make on the phone after a row was
  sent stay on the phone. The app keeps note of them and says how many there are.

### With a token both ways

- **Sync both ways.** What you or your care team add or change on your server comes to the phone, and what you change or delete
  on the phone goes to your server. This covers food you logged, your own foods, saved meals and recipes, lab results, symptoms,
  weight and blood pressure. The app syncs while it is open: after a change, when you open it, every 15 minutes, and when you tap
  **Sync now**.
- **Your profile, targets and settings come from your server.** Your care team may set your targets there, so the phone shows
  your server's. This covers your profile, your targets, your units, your weight and blood pressure goals, and your food
  preferences. You can still change them on the phone, but only while your server can be reached: the change goes straight to
  your server. Without a connection the app says "This needs a connection to your server." The theme, the camera, the phone's
  own keys and the lock stay on the phone.
- **"1 to review"** at the top of the screen means a row or your profile needs your choice. Tap it to see the choices. On Today,
  such an entry says **needs review**.
- **The first sync** of a phone that already has data compares each row with your server. If only one side changed a row, that
  side is kept. If both changed it, the row is listed in **Settings → This device → Your server** under **Your iPhone and your
  server differ**: choose **Keep your server's** or **Keep this iPhone's**. A row you deleted on the phone but that is still on
  your server is listed too: choose **Delete it there** or **Keep it**. Until you choose, the app shows your server's copy and
  keeps the phone's. If your profile and targets differ, one card shows both: **Keep your server's** or **Keep this iPhone's**.
  A saved meal with the same name on both becomes one. Food preferences you set only on the phone are sent to your server.
- **Changed in two places.** If you change an entry on the phone and it was also changed somewhere else, the app never picks one
  for you. The row is listed with both copies side by side: **Keep the saved one** keeps your server's, **Use mine** sends yours.
  If you change something on the phone that was deleted elsewhere, the app says your change was dropped.
- **A different server or account.** If you pair the app with another server, or with another person's token, the app asks
  before anything moves: **Send this iPhone's data** there, **Replace this iPhone's data** with the server's (a copy is saved in
  the Files app first), or **Cancel**.
- **Food look-ups** go through your server while it can be reached, with the key your server uses for you. A food it finds is
  saved on the phone at once, so it works offline. When your server cannot be reached, the phone uses its own keys from Keys and
  services, if you added them, and otherwise the food list it already has. No key ever moves between the phone and the server.
- **AI features** use your server's AI when your server can be reached and offers the feature, with the choices and consent you
  made there. Otherwise they use your own AI key if you added one, then the iPhone's own AI where it has one, and otherwise the
  app works without AI, as before.
  **Settings → AI features** lists which AI each feature uses.
- **Use only this iPhone's AI** in Settings → AI features keeps everything you write away from any AI but the iPhone's own,
  your own key included.
- An answer from your server is shown as it is. If it says to treat a low or to get help now, the app does not ask another AI.
- A lab report goes only to an AI on your own network or on the iPhone, never to a company's AI.
- **Ask**, the AI assistant, works on the phone when your server's admin has turned it on. It uses your server's AI, so it needs
  a connection and a phone that syncs both ways. On the phone it always asks before it saves: tap **Save** on the card and the
  entry is saved on the phone, then sent to your server. Talking to Ask is not on the phone. When Ask cannot be used, the Ask
  tab says why and what to do.
- **Plate photo (AI)** on the Add screen names the foods in a photo of your meal. It uses your server's AI, then your own AI key
  if you turned on photos for it, then the iPhone's own AI on iOS 27. Your server decides which of its AIs may see photos. When
  no AI can read a photo, the Add screen says so under the AI buttons. You tick each food, then choose **Eaten** or **Planned**:
  Planned puts the foods in the plan for the day you are looking at.
- **A recipe from a web page**, **Open in Instacart** and **Send to** your own list app work on the phone when your server has
  them turned on. Your server reads the page and sends the list, with its own keys, so they need a connection. The recipe's
  ingredients are matched with the foods on your phone. The shopping list comes from the plan on your server, so plans you made
  on the phone show there once they are sent. You set up your list app in the web app, not on the phone. Pasting ingredients
  works offline. Without a token both ways, these buttons do not appear.
- On an iPhone with Apple Intelligence, **Describe a meal**, **AI meal ideas**, **AI recipes** and reading the text of a lab
  report PDF can use Apple's AI on the phone. On iOS 27 it can also read a photo of your plate or of a label. Turn it on in
  **Settings → AI features**. Nothing you write, read or photograph leaves the iPhone, and the questions and answers are not kept.
  Apple's AI on the phone is small, so its meal ideas and recipes choose from fewer of your foods. The app checks every answer the
  same way your server would, and you check each line before anything is saved. The AI never gives insulin or medicine doses.
  AI order, AI swaps and AI day plans need your server. On other iPhones these buttons do not appear, and everything else works.

### Your own AI key on the iPhone

You can use AI features with a key of your own from an AI company, with no server at all.

1. Open **Settings → This device → Apple Health and server → Keys and services**.
2. Under **Your own AI key**, choose **OpenAI**, **OpenRouter** or **Nous Portal**.
3. Enter the model's name as the company writes it, and paste your key. Tap **Save the key**. The key is kept on this iPhone only
   and is not shown again. **Test the key** sends one short fixed question to check it.
4. In the app, turn on **Settings → AI features → Use AI features**. The first time you use it, the app shows where it will send
   your request and asks you to agree.

What it does:

- **Describe a meal**, **AI meal ideas** and **AI recipes** use your own key. If you have a server, your server's AI is used
  first, and your own key only when your server cannot be reached or does not offer it. Meal ideas and recipes send the foods the
  app's rules chose, your targets and today's totals, as your server would. They never send your name or date of birth.
- **Photos of a meal or a label** go to your own key only if you turn on **Also send meal and label photos to this AI**. It is off
  at first.
- **Lab reports, and anything with your name or date of birth, are never sent to it.** If you type your name in a meal
  description, the app does not send it.
- **Ask** still needs your server, because it reads your log there and checks every answer.
- The app checks every answer the same way your server would. A low, an emergency or a question about a dose gets the app's own
  card, and the AI is not asked. The AI never gives insulin or medicine doses.
- Nothing about your questions or the answers is kept on the phone. The company receives what is sent, under its own terms.
- **Remove the key** deletes it from the phone. **Use only this iPhone's AI** in Settings → AI features also stops the app from
  using your key.

## Updates

When the admin upgrades the server, the app notices the next time you open it and shows
**Update ready** with a **Reload** button. Tap it. Nothing you logged is lost.

## If something goes wrong

- **The icon is blank or shows a letter.** The phone could not fetch the icon. Open the address in the
  browser once, then remove the icon and add it again.
- **The app shows an old version.** Close it fully, open it again and tap **Reload** when
  "Update ready" appears.
- **"My data is gone."** Check the address. The same app at a different address starts empty. Your log
  is still on the server; open the original address.
- **It does not open without a connection.** Offline use needs HTTPS. Open the app once while
  connected, then check **Settings → This device**: *Works offline* says "Yes: the app opens without a
  connection" when it can.
- **The app keeps asking me to sign in.** The installed app has its own sign-in. Sign in once inside
  the app.

## Related pages

- [First setup](first-setup.md) · [Logging food](logging.md) · [Privacy and your data](privacy.md)
- For admins: [HTTPS for phones](../self-hosting/https.md)

## Sources

- [Design note 02: home-screen install, offline and HTTPS][NOTE02].
- [Design note 38: the iPhone app without a server][NOTE38].
- [Design note 39: the iPhone app with a server, both ways][NOTE39].
- [WebKit: Safari 26 and Home Screen web apps][WEBKIT-26].
- [Chrome Help: use web apps][CHROME-PWA].
- [MDN: secure contexts][MDN-SECURE].
