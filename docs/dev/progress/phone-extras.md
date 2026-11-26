Status: in progress

# phone-extras (owner request 2026-11-26)

Three device-mode gaps, done in the order 1, 3, 2.

1. Export: the phone gives the server's export .zip (export.json, CSVs, README) built in the page. — done
   * Twin `M.exportZip` + `MockApi._exportArchive()` in app/static/js/mock/export.js; `KH.demoLocal.exportFile()` downloads it
     (device mode and the Pages demo "Keep my data"). WebAppView already sends a blob download to the share sheet: no Swift change.
   * Vectors: tests/data/gen_export_vectors.py → export_vectors.json; `node tests/js/export_vectors.mjs` (separate from
     run_vectors.mjs because another agent had uncommitted hunks there); pytest tests/test_export_vectors.py.
   * Verified: node check 30/30; pytest test_export_vectors, test_demo_local_ui; `tools/e2e/demo_local.py --only export` 25 passed.
2. Voice for Ask: Apple's on-device speech recognition through the bridge. — done, committed (device_mode.py hunks landed in 6abf889 with the recipe walk)
   * ios/KidneyHealth/Phone/Dictation.swift: SFSpeechRecognizer, requiresOnDeviceRecognition = true, native sheet (Done/Cancel,
     60 s). Chose SFSpeechRecognizer over SpeechAnalyzer: available since iOS 13 (deployment target 17), a stable API I can write
     without a Mac to compile on; SpeechAnalyzer (iOS 26) could replace it later behind `if #available`.
   * Bridge kinds speechStatus / dictate in Services/FoodServices.swift. Plist sentences as INFOPLIST_KEY_* in project.pbxproj.
   * Page: js/views/ask-voice.js syncPhone()/listenOnPhone(); ask.js calls askVoice.sync before its DEVICE branch.
   * Tests: tests/test_phone_dictation.py, tests/test_ask_voice_ui.py; e2e tools/e2e/device_mode.py ask_walk (mic → words in box,
     nothing sent) and no_server_ask (no mic): 159 passed.
3. Handbook: bundle the built handbook into the iPhone app's web files. — in progress
   * Before: device-flag.js already points Learn links at the public Pages site (opened in Safari) — needs HANDBOOK_PAGES published.
   * scripts/build_preview.py --device DIR --handbook SITE: pack_handbook() copies an `mkdocs build` site into DIR/learn/,
     inline scripts → learn/assets/javascripts/inline/<sha>.js, meta CSP, instant loading off, no maps/lunr/sitemap/404. ~12 MB.
   * Local build: scratchpad/hbvenv (pip install handbook/requirements.lock), `cd handbook && mkdocs build --strict -d SITE` (60 s).
   * Next: WebShell/HandbookView.swift (native sheet with its own WKWebView + scheme handler mapping dir URLs → index.html),
     WebAppView intercepts learn/ links; mock/handbook.js local; CI macOS + TestFlight build the handbook; tests; docs.

## Notes
* Python venv: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
* Server zip: app/account.py build_export; CSV writer `_csv` + `app/log.csv_safe`.
