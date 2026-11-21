# Progress: the iPhone app without a server (design note 38)

Status: step 0 built, waiting for the owner's results on a real iPhone.

## Done

* Note 38 written and decided (2026-11-20, §10).
* Step 0 (2026-11-21): **Storage test** screen in the iPhone app (`ios/KidneyHealth/StorageCheck/`). Each time it opens it adds the
  time to a file in Application Support (the control), to a web page's IndexedDB and localStorage in WebKit's default store,
  and to the same in a store with a fixed identifier (`WKWebsiteDataStore(forIdentifier:)`). The page is served by
  `LocalSchemeHandler` at `kidneyhealth-app://local/`, from a list of three files, with a CSP that has `connect-src 'none'`.
  Checked by `tests/test_ios_app.py` (no inline script, no network words, the file list) and `LocalFilesTests.swift`
  (simulator, CI `ios-app` job).

## Next

1. A TestFlight build with the test screen; the owner runs it (steps on the screen) and sends "Copy results" after: a normal
   reopen, a force-quit, Offload App and reinstall, and more than 7 days unopened.
2. Read the results into note 38 §3 (F4) and §9: if the web stores keep everything the file keeps, step 1 uses IndexedDB in the
   app's own store; if not, the log goes in a native SQLite file through the bridge.
3. Remove the test screen when step 1 starts.

## Commands

* `python -m pytest -q tests/test_ios_app.py`
* CI runs the Swift tests on the simulator (Xcode 27.2, `xcode-27` runner).
