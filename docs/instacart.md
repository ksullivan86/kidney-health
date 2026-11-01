# Open the shopping list at Instacart

A person can open the Plan's shopping list at **Instacart**. Instacart makes a page with the foods, where the person picks a
store, checks the items and pays. Costco's same-day delivery runs through Instacart, so this covers it too. It is off unless the
person who runs the server turns it on with the server's own Instacart key.

This page is for the person who runs the server and for people who change the code. The contract is in
[`ARCHITECTURE.md`](../ARCHITECTURE.md) ("Open the shopping list at Instacart") and the design note, with what we read in
Instacart's docs, is [`dev/research/33-instacart.md`](dev/research/33-instacart.md). The person's side is in the handbook:
**Planning, menus and shopping**.

## What a person sees

* **Plan → Shopping list → Open in Instacart** shows the exact lines first, one per food, in the same words as **Share list**:
  "Rice, white, cooked: 3 servings of 1/2 cup (79 g)". Foods already ticked on this phone start unticked.
* The sheet says that Instacart is another company and that its own terms and privacy policy apply on its page.
* **Send to Instacart** sends the ticked lines. The person presses it each time; nothing is remembered between sends.
* The server gets a link back. The page opens it in a new tab and also shows it as a button, in case the browser blocked the tab.
  The link works for 7 days. The app does not keep it.
* Settings → Account → Activity lists each send with the number of items.
* The demo has the button too, but nothing leaves the page.

## What is sent

Only on **Send to Instacart**, from this server to Instacart:

* the title "Shopping list";
* for each ticked food: its name (Instacart searches with it), the line the person saw, and its weight in grams when the app
  knows it.

Nothing else: no name, user name, account id, targets, dates, diagnosis or the address of this server. The title is plain on
purpose: "Kidney Health" would tell Instacart something about the person's health. For the same reason, give your developer app
a plain name in Instacart's dashboard.

When the person opens the page, they are on Instacart's own site. Instacart asks them to sign in or make an account to check out,
and from then on Instacart's terms and privacy policy apply.

## Turn it on (server owner)

1. **Get a key.** Sign in to the Instacart Developer Dashboard (`dashboard.instacart.com`) → **API Keys** → **Create New API Key**.
   Choose **Development** first. Copy the key: Instacart shows it only once.
2. **Put the key in a file** that only the app can read, and point `INSTACART_API_KEY_FILE` at it. The key is never an
   environment variable (`INSTACART_API_KEY` stops the server at start-up), never shown in the app and never written to a log.

   ```
   install -m 0600 /dev/null deploy/secrets/instacart_api_key
   $EDITOR deploy/secrets/instacart_api_key
   ```

   Then uncomment `INSTACART_API_KEY_FILE` and the `instacart_api_key` secret in `deploy/compose.yaml` (Quadlet and Kubernetes
   have the same lines, commented out).
3. **Use the development host with a development key**:

   ```
   INSTACART_BASE_URL=https://connect.dev.instacart.tools
   ```

   Leave it empty for production (`https://connect.instacart.com`).
4. **Turn it on**: `INSTACART_ENABLED=true`, or **Server administration → Server settings → Instacart**. Both the switch and the
   key are needed. Without the key, the button stays hidden.
5. **Ask for a production key** when it works. Instacart reviews the app before a production key works (it says "Pending
   approval" until then). The review looks at its developer terms, that the requests follow its API, that errors are handled,
   and that you have a help desk account. Instacart answers by email. Then put the production key in the file, empty
   `INSTACART_BASE_URL` and restart.
6. **Network.** The server needs HTTPS to `connect.instacart.com` (or the development host). A firewall that allows only listed
   hosts must allow it ([network-allowlist.md](network-allowlist.md)). The server uses `HTTPS_PROXY` when one is set, like the
   other outside services.

## How the call is made

* `POST {INSTACART_BASE_URL}/idp/v1/products/products_link` with `Authorization: Bearer <key>` and

  ```json
  {"title": "Shopping list", "link_type": "shopping_list", "expires_in": 7,
   "line_items": [{"name": "Rice, white, cooked", "display_text": "Rice, white, cooked: 3 servings of 1/2 cup (79 g)",
                   "line_item_measurements": [{"quantity": 237, "unit": "g"}]}]}
  ```

  A food without a known weight has no measurement; Instacart then starts at 1 and the person sets the amount.
* The answer's `products_link_url` is used only when it is an `https://` link on `instacart.com` or `instacart.tools`.
* Every request goes through the app's SSRF-checked transport (`app/egress.py`): private and cloud metadata addresses are refused,
  redirects are never followed, at most 64 KiB of answer is read, 15 seconds a request and 20 seconds in all.
* The browser never calls Instacart's API. It calls this server, which answers the link.
* Limits per person: 200 foods a send, 10 sends an hour.

## Errors

| Code | What the person reads |
|---|---|
| `unreachable` | Instacart did not answer. Try again later. |
| `blocked` | This server could not reach Instacart. Ask the person who runs it to check its network. |
| `auth` | Instacart did not accept this server's key. Ask the person who runs the server to check it. |
| `rejected` | Instacart did not accept the list. Try again with fewer foods, or later. |
| `busy` | Instacart is busy. Try again in a few minutes. |
| `bad_answer` | Instacart gave an answer the app could not use. Try again later. |
| `timeout` | Instacart took too long to answer. Try again later. |

`auth` usually means the key is wrong, or a production key is still waiting for approval, or a development key is used with the
production host (or the other way round). The server log says only the code and the HTTP status, never the key, the list or the
link.
