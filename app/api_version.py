"""The API version: one integer, in one place (design note 14 change 2; ``docs/api/README.md``).

``API_VERSION`` is shown as ``info.x-api-version`` in ``docs/api/openapi.json`` and as ``api_version`` in ``GET /api/meta``; the demo's
copy of that route (``app/static/js/mock/meta.js``) is kept equal to it by ``tests/test_meta.py``.

**The rule:** bump it on a **breaking** change to the HTTP API, and only then. A breaking change is one that makes a correct, older client
fail or misread an answer: removing or renaming a route, a field, an enum value or a header; making an optional request field required;
narrowing what a request may hold; changing the type or meaning of a field; turning an allowed request into a refusal. An **additive**
change keeps the number: a new route, a new optional request field, a new field or enum value in an answer (a client must ignore what it
does not know), a new capability key in ``GET /api/meta``, a new documented error. ``/push/v1`` has its own version in its path and is not
this number's business.

It is not the app's version (``APP_VERSION`` in ``app/main.py``, which moves with every release) and not the schema step of the database.
"""
from __future__ import annotations

API_VERSION = 1
