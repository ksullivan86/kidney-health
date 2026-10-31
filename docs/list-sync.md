# Your own list app: Grocy, KitchenOwl or Mealie

Each person can send the Plan's shopping list to their own **Grocy**, **KitchenOwl** or **Mealie**. Only the foods' names and
amounts are sent, nothing else about the person.

This page is for the person who runs the server and for people who change the code. The contract is in
[`ARCHITECTURE.md`](../ARCHITECTURE.md) ("Your own list app") and the design note, with what we read in each app's own source, is
[`dev/research/30-list-sync-and-recipe-import.md`](dev/research/30-list-sync-and-recipe-import.md). The person's side is in the
handbook: **Planning, menus and shopping**.

## What a person sees

* **Settings → Shopping list app.** The person picks the app, types its address (as they open it in a browser) and their key:
  * Grocy: an API key (Grocy → Settings → Manage API keys → Add);
  * KitchenOwl: a long-lived token (KitchenOwl → Settings → your profile → Sessions);
  * Mealie: an API token (Mealie → your profile → API Tokens).
* The key is **write-only**: the box stays empty and says "Saved". It is kept locked on the server and never shown again. A new
  address or another app needs the key typed again, so a saved key never goes to an address it was not typed for.
* **Test** checks the address and the key and lists the person's shopping lists. With one list, it is chosen; with more, the
  person picks one.
* **Plan → Shopping list → Send to Grocy** (or KitchenOwl, Mealie) first shows the exact lines that would be sent, one per food,
  in the same words as **Share list**: "Rice, white, cooked: 3 servings of 1/2 cup (79 g)". Foods already ticked on this phone
  start unticked. **Send** adds each ticked line as one item.
* The app does not remember what was sent before. The sheet says when the list was last sent and how many items; sending again
  adds them again (KitchenOwl itself skips an item already on its list).
* **Remove** forgets the address and the key. Nothing is changed in the list app.
* Settings → Account → Activity lists setting it up, removing it and each send (the app and how many items).
* Test accounts cannot set one up: they are shared by testers. The demo shows a sample Grocy and a fake list app inside the page.

## Turn it on (server owner)

1. Set `LIST_SYNC_ENABLED=true` (or turn on **Server administration → Server settings → Shopping list app and recipe import**).
2. If people's list apps run **on your home network** (an address like `192.168.1.20`, a name like `grocy.lan`, or a container
   name), list them in `LIST_SYNC_ALLOWED_HOSTS`: host names, addresses or networks, separated by commas:

   ```
   LIST_SYNC_ALLOWED_HOSTS=grocy.lan,192.168.1.0/24
   ```

   Every other private or local address stays refused. Cloud metadata, link-local and reserved addresses are always refused,
   even when listed. The variable is read at start-up only (an outbound allowlist is never changed in the app). `0.0.0.0/0`,
   wildcards and ports are refused.
3. If you route the server's outbound traffic through a proxy (`HTTPS_PROXY`), put the home host in `NO_PROXY` too.
4. On Kubernetes, also allow the list app in `deploy/k8s/networkpolicy.yaml` (an `ipBlock` for its address).

## The address rules

* `http` or `https`, with a host. No user name or password in the address (the key has its own box), nothing after `?` or `#`.
  A path is kept (`https://home.example.com/grocy`).
* **Plain `http` only for a listed home address.** On the internet, the key travels only over `https`: an `http` address that
  turns out to be public is refused when the request is made.
* Every request goes through the app's SSRF-checked transport (`app/egress.py`): the address is looked up and checked when each
  request is made, so a name that later points somewhere else is checked again.
* **Redirects are never followed.** A list app that answers with a redirect gets the error "The list app sent the app on to
  another address": enter the address it sends you to.
* At most 1 MiB of answer is read; a request gives up after 15 seconds.
* Limits per person: 200 foods a send, 6 sends and 30 tests an hour.

## What each app is asked

| | Grocy | KitchenOwl | Mealie |
|---|---|---|---|
| Key header | `GROCY-API-KEY` | `Authorization: Bearer` | `Authorization: Bearer` |
| Test | `GET /api/system/info` | `GET /api/user` | `GET /api/users/self` |
| Lists | `GET /api/objects/shopping_lists` | `GET /api/household`, then `GET /api/household/{id}/shoppinglist` | `GET /api/households/shopping/lists` |
| Add | `POST /api/objects/shopping_list` `{shopping_list_id, note}` | `POST /api/shoppinglist/{id}/add-item-by-name` `{name, description}` | `POST /api/households/shopping/items/create-bulk` `[{shoppingListId, note, quantity: 0}]` |

Grocy and Mealie get the whole line as the item's note. KitchenOwl gets the food's name as the item and the amount as its
description. These were read from each project's source on 2026-10-31 (links in the design note); tests pin each shape with a fake
of each app.

## Errors

| Code | What the person reads |
|---|---|
| `unreachable` | The list app did not answer. Check the address, and that this server can reach it. |
| `blocked` | This server does not connect to that address. A home address works only when your admin allows it. |
| `redirect` | The list app sent the app on to another address. Enter the address it sends you to. |
| `auth` | The list app did not accept the key. Check it, or make a new one. |
| `not_found` | The list app has no such page. Check the address, and that it is the right app. |
| `app_error` | The list app gave an answer the app could not read. |
| `no_key` | The key can no longer be read on this server. Enter it again. (The server's secret key changed.) |

A send that stops half way says how many items went first.

## For people who change the code

* Server: `app/list_sync/apps.py` (the address rules, the transport, one small class per app) and `app/list_sync/api.py` (the
  routes, the sealed key, the words of each line). Schema step 32 (`list_sync`).
* The key is sealed with the app's keyring (purpose `list-sync`, owner the person's id); `list_sync.key_enc` is in
  `ENCRYPTED_COLUMNS`, so `rotate-secret-key` re-encrypts it. It is registered with the log redaction when read.
* Screens: `js/views/list_sync.js`. Demo: `js/mock/lists.js`. The words of each line are pinned to the server by
  `tests/data/lists_recipes_vectors.json`.
* Tests: `tests/test_list_sync.py` (a fake of each app behind the real transport, `tests/lists_support.py`),
  `tests/test_lists_recipes_ui.py`, and the Chromium walk `tools/e2e/lists_recipes.py`.
