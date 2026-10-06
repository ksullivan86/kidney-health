Status: in progress

# M1 integrator

Scope: make M1 work end to end (checklist in the workflow prompt): static checks, live server
scenarios, Chromium checks, `tools/e2e/` harnesses, README + CHANGELOG. Ports 8150-8159.
Scratch: `$SCRATCH/m1/m1-integrate/` (`$SCRATCH` = the session scratchpad). No commits (prompt).

## Done (verified)

(the previous attempt stopped before any tool call; this run started from scratch)

1. Static checks, all clean with no changes needed: `python -m pytest` 1207 passed, 1 skipped (M2
   guidance topics), one handbook UserWarning (unused sources; handbook-owned); no httpx imports.
   `node tests/js/run_vectors.mjs` (5153 rules + 136 settings checks); `build_preview.py` (678 KiB);
   pin check, actionlint 1.7.12 (+ shellcheck 0.11), hadolint 2.14.0 (3 Containerfiles),
   kustomize 5.8.2 + kubeconform 0.8.0 strict (10 resources), shellcheck, yaml_parse (25 files),
   zizmor 1.30.1 `--offline` (no findings; online mode cannot authenticate through the sandbox
   proxy). Tools downloaded with the CI's SHA-256 pins into `$SCRATCH/m1/m1-integrate/bin`.

2. Live server scenarios, all passing, no app changes needed (scripts in `$SCRATCH/m1/m1-integrate/`,
   using the new shared helper `tools/e2e/khserver.py`):
   * `live_local.py` (port 8150): setup code from the log → admin user 1; invite → second user; both
     log/plan/custom food/saved meal/apply; 11 cross-user routes → 404 both ways; search, meals,
     shopping, CSV, range only own; kh_session/kh_device attributes, no HSTS on http; logout
     (Clear-Site-Data, both names expired); CSRF/Origin/Sec-Fetch-Site/Host checks; export zip.
   * `live_tls.py` (8151-8153) with `tlsproxy.py` (self-signed TLS, adds X-Forwarded-*): __Host-
     cookies (Secure, no Domain), HSTS max-age=31536000, CSP upgrade-insecure-requests, each scheme
     reads only its own cookie name, untrusted peers' X-Forwarded-Proto ignored, LAN plain HTTP
     refused (https_required) once 2 accounts exist, loopback still allowed.
   * `live_modes.py` (8154-8158): AUTH_MODE=none (no_login, user 1 admin, login/setup/users/invites
     404); AUTH_MODE=proxy with TRUSTED_PROXY_SECRET_FILE (start refused without the secret and with
     0.0.0.0/0; setup `{code}` claims user 1 as the proxy identity; header without/with wrong secret
     or from an untrusted peer ignored; unknown identity 403; pre-created user works; groups header
     promotes/demotes; invites 409; logout redirect).
   * `live_v02.py` + `live_v02_nopw.py` (8158-8159): v0.2 DB built by running 8b8d4ec from a scratch
     `git worktree` (`$SCRATCH/m1/m1-integrate/v02`), upgraded with a weak and a strong APP_PASSWORD
     and with none: data identical on user 1, `kidney.db.pre-v3.bak` mode 0600, Basic auth gone,
     must_change_password only for the weak one, restart ignores APP_PASSWORD.

3. Chromium against the real server (`$SCRATCH/m1/m1-integrate/chromium_check.py`, 73/73): zero
   CSP/Trusted Types violations and no unexpected console errors over every view (Today, Add +
   quick add + USDA sheet, Plan + copy-day + saved meal, Trends ranges + CSV, Profile save +
   suggest, Settings sections, Admin) for an admin at 375 light and an invited user at 1280 dark;
   isolation visible in the UI; SW registers on http://localhost and controls after reload;
   `Page.getAppManifest` no errors; `Page.getInstallabilityErrors` empty in a persistent profile
   (Playwright's incognito contexts report only `in-incognito`); every manifest icon loads at its
   declared size; behind `tlsproxy.py` the browser holds `__Host-kh_session` (Secure, HttpOnly, Lax),
   HSTS, SW on https.

## In progress

4. `tools/e2e/` harnesses (parity, sandbox, regress) + README.

## Next
 4. tools/e2e. 5. README + CHANGELOG.

## Decisions

## Reproduce
