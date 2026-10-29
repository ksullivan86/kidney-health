"""The brand strings: the product's names and the identifying strings it puts on disk, on the wire and on the screen.

They are here, and not spelled out where they are used, so that a second product built on this code changes them in one
place (and in the browser's copy, ``app/static/js/engine/brand.js``) and does not have to search for them
(design note 14, change 3; ARCHITECTURE.md "Brand strings").

Every value is what the code had before this file existed. Each comment says what the string is and whether it is
**compatibility surface**: a string that something outside this process has already stored, sent or remembered. Changing
one of those on an install in use does real harm (people are signed out, tokens stop working, data is not found).
``tests/test_brand.py`` pins every value for that reason. A new product picks its values before its first start and does
not change them later. Each value is written out in full, not built from another, so changing the name never moves a
compatibility string by accident.

This file imports nothing, so any module can import it.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Names (shown to people; not compatibility surface)
# --------------------------------------------------------------------------- #

# The product's name in the server's own words: the default "Server name", the title of the API document, the export README and the
# import refusals. The browser's twin is ``name``.
NAME = "Kidney Health"

# The name on the screen: the page title, the install name and the Visit prep footer. The static files (``index.html``,
# ``manifest.webmanifest``, the style sheets) cannot import this file and repeat it. The browser's twin is ``screenName``.
SCREEN_NAME = "Kidney Diet Log"

# The short machine-friendly name: the start of the export's file name (``kidney-health-<name>-<date>.zip``) and of the start-up
# error message. The browser's twin is ``slug``. The strings below that look like it are separate on purpose.
SLUG = "kidney-health"

# Where the project lives. The default contact that Open Food Facts asks to see in the User-Agent (setting ``food.off_contact``).
PROJECT_URL = "https://github.com/ksullivan86/kidney-health"

# The start of the food log download's file name (``kidney-log_<from>_<to>.csv``). The browser's twin is ``logCsvPrefix``.
LOG_CSV_PREFIX = "kidney-log_"

# The root of every logger name (``kidney_health.ai``, ``kidney_health.auth`` and so on).
# Compatibility: operators filter their logs by it.
LOGGER_NAME = "kidney_health"

# --------------------------------------------------------------------------- #
# On disk
# --------------------------------------------------------------------------- #

# The database file in the data directory, and the stem of the v0.2 backup (``<this>.pre-v3.bak``).
# Compatibility: an install finds its data by this name. A new name on an install in use starts an empty database.
DB_FILENAME = "kidney.db"

# The start of the file names that ``python -m app.admin backup --dir`` writes (``kidney-YYYYMMDDTHHMMSSZ.db``) and prunes by.
# Compatibility: backups that exist keep their old prefix, and ``--keep`` counts only files with the current one.
BACKUP_PREFIX = "kidney-"

# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #

# The session cookie: the plain name over HTTP, the ``__Host-`` name over HTTPS (ARCHITECTURE.md "Identity").
# Compatibility: a new name signs everyone out. Each scheme reads only its own name.
SESSION_COOKIE = "kh_session"
SESSION_COOKIE_HOST = "__Host-kh_session"

# The remembered-device cookie of the sign-in throttle, over HTTP and over HTTPS.
# Compatibility: a new name makes every remembered device look new, so a wrong password is delayed as for a stranger.
DEVICE_COOKIE = "kh_device"
DEVICE_COOKIE_HOST = "__Host-kh_device"

# --------------------------------------------------------------------------- #
# Request headers and tokens
# --------------------------------------------------------------------------- #

# The value of ``X-Requested-With`` that every unsafe ``/api`` request must carry (the CSRF check).
# Compatibility: the page (browser twin ``csrfHeaderValue``), the demo, the end-to-end tools and any script that calls the API send it.
CSRF_HEADER_VALUE = "kidney-health"

# The response header that carries the shell's version on every ``/api`` answer. ``app/pwa.py`` sets it; ``core.js`` and
# ``offline.js`` read it to offer "Update ready". The browser's twin is ``versionHeader``.
# Compatibility: a page cached before a change would stop noticing updates.
VERSION_HEADER = "X-KDL-Version"

# The start of an assistant access token (``kha_`` and 43 characters; Settings → Assistant access) and of a device token
# (``khd_``; Settings → Phone shortcuts).
# Compatibility: tokens people already made, the check of their shape and the log redaction all depend on them.
ASSISTANT_TOKEN_PREFIX = "kha_"
DEVICE_TOKEN_PREFIX = "khd_"

# The link scheme of the iPhone app (``kidneyhealthsync://pair?…``): the QR code that Settings → Phone shortcuts shows with a new
# device token opens the app with the address and the token (``app/pairing.py``, design note 15 §4.3).
# Compatibility: the app registers this scheme, and an app already installed only opens links that use it.
PAIRING_SCHEME = "kidneyhealthsync"

# The realm of the ``WWW-Authenticate: Bearer`` challenge that a refused token gets at ``/mcp`` and ``/push/v1``.
# Compatibility: a client may match on it.
BEARER_REALM = "kidney-health"

# --------------------------------------------------------------------------- #
# The assistant's MCP server
# --------------------------------------------------------------------------- #

# ``serverInfo.name`` and ``serverInfo.title`` in the answer to MCP ``initialize``.
# Compatibility: an assistant may list the server by that name.
MCP_SERVER_NAME = "kidney-health"
MCP_SERVER_TITLE = "Kidney Health food log"

# The ``source`` field on every MCP tool answer. Compatibility: an assistant's own instructions may refer to it.
MCP_SOURCE = "kidney-health"

# --------------------------------------------------------------------------- #
# The export
# --------------------------------------------------------------------------- #

# The ``format`` of ``export.json``. ``app/account.py`` writes it and ``app/data_import.py`` reads only it.
# Compatibility: every export file people keep has it. The browser's demo writes and reads the same value (``exportFormat``).
EXPORT_FORMAT = "kidney-health-export"

# --------------------------------------------------------------------------- #
# Outbound User-Agent headers
# --------------------------------------------------------------------------- #

# What each outside service sees. Not compatibility surface in a strict sense, but providers read them in their logs, so keep them stable.
# ``{version}`` is the app's version and ``{contact}`` the contact address; fill them in with ``str.format``.
USER_AGENT_AI = "kidney-health/{version}"  # AI providers and speech-to-text (``app/ai/client.py``)
USER_AGENT_USDA = "kidney-health/0.3 (self-hosted food log)"  # USDA FoodData Central (``app/foods.py``)
USER_AGENT_OFF = "KidneyHealth/{version} ({contact})"  # Open Food Facts asks for ``name/version (contact)`` (``app/off.py``)
USER_AGENT_HIBP = "kidney-health"  # the Pwned Passwords range lookup (``app/auth/policy.py``)

# --------------------------------------------------------------------------- #
# Key derivation labels (the HKDF ``info`` of ``app.crypto.Keyring``)
# --------------------------------------------------------------------------- #

# Each label picks one key out of the server's ``SECRET_KEY``. Compatibility, the strictest kind:
# * ``HKDF_SECRETS_INFO`` seals the stored API keys. A new label makes every stored key unreadable.
# * ``HKDF_LOGIN_FAILURES_INFO`` and ``HKDF_DEVICE_INFO`` only reset the sign-in throttle's counters and remembered devices.
# * ``HKDF_OPENAI_SAFETY_ID_INFO`` makes the per-person id sent to OpenAI. A new label makes everyone look like a new user there.
# * ``HKDF_AI_KEY_FINGERPRINT_INFO`` tells that a key in the environment was replaced. A new label reads as one replacement.
HKDF_SECRETS_INFO = b"kidney-health/v1/secrets"
HKDF_LOGIN_FAILURES_INFO = "kidney-health/v1/login-failures"
HKDF_DEVICE_INFO = "kidney-health/v1/device"
HKDF_OPENAI_SAFETY_ID_INFO = "kidney-health/v1/openai-safety-id"
HKDF_AI_KEY_FINGERPRINT_INFO = "kidney-health/v1/ai-key-fingerprint"
