# The HTTP API document

[`openapi.json`](openapi.json) in this folder is the app's HTTP API as an [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0) document. It
is **made from the code and checked in**: `scripts/gen_openapi.py` builds it from the running app's routes and models, and a test fails when
the committed file is out of date. It is meant for the people who write programs against the server: **the native iOS app of the
[ROADMAP](../ROADMAP.md) and any other client generate their code from this file** (for example with Apple's `swift-openapi-generator`)
instead of reading the server's source.

The live `/openapi.json` and `/docs` pages stay **off** unless the operator sets `ENABLE_API_DOCS=true`. The file here needs neither them nor
a running server.

## Change a route? Regenerate the file

```bash
python scripts/gen_openapi.py           # rewrite docs/api/openapi.json (sorted keys, 2-space indent, a trailing newline)
python scripts/gen_openapi.py --check   # exit 1, with a short list of what differs, when the committed file is stale
```

The script builds the app in its own process with a temporary `DATA_DIR`. It starts no server, uses no network and writes only that file;
the caller's settings (`AUTH_MODE`, `PUBLIC_URL`, ...) do not change it. `tests/test_openapi_snapshot.py` runs the same check, so
`python -m pytest` fails until you regenerate. Read the diff before you commit it: it is the list of API changes in your pull request.

## The API version

`info.x-api-version` is a whole number, `API_VERSION` in [`app/api_version.py`](../../app/api_version.py); `GET /api/meta` answers it as
`api_version`. `info.version` is the app's version (`APP_VERSION`), which moves with every release. They are different things.

**Raise the API version on a breaking change, and only then.** A change is breaking when a correct client written against the older document
can fail or misread an answer:

* removing or renaming a route, a field, an enum value, a header or an operation id;
* making an optional request field required, narrowing what a request may hold, or refusing what was accepted;
* changing the type or the meaning of a field, or the status a request gets.

An **additive** change keeps the number: a new route, a new optional request field, a new field or enum value in an answer (so a client
ignores what it does not know), a new capability in `GET /api/meta`, a new documented error. The diff of `openapi.json` in the pull request
shows which kind it is. `/push/v1` carries its own version in its path (a breaking change there is `/push/v2`, and v1 keeps working for at
least one release) and is not this number.

## What the document says

* **Operation ids** are `<first tag>_<route function>`, for example `auth_login`, `log_create_entry`, `meta_info` (the tag is left off when the
  function already starts with it). FastAPI's default, `login_api_auth_login_post`, contains the path and the method and changed whenever a route
  moved. A generator turns the id into a method name, so renaming a route function (or its first tag) is a change a client will notice.
* **Errors.** Every error answer is `{"detail": "<a sentence>", ...}`: the shared `Problem` schema, with the keys some routes add next to it
  (`reason`, `field`, `retry_after`, `reauth_required`, ...). A request that fails validation is **400** with `{"detail", "errors": [{"type",
  "loc", "msg"}]}` (`ValidationProblem`), never 422; the value the person sent is never echoed. The one real 422 is the out-of-scope
  refusal of `GET /api/profile/suggested-targets`. Statuses are shared `components.responses` (`BadRequest`, `Unauthorized`, `Forbidden`,
  `NotFound`, `Conflict`, `PayloadTooLarge`, `UnsupportedMediaType`, `TooManyRequests` with `Retry-After`, ...) and are listed by rule, not
  route by route: 400 where a request has input, 401 and 403 on every signed-in route, 404 where the path names a record or a feature can be
  switched off, 413 where a body is read, and 409, 415 and 429 on the routes named in `app/openapi_doc.py`. Every `/api` operation also has a
  `default` response with the same shape, so a status the list does not name is still described.
* **Security schemes.** `session` is the cookie (`kh_session`, or `__Host-kh_session` over HTTPS) and every unsafe `/api` request must also
  send `X-Requested-With: kidney-health`; its text says so. `assistantToken` (`kha_...`) is the bearer token of `POST /mcp`; `deviceToken`
  (`khd_...`) is the bearer token of `POST /push/v1/body`. A route has the scheme its dependencies give it: the public sign-in routes have
  none, and a bearer token is never a sign-in on `/api`.
* **Capabilities.** [`GET /api/meta`](../../ARCHITECTURE.md#the-api-document-and-get-apimeta-design-note-14-changes-2-and-4) tells a signed-in client
  the versions, what it can use now (AI features, chat, voice, assistant tokens, phone shortcuts, the barcode providers, the handbook), the
  nutrient registry and the meal names.

## What it does not say yet

* The routes that read a raw body have no request schema: `POST /mcp` (JSON-RPC 2.0), `POST /push/v1/body` (its rules are in
  [`../push.md`](../push.md)), the photo routes (`image/jpeg`), `POST /api/ai/transcribe` (audio) and `POST /api/me/import`.
* Some success answers are untyped objects (`POST /api/auth/login`, for example).
* A status a handler raises that is not in the rules above is covered by `default` only.

Fixing any of these is additive: it adds to the file and does not raise the API version.
