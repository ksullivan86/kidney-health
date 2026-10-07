# USDA FoodData Central test fixtures

FoodData Central Branded Foods data is in the public domain (CC0 1.0); citation: U.S. Department of
Agriculture, Agricultural Research Service. FoodData Central, 2019. fdc.nal.usda.gov.

Tests replay these files as answers of the documented API (`https://api.nal.usda.gov/fdc/v1`,
`GET /foods/search?query=<barcode form>&dataType=Branded&pageSize=10` and `GET /food/{fdcId}`) with
`httpx2.MockTransport`; no test touches the network.

| File | What it is |
|---|---|
| `rate_limited.json` | A real API answer (2026-10-06): `429 OVER_RATE_LIMIT` for `DEMO_KEY` (`Retry-After: 24080`) |
| `search_<form>.json` | The branded search for one barcode form (12-, 13- or 14-digit); `028400421584`, `00028400161909` and `00049000028911` find the product, the other forms find nothing |
| `food_1633665.json` | Lay's Classic Potato Chips 1 oz (GTIN `028400421584`, stored as 12 digits) |
| `food_1458203.json` | Lay's Classic Potato Chips 1.125 oz (GTIN `00028400161909`, stored as 14 digits) |
| `food_2742723.json` | Diet Coke 12 fl oz (GTIN `00049000028911`), potassium 0 on the label |

**Provenance (read this before re-using them).** On 2026-10-06 the API answered `429 OVER_RATE_LIMIT`
to `DEMO_KEY` from the development network after the first call (as note 03 F3 predicted: "treat
DEMO_KEY as unusable"), and no personal key was available. The search and food bodies were therefore
recorded the same day from the FoodData Central web application's own endpoints
(`POST https://fdc.nal.usda.gov/portal-data/external/search` and
`GET https://fdc.nal.usda.gov/portal-data/external/{fdcId}`), which serve the same database. Each
file says so in its `source` field. Differences from the public API: a food record names each
nutrient amount `value` (the API's `FoodNutrient` uses `amount`) and has no `fdcId` key (the URL
carries it); the search answer's `aggregations` block was dropped. The app's parser accepts both
spellings. To replace them with API recordings, run
`USDA_API_KEY=<your key> python3 scripts/record_barcode_fixtures.py usda`.
