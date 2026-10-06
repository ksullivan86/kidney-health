---
title: Units and conversions
description: Convert lab results between US units and international (SI) units, plus glucose, A1c, salt, kitchen measures and body weight.
slug: units
audience: [patient, caregiver, clinician]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
sources: [K24, K22, K17, K26A, NGSP, A26-6, HC24, DG34, CFR-LABEL]
---

# Units and conversions

## In short

US labs report most results in "conventional" units such as mg/dL. Most other countries use
international (SI) units such as mmol/L and µmol/L. It is the same test with a different number, so
always check the unit before you compare a result with a target. Pages in this handbook have
**US units** and **International** tabs; choose one and every page follows. Your lab's own range,
printed next to the result, always wins.

## Lab results

Multiply the US number by the factor to get the international number. To go the other way, divide.

| Test | US unit | × factor | International unit | Example | Source |
|---|---|---|---|---|---|
| Creatinine | mg/dL | 88.4 | µmol/L | 1.5 mg/dL = 133 µmol/L | [KDIGO 2024][K24] |
| eGFR | mL/min/1.73 m² | 1 (same) | mL/min/1.73 m² | 45 = 45 | [KDIGO 2024][K24] |
| UACR (urine albumin) | mg/g | 0.113 | mg/mmol | 30 mg/g = 3.4 mg/mmol (guidelines round to 3) | [KDIGO 2024][K24] |
| Glucose | mg/dL | 0.0555 (or divide by 18) | mmol/L | 70 mg/dL = 3.9 mmol/L | [KDIGO 2022][K22] |
| A1c | % | see the formula below | mmol/mol | 7.0 % = 53 mmol/mol | [KDIGO 2022][K22]; [NGSP][NGSP] |
| Potassium, sodium, bicarbonate | mEq/L | 1 (same) | mmol/L | potassium 5.0 = 5.0 | [KDIGO 2024][K24] |
| Phosphate | mg/dL | 0.3229 | mmol/L | 4.5 mg/dL = 1.45 mmol/L | [KDIGO 2024][K24]; [KDIGO 2017][K17] |
| Calcium (total) | mg/dL | 0.2495 | mmol/L | 9.5 mg/dL = 2.37 mmol/L | [KDIGO 2024][K24]; [KDIGO 2017][K17] |
| PTH | pg/mL | 0.106 | pmol/L | 300 pg/mL = 31.8 pmol/L | [KDIGO 2017][K17] |
| Hemoglobin | g/dL | 10 | g/L | 12 g/dL = 120 g/L | [KDIGO 2026 anemia][K26A] |
| Albumin (blood) | g/dL | 10 | g/L | 4.0 g/dL = 40 g/L | same rule as hemoglobin |
| Ferritin | ng/mL | 1 (same) | µg/L | 100 = 100 | [KDIGO 2026 anemia][K26A] |
| Uric acid (urate) | mg/dL | 59.48 | µmol/L | 7 mg/dL = 416 µmol/L | [KDIGO 2024][K24] |
| Blood ketones | mmol/L everywhere | – | mmol/L | 3.0 = 3.0 | [2024 consensus][HC24] |
| TSAT (iron) | % everywhere | – | % | 20 % = 20 % | [KDIGO 2026 anemia][K26A] |

**A1c formula:** mmol/mol = (% − 2.15) × 10.929. Going back: % = mmol/mol ÷ 10.929 + 2.15
([KDIGO 2022][K22]; [NGSP][NGSP]).

## A worked example: one lab report, two units

=== "US units"

    | Test | Result |
    |---|---|
    | Creatinine | 1.8 mg/dL |
    | eGFR | 42 mL/min/1.73 m² |
    | UACR | 150 mg/g |
    | Potassium | 5.2 mEq/L |
    | Phosphate | 4.8 mg/dL |
    | Glucose | 162 mg/dL |
    | A1c | 7.4 % |

=== "International"

    | Test | Result |
    |---|---|
    | Creatinine | 159 µmol/L |
    | eGFR | 42 mL/min/1.73 m² |
    | UACR | 17 mg/mmol |
    | Potassium | 5.2 mmol/L |
    | Phosphate | 1.55 mmol/L |
    | Glucose | 9.0 mmol/L |
    | A1c | 57 mmol/mol |

The working: 1.8 × 88.4 = 159; 150 × 0.113 = 17; 4.8 × 0.3229 = 1.55; 162 × 0.0555 = 9.0;
(7.4 − 2.15) × 10.929 = 57.

## Glucose numbers you will meet

| mg/dL | mmol/L | Why it matters |
|---|---|---|
| 54 | 3.0 | below this is a level 2 low ([ADA 2026 §6][A26-6]) |
| 70 | 3.9 | below this is a low; treat it ([ADA 2026 §6][A26-6]) |
| 100 | 5.6 | |
| 180 | 10.0 | top of the CGM target range ([ADA 2026 §6][A26-6]) |
| 200 | 11.1 | check ketones if you are ill or have symptoms ([ADA 2026 §6][A26-6]) |
| 250 | 13.9 | |
| 300 | 16.7 | |

## A1c and average glucose

ADA's table links A1c to an estimated average glucose (eAG) ([ADA 2026 §6][A26-6]). In stage 4–5 and
on dialysis A1c is less reliable, so a CGM report may be the better guide
([KDIGO 2022][K22], practice point 2.1.2; [A1c](../labs/a1c.md)).

| A1c % | A1c mmol/mol | Average glucose mg/dL | Average glucose mmol/L |
|---|---|---|---|
| 6 | 42 | 126 | 7.0 |
| 7 | 53 | 154 | 8.6 |
| 8 | 64 | 183 | 10.2 |
| 9 | 75 | 212 | 11.8 |
| 10 | 86 | 240 | 13.4 |

## Food, drink and the kitchen

| From | To | How | Source |
|---|---|---|---|
| Sodium 2,000 mg | mmol and salt | 2 g sodium = about 90 mmol = about 5 g of salt | [KDIGO 2024][K24], recommendation 3.3.2.1 |
| 1 teaspoon of table salt | sodium | about 2,300 mg sodium | [FDA][DG34] |
| 1 cup | mL | 240 mL (on US food labels) | [21 CFR 101.9][CFR-LABEL] |
| 1 fluid ounce | mL | 30 mL | [21 CFR 101.9][CFR-LABEL] |
| 1 tablespoon / 1 teaspoon | mL | 15 mL / 5 mL | [21 CFR 101.9][CFR-LABEL] |
| 1 ounce (weight) | grams | 28 g | [21 CFR 101.9][CFR-LABEL] |
| 1 liter | cups | about 4 cups (1,000 ÷ 240 = 4.2) | [21 CFR 101.9][CFR-LABEL] |

**Protein per kilogram:** a goal of 0.8 g per kg of body weight for a 70 kg (154 lb) person is
0.8 × 70 = 56 g a day ([KDIGO 2022][K22], recommendation 3.1.1; [Protein](../eat/protein.md)).

## Body weight, fluid and temperature

- **Weight:** 1 kg = 2.2 lb; 1 lb = 0.45 kg.
- **Fluid weight:** 1 liter of water weighs 1 kg (2.2 lb). So a weight gain of 1 kg between dialysis
  sessions is about 1 liter of fluid ([Fluid](../eat/fluid.md)).
- **Temperature:** °F = °C × 9 ÷ 5 + 32. So 37.8 °C = 100 °F and 38.0 °C = 100.4 °F.

## What to do

- [ ] Check the unit printed next to every result before comparing it with a target.
- [ ] Choose **US units** or **International** once on any page with tabs; the site remembers it.
- [ ] Use your lab's reference range, not a range from another country or website.
- [ ] If you travel or move, ask the new clinic which units they use and write both on your
      [wallet card](wallet-card.md).

## Ask your care team

1. Which units does my lab use for creatinine, glucose and UACR?
2. Can you write my targets in the same units as my lab report?
3. My meter shows mmol/L but my clinic uses mg/dL (or the other way round). Can we agree on one?

## Sources

- [KDIGO 2024 CKD guideline][K24]: conversion factors (creatinine, ACR, calcium, phosphate, urate);
  recommendation 3.3.2.1.
- [KDIGO 2022 diabetes in CKD guideline][K22]: conversion factors (glucose, HbA1c); recommendation
  3.1.1; practice point 2.1.2.
- [KDIGO 2017 CKD-MBD update][K17]: conversion factors (calcium, phosphate, PTH).
- [KDIGO 2026 anemia guideline][K26A]: conversion factors (hemoglobin, ferritin).
- [NGSP: HbA1c units][NGSP]; [ADA Standards of Care 2026, section 6][A26-6]: glucose levels and
  estimated average glucose.
- [2024 hyperglycemic crises consensus][HC24]: ketones in mmol/L.
- [FDA: sodium in your diet][DG34]; [21 CFR 101.9(b)(5)(viii)][CFR-LABEL].
