# Install Kidney Diet Log on your phone

Kidney Diet Log is a web app that you can add to the home screen of an iPhone, iPad or Android
phone, or install on a computer. Once installed it opens in its own window with its own icon,
like an app from an app store, but nothing comes from an app store: it is your own server's web
page, kept on the device.

Before you start, ask whoever runs the server for **the address you will keep using**, for
example `https://food.home.example.net`. The installed app belongs to that exact address. If
the address changes later (another name, another port, `http` instead of `https`), the device
treats it as a different app with its own, empty storage, and you install it again.

## HTTPS or plain HTTP?

The app can be installed from a plain `http://192.168.x.y:8000` address, but only as a
shortcut. Most of what makes it feel like an app needs a secure (HTTPS) address that the phone
trusts:

| Feature | `https://` address the phone trusts | plain `http://` on your network |
|---|---|---|
| Icon on the home screen, opens full screen | Yes | Yes (iOS 26 and later; elsewhere a shortcut) |
| Opens without a connection to the server (offline) | Yes | No |
| "Update ready" message after the server is upgraded | Yes | No |
| Live barcode scanning with the camera (when available) | Yes | No (taking a photo still works) |
| "Install app" button on Android and desktop Chrome | Yes | No |
| Your password travels encrypted | Yes | **No**: anyone on the Wi-Fi can read it |

Plain HTTP is fine for a first look on a network you trust. For everyday use, the person who
runs the server sets up HTTPS by following [docs/https.md](https.md), which lists four ways
(your own domain, Tailscale, a private certificate authority, or Kubernetes), each ending with
the same check on the phone.

## iPhone and iPad

1. Open the app's address in **Safari** (Chrome, Edge and Firefox on iOS 16.4 and later can do
   this too).
2. Sign in if the app asks you to.
3. Tap **Share** (the square with an arrow), then **Add to Home Screen**.
4. Keep **Open as Web App** switched on, check the name ("Kidney Log"), then tap **Add**.
5. Open the app from its new icon. The first time, it may ask you to sign in again: an app on
   the home screen keeps its own sign-in, separate from Safari's.

Supported: installable on iOS and iPadOS 17 and later; tested on 26 and 27.

## Android

1. Open the app's address in **Chrome**.
2. Sign in if the app asks you to.
3. Tap **Install app** on the banner, or open the **⋮** menu and choose **Install app** (on some
   phones: **Add to Home screen**). In the app, **Settings → This device** (the gear at the top)
   also offers an **Install app** button when Chrome allows it.
4. Open the app from its new icon.

Firefox for Android can also add the app to the home screen from its menu.

## Computer (Windows, macOS, Linux, ChromeOS)

* **Chrome or Edge:** click the install icon at the right end of the address bar, or open the
  menu and choose **Install Kidney Diet Log** (Edge: **Apps → Install this site as an app**).
* **Safari on a Mac (macOS 14 or later):** **File → Add to Dock**.
* **Firefox:** use it in a normal tab; Firefox on Windows can pin it as a web app.

## Keeping the app up to date

When the server is upgraded, the app notices the new version the next time you open it and
shows **Update ready** with a **Reload** button. Tap it to switch to the new version. Nothing
you logged is lost: your log lives on the server, not in the app on the device.

## Troubleshooting

* **The home-screen icon is blank or shows a letter.** The phone could not fetch the icon when
  you installed. Make sure you can open the app's address, then remove the icon and add it
  again. (The icons are deliberately reachable without signing in.)
* **The app shows an old version.** Close it completely and open it again, then tap **Reload**
  when "Update ready" appears. If the server's administrator has switched the installable app
  off (`PWA_ENABLED=false`), opening the app once removes the old version.
* **The app does not open without a connection.** Offline use needs HTTPS (see the table above).
  Open the app once while connected, then check **Settings → This device**: "Works offline" says
  "Yes" when the app can open without a connection.
* **The camera shows a black picture.** Use the photo button instead and take a picture of the
  barcode or label.
* **"My data is gone."** Check the address: the same app at a different address starts empty.
  Your log is on the server, so opening the original address shows it again.
* **The app keeps asking me to sign in.** An installed app has its own sign-in, separate from the
  browser's; sign in once inside the app.

The app shows what it can do on this device under **Settings → This device** (the gear at the
top, or **Profile → Open Settings**): installed or in the browser, offline ready, storage used, the
connection (HTTPS or not) and the app version, with **Clear offline data on this device**, which
removes the app's offline copy (your log stays on the server).
