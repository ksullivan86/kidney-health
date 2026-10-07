# 02 · Installable app on iOS, Android and desktop (PWA)

| | |
|---|---|
| Status | Decision note, proposed for v0.3. No application code has been changed. |
| Date researched | 2026-10-05 (iOS/iPadOS 27 and Safari 27.0 shipped 2026-09-17) |
| Scope | Home Screen install, manifest and icons, service worker and offline, Web Push, camera and barcode, safe areas, HTTPS for homelab users, Android and desktop install |
| Out of scope | Barcode data sources and food APIs, the auth and multi-user model, container hardening, AI guidance. Sibling notes in `docs/dev/research/` cover those. This note only records how they touch the PWA. |
| Re-verify | Every major iOS release (September) and every Safari x.4 release (March). See [How to re-verify](#how-to-re-verify). |

---

## 1. Context

**The ask.** The owner wants the app "saveable on the home screen of iOS so it runs like a local
app", without the App Store. That is an iOS **Home Screen web app**: a web app manifest, icons and a
service worker. It must also work on Android and desktop. Two related asks change the PWA design:
barcode or photo lookup (camera), and meal or hypo reminders (push).

**What exists today (v0.2).**

* `app/static/index.html` already has `viewport-fit=cover`, `color-scheme`, a light and a dark
  `theme-color`, and an inline SVG `data:` favicon. `app.js` keeps both `theme-color` tags in
  step with the theme toggle (`app.js` line ~1872).
* `style.css` already pads the root and the bottom tab bar with `env(safe-area-inset-*)` and uses
  `100dvh`.
* The app has **no manifest, no service worker, no PNG icons and no IndexedDB**. Views use hash
  routes (`#today`, `#add`, `#plan`, `#trends`, `#profile`). The only browser storage is
  `localStorage`, used for the theme and the shopping-list ticks.
* The server is FastAPI + `StaticFiles(html=True)` mounted at `/`, plain HTTP on port 8000.
  Optional auth is HTTP Basic (`APP_PASSWORD`), and `/healthz` is exempt. There is no gzip.
* `scripts/build_preview.py` inlines everything into one HTML file with `window.KDL_PREVIEW = true`
  and a `MockApi` that already re-implements food search and `evaluateWarnings` client-side. That
  parity code can also serve offline mode.
* `data/foods.json` is 227 KB raw and 33 KB gzipped (395 foods), small enough to keep on the device.

**Constraints.** No build step and no CDN, so any third-party front-end code is vendored. The app is
public and open source (PolyForm Noncommercial), self-hosted by homelab users on rootless
Podman/Docker or Kubernetes. It handles health data, so it must be private by default and make no
outbound calls unless a feature is opted into. v0.3 adds multiple users, so a phone or iPad may be
shared.

---

## 2. Findings

### F1. What a Home Screen web app is on iOS in 2026

* Since **iOS/iPadOS 26**, *every* site added to the Home Screen opens as a web app by default.
  The user can untick "Open as Web App" to get a plain bookmark instead. A manifest is no longer
  *required* for standalone mode, but WebKit says it "continues to work as before"
  ([WebKit, Safari 26 beta](https://webkit.org/blog/16993/news-from-wwdc25-web-technology-coming-this-fall-in-safari-26-beta/)).
* Since **iOS 16.4**, Chrome, Edge and Firefox on iOS can also offer "Add to Home Screen". The
  same release added Web Push, Badging and manifest `id` for Home Screen apps
  ([WebKit, Safari 16.4](https://webkit.org/blog/13966/webkit-features-in-safari-16-4/)).
* **Safari 27.0** (2026-09-17) adds no manifest, push, camera or barcode features. The only
  relevant addition is the Service Worker **static routing API** (`InstallEvent.addRoutes`)
  ([WebKit, Safari 27.0](https://webkit.org/blog/18325/webkit-features-for-safari-27-0/),
  [WWDC26 beta notes](https://webkit.org/blog/17967/news-from-wwdc26-webkit-in-safari-27-beta/)).
* **EU:** Apple reversed its plan to drop Home Screen web apps in the EU (iOS 17.4, March 2024).
  They still work there and still run on WebKit
  ([The Register, 2024-03-02](https://www.theregister.com/2024/03/02/apple_reverses_pwa_decision/), secondary source).
* A Home Screen web app **cannot**: run in the background (no Background Sync, Periodic Sync or
  Background Fetch), schedule local notifications while offline, read Apple Health or CGM data,
  use Web Bluetooth or NFC, show an install prompt, or use a native barcode API on iOS. It **can**:
  run full-screen with its own icon, work offline through a service worker, use the camera, receive
  Web Push (16.4+), set an icon badge, use the share sheet, and keep its storage. See F5 to F7.

### F2. Manifest members Safari honours

Source: MDN browser-compat-data **8.1.4** (built 2026-10-01), `manifests.webapp.*`.

| Member | iOS Safari | Chrome Android | Notes for this app |
|---|---|---|---|
| `name`, `short_name` | 11.3 | 39 | One of them is required by Chrome |
| `start_url` | 11.3 | 39 | Required by Chrome |
| `scope` | 11.3 | 53 | Links outside the scope open in SFSafariViewController on iOS ([WWDC23](https://developer.apple.com/videos/play/wwdc2023/10120/)) |
| `display: standalone` | 11.3 | 39 | `fullscreen` and `minimal-ui` are **not** supported on iOS. `display_override` is not supported. |
| `id` | 16.4 | 96 | Identity used for push, badging and Focus sync. Defaults to `start_url`, so set it explicitly ([W3C manifest](https://w3c.github.io/manifest/)) |
| `icons` | 15.4 | 39 | iOS uses them **only when there is no `apple-touch-icon`**, and only entries with `purpose` absent or `any` ([WebKit 15.4](https://webkit.org/blog/12445/new-webkit-features-in-safari-15-4/)) |
| `theme_color` | 15 | 46 | From iOS 26 the `<meta name="theme-color">` is only used for installed web apps (BCD note) |
| `background_color` | **no** | 46 | Ignored on iOS, used for the Android splash |
| `orientation`, `shortcuts`, `share_target`, `description` | **no** | yes | `shortcuts` works on Chrome Android and macOS Safari 17.4+ |

### F3. Icons

* **Precedence on iOS:** `apple-touch-icon` overrides manifest icons. iOS ignores `maskable`,
  `monochrome` and SVG icons. The icon must be an **opaque** square PNG: iOS rounds the corners
  itself and fills transparent areas. With no `<link>`, iOS also looks for `/apple-touch-icon.png`
  at the site root
  ([Apple, Configuring Web Applications, archived 2016](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/ConfiguringWebApplications/ConfiguringWebApplications.html)).
  One 180×180 file (iPhone @3x) is enough. iOS scales it for iPad sizes (152 and 167).
* **Chrome install criteria** need icons of **192 and 512** px, plus `name`/`short_name`,
  `start_url`, `display` and HTTPS. A service worker with a `fetch` handler has **not** been
  required since Chrome 108 (Android) and 112 (desktop)
  ([web.dev install criteria](https://web.dev/articles/install-criteria),
  [Chrome blog](https://developer.chrome.com/blog/update-install-criteria)).
* **Maskable safe zone:** the important content must sit inside a circle of radius **40%** of the
  icon size ([W3C manifest](https://w3c.github.io/manifest/)). The current glyph reaches at most
  about 10/32 (31%) from the centre, so a full-bleed green square with the glyph at its current
  scale is already a valid maskable icon.
* **Rendering check:** Playwright 1.63.0's Chromium was used here to render the app's SVG to
  180/192/512 PNGs (scratch prototype, 2.4 to 7.4 KB each). Opaque renders come out as PNG colour
  type 2 (RGB). With `omit_background=True` they come out as type 6 (RGBA). Pillow 12.3 **cannot
  read SVG**.

### F4. Apple-specific meta tags in 2026

| Tag | Still needed? | Evidence |
|---|---|---|
| `apple-mobile-web-app-capable` | **No.** The manifest's `display: standalone` has been enough since iOS 11.3, and on 26+ every Home Screen site is a web app anyway. Chrome logs a deprecation warning for it. | WebKit Safari 26 post, BCD |
| `apple-mobile-web-app-status-bar-style` | **No.** Since iOS 15, `theme-color` colours the status bar. `black-translucent` is legacy. | BCD `theme_color` 15; [firt.dev iOS PWA notes](https://firt.dev/notes/pwa-ios/) (last updated 2023) |
| `apple-mobile-web-app-title` | **Optional but useful.** It sets the Home Screen label deterministically (otherwise `<title>` or the manifest name is used). | Apple archived doc |
| `apple-touch-startup-image` (splash) | **Optional.** It is still the *only* way to get a custom iOS launch image, because `background_color` is ignored. It needs one PNG per device size, orientation and theme, roughly 20 to 40 files. Without it iOS shows a blank screen until first paint, which is short when the shell comes from the service worker cache. | BCD `background_color` = no; nothing in the WebKit 26 or 27 notes |

### F5. Service workers, storage and offline on iOS

* Service workers, Cache Storage and IndexedDB have been supported since iOS 11.3. Navigation
  preload since 15.4. `navigator.storage.estimate()` since 17 and `persist()` since 15.2. All of
  these except IndexedDB need a **secure context** (HTTPS, or `localhost`, which a phone never is).
* **Quota** (Safari 17+): a browser app's origin may use up to **60% of disk** and all origins up to
  80%. A Home Screen web app gets the **same quota as in Safari**. Eviction is least-recently-used,
  and origins in *persistent* mode are excluded. `persist()` is granted by heuristics such as
  "opened as a Home Screen Web App"
  ([WebKit, Updates to Storage Policy](https://webkit.org/blog/14403/updates-to-storage-policy/)).
* **7-day cap:** ITP deletes script-writable storage after 7 days without interaction **in
  Safari**. Home Screen web apps keep their own day counter, which only advances when the app is
  used, so an installed app's data is not deleted for being idle (same WebKit source). **Unsynced
  writes in a plain Safari tab are at risk**, so the app should encourage installing.
* **Separate storage:** a Home Screen app has its own cookies and storage, separate from Safari.
  macOS copies cookies when a web app is added to the Dock. Nothing says iOS does, so plan for an
  in-app login after install. `localStorage` is never copied
  ([WWDC23 "What's new in web apps"](https://developer.apple.com/videos/play/wwdc2023/10120/)).
* **No Background Sync on iOS:** `SyncManager`, `PeriodicSyncManager` and `BackgroundFetchManager`
  are all *false* for Safari iOS in BCD 8.1.4. Queued writes must be replayed when the app opens
  or resumes, or when a request succeeds. iOS also freezes or kills backgrounded web apps, so the
  app resumes with stale state: "today" may now be yesterday.
* `navigator.onLine` is unreliable on a LAN: it says "online" whenever Wi-Fi is up, even when the
  homelab is unreachable. Away from home without a VPN, requests to a private IP can **hang**
  rather than fail. Use fetch timeouts and treat failures as "offline".
* `Clear-Site-Data: "cache", "storage"` is supported on iOS 17+. Useful on logout.

### F6. Web Push (reminders)

* Available on iOS/iPadOS **16.4+, only for Home Screen web apps** whose manifest `display` is
  `standalone`. Permission must be requested **from a user gesture**. It is the standard
  Push API + VAPID ([WebKit](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/)).
* Apple's server rules ([Apple docs](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers)):
  * The server must be able to reach `https://*.push.apple.com`.
  * The JWT `sub` must be a `mailto:` or `https:` URL, and `exp` must be at most 1 day ahead.
  * The JWT should not be refreshed more than once an hour.
  * The `TTL` header is required (messages are kept for at most 30 days). `Urgency` and `Topic`
    are optional.
  * The payload limit is **4 KB**.
  * **There is no invisible push.** If the service worker does not show a notification, Safari
    revokes the permission.
* **Declarative Web Push** (iOS 18.4+): the payload `{"web_push": 8030, "notification": {"title",
  "body", "navigate", "app_badge"…}}` is shown by the OS without running the service worker.
  `window.pushManager` exists without a service worker. Old browsers fall back to the imperative
  `push` handler ([WebKit](https://webkit.org/blog/16535/meet-declarative-web-push/)). Chrome and
  Firefox have not shipped it yet (BCD).
* BCD lists `notificationclick` as **unsupported on iOS**, so rely on the declarative `navigate`
  URL for tap-through and verify on a device. Badging (`navigator.setAppBadge`) has been available
  since 16.4 and is granted together with notification permission.
* **Fit for this app:** good for *convenience* nudges ("log lunch?", "dialysis day: fluid so far
  0.6 L"). It is **not acceptable for hypoglycaemia safety alerts**. Delivery is best-effort, Focus
  can silence it, it needs the homelab server online and reachable to Apple, and a CGM app already
  does this job properly. Push also breaks the "no outbound calls" default, so it must be opt-in.

### F7. Camera and barcode on iOS

* `getUserMedia` works in iOS Safari since 11 and in Home Screen apps since 13.4. It needs a
  secure context. Open WebKit bugs:
  * [282327](https://bugs.webkit.org/show_bug.cgi?id=282327): in iOS 18.x PWAs the camera starts
    and then closes with no error. Still NEW.
  * [273938](https://bugs.webkit.org/show_bug.cgi?id=273938): standalone camera on some 17.x
    devices; reported fixed in the 18 betas.

  So live scanning must always have a fallback.
* **`BarcodeDetector` is not available on iOS or macOS Safari** except behind a feature flag (17+),
  and on iOS even the flag has been broken since 18.
  * [WebKit bug 281848](https://bugs.webkit.org/show_bug.cgi?id=281848) is still NEW, last
    activity July 2026.
  * Neither the Safari 27 notes nor
    [caniuse](https://caniuse.com/mdn-api_barcodedetector) list it.
  * Chrome Android 83+ has it natively. Desktop Chrome has it only on macOS and ChromeOS.
    Firefox has none.
* **Polyfill.** `barcode-detector` **3.2.2** (MIT, 2026-08-16) is a spec-compatible ponyfill over
  ZXing-C++ compiled to WASM (`zxing-wasm`, MIT; ZXing-C++ is Apache-2.0). Details:
  * It pins **`zxing-wasm` 3.1.3**. The matching reader WASM is 1,093,289 bytes (about 459 KB
    gzipped), SHA-256 `2ebda08a93eea3efcd8399cda6b276e6a0b1de4fec60b4d8988a047de4c6d1ba`.
    The newer zxing-wasm 3.1.4 WASM is a different file, so do not mix them.
  * The IIFE `dist/iife/ponyfill.js` is 44 KB (15 KB gzipped) and exposes
    `window.BarcodeDetectionAPI`.
  * By default it fetches the WASM from **jsDelivr**. Self-host it with
    `prepareZXingModule({ overrides: { locateFile } })`.
  * A CSP must allow `'wasm-unsafe-eval'`, which iOS supports since 16.
* **Photo fallback:** `<input type="file" accept="image/*" capture="environment">` opens the
  rear camera directly on iOS 10+ and Chrome Android 25+. Desktop ignores `capture`.
  **It does not need HTTPS.** Without `capture`, iOS offers Camera *or* Photo Library, which is
  better for "photo of a label I took earlier". Re-encode via a canvas to JPEG before upload. That
  also **strips EXIF/GPS**.
* `ImageCapture` (iOS 18.4+) is not needed.

### F8. Standalone-mode UX and CSS

* `env(safe-area-inset-*)` works on iOS 11+, the `display-mode` media query on 12.2+, `dvh` units
  on 15.4+, and `overscroll-behavior` on 16+ (partial). The app already uses the first and third.
* A standalone app has **no back button, no reload and no URL bar**. The app must provide
  navigation (it has tabs), a way to refresh data, and an "update available, reload" control. Links
  outside `scope` open in an in-app Safari sheet.
* JS detection: `matchMedia('(display-mode: standalone)').matches || navigator.standalone === true`
  (`navigator.standalone` is non-standard and iOS-only).
* Inputs need a font-size of at least 16 px, or iOS zooms on focus. The app's base size is
  already 16 px.

### F9. What breaks over plain HTTP on a LAN

| Feature | `http://192.168.x.y:8000` | Why |
|---|---|---|
| Add to Home Screen | Works. It opens standalone on iOS 26+ | No secure-context requirement |
| Service worker, Cache Storage, offline shell | **Broken** (`navigator.serviceWorker` and `caches` are undefined) | `[SecureContext]` |
| Live camera scanning (`getUserMedia`) | **Broken** (`navigator.mediaDevices` is undefined) | Secure context |
| Photo via `<input capture>` | Works | No requirement |
| Web Push, notifications, badging | **Broken** | Secure context + Home Screen |
| `navigator.storage.persist()/estimate()` | **Broken** | Secure context |
| `crypto.randomUUID()`, `crypto.subtle`, `navigator.share`, Clipboard write | **Broken** | Secure context. `crypto.getRandomValues()` still works |
| Chrome "Install app" | **Broken** (shortcut only) | HTTPS required |
| Session cookies with `Secure` | Not stored | So logins would travel and live in clear text |
| HTTP Basic / login passwords | Sent in clear text | Anyone on the Wi-Fi can read them |

Conclusion: plain HTTP is a **degraded bookmark mode**. It is fine for a first try on a trusted
LAN and nothing more.

### F10. Getting HTTPS that iOS trusts (homelab)

* **Apple's certificate rules** apply to every TLS server certificate, private CAs included
  ([Apple 103769](https://support.apple.com/en-us/103769)): the DNS name must be in the **SAN**,
  the EKU must include `serverAuth`, the signature must be SHA-2, RSA keys must be at least 2048
  bits, and validity must be **≤ 825 days**.
* **Manually installed root profiles** need two steps. First install the profile. Then go to
  *Settings → General → About → Certificate Trust Settings → Enable full trust for root
  certificates*. Profiles from Configurator or MDM are trusted automatically
  ([Apple 102390](https://support.apple.com/en-us/102390)).
* **Let's Encrypt lifetimes are shrinking**
  ([LE, 2025-12-02](https://letsencrypt.org/2025/12/02/from-90-to-45/)):
  * opt-in `tlsserver` profile issues 45-day certificates from 2026-05-13;
  * default becomes 64 days on 2027-02-10;
  * default becomes 45 days on 2028-02-16.

  LE recommends ARI or renewing at two-thirds of the lifetime. **Manual certificates are no longer
  viable. Use an ACME client that renews automatically.**
* **Caddy 2.11.x** (Go module v2.11.7 tagged 2026-10-03; Docker image `caddy:2.11.6`; Apache-2.0):
  * automatic ACME with renewal;
  * the **DNS-01** challenge (no open ports, works for LAN-only names) needs a build with a DNS
    module, e.g. `caddy-dns/cloudflare` **v0.2.4** via `xcaddy`;
  * an ACME `profile` option exists but is marked experimental;
  * `tls internal` runs a local CA: **root 3600 days, intermediate 7 days, leaf 12 hours**. The
    root lives in Caddy's data dir under `pki/authorities/local/` (`/data/caddy/...` in the
    official image)
    ([automatic HTTPS](https://caddyserver.com/docs/automatic-https),
    [tls directive](https://caddyserver.com/docs/caddyfile/directives/tls),
    [global options](https://caddyserver.com/docs/caddyfile/options)).
* **Tailscale** (stable **v1.102.5**):
  * `tailscale serve --bg localhost:8000` publishes `https://<machine>.<tailnet>.ts.net` to the
    tailnet with a Let's Encrypt certificate obtained by DNS-01. It adds `Tailscale-User-Login` and
    related identity headers;
  * **Funnel** exposes it to the public internet and does not add identity headers;
  * machine names are published in Certificate Transparency logs. Tailscale's own warning is "Do
    not enable the HTTPS feature if any of your machine names contain sensitive information";
  * the phone needs the Tailscale app running, and it takes the iOS VPN slot
    ([HTTPS](https://tailscale.com/kb/1153/enabling-https),
    [Serve](https://tailscale.com/kb/1312/serve),
    [CLI](https://tailscale.com/kb/1242/tailscale-serve)).
* **step-ca 0.30.2** (Helm chart `step-certificates` 1.30.1) is a full private ACME CA, an
  alternative to Caddy's internal CA.
* **cert-manager v1.21.2** on Kubernetes: an ACME `ClusterIssuer` with a DNS-01 solver, or a `CA`
  issuer for a private root. `deploy/k8s/ingress.yaml` already has the annotation stub.
* **Certificate Transparency privacy:** every publicly trusted certificate is logged publicly.
  A hostname like `kidney.smith-family.net` **publishes a medical condition**. Use a wildcard
  (`*.home.example.net`) or a neutral name (`food.`, `log.`).

### F11. Android and desktop

* **Chrome / Edge (Android, Windows, macOS, Linux, ChromeOS):** install needs HTTPS and a manifest
  with name, 192/512 icons, `start_url` and `display`, plus a light engagement heuristic.
  Chromium fires `beforeinstallprompt`, so an in-app "Install" button is possible there (and only
  there). Android uses `background_color`, `theme_color` and the icon for its splash.
* **Firefox Android** supports manifest display and icons (BCD) and can add or install to the home
  screen. **Firefox 143** (2025-09-16) added "web apps" (Taskbar Tabs) on Windows only
  ([release notes](https://www.firefox.com/en-US/firefox/143.0/releasenotes/)).
* **Safari macOS 14+:** *File → Add to Dock*. Supports `display`, `id`, `scope`, `icons`,
  `theme_color` and `shortcuts` (17.4).
* **Private CA on Android:** Chrome trusts user-installed CAs for browsing, but installing a WebAPK
  from a private-CA origin is unverified and may fall back to a plain shortcut. Prefer a public
  certificate (DNS-01 or Tailscale) for Android users.

### F12. Interaction with authentication

* By default a manifest is fetched **without credentials**. Behind cookie auth or an auth proxy,
  use `<link rel="manifest" crossorigin="use-credentials">`, or make the manifest and icons public
  ([W3C manifest](https://w3c.github.io/manifest/): credentials follow the CORS settings
  attribute).
* HTTP Basic auth (`APP_PASSWORD`) is a poor fit for a standalone app:
  * there is no logout;
  * credentials can only be entered through a browser prompt;
  * the separate Home Screen storage means the user re-enters them in the app.

  The v0.3 multi-user work should move to **cookie sessions with an in-app login page**. Keep
  `APP_PASSWORD` only as a legacy single-user switch.
* Forward-auth proxies (Authelia and similar) redirect expired sessions to another origin. A
  service worker that serves a cached shell for every navigation hides that redirect. The service
  worker needs a bypass, and the app needs a "Sign in again" path (see R4).

---

## 3. Options compared

### 3.1 How to get "an app" on iPhone

| Option | Cost to users | Offline | Camera | Push | Maintenance | Verdict |
|---|---|---|---|---|---|---|
| **A. Home Screen web app (manifest + service worker)** | None. Share → Add to Home Screen | Yes (HTTPS) | Yes (HTTPS) | Yes (16.4+) | One codebase | **Chosen** |
| B. Manifest only, no service worker | None | No | Yes | No (push needs a service worker before 18.4) | Lowest | Too weak; it is A without the parts that matter |
| C. Native wrapper (Capacitor/Cordova) via App Store or TestFlight | Apple Developer Program per publisher; review; TestFlight builds expire after 90 days | Yes | Native VisionKit scanner | APNs | Second codebase, Xcode, signing | Not for a self-hosted homelab project |
| D. Sideloading (AltStore, SideStore, EU Web Distribution) | Re-signing every 7 days, or EU-only plus a developer account | Yes | Native | Native | High | No |

### 3.2 Offline data strategy

| Option | Multi-user safe | Secure | Complexity | Verdict |
|---|---|---|---|---|
| Service worker caches `/api/*` GETs in Cache Storage (network-first) | Poor: one cache per origin, shared between users of a device; hard to purge per user | Personal data sits in Cache Storage; conflicts with `Cache-Control: no-store` | Low | Rejected |
| **App keeps per-user snapshots and an outbox in IndexedDB; service worker caches only the static shell** | Good: keys carry `user_id`, and logout deletes the database | Shell has no personal data; API stays `no-store` | Medium (~300 lines JS) | **Chosen** |
| No offline, shell only | n/a | Best | Lowest | Fallback if the outbox slips from v0.3 |

### 3.3 HTTPS for the documented setups

| Option | Device setup | Needs | Works off-LAN | Android install | CT exposure | Verdict |
|---|---|---|---|---|---|---|
| **Own domain + Caddy DNS-01 (LE)** | None | Domain (~$10/yr), DNS API token, Caddy built with a DNS module | Only via your VPN or reverse proxy | Full | Hostname, unless wildcard | **Recommended default** |
| **Tailscale Serve (`*.ts.net`)** | Tailscale app on each phone | Tailscale account | Yes | Full | Machine name | **Recommended "easiest"** |
| Caddy `tls internal` / step-ca + root profile on iPhone | Install the profile and enable full trust on every device | Nothing external | Via VPN | Possibly a shortcut only | None | **Supported, "air-gapped" tier** |
| cert-manager (K8s) DNS-01 or CA issuer | As the rows above | cert-manager v1.21.2 | as above | as above | as above | **Kubernetes tier** |
| Self-signed leaf, tap through the warning | Warning on every visit; browsers refuse to register a service worker from a page with a certificate error (Chromium documents this; verify Safari on a device) | Nothing | n/a | No | None | **Not supported** |
| Plain HTTP | None | Nothing | n/a | No | None | Degraded bookmark mode only (F9) |

### 3.4 Live barcode scanning

| Option | iOS | Size | Network | Verdict |
|---|---|---|---|---|
| Native `BarcodeDetector` only | **Does not work** | 0 | none | Use when present (Chrome Android) |
| **`barcode-detector` 3.2.2 ponyfill + vendored `zxing-wasm` 3.1.3 reader** | Works | 44 KB JS + 1.09 MB WASM, loaded only on first scan, then cached | none, self-hosted | **Chosen for live scan** |
| `@zxing/library` 0.23.0 (Apache-2.0, pure JS) | Works | Hundreds of KB of JS | none | Slower pure-JS decoder, in maintenance mode; fallback only |
| `html5-qrcode` 2.3.8 | Works | Large (bundles a ZXing JS port) | none | No release since 2023-04. No |
| `@undecaf/zbar-wasm` 0.11.0 | Works | A WASM module | none | LGPL-2.1+, last release 2024-05. No |
| Photo upload, decoded server-side (`zxing-cpp` 3.1.1, Apache-2.0, Python wheels) | Works, even over HTTP | 0 on the client | none | **Fallback.** Belongs to the barcode note |

### 3.5 Generating PNG icons from SVG without a runtime dependency

| Tool (dev-time only) | Licence | Fidelity | Install weight | Verdict |
|---|---|---|---|---|
| **Playwright 1.63.0 Chromium screenshot** | Apache-2.0 | Exact browser rendering | ~150 MB browser download, already in this repo's dev workflow (UI walkthroughs) | **Chosen** (prototype worked) |
| resvg CLI / `resvg_py` 0.5.0 | MPL-2.0 (resvg) | Very good | Small binary | Good alternative |
| CairoSVG 2.9.1 | LGPL-3.0-or-later | Good | Needs system cairo | No |
| `rsvg-convert` (librsvg) | LGPL-2.1+ | Good | apt package | OK for maintainers on Linux |
| Pillow 12.3 | MIT-CMU | Cannot read SVG; would need the shapes redrawn in Python | Small | No |

### 3.6 Reminders

| Option | Outbound from server | Reliability | Verdict |
|---|---|---|---|
| None (v0.3) | none | n/a | **v0.3** |
| **Web Push via `pywebpush` 2.5.0 (MPL-2.0) + `py-vapid` 1.9.4 (MPL-2.0)** | `*.push.apple.com`, `fcm.googleapis.com`, `updates.push.services.mozilla.com` | Best-effort | **v0.4, opt-in, off by default** |
| Point users to ntfy / Home Assistant / calendar reminders | their choice | theirs | Document as an alternative |

---

## 4. Recommendation

### R1. File layout (new or changed)

```
app/static/
  manifest.webmanifest              # static JSON, served as application/manifest+json
  apple-touch-icon.png              # 180x180 opaque RGB (root path is also auto-probed by iOS)
  icons/
    icon.svg                        # source: round badge on transparent (favicon, purpose any)
    icon-maskable.svg               # source: full-bleed #2e7d32 square + glyph (apple-touch + maskable)
    icon-192.png  icon-512.png      # purpose any (RGBA allowed)
    icon-maskable-192.png  icon-maskable-512.png   # purpose maskable (opaque RGB)
  sw.js                             # template; served by GET /sw.js with __VERSION__ substituted
  offline.js                        # IndexedDB snapshots + outbox + sync (plain script, no build)
  scan.js                           # camera/photo barcode UI; lazy-loads the vendor files below
  vendor/barcode-detector-3.2.2/ponyfill.iife.js + LICENSE
  vendor/zxing-wasm-3.1.3/zxing_reader.wasm + LICENSE + LICENSE.zxing-cpp (Apache-2.0)
  vendor/README.md                  # versions, upstream URLs, SHA-256 of every vendored file
app/pwa.py                          # GET /sw.js (versioned, no-cache), header helpers
scripts/build_icons.py              # Playwright render of icons/*.svg -> PNGs (dev only, PNGs committed)
requirements-tools.txt              # playwright==1.63.0 (NOT in requirements-dev.txt; CI doesn't need it)
tests/test_pwa.py                   # manifest, icons, sw.js, headers, offline idempotency
docs/install-on-your-phone.md       # end-user guide (iOS, Android, desktop, troubleshooting)
docs/https.md                       # homelab HTTPS guide (or a new section in docs/deployment.md)
```

### R2. `app/static/manifest.webmanifest`

```json
{
  "id": "/",
  "name": "Kidney Diet Log",
  "short_name": "Kidney Log",
  "description": "Self-hosted food log for a renal diet with type 1 diabetes.",
  "lang": "en",
  "dir": "ltr",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#f4f5f7",
  "theme_color": "#f4f5f7",
  "categories": ["health", "food", "medical"],
  "icons": [
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" },
    { "src": "/icons/icon-maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable" },
    { "src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" },
    { "src": "/icons/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any" }
  ],
  "shortcuts": [
    { "name": "Add food", "url": "/#add", "icons": [{ "src": "/icons/icon-192.png", "sizes": "192x192" }] },
    { "name": "Plan", "url": "/#plan", "icons": [{ "src": "/icons/icon-192.png", "sizes": "192x192" }] }
  ]
}
```

* `id` is pinned to `/` so a later change to `start_url` does not create a "new app".
* Do not put query strings in `start_url`.
* Keep the app at the root of its own hostname (already required).

### R3. `<head>` additions to `index.html`

```html
<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">
<link rel="icon" href="/icons/icon.svg" type="image/svg+xml">
<link rel="icon" href="/icons/icon-192.png" sizes="192x192" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="apple-mobile-web-app-title" content="Kidney Log">
<!-- keep the existing two theme-color metas (app.js already rewrites them on theme toggle) -->
<!-- deliberately omitted: apple-mobile-web-app-capable, mobile-web-app-capable,
     apple-mobile-web-app-status-bar-style, apple-touch-startup-image (see F4) -->
```

`build_preview.py` must not emit these tags, nor register a service worker (`PREVIEW`/`MOCK`
true). Its test should assert that.

### R4. Service worker: static shell only

* **Serving.** Serve it from `app/pwa.py` at `GET /sw.js`, registered **before** the static mount.
  * Read `app/static/sw.js` and replace `__VERSION__` with the first 12 hex digits of a SHA-256
    over every file in the shell list. Compute it once at startup.
  * Headers: `Content-Type: text/javascript; charset=utf-8`, `Cache-Control: no-cache`.
  * A new deploy then changes `sw.js` byte-for-byte, so update detection works with no build step.
* **Scope** is `/` (the default for `/sw.js`). Register only when
  `'serviceWorker' in navigator && isSecureContext && !MOCK`.
* **Strategy:**

| Request | Strategy |
|---|---|
| Navigations to the app itself (`/`, `/index.html`) | Cache-first from the versioned shell, so `index.html`, `app.js` and `style.css` always come from the same release. **Bypass** (straight to the network) when the URL carries `?reauth=1`, so an auth proxy can redirect to its login page. |
| Navigations to anything else (e.g. the same-origin patient handbook under `/learn/`, note 08 §4.10) | **Not intercepted.** Never answer them with the app shell. Caching handbook pages for offline reading can come later as a separate runtime cache. |
| `/style.css`, `/app.js`, `/offline.js`, `/scan.js`, `/manifest.webmanifest`, `/icons/*`, `/apple-touch-icon.png` | Precached at install, cache-first |
| `/vendor/**` | Runtime cache-first in `kdl-vendor-<version>`, filled only on first scan |
| `/api/**`, `/healthz`, any non-GET, cross-origin | **Not intercepted**; the network decides. Personal data never enters Cache Storage. |

* **Update UX.**
  1. `registration.waiting` → toast "Update ready" with a **Reload** button.
  2. The button posts `SKIP_WAITING`; the app then reloads on `controllerchange`.
  3. Call `registration.update()` at start and on `visibilitychange`, at most once an hour.

  This matters because standalone mode has no reload button.
* **Kill switch.** If `PWA_ENABLED=false` (env, default `true`), `/sw.js` returns a service worker
  that deletes its caches, unregisters itself and reloads clients. This is the documented recovery
  for a bad release.
* Safari 27's `addRoutes` static routing is optional later: it lets `/api/` skip the service worker
  entirely. Feature-detect it.

Skeleton (`app/static/sw.js`, about 50 lines):

```js
const VERSION = '__VERSION__';
const SHELL = `kdl-shell-${VERSION}`;
const SHELL_URLS = ['/', '/style.css', '/app.js', '/offline.js', '/scan.js', '/manifest.webmanifest',
  '/apple-touch-icon.png', '/icons/icon-192.png', '/icons/icon.svg'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_URLS.map((u) => new Request(u, { cache: 'reload' })))));
});
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k.startsWith('kdl-') && !k.endsWith(VERSION)) await caches.delete(k);
    await self.clients.claim();
  })());
});
self.addEventListener('message', (e) => { if (e.data === 'SKIP_WAITING') self.skipWaiting(); });
self.addEventListener('fetch', (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/healthz') return;
  if (req.mode === 'navigate') {
    if (url.pathname !== '/' && url.pathname !== '/index.html') return; // handbook etc. go to the network
    if (url.searchParams.has('reauth')) return;                       // let auth proxies redirect
    e.respondWith(caches.match('/', { cacheName: SHELL }).then((r) => r || fetch(req)));
    return;
  }
  if (url.pathname.startsWith('/vendor/')) {
    e.respondWith(caches.open(`kdl-vendor-${VERSION}`).then(async (c) =>
      (await c.match(req)) || fetch(req).then((r) => { if (r.ok) c.put(req, r.clone()); return r; })));
    return;
  }
  e.respondWith(caches.match(req, { cacheName: SHELL }).then((r) => r || fetch(req)));
});
```

### R5. Offline data (`offline.js`, IndexedDB, no library)

* **Database:** `kdl`, version 1. Object stores:
  * `meta` (key: string): `{user_id, foods_version, last_full_sync}`
  * `snapshots` (key: `[user_id, path]`): `{data, fetched_at}`. Holds the profile, the last
    **14 days** of `/api/log?date=`, `/api/log/summary`, custom foods and saved meals. It is
    written after every successful GET.
  * `foods` (key: `id`): builtin + custom foods, for offline search with the existing `MockApi`
    search code.
  * `outbox` (key: `client_id`, index `created_at`):
    `{client_id, user_id, method, path, body, created_at, attempts, state: 'pending'|'failed', last_error}`
* **Builtin foods:** `GET /api/foods/builtin` returns `data/foods.json` with an `ETag` equal to its
  `version`. The app refreshes the `foods` store when the version changes (33 KB gzipped).
* **Queueable offline actions (v0.3):** add an entry (`POST /api/log`), quick add
  (`POST /api/log/quick`) and mark eaten (`POST /api/log/mark-eaten`). Edits and deletes of
  server-side entries, profile changes and USDA import need a connection; their buttons say so.
  Pending entries show a "waiting to sync" badge, and their warnings are computed locally with
  `evaluateWarnings`, which is already kept in parity with the server for the preview.
* **Idempotency (server change):**
  * Add `client_id TEXT` to `log_entries` (migration) and
    `CREATE UNIQUE INDEX log_client_id ON log_entries(user_id, client_id) WHERE client_id IS NOT NULL`.
  * `POST /api/log` and `/api/log/quick` accept an optional `client_id` (UUID, at most 36
    characters).
  * A repeat returns the existing entry with **200** instead of 201.
  * Generate it with `crypto.randomUUID()`, falling back to a `getRandomValues` v4 builder on
    HTTP.
  * The IETF `Idempotency-Key` header draft (-07) expired in April 2026, so a body field is simpler
    and fits SQLite.
* **Sync triggers.** There is no Background Sync on iOS, so replay the outbox:
  * at app start;
  * on `visibilitychange` → visible and on `pageshow`;
  * on `online`;
  * after any successful API call;
  * every 30 s while the page is visible and the queue is not empty.

  Rules for replaying:
  * Replay FIFO under `navigator.locks.request('kdl-sync', …)` so two tabs cannot replay at once.
  * Stop at the first network error or 5xx.
  * On a 4xx, mark the item `failed` and **show it** with Retry and Discard. Never drop health
    data silently.
* **Timeouts:** every API fetch uses an `AbortController` with a 6 s timeout. Away from home, a
  private IP can hang for more than a minute.
* **Resume:** on becoming visible, if the local date changed and the user was on "today", move to
  the new today and refetch.
* **Logout / user switch:**
  1. If the outbox has entries for this user, warn: "3 entries have not synced and will be lost".
  2. Then `indexedDB.deleteDatabase('kdl')`.
  3. The logout response sends `Clear-Site-Data: "cache", "storage"` (iOS 17+). This also removes
     the service worker; it re-registers on the next load.
* **Persistence:** after the first successful login in standalone mode, call
  `navigator.storage.persist()`. Show `estimate()` and `persisted()` under Settings → This device.

### R6. Server headers and auth exemptions (`app/pwa.py`, `app/main.py`)

* `/manifest.webmanifest`: `Content-Type: application/manifest+json`, `Cache-Control: no-cache`.
  (Python's built-in mimetypes table already maps `.webmanifest` and `.wasm`.)
* `/icons/*`, `/apple-touch-icon.png`, `/vendor/*`: `Cache-Control: public, max-age=604800`.
* `/api/*`: `Cache-Control: no-store` (owned by the security note; listed here because R5 relies
  on it).
* **Public, no auth:** `/manifest.webmanifest`, `/icons/*`, `/apple-touch-icon.png`, `/sw.js`
  (plus `/healthz`). They carry no personal data, and iOS fetches the icon at install time.
  Extend `AUTH_EXEMPT_PATHS` to support prefixes.
* **CSP** directives the PWA needs (merge into the security note's policy): `worker-src 'self'`,
  `manifest-src 'self'`, `script-src 'self' 'wasm-unsafe-eval'`, `img-src 'self' data: blob:`,
  `connect-src 'self'`. Move the inline theme bootstrap `<script>` into a file or give it a hash.
* `Permissions-Policy: camera=(self), microphone=(), geolocation=()`. Safari ignores it; Chromium
  honours it.
* Add `GZipMiddleware(minimum_size=1024)`, or document `encode zstd gzip` at the proxy. It roughly
  halves the 1.09 MB WASM.
* **Do not** serve user uploads (photos) from paths under `/` that could be mistaken for scripts.
  Serve them from `/api/...` with an explicit `image/*` type, `X-Content-Type-Options: nosniff`
  and `Content-Disposition`. A same-origin script at the root could register a malicious service
  worker.

### R7. Camera and barcode UI (`scan.js`)

1. Show the **Scan** button only when `isSecureContext && navigator.mediaDevices?.getUserMedia`.
   Otherwise show "Live scanning needs HTTPS. See docs/https.md" and the photo button.
2. On tap:
   * call `getUserMedia({video: {facingMode: {ideal: 'environment'}, width: {ideal: 1280}, height: {ideal: 720}}, audio: false})`;
   * attach to a `<video playsinline muted autoplay>` (without `playsinline` iOS goes full-screen);
   * stop all tracks on close, on `visibilitychange` hidden, and on route change.
3. Pick the detector:
   * native `BarcodeDetector` when `getSupportedFormats()` includes `ean_13`;
   * otherwise lazy-load `/vendor/barcode-detector-3.2.2/ponyfill.iife.js` and call
     `BarcodeDetectionAPI.prepareZXingModule({ overrides: { locateFile: (p, pre) => p.endsWith('.wasm') ? '/vendor/zxing-wasm-3.1.3/' + p : pre + p } })`.

   Formats: `ean_13, ean_8, upc_a, upc_e`. Throttle to about 8 detections per second.
   Require **two identical reads** before accepting a code.
4. **Photo button:** `<input type="file" accept="image/*">`, without `capture`, so iOS offers
   camera *and* library. Decode with `createImageBitmap(file)` and run the same detector on the
   bitmap. If the barcode note chooses server-side decode, downscale to a long edge of at most
   1600 px and re-encode `canvas.toBlob('image/jpeg', 0.85)` (this strips EXIF/GPS).
5. If the camera starts but no frame arrives within 4 s (WebKit 282327), close it and switch to
   the photo button with a short explanation.

### R8. Reminders (Web Push), deferred to v0.4 and opt-in

* Env: `PUSH_ENABLED=false` (default), `VAPID_SUBJECT=mailto:admin@example.org` (required when
  enabled), and `VAPID_PRIVATE_KEY_FILE=${DATA_DIR}/vapid_private.pem` (generated on first use,
  mode 0600).
* Dependencies: `pywebpush==2.5.0` and `py-vapid==1.9.4` (both MPL-2.0, file-level copyleft,
  fine as unmodified dependencies).
* Endpoints:
  * `GET /api/push/public-key`
  * `POST /api/push/subscriptions` (body: `PushSubscription.toJSON()`)
  * `DELETE /api/push/subscriptions/{id}`
  * a table `push_subscriptions(id, user_id, endpoint UNIQUE, p256dh, auth, created_at, last_ok_at)`.
    Delete a row on 404/410.
* Payloads: send the declarative form (`{"web_push":8030,"notification":{"title":"Kidney Log","body":"Log lunch?","navigate":"/#add"}}`)
  with `TTL: 3600` and `Urgency: normal`. The service worker's `push` handler parses the same JSON
  for non-declarative browsers. **Bodies stay generic** ("Time to log lunch"): no nutrient values
  and no condition names, because the push service learns timing and metadata.
* The Settings toggle is visible only when `display-mode: standalone` (iOS) or a service worker is
  supported (others). Permission is requested from that button tap.
* Document clearly: "Reminders are a convenience. Do not rely on them for hypoglycaemia; use your
  CGM's alerts." Add the push domains to `docs/network-allowlist.md` under the app's own outbound
  list.

### R9. HTTPS documentation (`docs/https.md`), four tiers

1. **Recommended: your own domain + Caddy DNS-01.**

   ```Dockerfile
   # deploy/caddy/Containerfile
   FROM docker.io/library/caddy:2.11.6-builder AS build
   RUN xcaddy build --with github.com/caddy-dns/cloudflare@v0.2.4
   FROM docker.io/library/caddy:2.11.6
   COPY --from=build /usr/bin/caddy /usr/bin/caddy
   ```

   ```caddyfile
   {
       email admin@example.net
   }
   *.home.example.net {                 # wildcard: the app's name never reaches CT logs
       tls {
           dns cloudflare {env.CF_API_TOKEN}
       }
       encode zstd gzip
       @food host food.home.example.net
       handle @food {
           reverse_proxy kidney-health:8000
       }
       handle {
           abort                        # unknown names under the wildcard get nothing
       }
   }
   ```

   Point `food.home.example.net` at the LAN IP in local DNS (split horizon). Rootless Podman
   cannot bind 443 by default. Either publish `8443:443` and use `https://food.home.example.net:8443`
   (iOS is fine with a port; the port is part of the origin, see Risks), or follow the rootless
   note for `ip_unprivileged_port_start`.
2. **Easiest: Tailscale.** Name the node neutrally (e.g. `homelab-1`, not `kidney-health`), then
   run `tailscale serve --bg localhost:8000` and open `https://homelab-1.<tailnet>.ts.net`.
   Do **not** use Funnel unless the app's own login is enabled.
3. **No external dependencies: private CA.**
   * Get the root: `caddy` with `tls internal` → `podman cp caddy:/data/caddy/pki/authorities/local/root.crt .`,
     or step-ca 0.30.2.
   * Use an internal name under `home.arpa` (RFC 8375).
   * Install it on the iPhone: AirDrop, or open it in Safari → *Settings → Profile Downloaded →
     Install*.
   * Then *Settings → General → About → Certificate Trust Settings → enable full trust*.
   * Warn the user: that root can impersonate **any** site on the phone, so keep its key offline
     (step-ca supports name-constrained roots; verify on the device).
4. **Kubernetes:** cert-manager v1.21.2 `ClusterIssuer` (ACME, `dns01.cloudflare.apiTokenSecretRef`)
   + `cert-manager.io/cluster-issuer` annotation on the existing Ingress, or `CA` issuer from a
   private root.

Each tier ends with the same check on the phone:

1. The padlock shows and there is no warning.
2. *Settings → This device* shows "Offline ready ✓".
3. Install, switch on Airplane Mode, and confirm the app still opens.

### R10. Install UX (Settings → "This device")

* State: "Installed as app" / "In browser" (display-mode), "Offline ready" (service worker
  active), storage used and quota, persisted yes/no, pending sync count with **Sync now**,
  **Clear data on this device**, and the app version.
* **iOS, not standalone:** a short illustrated sheet: "Safari (or Chrome) → Share → Add to Home
  Screen → keep *Open as Web App* on → Add". Show it on the Settings page and **once** as a
  dismissible tip after the third visit (remembered in `localStorage`). Never block the UI.
* **Chromium:** keep the `beforeinstallprompt` event and show an **Install app** button in
  Settings.
* **Plain HTTP:** a yellow note, "Offline, camera scanning and reminders need HTTPS", linking to
  `docs/https.md`.

### R11. Icon build (`scripts/build_icons.py`, dev only, outputs committed)

* Inputs: `app/static/icons/icon.svg` and `icon-maskable.svg`.
* Render with Playwright Chromium: a data-URI `<img>` at the exact size, `device_scale_factor=1`,
  and `page.screenshot(clip=…)`. Use `omit_background=True` for `purpose:any`. Use `False` for
  `apple-touch-icon.png` and the maskable icons, which gives opaque RGB.
* Outputs: `apple-touch-icon.png` (180), `icon-192.png`, `icon-512.png`, `icon-maskable-192.png`,
  `icon-maskable-512.png`.
* Honour `CHROMIUM=/path/to/chrome` for environments whose browser revision differs from the
  Playwright package (true in this cloud environment: `/opt/pw-browsers/chromium-1194`).
* `tests/test_pwa.py` checks the PNG signature, the IHDR width and height, and colour type 2 for
  the opaque icons, using only `struct`. **CI does not need Playwright.**

### R12. Supported platforms (state in README)

* "Installable app" is tested on **iOS/iPadOS 26 and 27** and expected to work on iOS 17+.
* Push and badging need 16.4+. Declarative tap-through needs 18.4+.
* Android Chrome is supported. Desktop Chrome, Edge and Safari 17+ are supported.
* On Firefox, desktop is "browser tab or Windows web app" and Android is "Install".

---

## 5. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **The origin is the app's identity.** Changing hostname, scheme or port (e.g. moving `:8443` to `:443`, or from Tailscale to your own domain) creates a *different* app with empty storage. | Users lose unsynced outbox entries and must reinstall | Docs say "choose the final URL before installing on phones". Settings shows the pending count; Logout and Clear warn first. |
| WebKit camera-in-PWA bugs (282327) and no native `BarcodeDetector` | Scanning fails for some iPhone users | Polyfill, a 4 s no-frame watchdog, and the photo fallback that is always visible |
| A bad service worker release keeps serving an old or broken shell | App stuck on a version | Versioned caches, Reload toast, `PWA_ENABLED=false` kill switch, `/?reauth=1` bypass, documented in troubleshooting |
| Cached shell and new API disagree after an upgrade | JS errors | The server sends `X-KDL-Version` on API responses; on a mismatch the app shows the Reload toast. Add API changes only, never remove. |
| Shared device, multiple users: health data left on the phone | Privacy | IndexedDB keyed by user, logout deletes the database plus `Clear-Site-Data`, nothing personal in Cache Storage. iOS Data Protection encrypts app data while locked, if a passcode is set. |
| Offline warnings drift from server rules | Wrong colour shown while offline | Reuse the parity-tested `evaluateWarnings`; label offline results "estimate, waiting to sync"; recompute on sync |
| Duplicate entries from replay | Wrong totals (potassium) | `client_id` unique index + 200-on-repeat; test it |
| Push privacy, outbound calls, unreliability | Metadata leaks to Apple, Google or Mozilla; missed reminders | Opt-in, generic bodies, never for hypos, allowlist documented, v0.4 only |
| Hostname in CT logs reveals a medical condition | Privacy | Wildcard certificates or neutral names; neutral Tailscale node names |
| Private-CA root on the phone | MITM potential if the key leaks | Recommend public certificates first; keep the CA key offline; name constraints |
| Let's Encrypt lifetimes drop to 45 days | Manual setups break | Docs only show auto-renewing ACME (Caddy, cert-manager, Tailscale) |
| HTTP Basic auth in standalone mode | Re-prompts, no logout | Cookie sessions from the auth note; keep Basic only as legacy |
| Apple changes behaviour yearly (e.g. the iOS 26 "Open as Web App" default) | Docs go stale | Re-verify each September and March; checklist item 9 |
| 1.09 MB WASM on a metered connection | Data use | Loaded only on first scan, then cached; gzip ≈ 459 KB |
| Vendored code goes stale or is tampered with | Security | `vendor/README.md` records version, URL and SHA-256; a test verifies the hashes; review on each update |

---

## 6. Implementation checklist

Each phase is shippable on its own. Check the boxes in the PR description.

**Phase 1: installable (no offline yet)**

1. [ ] Add `app/static/icons/icon.svg` (current round badge) and `icon-maskable.svg` (full-bleed
   `#2e7d32` square with the same glyph, not scaled; it is inside the 40% safe zone).
2. [ ] Add `requirements-tools.txt` (`playwright==1.63.0`) and `scripts/build_icons.py` (R11). Run
   it and commit the 5 PNGs plus `app/static/apple-touch-icon.png`.
3. [ ] Add `app/static/manifest.webmanifest` exactly as in R2. Add the R3 `<head>` tags. Make sure
   `scripts/build_preview.py` strips them, and extend `tests/test_preview_build.py`.
4. [ ] `app/main.py`: make the manifest, icons, `apple-touch-icon.png` and `sw.js` public
   (prefix-aware `AUTH_EXEMPT_PATHS`). Add cache headers (R6) and `GZipMiddleware`.
5. [ ] `tests/test_pwa.py`:
   * the manifest parses, `id`/`start_url`/`scope` are `/`, `display` is `standalone`;
   * 192/512 `any` and maskable icons exist with the right IHDR sizes;
   * the apple-touch icon is 180×180 RGB;
   * every manifest `src` returns 200 with no auth even when `APP_PASSWORD` is set;
   * the `Content-Type` headers are right.

**Phase 2: offline shell**

6. [ ] `app/static/sw.js` (R4 skeleton) and `app/pwa.py` serving `/sw.js` with `__VERSION__` set
   to a hash of the shell files, `no-cache`, and the `PWA_ENABLED` kill switch. Tests: the version
   changes when a shell file changes; the kill-switch body unregisters; the route is not under
   auth.
7. [ ] `app.js`: register only when `isSecureContext && !MOCK`. Add the update toast
   (`waiting` → `SKIP_WAITING` → reload on `controllerchange`), hourly `registration.update()` on
   visibility, an "offline" banner driven by fetch failures and a 6 s `AbortController` timeout,
   and day rollover on resume.
8. [ ] Settings → **This device** section (R10), the iOS install sheet, and the Chromium install
   button.

**Phase 3: offline data**

9. [ ] Server: `client_id` migration, unique partial index, accepted on `POST /api/log` and
   `/api/log/quick`, 200 on repeat. Add `GET /api/foods/builtin` with an ETag. Add the
   `X-KDL-Version` header. Tests: double POST gives one row; different users with the same
   `client_id` do not clash; ETag 304.
10. [ ] `app/static/offline.js`: the IndexedDB stores, snapshots after GETs, offline food search
    reusing the `MockApi` search, the outbox with Web Locks, FIFO replay, the triggers in R5,
    failed-item UI, and logout purge with the unsynced warning plus `Clear-Site-Data`.
11. [ ] A Playwright test (desktop Chromium, `context.set_offline(True)`): install the service
    worker, go offline, reload, add an entry, see it pending, go online, see one server row.

**Phase 4: camera**

12. [ ] Vendor `barcode-detector@3.2.2` `dist/iife/ponyfill.js` and `zxing-wasm@3.1.3`
    `dist/reader/zxing_reader.wasm` (SHA-256 `2ebda08a…c6d1ba`), with their licences and the
    ZXing-C++ Apache-2.0 licence. Write `vendor/README.md` and a test that checks the hashes.
13. [ ] `app/static/scan.js` per R7: live scan gated on a secure context, native detector first,
    lazy polyfill, two-read confirmation, track cleanup, 4 s watchdog, photo fallback. Hand the
    code to the lookup flow defined by the barcode note.
14. [ ] Add `'wasm-unsafe-eval'`, `worker-src`, `manifest-src` and `blob:` to the CSP in
    coordination with the security note.

**Phase 5: docs**

15. [ ] `docs/https.md` (R9, four tiers, CT-log privacy warning, the iOS trust steps verbatim, the
    "choose your final URL first" warning) and a link from `docs/deployment.md` §g.
16. [ ] `docs/install-on-your-phone.md` for users: iOS, Android, desktop, what works over
    HTTP vs HTTPS (the F9 table), and troubleshooting (blank icon → icon behind auth; old version
    → Reload or kill switch; camera black → photo button; "data gone" → origin changed).
17. [ ] README feature list: "Installable app (iPhone, Android, desktop), works offline". Add the
    supported platforms (R12). Update `ARCHITECTURE.md` with the new routes, files and the
    `client_id` column.

**Phase 6: v0.4, opt-in reminders**

18. [ ] Implement R8 behind `PUSH_ENABLED`. Add the push domains to `docs/network-allowlist.md`,
    and add device tests on iOS 18.4+ (declarative) and on Chrome Android.

**Manual device test matrix (before the release tag):** iPhone on iOS 27 and on iOS 26 (or 18),
an iPad, an Android phone with Chrome, and desktop Chrome and Safari. Run each step over the
Tailscale tier *and* the private-CA tier:

1. Install.
2. Icon and name look right.
3. Status bar matches the theme in light and dark.
4. Safe areas are correct in portrait and landscape.
5. Airplane-mode launch works.
6. Queued entry syncs once.
7. Update toast appears after a redeploy.
8. Scan an EAN-13 live, then from a photo.
9. Logout purges local data.

## How to re-verify

Run this each September (new iOS) and March (x.4). It prints Safari iOS support for the APIs this
note depends on:

```bash
curl -sL https://unpkg.com/@mdn/browser-compat-data/data.json -o /tmp/bcd.json
python3 - <<'EOF'
import json; d = json.load(open('/tmp/bcd.json')); print(d['__meta'])
for p in ['api.BarcodeDetector', 'api.SyncManager', 'api.PushManager', 'api.Window.pushManager',
          'api.ServiceWorkerGlobalScope.notificationclick_event', 'api.InstallEvent.addRoutes',
          'manifests.webapp.icons', 'manifests.webapp.background_color', 'manifests.webapp.shortcuts']:
    n = d
    for k in p.split('.'): n = n[k]
    print(p, n['__compat']['support']['safari_ios'])
EOF
```

Also re-read the latest "WebKit Features in Safari N.0" post and WebKit bugs 281848 and 282327.
