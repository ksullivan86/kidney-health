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
sources: [NOTE02, WEBKIT-26, CHROME-PWA, MDN-SECURE]
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
| **Add**, **Quick add** and **Mark eaten**: entries wait on the phone with a "waiting to sync" badge and are sent once, in order, when the server is back. | Editing or deleting an entry that is already on the server, and changing your profile or settings: the app says the change needs a connection. |
| **Today**, the last two weeks and the coming week, from the copy saved the last time you looked (the screen says so). | Barcode lookups, USDA search, AI and new meal suggestions. |
| Search among the foods this phone has seen (the builtin list is checked once a day while connected and downloaded again only when it changed). | This handbook (**Learn**): print the pages you need away from home, such as the [Wallet cards](../reference/wallet-card.md). |
| The **Treating a low** card. | |

A badge at the top shows how many entries are waiting ("Offline · 2 to sync"; on a phone just the
number). Tap it to open **Settings → This device**, where you can **Retry** or **Discard** an entry the
server refused when it arrived (for example because the food was deleted meanwhile)
([Logging food](logging.md#offline)).

Your log lives on the server, not on the phone. Removing the icon or getting a new phone does not
delete it. Only entries still "waiting to sync" live on the phone alone, and only for the person who
logged them; the app asks before you sign out if any are left, because signing out removes everything
the app kept on the phone ([design note 02][NOTE02]).

!!! danger "Lows come first, even offline"
    If your glucose is low and the app will not load, treat the low anyway and log it later. Nothing
    in the app has to work before you treat a low ([Treating a low](../t1d/treating-a-low.md)).

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
  connected, then check **Settings → This device → Install this app**: it says "Offline ready" when it can open
  without a connection.
- **The app keeps asking me to sign in.** The installed app has its own sign-in. Sign in once inside
  the app.

## Related pages

- [First setup](first-setup.md) · [Logging food](logging.md) · [Privacy and your data](privacy.md)
- For admins: [HTTPS for phones](../self-hosting/https.md)

## Sources

- [Design note 02: home-screen install, offline and HTTPS][NOTE02].
- [WebKit: Safari 26 and Home Screen web apps][WEBKIT-26].
- [Chrome Help: use web apps][CHROME-PWA].
- [MDN: secure contexts][MDN-SECURE].
