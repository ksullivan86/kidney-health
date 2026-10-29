Status: complete

Base: current main 867b09b (#118). Refreshed all remote branches before starting. The prior phone
walk on bf7436b had 140 passing checks and two failures solely because installed Chromium now says
"Applying inline style violates ..." rather than "Refused to apply inline style" for its malformed-XML
error documents. The actual parser/import checks passed, and strict CSP blocked the generated styles.

Fix only the harness matcher: accept old/new prefixes for error severity with style-src 'self', only
within the existing controlled-fixture window. Keep the all-messages and <=8 count assertions intact.
Unit tests reject script errors, another style directive, warning/log severity and unrelated errors.
No app/parser/CSP policy change.

Validation: `python -m pytest tests/test_xml_parser_diagnostics.py tests/test_e2e_tools.py`: 42 passed.
Ruff and git diff --check passed. Real Chromium phone regression on current main plus this fix:
142 passed, zero failed, one informational result (/tmp/kidney-chromium-xml-fixed-20261029/report.json).
The earlier run had 140 passed and two diagnostic-only failures. The walk's JS syntax/parity and
repository-unchanged checks also passed. No PR/deployment; full suite not repeated for a test-harness change.
