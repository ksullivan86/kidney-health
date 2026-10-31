# Import a recipe: from a web page or pasted ingredients

**Plan → Saved meals → Import a recipe** turns a recipe into a saved recipe the app can count and fit to a person's targets. It
reads the ingredient list, matches each line to a food from the app's own list, and the person checks every match before saving.

This page is for the person who runs the server and for people who change the code. The contract is in
[`ARCHITECTURE.md`](../ARCHITECTURE.md) ("Recipe import") and the design is in
[`dev/research/30-list-sync-and-recipe-import.md`](dev/research/30-list-sync-and-recipe-import.md). The person's side is in the
handbook: **Planning, menus and shopping → Import a recipe**. Recipes themselves (servings, steps, Fit to my targets) are in
[`guidance.md`](guidance.md#recipes-that-fit).

## What a person sees

1. **Paste the ingredients**, one on each line, with a name and how many servings it makes. This always works and nothing leaves
   the server. Or, when the server owner turned it on, **paste the link of a recipe page**.
2. The app shows every ingredient line with the food it chose, the amount in servings, and a **Checked** box. The person can pick
   another of the suggestions, search for another food, or **leave the line out**. **Save** stays off until every line is
   checked.
3. Under the lines: one serving's potassium, phosphorus, sodium, protein, carbohydrate and the rest, the kidney warnings for one
   serving, and always this sentence: "These numbers are estimates. Recipe sites rarely list potassium or phosphorus, so the app
   works them out from its own food list. Cooking, soaking and draining change what ends up on the plate, and the app does not
   count that."
4. **Save recipe** saves it as a saved meal with its servings, the page's cooking steps and the page's link. Lines left out are
   named in the recipe's note ("Not counted: salt to taste").

What the app does with a line:

* It reads the amount and unit ("1 ½ cups", "2 (15-ounce) cans", "a pinch of"), the food words, and keeps what comes after a comma
  as a note ("3 cloves garlic, minced").
* It searches the person's own foods and the built-in list with the food words, then fewer words, and offers up to three foods.
* It works out the servings only when the food's serving allows it: a weight through the food's gram weight, a volume through a
  volume serving ("1/2 cup"), a count through a count serving ("1 large"). Otherwise the box is empty and the person types the
  number. **Never a guess, never 0.**
* A food that does not list a nutrient makes the total "at least" (or "not listed"), as everywhere in the app.
* The page's own nutrition panel is never used: it usually leaves out potassium and phosphorus.
* A food marked as a low treatment stays one in the recipe, as in any saved meal. Nothing here warns against treating a low.

## Turn on web pages (server owner)

Set `RECIPE_IMPORT_ENABLED=true` (or turn it on in **Server administration → Server settings → Shopping list app and recipe
import**). Pasting the ingredients works without it.

When it is on, **this server opens the page a person pastes**, from the internet:

* Only `http` and `https` links on the usual ports (80 and 443), with no user name or password in them.
* Through the app's SSRF-checked transport (`app/egress.py`): **private and local addresses are always refused**, and so are cloud
  metadata addresses. There is no allowlist for pages.
* Up to 3 redirects are followed; each new address is checked again the same way.
* At most 2 MiB of page, 15 seconds in all, and only HTML.
* The request carries no cookie, no key and nothing about the person. Its user agent is `kidney-health (recipe import)`.
* The server reads the page's schema.org `Recipe` data (the `<script type="application/ld+json">` blocks most recipe sites have)
  with Python's own HTML parser. Nothing on the page runs. **The page itself is never stored**; only its link is kept with the
  recipe.
* At most 20 pages an hour per person.

Because the destination is any public web site, a strict egress firewall must allow HTTPS to the internet for this to work. If you
cannot, leave it off: pasting works with no network.

## Errors

| Code | What the person reads |
|---|---|
| `bad_link` | That link cannot be read. Use a web address that starts with http:// or https://. |
| `blocked` | This server does not open that address. It may be a private or local address. |
| `unreachable`, `timeout` | The page did not answer, or took too long. Paste the ingredients instead. |
| `too_large`, `not_html`, `http_error` | The page is too large, not a web page, or the site did not give it. |
| `too_many_redirects` | That link sends the app on to too many other addresses. |
| `no_recipe` | This page has no recipe data the app can read. Paste the ingredients instead. |

## For people who change the code

* Server: `app/recipe_import/parse.py` (pure: JSON-LD, the ingredient-line parser, search words, amounts),
  `app/recipe_import/fetch.py` (the page), `app/recipe_import/api.py` (the routes and the draft).
* The demo cannot fetch: any link answers with a built-in sample page (`js/mock/lists.js`). The parser has a JavaScript twin,
  `js/engine/recipe_import.js`, pinned by `tests/data/lists_recipes_vectors.json` (`tests/data/gen_lists_recipes_vectors.py`;
  `node tests/js/run_vectors.mjs`).
* Screens: `js/views/recipe_import.js`. Tests: `tests/test_recipe_import.py` (a fake site behind the real transport,
  `tests/lists_support.py`), `tests/test_lists_recipes_ui.py`, and the Chromium walk `tools/e2e/lists_recipes.py`.
