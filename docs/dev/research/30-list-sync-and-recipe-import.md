# 30 · The shopping list in your own list app, and recipes from a web page or pasted ingredients

| | |
|---|---|
| Status | Accepted and built for 0.19, 2026-10-31. Schema step **32**. |
| Owner's words (2026-10-31) | "Send the shopping list to the person's own Grocy, KitchenOwl or Mealie (note 22 option B). Each person adds their own server's address and key in Settings. Only the list of foods (names and amounts) is sent, nothing else about the person." And: "Recipes from a web page or pasted ingredients. The person's server fetches the page (never the browser), through the same SSRF-checked transport as Whoop and Withings. It reads the page's schema.org `Recipe` data. Pasting ingredients works with no network. Each ingredient is matched to a food like any item; the result shows per-serving totals and the kidney warnings, says plainly the numbers are estimates, and saves as a saved meal (recipe) with the source link. The person confirms or fixes every match before saving." The privacy filter for cloud AI moved to 0.20. |
| Changes | The ROADMAP line "web fetching stays in the chat client; the app keeps talking only to USDA, Open Food Facts and its AI provider" (note 16 §13 said the same) is replaced by the owner's decision above: the server fetches a recipe page when the admin turns it on. Note 22 §3's "items already sent for that week are not sent twice" is replaced by §2.6. |
| Builds on | Note 22 (the list leaving the app; part A, share and copy, is built), note 16 (recipes: `servings_made`, `steps`, `source_url`, per-serving numbers with unknowns), note 27 and 28 (env switches, secrets sealed per person, the checked transport, fakes behind it in tests), `app/ai/features.py` (`servings_for`, the describe-a-meal matching). |
| Out of scope | The cloud AI privacy filter (0.20). Grocery delivery (note 22 part C). Reading a site's nutrition panel. Cooking losses and leaching as numbers. Photos of recipes. Syncing ticks back from the list app. |

## 1. What the three list apps offer (checked 2026-10-31)

Read from each project's own source on 2026-10-31 (their API reference pages are generated from these files):

* **Grocy**: the OpenAPI file in the repository, [`grocy.openapi.json`](https://github.com/grocy/grocy/blob/master/grocy.openapi.json).
* **KitchenOwl**: the backend routes, [`register_controller.py`](https://github.com/TomBursch/kitchenowl/blob/main/backend/app/api/register_controller.py),
  [`shoppinglist_controller.py`](https://github.com/TomBursch/kitchenowl/blob/main/backend/app/controller/shoppinglist/shoppinglist_controller.py),
  [`shoppinglist/schemas.py`](https://github.com/TomBursch/kitchenowl/blob/main/backend/app/controller/shoppinglist/schemas.py),
  [`household_controller.py`](https://github.com/TomBursch/kitchenowl/blob/main/backend/app/controller/household/household_controller.py),
  [`user_controller.py`](https://github.com/TomBursch/kitchenowl/blob/main/backend/app/controller/user/user_controller.py) and
  [`auth_controller.py`](https://github.com/TomBursch/kitchenowl/blob/main/backend/app/controller/auth/auth_controller.py) (long-lived tokens).
* **Mealie**: [`routes/households/controller_shopping_lists.py`](https://github.com/mealie-recipes/mealie/blob/mealie-next/mealie/routes/households/controller_shopping_lists.py),
  [`schema/household/group_shopping_list.py`](https://github.com/mealie-recipes/mealie/blob/mealie-next/mealie/schema/household/group_shopping_list.py),
  [`schema/recipe/recipe_ingredient.py`](https://github.com/mealie-recipes/mealie/blob/mealie-next/mealie/schema/recipe/recipe_ingredient.py)
  (how an item's `display` is made), [`schema/_mealie/mealie_model.py`](https://github.com/mealie-recipes/mealie/blob/mealie-next/mealie/schema/_mealie/mealie_model.py)
  (camelCase names) and [`routes/users/crud.py`](https://github.com/mealie-recipes/mealie/blob/mealie-next/mealie/routes/users/crud.py).

| | Grocy | KitchenOwl | Mealie |
|---|---|---|---|
| Key | An API key made in Grocy (Manage API keys), sent as the header `GROCY-API-KEY`. | A long-lived token (Profile → Sessions; `POST /api/auth/llt`), sent as `Authorization: Bearer`. | An API token (Profile → API tokens), sent as `Authorization: Bearer`. |
| Test | `GET /api/system/info` (answers `grocy_version`). | `GET /api/user`. | `GET /api/users/self`. |
| Lists | `GET /api/objects/shopping_lists` → `[{id, name}]`. | `GET /api/household` → `[{id, name}]`, then `GET /api/household/{id}/shoppinglist` → `[{id, name, items, …}]`. | `GET /api/households/shopping/lists?page=1&perPage=50` → `{items: [{id, name}]}`. |
| Add one item | `POST /api/objects/shopping_list` `{"shopping_list_id": <id>, "note": "<text>"}`: an item may be free text, with no product. | `POST /api/shoppinglist/{id}/add-item-by-name` `{"name": "<food>", "description": "<amount>"}`: KitchenOwl finds or makes the item by name; an item already on the list is left as it is. | `POST /api/households/shopping/items/create-bulk` `[{"shoppingListId": "<uuid>", "note": "<text>", "quantity": 0}]`: with quantity 0 and no food or unit, the item shows exactly the note. |

Not tried against a real server here (no network for tests); every request shape is pinned by a fake of each app in the tests.

## 2. List sync: decisions

1. **Off by default.** `LIST_SYNC_ENABLED` (setting `lists.sync_enabled`, admin). While off, `GET /api/list-sync` answers `200`
   with `enabled: false` (Settings and Plan ask on every open), every other `/api/list-sync` route is `404`, and nothing is sent.
2. **Per person.** Each person enters their app (Grocy, KitchenOwl or Mealie), its address and their key in **Settings → Shopping
   list app**, then picks one of their lists after **Test**. Test accounts cannot set one up (shared by testers; a real key must
   not land there), as for connected devices.
3. **The key is write-only.** Sealed with the app's keyring (purpose `list-sync`, owner the person's id), so a copied row does not
   open for another person; `list_sync.key_enc` is in `ENCRYPTED_COLUMNS` for key rotation. The API shows only "set" or "not set";
   the key is registered with the log redaction whenever it is read and never written to a log or an audit row. **A new address
   needs the key again**: changing the address with the stored key is refused, so a stored key can never be sent to a host the
   person did not type it for.
4. **Addresses.** `http` or `https`, a host, no user name or password, no query or fragment. A path is kept (a list app behind
   `/grocy`). Every request goes through `app.egress.CheckedTransport`: the address is checked when each request is made, cloud
   metadata, link-local and reserved addresses are always refused, redirects are never followed (a `3xx` answer is an error that
   says so), at most 1 MiB of answer is read and a request gives up after 15 seconds. **Private addresses** (a list app at home:
   `192.168.x.x`, `grocy.lan`, `localhost`) are refused unless the admin lists the host name, address or a network in the env-only
   `LIST_SYNC_ALLOWED_HOSTS` (for example `grocy.lan,192.168.1.0/24`). Plain `http` is allowed only for a host on that list: on the
   internet the key must travel over `https`. The standard proxy variables apply as for the other outbound calls; put a home host
   in `NO_PROXY`.
5. **What is sent**: for each food of the list, one item: the food's name and the amount as Plan's "Share list" writes it
   ("Rice, white, cooked: 3 servings of 1/2 cup (79 g)"). Grocy and Mealie get that line as the item's note; KitchenOwl gets the
   name as the item and the amount as its description. Nothing else: no date, no targets, no health data, no name of the person.
6. **Preview, then Send.** Plan → Shopping list → **Send to <app>** shows the exact lines first, with a box per line (foods already
   ticked on this phone start unticked). **Send** sends the ticked lines and says how many went. There is no "already sent"
   memory: the preview says when the list was last sent and how many items, and KitchenOwl itself skips an item already on its
   list. At most 200 items a send, 6 sends and 30 tests an hour per person.
7. **Activity.** The person's activity list records setting it up, removing it and each send (the app and the number of items).
8. **Demo.** The demo shows a sample Grocy at `http://grocy.example` with a key set; Test, preview and Send work against a fake
   in the page, which keeps what was sent in memory. Nothing leaves the page.

## 3. Recipe import: decisions

1. **Pasted ingredients always work** (no network, nothing leaves the server). **A web page needs the admin's switch**
   `RECIPE_IMPORT_ENABLED` (setting `recipes.import_enabled`, admin, off). `GET /api/recipe-import` always answers `200` and says
   whether pages can be read; while off, `POST /api/recipe-import/page` is `404`.
2. **Fetching** (`app/recipe_import/fetch.py`): the server, never the browser. Only `http` and `https` links that pass
   `models.check_source_url`, on the usual ports (80 and 443). Private and local addresses are always refused (there is no
   allowlist for pages). Up to 3 redirects are followed, each one checked again as a new link; at most 2 MiB of page, 15 seconds in
   all; only `text/html` (or `application/xhtml+xml`). The request carries no cookie, no key and nothing about the person. At most
   20 pages an hour per person.
3. **Reading** (`app/recipe_import/parse.py`): the standard library's `html.parser` collects every
   `<script type="application/ld+json">` block; nothing on the page runs. Each block is read as JSON; the first `Recipe` is taken
   from a plain object, an array, an `@graph`, or a `mainEntity` (to 6 levels). `@type` may be a string or a list. Taken: `name`,
   `recipeYield` (the first number in it, 1 to 100), `recipeIngredient` (or the old `ingredients`), and `recipeInstructions` (text,
   a list of text, `HowToStep`, `HowToSection`). The page's own `nutrition` is ignored: it usually leaves out potassium and
   phosphorus. Tags and entities in any text are removed. **The page itself is never stored**; only the link the person typed is
   saved, as the recipe's `source_url`.
4. **Steps** become the recipe's steps, within the existing limits: at most 20 steps of at most 500 characters. A longer step is
   split at sentence ends; past 20 the rest is left out and the screen says so.
5. **Ingredient lines** (`parse_line`, a small parser with a JavaScript twin): unicode fractions and mixed numbers ("1 ½", "1½"),
   ranges (the first number: "2–3 carrots" is 2), number words ("a", "one" to "twelve"), units (g, kg, oz, lb, ml, l, cup, tbsp,
   tsp, fl oz, pinch, dash, clove, slice, piece, can), a package size in brackets ("1 (14.5 oz) can" is 14.5 oz), and the
   preparation after a comma kept as a note ("3 cloves garlic, minced"). A line without a number keeps no amount ("Salt to taste").
6. **Matching** (`search_terms`, twin): the food words lose brackets, the preparation, size and cooking words, "or …" alternatives
   and plurals; the server then runs the app's own food search (the person's own foods and the built-in list, as in Add) with all
   words, then the last two, then the last one, then the first, and keeps the first three foods of the first search that finds any.
7. **Amounts** (`recipe_servings`, twin): weight units become servings through the food's gram weight; volume units through the
   food's serving when it is a volume ("1/2 cup"); a count ("2 eggs", "3 cloves") through a serving that is a count ("1 large",
   "1 clove"). Anything else has **no amount**: the person types the servings. Never a guess, never 0.
8. **The person confirms every line.** The review sheet shows each ingredient line with the suggested food, the amount in
   servings, and a box "Checked". Save stays off until every line is checked or left out. A line can take another food (search) or
   be left out. Lines left out are named in the recipe's note ("Not counted: salt to taste; 1 tsp thyme") and the sheet says how
   many are not counted.
9. **Numbers.** One serving's key numbers come from the matched foods, the same way as the saved-meal editor (a nutrient a food
   does not list is "not listed" or "at least", never 0), with each food's kidney rating and warnings, and the warnings for one
   serving (`food_warnings` with `scope` "in one serving"). Under them, always: "These numbers are estimates. Recipe sites rarely
   list potassium or phosphorus, so the app works them out from its own food list. Cooking, soaking and draining change what ends
   up on the plate, and the app does not count that."
10. **Saving** is the ordinary `POST /api/meals` with `servings_made`, `steps`, `source_url` and the note: every rule of saved meals
    runs again. A food marked as a low treatment stays one, as in any saved meal; no line is ever refused or warned against for
    being a low treatment.
11. **Demo.** The demo cannot fetch: any link answers with a built-in sample recipe page (its `Recipe` data, kept in the page) and
    the same parser and matcher as the server; pasted ingredients work as on a server.

## 4. Data (schema step 32)

```
list_sync(user_id PRIMARY KEY → users ON DELETE CASCADE, app, base_url, list_id, list_name, key_enc, key_id,
          last_test_at, last_test_error, last_sent_at, last_sent_count, created_at, updated_at)
```

No table for recipe import: nothing is kept but the saved meal.

## 5. API

| Route | What |
|---|---|
| `GET /api/list-sync` | Always 200: `{enabled, can_use, apps, connection}`; the connection has `app`, `base_url`, `list_id`, `list_name`, `key_set`, the last test and the last send. Never the key. |
| `PUT /api/list-sync` | `{app, base_url, key?, list_id?, list_name?}`. The key may be left out only while the app and address stay the same. 403 for a test account. |
| `DELETE /api/list-sync` | Removes the address and key. 404 when there is none. |
| `POST /api/list-sync/test` | `{ok, error, lists}`. `error` is a short code: `unreachable`, `blocked`, `redirect`, `auth`, `not_found`, `app_error`. |
| `POST /api/list-sync/preview` | `{start, end}` → `{app, list_name, items: [{food_id, name, amount, text}], last_sent_at, last_sent_count}`. |
| `POST /api/list-sync/send` | `{start, end, food_ids}` → `{sent, error}`. Only foods of that range's list; 409 before a list is chosen; 429 past the hourly limit. |
| `GET /api/recipe-import` | Always 200: `{web, max_lines}`. |
| `POST /api/recipe-import/page` | `{url}` → a draft. 404 while the switch is off; 400 for a link that is not allowed; 422 with a plain reason when the page has no recipe. |
| `POST /api/recipe-import/text` | `{text, name?, servings?}` → a draft. |

A draft is `{name, servings_made, steps, steps_cut, source_url, lines: [{text, amount, unit, food_text, note, matches:
[{food, servings}]}], notice}`. Every route needs a signed-in person and reaches only that person's rows and foods.

## 6. Decisions the owner may change

1. Switch names: `LIST_SYNC_ENABLED` and `RECIPE_IMPORT_ENABLED` (note 22 proposed `SHOPPING_SYNC_ENABLED`).
2. Pasted ingredients work with the switch off; the switch covers only reading web pages.
3. Private list-app addresses only through the env-only `LIST_SYNC_ALLOWED_HOSTS`; plain `http` only for those hosts.
4. A new address needs the key typed again.
5. No "already sent" memory (note 22 had one); the preview shows the last send instead.
6. Limits: 200 items a send; 6 sends, 30 tests and 20 recipe pages an hour per person; 2 MiB and 15 s per page; 3 redirects;
   ports 80 and 443 for pages; 60 ingredient lines.
7. A range of amounts takes the first number; "a pinch" and "a dash" have no amount.
8. Test accounts cannot set up list sync; they can import recipes.
