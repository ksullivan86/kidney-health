# Open Food Facts test fixtures

Single-product responses from the Open Food Facts product API, recorded once on 2026-10-06 by
`scripts/record_barcode_fixtures.py off` with the project's User-Agent
(`KidneyHealth/<version> (https://github.com/ksullivan86/kidney-health)`) and the exact `fields` list
the app requests (`app/off.py`). Tests replay them with `httpx2.MockTransport`; no test touches the
network. Each file holds the request URL, the HTTP status, the `Content-Type` and the JSON body as sent.

| File | Barcode | Why it is here |
|---|---|---|
| `diet_coke_v3.4.json` | 0049000028911 | US label, serving in mL (`counts_as_fluid`), E338 phosphoric acid, potassium not listed |
| `kraft_mac_cheese_v3.4.json` | 0021000658831 | Only *prepared* values; E451 triphosphates from the tags and the ingredient list |
| `lays_classic_v3.4.json` | 0028400090858 | US label with potassium listed, per-100 g values scaled to a 28.3 g serving |
| `nutella_v3.4.json` | 3017624010701 | EU label: salt (sodium derived from it), no serving size, carbohydrate excludes fibre |
| `nutella_v3.6.json` | 3017624010701 | API 3.6: `nutriments` is empty, the values are in `nutrition.aggregated_set` |
| `not_found_v3.4.json` | 0099999999990 | A valid code nobody has added: HTTP 404 `product_not_found` |
| `lays_1oz_v3.4.json` | 0028400421584 | In Open Food Facts without any nutrition facts (`no_nutrition`); FoodData Central has it |
| `lays_1125oz_v3.4.json` | 0028400161909 | In both Open Food Facts and FoodData Central (merge rule) |

Open Food Facts data can be edited by anyone; these copies keep its mistakes on purpose (the Lay's
record carries cheese categories and ingredients, Kraft's prepared fat does not match its calories),
because the app must cope with them.

## Licence and attribution

Contains information from [Open Food Facts](https://world.openfoodfacts.org), which is made available
here under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/).
Individual contents are under the [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/).
These few single-product records are insubstantial extracts kept only as test fixtures; the repository
and the container image ship no other Open Food Facts data (note 03 R11). Product pages:
`https://world.openfoodfacts.org/product/<barcode>`.
