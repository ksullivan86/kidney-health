# Progress: the iPhone app without a server (design note 38)

Status: steps 0 and 1 merged (#186, TestFlight build 5). Steps 2 and 3 built and committed; steps 4 and 5 next.

## Done

* Note 38 written and decided (2026-11-20, §10).
* Step 0 (2026-11-21): the **Storage test** screen (`ios/KidneyHealth/StorageCheck/`), reached from the app's settings sheet.
  Each open adds the time to a file in Application Support (the control), and to a test page's IndexedDB and localStorage in
  WebKit's default store and in a store with a fixed identifier. Checked by `tests/test_ios_app.py` and `LocalFilesTests.swift`.
* Step 1 (2026-11-21): **device mode** and the **web shell**. See ARCHITECTURE.md "Device mode: the web app inside the iPhone app".
  * `scripts/build_preview.py --device DIR` (the Pages site with `device-flag.js`); CI and TestFlight pack it into `ios/WebApp`.
  * Engine: `KH.flags.DEVICE`, an empty start, one person who is not an admin, kept from the first start, the safety copy posted
    after each save. Screens: no demo pill or banner, no sign-out or device list, This device → Apple Health and server.
  * iPhone: `ios/KidneyHealth/WebShell/` (product-neutral; a second app changes only `WebShellConfig.swift`), the web app full
    screen in `RootView`, the old screen as a settings sheet, the safety copy in Documents (Files app), Export via the share sheet.
  * Verified: `node tests/js/device_mode.mjs` (18 checks), `tests/test_device_mode.py`, `tests/test_ios_app.py`,
    `python tools/e2e/device_mode.py` (24 checks in Chromium). The Swift code builds only on CI (Xcode 27.2).

## Steps 2 and 3 (in progress, 2026-11-21)

* Step 3 done in the working tree: `ios/KidneyHealth/Phone/LocalLog.swift` (`LocalLogTransport`: Sync.run delivers to the page,
  rows planned with `Push.plan`, watch readings counted not stored, anchor kept only after the page saved), `PageBridge`,
  `SyncModel.syncToPhone()` (own anchors `phoneAnchors` and start day), observing once Health was allowed; `app/static/js/mock/device.js`
  (`window.KHDevice.addBody`, batch routes, flush before answering; `KH.mock.device.lookup` for step 2); `Phone/AppLock.swift`
  (optional Face ID or passcode, off by default; covers the app in the background). Tested: `node tests/js/device_mode.mjs` (27),
  `PhoneTests.swift` (CI only).
* Step 2, iPhone side done: `Services/FoodServices.swift` (USDA with the person's key in the Keychain, sent as `X-Api-Key`; Open
  Food Facts API 3.4 with the page's field list; off until turned on; limits 900/h and 12/min; no cookies, cache or redirects;
  fixed hosts), `FoodBridgeHandler` (reply handler, own origin only), `Services/KeysView.swift`.
* Step 2, web side done: the helper agent's JS twins of `app/off.py` `map_product` and `app/foods.py` `map_usda_record`
  with vectors (role `offusda-twins`, merged), and device-mode branches in `js/mock/barcode.js` and `js/mock/foods.js` that call
  `KH.mock.device.lookup` and map with the twins; the Open Food Facts consent turns the service on (`enableOff`). The mock's
  `request()` awaits a route that answers later. `node tests/js/device_mode.mjs`: 36 checks.

## Next

1. CI on the step 0 + 1 pull request (the simulator build is the first compile of the Swift code), then TestFlight.
2. The owner: the Storage test (reopen, force-quit, Offload App, more than 7 days) and a first try of the app with no server.
3. Not yet done in step 1, by choice: barcode camera inside the web view (needs a check on the phone: a custom scheme may not
   count as a secure context for getUserMedia; photo upload works either way), and hiding the other server-only Settings blocks
   (Care team, phone shortcuts, connected devices, Outside AI apps), which say "Your admin has not turned this on".
4. Step 2: Keys and services (USDA key, Open Food Facts) through a native bridge.

## Commands

* `python3 scripts/build_preview.py --device ios/WebApp` before building in Xcode.
* `python -m pytest -q tests/test_ios_app.py tests/test_device_mode.py`; `node tests/js/device_mode.mjs`; `python tools/e2e/device_mode.py`.
