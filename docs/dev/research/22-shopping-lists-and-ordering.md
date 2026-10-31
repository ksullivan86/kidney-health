# 22 · The shopping list outside the app: share, sync, order

| | |
|---|---|
| Status | Proposed, 2026-10-29. Part A (share and copy) is built; B is built for 0.19 ([note 30](30-list-sync-and-recipe-import.md), which changes some of §3); C is not. The owner asked for "integration with shopping list apps (open source) or ordering online or delivery (whatever makes it easy for someone to follow the guidance)". The choices in §6 are defaults the owner can change. |
| Scope | The week's shopping list that Plan already builds from planned entries (`GET /api/plan/shopping`) leaves the app in three ways, cheapest first: (A) share or copy it as text, (B) send it to a self-hosted, open-source list app, (C) open it at a grocery delivery service. |
| Out of scope | Prices, stock and store choice (the app has no data for them). Buying anything from inside the app. Sending the person's log, targets or health data anywhere: only the food names and amounts on the list leave. |
| Builds on | `app/meals.py` (`/api/plan/shopping`), `js/views/plan.js` (the list, ticks kept on the device), the SSRF-checked transport and write-only secrets used by AI providers (`app/ai/transport.py`, `app/credentials.py`), the settings registry (every setting an environment variable). |

## 1. Why

Following the guidance means buying the planned food. Today the list is on the Plan tab and its ticks stay on one phone. A person
who shops with a family list app, or a carer who shops for them, retypes it.

## 2. A. Share or copy (no setup, works with any app)

* **Share list** on the Plan tab opens the phone's share sheet (the Web Share API, text only) with one line per food: name and
  amount ("Rice, white, cooked: 3 cups"), grouped as the list on screen is, and the week it covers. Where the browser has no share
  sheet, **Copy list** puts the same text on the clipboard.
* Any list app takes it: Apple Reminders, Google Keep, Bring!, AnyList, and the open-source ones below.
* Nothing leaves the server: the browser hands the text to the phone. No setting, no network, no new route.
* Cost: about 0.3M tokens, with a test of the text format and a Chromium check of the button.

## 3. B. Send to an open-source list app (the person's own server)

For people who already run one at home, beside this app. Each person enters their app's address and a token in **Settings →
Shopping list app**; the token is write-only like other keys, and the address goes through the same SSRF-checked transport
(private addresses allowed only where the admin allows them, as for a local AI). **Send list** adds each food as one item.

| App | What the app would call (to verify against each project's current API docs before building) |
|---|---|
| **Grocy** | Its REST API with the `GROCY-API-KEY` header; a shopping list item can be free text (a note), so no product has to exist first. |
| **KitchenOwl** | Its REST API with a bearer token; items are added by name to a household's list. |
| **Mealie** | Its REST API with a bearer token; shopping list items with a note. |

* Off unless the admin turns on `shopping.sync_enabled` (env `SHOPPING_SYNC_ENABLED`) and the person enters an address.
* Sent: the food names and amounts on the list, nothing else. The activity log records each send (app, number of items).
* Items already sent for that week are not sent twice (a hash of the week's list is kept on the server).
* Cost: about 1.5-2M tokens for the three apps: settings, the client for each (with recorded answers as test fixtures), the send
  route, the Plan button, the demo's twin (it pretends to send), tests and docs.

## 4. C. Open it at a delivery service (another company: off by default)

Grocery delivery services that accept a shopping list (for example Instacart's developer platform, which turns a list into a
page on their site) are other companies. That goes against the project's rule that no third company is involved by default, so:

* Off unless the admin turns it on (`shopping.delivery_provider`, env `SHOPPING_DELIVERY_PROVIDER`), with the admin's own API key
  from that company, agreeing to its terms.
* The person sees **Open in <service>**, a sentence saying what will be sent (the food names and amounts, nothing else) and that
  the service's own privacy terms apply, and taps it each time. The answer is a link that opens in the browser; the person shops
  and pays there, never in this app.
* Not built until the owner decides: which service (availability is by country), whether its terms allow a self-hosted app,
  and whether it is worth it next to A, which already reaches the service's own app through the share sheet.

## 5. The list itself: make it worth following

Before B or C, two small changes make the list better for anyone:

* **Amounts people buy, not servings.** "Rice: 3 cups cooked" becomes "Rice: about 1 cup dry" only where the food list has the
  conversion; otherwise the serving stays. No guessing.
* **Kidney notes on the list.** A food with a potassium or phosphate additive says so on the list line, so the person checks the
  label in the shop ("check the label: phosphate additives").

## 6. Decisions for the owner

1. **Build A first** (share and copy). It covers most of the need with no setup and no other company.
2. **B for Grocy, KitchenOwl and Mealie**, all off unless the admin turns sync on.
3. **C waits** for the owner to choose a service, given the third-company rule.
4. **The list stays a plan, not a purchase**: ticks remain on the device; nothing in the log changes when something is bought.
