---
title: Logging food
description: "Search for a food or scan its barcode, log it by servings or grams, type in a label with Quick add, import from USDA, keep your own foods, and log while offline."
slug: logging
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-07
fact_checked: 2026-10-05
sources: [ARCH, FDC, FDC-API, FDA-label, DG38, NOTE02, NOTE03, NOTE06, A26-6]
---

# Logging food

Logging means telling the app what you ate, how much, and at which meal. It then adds up your day and
shows warnings **before** you save, so you can change the portion first ([architecture contract][ARCH]).

## The quick way: search

1. Tap **Add**.
2. Type a few words, for example `rice white`. Every word must match, so fewer words find more. With
   the box empty you see **Recent foods**, the ones you log most recently, first.
3. Tap a category chip (**Fruits**, **Vegetables**, **Beverages** …) to narrow the list.
4. Tap the food. The sheet shows its warnings and the numbers **for this amount**.
5. Pick the meal (**Breakfast**, **Lunch**, **Dinner** or **Snack**) and the amount.
6. Choose **Eaten** or **Planned**. Today and past days start on Eaten, future days on Planned.
7. Tap **Add to meal**.

The builtin list has about 400 common foods from USDA FoodData Central, each with a household serving
such as "1 cup (158 g)" ([USDA FoodData Central][FDC]).

## Servings or grams

You can enter **servings** (steps of ¼) or **grams**. If you weigh your food, type the grams and the app
works out the servings for you.

| You ate | Food's serving | Enter | The app logs |
|---|---|---|---|
| 1 cup of cooked white rice | 1 cup (158 g) | 1 serving | 45 g carbs, 55 mg potassium |
| 100 g of the same rice, weighed | 1 cup (158 g) | 100 grams | 0.63 servings: 28 g carbs, 35 mg potassium |
| half a banana | 1 medium (118 g) | 0.5 servings | 13.5 g carbs, 211 mg potassium |

Weighing is the most accurate way to count carbohydrate ([Carb counting](../eat/carb-counting.md)).

## Change or delete an entry

On **Today**, tap the entry. Change the amount, meal, day or note, then **Save changes**, or tap
**Delete**. Planned entries have an **Eaten** button; **Mark all eaten** turns a whole meal's plan into
eaten food ([Planning meals](planning-and-menus.md)).

## Quick add: type in a label

Use **Add → Quick add** for a packaged food that is not in the list.

1. Enter the **name** and the **serving** as the label says it ("2 cakes") and its weight in grams.
2. Copy the numbers **per serving** from the Nutrition Facts label.
3. **Leave a box empty** when the label does not list that nutrient. Do not type 0: empty means
   "unknown", and the app tells you a total may be low.
4. Copy the ingredient list into **Ingredients** (optional, but worth it). The app checks it as you
   type and shows "Phosphate additives" or "Potassium additives" when it finds one (for example sodium
   phosphate or potassium chloride); saving sets the same flags. You can also tick them yourself under
   **Flags**, and **Counts as fluid** for drinks.
5. If the package has a barcode, type its digits into **Barcode** (optional): scanning it next time finds
   this food.
6. Enter how many servings you ate, then tap **Log it**. The food is kept as **your own food** for next
   time.

**Use a photo of the label** shows a picture of the label beside the form (above it on a phone), with
1×, 2× and 3× zoom, so you can copy the numbers without holding the package. The photo stays on your
phone. If your admin turned on AI and you opted in, **Read the label for me (AI)** fills in the boxes
from the photo; fields filled this way are marked "from photo" until you check and change them
([Optional AI](ai.md)).

On a US label potassium must be listed, but phosphorus does not have to be
([FDA][FDA-label]; [NKF label guide][DG38]). See [Reading a label](../eat/label-reading.md) for what
each line means.

## Scan a barcode

**Add → Scan a barcode** reads a packaged food's barcode with the camera, from a photo, or from the
digits you type. Your phone reads the code itself and sends only the number to your server. A food you
saved with that barcode is always found; other products are looked up only if your admin turned on
barcode lookups ([design note 03][NOTE03]). The details, and what to do when a product is not found,
are on [Barcodes and label photos](barcode-and-photo.md).

## Search USDA

If your admin added a USDA key, **Add → Search USDA** looks through the full FoodData Central
database, including branded foods. Tap **Import** to copy one into your list. Imported foods use a
100 g serving unless USDA gives a household portion, so check the serving before you log
([architecture contract][ARCH]). You can also add your own free USDA key in **Settings → Food data**
([USDA API guide][FDC-API]; [Settings and keys](settings-and-keys.md)).
"USDA search is not set up on this server" means nobody has added a key yet: add your own, or ask
your admin to share one.

## Your own foods

- Builtin foods cannot be changed, and neither can foods imported from USDA or found by barcode: they
  are shared reference data that you add to **your list**. A food you add with **Quick add** is
  **yours** and only you can see it.
- To remove a food from your list, open it from **Add** and tap **Delete food**. If one of your own
  foods is already in your log, it is only hidden from search; your old entries keep their numbers.
- To fix a mistake in one of your foods, add it again with the right numbers and delete the old one.
- Each entry keeps a **snapshot** of the numbers at the time you logged it, so fixing a food later does
  not rewrite your history.

## Low treatments

!!! danger "Treat first, log later"
    If your glucose is under 70 mg/dL (3.9 mmol/L), treat it straight away with 15 g of fast
    carbohydrate, check again after 15 minutes, and repeat if you are still low ([ADA 2026][A26-6],
    section 6; [Treating a low](../t1d/treating-a-low.md)). Log it afterwards.

- Search `glucose` to find glucose tablets, gel and liquid shots. Measured juices, lemon-lime soda,
  ginger ale, hard candy, jelly beans, honey and sugar in a treatment-sized portion are marked as low
  treatments too.
- These foods get **no carbohydrate warning**: fast carbohydrate is the point. Their potassium, sodium
  and fluid still count, so you can see which treatment suits your kidneys best
  ([Targets and warnings](targets-and-warnings.md)).
- **Used to treat a low**: the box under the warnings when you log a low-treatment food (ticked for
  you), or any food if you have diabetes. A ticked entry still counts toward your potassium, sodium and
  fluid for the day, but never toward the meal's carbohydrate or the meal suggestions, and the warnings
  become a plain note with the numbers. Instead of swap ideas the sheet then shows **For your next low**:
  other low treatments with at least your usual treatment amount and less potassium ([design note
  06][NOTE06]; [Meal guidance](guidance.md)).

## Offline

**Add**, **Quick add** and **Mark eaten** also work with no connection. The entry waits on
your phone with a "waiting to sync" badge and is sent when you are back online, once, even if the
connection drops halfway. A badge at the top shows how many entries wait; tap it to see them. Editing or
deleting an older entry, changing your profile, scanning a barcode and meal suggestions still need the
server, and the app says so instead of saving it ([design note 02][NOTE02];
[Install the app](install.md)).

Your phone also keeps a copy of the last two weeks and the coming week, so **Today** opens while you are
offline when the app was installed from an `https://` address (it says it is showing the copy saved on
this device), and search finds the foods this phone has
seen. Signing out deletes everything the app kept on the phone, so it asks first when entries are still
waiting to sync.

If the server refuses a waiting entry when it arrives (for example, the food was deleted in the
meantime), the entry is kept as **not saved** with the reason under **Settings → This device**. Tap
**Retry** or **Discard**; nothing is thrown away without you seeing it.

## What to do

- [ ] Log as you go, not at the end of the day. Include drinks, sauces and low treatments.
- [ ] Weigh foods you eat often for a week, then you will know your usual portions
      ([Portions](../eat/portions.md)).
- [ ] Check the serving size on every Quick add and USDA import.
- [ ] Save meals you repeat ([Planning meals](planning-and-menus.md)).

## If something goes wrong

- **"No foods match."** Use fewer words or a different word ("chicken breast" instead of "grilled
  chicken"), try **Quick add**, or search USDA.
- **The numbers look far too high.** The serving is probably 100 g while you ate less, or the other way
  round. Enter grams instead.
- **A food has no potassium value.** Check the package label and add a corrected copy with
  **Quick add**.

## Related pages

- [Targets and warnings](targets-and-warnings.md) · [Planning meals](planning-and-menus.md) · [Barcodes and label photos](barcode-and-photo.md)
- [Carb counting](../eat/carb-counting.md) · [Reading a label](../eat/label-reading.md) · [Portions](../eat/portions.md)

## Sources

- [Project architecture contract][ARCH]: search, servings and grams, Quick add, USDA import, snapshots.
- [USDA FoodData Central][FDC]; [USDA API guide][FDC-API].
- [FDA: changes to the Nutrition Facts label][FDA-label]; [NKF label guide][DG38].
- [Design note 02][NOTE02] (offline logging); [design note 03][NOTE03] (barcodes, ingredients, label
  photos); [design note 06][NOTE06] (low treatments in guidance).
- [ADA Standards of Care 2026, section 6][A26-6]: treating a low.
