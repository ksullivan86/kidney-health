# 33 · Open the Plan's shopping list at Instacart

| | |
|---|---|
| Status | Accepted and built for 0.22, 2026-11-01. No schema change. |
| Owner's words (2026-10-30, `docs/dev/progress/0.14-plan.md`) | "Grocery delivery, USA / California. Only the food list may go to the company. Phase 1: Instacart Developer Platform shopping-list link with the server owner's key (`INSTACART_API_KEY_FILE`), consent sheet showing the exact lines, off by default." Costco's same-day delivery runs through Instacart, so this one button covers it. |
| Builds on | Note 22 §4 (option C: a delivery service, another company, off by default), note 30 (the list sync: the shopping list items and their words, the checked transport, `egress.run_with_deadline`, fakes behind the real transport in tests). |
| Out of scope | Kroger and other services (phase 2, only if practical). Filling a cart or paying in this app. Product ids, UPCs, brands, health filters. Remembering a link. A Care helper sending another person's list. |

## 1. What Instacart offers (read 2026-11-01)

The Instacart Developer Platform turns a list into a page on Instacart's site. Read on 2026-11-01 from Instacart's own docs:

* [Create shopping list page](https://docs.instacart.com/developer_platform_api/api/products/create_shopping_list_page):
  `POST /idp/v1/products/products_link`. Production host `https://connect.instacart.com`, development host
  `https://connect.dev.instacart.tools`. Headers `Authorization: Bearer <API key>`, `Content-Type: application/json`,
  `Accept: application/json`. Body: `title` (required), `line_items` (required; each a `name`, the search term, required;
  optional `display_text`, `line_item_measurements` `[{quantity, unit}]`, `product_ids`, `upcs`, `filters`), and optional
  `image_url`, `link_type` (`shopping_list`, the default, or `recipe`), `expires_in` (days, at most 365, no default for a shopping
  list), `instructions`, `landing_page_configuration` (`partner_linkback_url`). `quantity` and `unit` on the line item itself
  are deprecated in favour of `line_item_measurements`. The answer is `{"products_link_url": "<link>"}`. Errors are `400` with
  a code (`9999` missing fields, `1001` a bad value). The page names no rate limit and no largest list.
* [Shopping list concept](https://docs.instacart.com/developer_platform_api/guide/concepts/shopping_list): the person opens the
  link, picks a store, reviews the items there and adds them to a cart; they sign in to Instacart (or make an account) to check
  out. `name` is the search term; `display_text` only changes what is shown. Quantities come from the measurements in order.
* [Units of measurement](https://docs.instacart.com/developer_platform_api/api/units_of_measurement): `g`, `kg`, `oz`, `lb`,
  `cup`, `ml`, `each`, `package` and more. An unsupported unit makes quantity matching fail.
* [API keys](https://docs.instacart.com/developer_platform_api/get_started/api-keys): made in the Instacart Developer Dashboard
  (`dashboard.instacart.com`) → API Keys → Create New API Key, choosing Development or Production. The key is shown once.
* [Approval process](https://docs.instacart.com/developer_platform_api/guide/concepts/launch_activities/approval_process) and the
  [pre-launch checklist](https://docs.instacart.com/developer_platform_api/guide/concepts/launch_activities/pre-launch_checklist):
  a production key stays "Pending approval" and does not work until Instacart reviews the app (the developer terms, requests
  that follow the spec, error handling, a help desk account). Instacart emails the answer.

## 2. Decisions

1. **Off by default, two locks.** The setting `lists.instacart_enabled` (env `INSTACART_ENABLED`, instance scope, off) and the
   server's own key `INSTACART_API_KEY_FILE`. Both are needed. The key is a file only: `INSTACART_API_KEY` is a start-up error,
   as for Withings and Whoop. It is never returned, logged or written to the activity list; it is registered with the log
   redaction when used. While either is missing, `GET /api/instacart` answers `200 {"enabled": false}` and the other routes 404.
2. **`INSTACART_BASE_URL`**, env only, default `https://connect.instacart.com`. `https://` with a host (and a port), nothing else:
   no path, user name, query or fragment. A host other than the two Instacart hosts starts with a warning. The owner uses
   `https://connect.dev.instacart.tools` with a development key while the production key waits for approval.
3. **Only the food list leaves.** For each food the person leaves ticked: `name` (the food's name), `display_text` (the same
   words as Share list and the list sync: "Rice, white, cooked: 3 servings of 1/2 cup (79 g)"), and, when the app knows the
   weight, `line_item_measurements: [{quantity: <grams, whole>, unit: "g"}]`. Without a weight, no measurement: Instacart then
   starts at 1 and the person sets the amount. The list's `title` is the fixed, plain **"Shopping list"**: the brand name
   "Kidney Health" would tell Instacart something about the person's health, so it is left out. `link_type: "shopping_list"` and
   `expires_in: 7` (a week of shopping; the link is made again each time). No `instructions`, `image_url`, linkback, product
   ids, brands or filters. Nothing about the person: no name, user id, targets, dates or address of this server.
4. **The server builds the lines.** The browser sends only the range and the food ids it keeps ticked. The server makes the
   lines from that range's shopping list (`app.meals.shopping_items`, the person's own planned entries), so no other text can be
   sent. Food ids not on that list are ignored; none left is `400`. At most 200 foods.
5. **Confirm each time.** Plan → Shopping list → **Open in Instacart** opens a sheet with the exact lines, a box for each (foods
   ticked on this phone start unticked), and the sentence: "Instacart is another company. Its own terms and privacy policy apply
   when you use its page." The person presses **Send to Instacart** each time. Nothing is remembered between sends.
6. **The browser never calls Instacart's API.** The server calls it and returns the link. The page opens the link in a new tab
   (`noopener`, `noreferrer`) and also shows it as a link to press, because a browser may block a tab opened after a wait. A link
   is used only when it is `https://` on `instacart.com` or `instacart.tools` (or a subdomain), at most 2,048 characters,
   without a user name; anything else is the error `bad_answer`.
7. **Egress.** `egress.CheckedTransport` with private addresses always refused (Instacart is a public host), redirects never
   followed (a `3xx` is the error `bad_answer`), at most 64 KiB of answer, 15 seconds a request and 20 seconds in all through
   `egress.run_with_deadline("instacart", …)`. Like the other fixed public hosts, an outbound proxy in `HTTPS_PROXY` is used.
8. **Errors** in short codes, each with one plain sentence: `unreachable`, `blocked`, `auth` (401, 403: the key), `rejected` (400,
   404, 422: Instacart refused the list), `busy` (429, 5xx), `bad_answer`, `timeout`. Exception text never reaches a response or
   a log line; logs say only the code.
9. **Limit**: `instacart_send` 10 an hour per person.
10. **Audit**: `instacart.sent` with `items` (how many lines) only, person-visible, for every send that reached the network
    (not for `blocked`). Nothing else is stored: not the list, not the link.
11. **Who.** Every signed-in person, test accounts too (nothing of theirs is stored, the limit holds, and testers can try it).
    Only their own Plan: the Care team's shopping list for someone else does not offer it.
12. **Demo.** The demo answers like a server with Instacart on. Send gives a placeholder that does not leave the page, and the
    sheet says nothing was sent.

## 3. API

| Method and path | Auth | Body → response |
|---|---|---|
| `GET /api/instacart` | signed in | `{enabled, max_items}`. Always 200 |
| `POST /api/instacart/preview` | signed in | `{start, end}` → `{title, items: [{food_id, name, amount, text}]}`. 404 while off |
| `POST /api/instacart/send` | signed in | `{start, end, food_ids (1–200)}` → `{url, items, error, message}`. 400 none of them on the list; 404 while off; 429 |

## 4. Decisions the owner may change

* The title "Shopping list" instead of the brand name.
* Grams as the only measurement (a countable food such as eggs is then matched by weight).
* `expires_in: 7` days.
* Test accounts may use it.
* 10 sends an hour per person.
