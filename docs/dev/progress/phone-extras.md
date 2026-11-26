Status: in progress

# phone-extras (owner request 2026-11-26)

Three device-mode gaps, done in the order 1, 3, 2.

1. Export: the phone gives the server's export .zip (export.json, CSVs, README) built in the page. — done
   * Twin `M.exportZip` + `MockApi._exportArchive()` in app/static/js/mock/export.js; `KH.demoLocal.exportFile()` downloads it
     (device mode and the Pages demo "Keep my data"). WebAppView already sends a blob download to the share sheet: no Swift change.
   * Vectors: tests/data/gen_export_vectors.py → export_vectors.json; `node tests/js/export_vectors.mjs` (separate from
     run_vectors.mjs because another agent had uncommitted hunks there); pytest tests/test_export_vectors.py.
   * Verified: node check 30/30; pytest test_export_vectors, test_demo_local_ui; `tools/e2e/demo_local.py --only export` 25 passed.
   * PENDING COMMIT (shared files with other agents' hunks): app/static/js/views/settings.js (button label
     'Export my data (.zip)'), app/static/index.html (#dl-export text). Commit when those files have no foreign hunks.
2. Voice for Ask: Apple's on-device speech recognition through the bridge. — not started
3. Handbook: bundle the built handbook into the iPhone app's web files, or the smallest safe version. — not started

## Notes
* Python venv: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
* Server zip: app/account.py build_export; CSV writer `_csv` + `app/log.csv_safe`.
