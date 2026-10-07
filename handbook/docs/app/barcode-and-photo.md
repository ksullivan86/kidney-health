---
title: Barcodes and label photos
description: "Scan a packaged food's barcode, where the numbers come from, what the additive warnings mean, and how to use a photo of the label."
slug: barcode-and-photo
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-07
fact_checked: 2026-10-05
sources: [NOTE03, NOTE04, ARCH, OFF-API, ODBL, FDC-API, DG12, LEON13, SHERMAN09, FRIDOLFSSON25, A26-6]
---

# Barcodes and label photos

Scanning a barcode fills in a packaged food for you, so you do not have to type the label. A photo of
the label helps when the barcode is not found: you see the picture next to the form while you copy the
numbers, and nothing is uploaded ([design note 03][NOTE03]).

## Three ways to enter a barcode

On **Add**, tap **Scan a barcode** and choose one:

1. **Camera → Use the camera**: point it at the barcode. Hold still until it reads the same code twice;
   the camera then stops by itself. Live scanning needs HTTPS ([Install the app](install.md)). On HTTPS
   the camera starts as soon as you open Scan; switch off **Start the camera when I open Scan** in
   **Settings → Food data** if you would rather choose each time.
2. **Photo of a barcode**: take or choose a picture; the phone reads the code. This also works over
   plain HTTP, and the photo never leaves your phone.
3. **Type the barcode**: type the numbers under the lines and tap **Look up**. This also works with a
   USB or Bluetooth scanner and with a screen reader.

Your phone reads the code itself and sends **only the digits** to your server ([design note 03][NOTE03]).

## Where the numbers come from

The server looks in this order and stops at the first match:

| Order | Source | Needs |
|---|---|---|
| 1 | Foods you already saved with this barcode, and products you scanned before | nothing |
| 2 | Products someone on your server looked up before | the same as 3 or 4: you get them only if you could look them up yourself |
| 3 | **Open Food Facts**, a free database that anyone can edit | the admin switches it on **and** you agree in **Settings → Food data** |
| 4 | **USDA FoodData Central, branded foods** (US products) | a USDA key, shared by the admin or your own |

**Open Food Facts is off until your admin switches it on** in **Settings** or on the first-run setup
screen ([architecture contract][ARCH], v0.3 item 8), and then each person decides for their own scans
with **"Send barcodes I scan to Open Food Facts"**. Its data is shared under the Open Database License,
and the app shows "Product data © Open Food Facts contributors (ODbL)" on those foods
([Open Food Facts][OFF-API]; [ODbL][ODBL]). USDA data is public domain ([USDA API guide][FDC-API]).

For a US-labeled product found in both, the app takes the numbers from USDA (they come from the
maker) and fills gaps from Open Food Facts ([design note 03][NOTE03]).

## Check before you save

Community data can be wrong. The entry sheet shows:

- **"Potassium: not listed"** or **"Phosphorus: not listed"** instead of 0 when the source has no number.
  Unknown is not zero: your day's totals then say "not listed" and **Not complete**, because they may be
  higher.
- **"Community data. Check it against the package"** on every Open Food Facts food.
- A note when the calories do not add up, when sodium was worked out from "salt" (salt ÷ 2.5 = sodium),
  or when the values are for the "prepared" food.
- The serving. If the source has no serving size, the app uses 100 g. Change the amount to what you ate.
- For a food with values only **as prepared** (a boxed macaroni made with milk and butter), there is no
  **Grams** box: the serving weight on the box is the dry product, so log it in **servings** ("1 cup
  prepared" is one serving).
- A drink sold by volume counts toward your fluid limit.

## The additive warnings

The app reads the ingredient list and the additive codes and sets flags by itself:

| It finds | For example | What you see |
|---|---|---|
| A phosphate additive | sodium phosphate, phosphoric acid, E338–E341, E450–E452 | **red** for phosphorus, whatever the number says |
| A potassium additive and **no potassium number** | potassium chloride (E508), potassium lactate (E326) | a **medium** warning: "contains a potassium additive; potassium not listed" |
| A potassium additive **with** a potassium number | the same | the normal potassium thresholds |
| A salt substitute | "lite salt", or potassium chloride as the first ingredient | **avoid** with kidney disease |

Why it matters: the body absorbs nearly all the phosphorus from additives, much more than from natural
foods ([Kalantar-Zadeh 2010][DG12]). In one Ohio study, 44 % of best-selling grocery products had
phosphorus additives ([León 2013][LEON13]). Meat and poultry "enhanced" with potassium salts held up to
930 mg of potassium per 100 g, and 8 of 25 such products did not list the additives
([Sherman and Mehta 2009][SHERMAN09]). The potassium-additive rule is waiting for review by a renal
dietitian ([architecture contract][ARCH], v0.3 item 9).

If the scan finds no ingredient list, read it on the package. See
[Phosphate additives](../eat/phosphate-additives.md) and [Reading a label](../eat/label-reading.md).

## When nothing is found

The app offers **Enter from the label**: Quick add opens with the barcode filled in.

1. Tap **Use a photo of the label** and take a clear, flat picture.
2. The photo stays on your phone and appears above the form (beside it on a wide screen). Use the
   **1×, 2×, 3×** buttons, or pinch, to zoom.
3. Copy each number per serving. Leave a box empty if it is not on the label.
4. Type or paste the **ingredients** so the app can set the additive flags.
5. Save. The new food keeps the barcode, so the next scan finds it at once.

**Optional: Read a label (AI).** If your admin switched on AI with photos and you opted in, **Add →
Read a label (AI)**, or **Read the label for me (AI)** under the photo in Quick add, sends the photo to
the AI ([Optional AI](ai.md)). Your phone first redraws it, which
removes the location and camera data, and the server removes any that remain. The AI only copies printed
numbers and leaves missing ones empty; the app works out sodium from salt and marks values it estimated
from the % Daily Value. You get a draft with every field the AI filled marked "from photo". Check each one
against the label, correct the ingredients if needed, then tap **Save as my food**: saving checks the
ingredients you confirmed for phosphate and potassium additives. The app never saves it for you
([design note 04][NOTE04]).

## Photo of a plate (optional, AI only)

If your admin enables it, **Add → Plate photo (AI)** can suggest **which foods** are on your plate and a
rough weight. The app matches each one to foods in your own list and works out servings from the weight;
the AI never supplies nutrient numbers. Foods the AI was unsure about start unticked, and nothing is added
until you tap **Add selected** (as planned, unless you choose eaten). Portions from photos are
rough: in a 2025 test the best AI models were off by about 36 % on average, and they guessed too low for
large portions ([Fridolfsson 2025][FRIDOLFSSON25]). On a 60 g carbohydrate meal, that is about 20 g too
many or too few. Weigh or measure when it matters.

!!! warning "Do not count carbohydrate for insulin from a photo estimate alone"
    Use the label, a scale or your usual measured portion. If you are unsure and your glucose drops,
    treat the low straight away ([ADA 2026][A26-6], section 6; [Treating a low](../t1d/treating-a-low.md)).

## If something goes wrong

- **"Live scanning needs HTTPS."** Use **Photo of a barcode** or **Type the barcode**, or ask the admin
  for HTTPS.
- **The camera shows a black picture.** Use the photo button instead.
- **"Barcode lookups are off."** Ask your admin to switch on Open Food Facts, or use Quick add.
- **"Turn on 'Send barcodes I scan to Open Food Facts'"**: your admin switched lookups on, but they only
  happen for you after you agree in **Settings → Food data**.
- **"This is a store barcode for a weighed item."** Deli, meat and produce labels printed in the shop are
  only unique inside that shop, so the app does not look them up. Use Quick add.
- **"Try again in a minute."** Open Food Facts allows each server 15 product lookups a minute, so
  the server spaces them out ([Open Food Facts][OFF-API]).
- **The product is wrong or the numbers look odd.** Compare with the package. If they differ, use
  **Enter from the label**; your own copy wins next time.

## Related pages

- [Logging food](logging.md) · [Targets and warnings](targets-and-warnings.md) · [Optional AI](ai.md) · [Settings and keys](settings-and-keys.md)
- [Reading a label](../eat/label-reading.md) · [Phosphate additives](../eat/phosphate-additives.md) · [Potassium](../eat/potassium.md)

## Sources

- [Design note 03: barcodes, Open Food Facts and label photos][NOTE03]; [design note 04: optional AI][NOTE04].
- [Project architecture contract][ARCH], v0.3 items 8 and 9.
- [Open Food Facts API documentation][OFF-API]; [Open Database License][ODBL]; [USDA FoodData Central API guide][FDC-API].
- [Kalantar-Zadeh 2010][DG12]; [León 2013][LEON13]; [Sherman and Mehta 2009][SHERMAN09]: additives.
- [Fridolfsson 2025][FRIDOLFSSON25]: AI estimates from food photos.
- [ADA Standards of Care 2026, section 6][A26-6]: treating a low.
