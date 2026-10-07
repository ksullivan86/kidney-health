---
title: First setup
description: "Sign in, fill in your profile, get starting targets with \"Suggest targets\", and learn which details change your targets and which do not."
slug: first-setup
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-07
fact_checked: 2026-10-05
sources: [NOTE05, NOTE07, ARCH, Q20, K24, A26-11, A26-5, NIST-63B4, MEDLINE-K]
---

# First setup

Setup takes about ten minutes: sign in, fill in your profile, then copy in your care team's targets or
ask the app for starting ones. Have your latest lab report and your dialysis schedule (if you have one)
next to you.

--8<-- "includes/starting-points.md"

## 1. Sign in

Every person has their own account, with their own log, profile, targets and keys
([design note 07][NOTE07]):

1. Your admin sends you a link: an **invite link**, or a **setup link** for an account the admin already
   made for you (the page then shows your user name). Each link works once and expires, after 7 days
   unless your admin chose another time.
2. Open it on the device you will use most, and choose a user name (for an invite) and a password.
3. The password must be **at least 15 characters** (unless your admin chose another minimum). Long is what makes it strong: a short sentence such
   as `blue kettle on a sunny porch` is fine, and you do not need symbols or capitals
   ([NIST SP 800-63B-4][NIST-63B4], section 3.1.1.2). The app refuses very common passwords, your user
   name or name, and runs such as `aaaa…` or `12345…`. A password manager and pasting are allowed.
4. You stay signed in for up to 30 days, or 14 days if you do not open the app. **Settings → Account**
   lists the devices you are signed in on, and signs out any of them.
5. On a shared computer, sign out when you finish (**Settings → Account → Sign out**).

Some changes, such as a new password, exporting your data or adding a key, ask for your password again
if you have not typed it in the last 10 minutes. If you forget your password, ask the admin for a reset
link; there is no email reset. If your admin set up sign-in through another service (for example
Authelia or Tailscale), you sign in there instead and never set a password in the app.

The person who installs the server creates the first account, the admin, with a one-time setup code
from the server's log ([Self-hosting](../self-hosting/index.md)).

## 2. Fill in your profile

Open **Profile** and enter:

| Field | What to enter | Tip |
|---|---|---|
| Weight (kg) | Your weight today. On dialysis, your **dry (target) weight** after a session | pounds ÷ 2.2 = kg: 154 lb = 70 kg |
| Height (cm) | Your height | inches × 2.54 = cm: 5 ft 7 in = 67 in = 170 cm |
| CKD stage | 1, 2, 3a, 3b, 4 or 5, from your nephrologist | after a transplant, the stage of the new kidney |
| Dialysis | None, Hemodialysis or Peritoneal | |
| Dialysis days | The weekdays of your hemodialysis sessions | lets the app total potassium, sodium and fluid between sessions ([Dialysis days](../eat/dialysis-days.md)) |
| Diabetes | Type 1, Type 2 or None | |
| Warn at (% of limit) | 80 % unless your team prefers another number | when a day turns from "ok" to "near limit" |
| Week starts on | Monday or Sunday | used by **Plan** and the shopping list |

Then tap **Save profile**.

## 3. Set your targets

**If your care team gave you numbers**, type them into **Daily targets** and save. Those are your
targets. Leave a box empty for anything they did not limit.

**If not**, tap **Suggest targets**. The app fills the boxes with guideline starting points and a note
on each one, and it saves nothing until you tap **Save profile** ([architecture contract][ARCH]).
Take the numbers to your next visit and ask your team to change them.

### Example: stage 4, type 1 diabetes, 70 kg, 170 cm

| Target | Suggested | Why |
|---|---|---|
| Protein | about 56 g a day (0.8 g per kg) | with diabetes, not below 0.8 g/kg before dialysis ([ADA 2026][A26-11], Rec 11.3; [KDIGO 2024][K24], Rec 3.3.1.1) |
| Potassium | 3,000 mg | a review ceiling: only restrict potassium if your blood potassium is high |
| Phosphorus | 1,000 mg | |
| Sodium | 2,000 mg | the same at every stage ([KDIGO 2024][K24], Rec 3.3.2.1) |
| Calories | 2,100 kcal (30 per kg) | KDOQI's range is 25–35 kcal/kg ([KDOQI 2020][Q20], 3.1.1) |
| Carbohydrate | 236 g a day, 60 g per meal | the app's default: 45 % of calories, split over four meal slots. There is no ideal share for everyone, so your diabetes team sets yours ([ADA 2026][A26-5], Rec 5.13). **Carbohydrate per snack** is empty until you type your team's number |
| Fiber | at least 29 g a day | 14 g per 1,000 kcal ([ADA 2026][A26-5], Rec 5.24); a goal to reach, never "over" |
| Fluid | not tracked | fluid limits start on dialysis |

At a BMI above 25 (or below 18.5) the app uses an adjusted weight instead of your scale weight, and
the first note says which weight it used ([design note 05][NOTE05]).

## Which details change your targets

**Profile → About you** has optional details: birth month, the sex used in medical formulas, height,
weight 6 months ago, activity level, frailty, pregnancy, and "I have had high potassium". On dialysis
**Kidneys and diabetes** also asks for your urine volume (and on peritoneal dialysis your ultrafiltration
and the calories from the dialysis fluid); without dialysis it asks for a transplant date if you have one.
Lab results go in **Lab results** (Profile → Blood and urine tests). Each detail changes only some targets
([design note 05][NOTE05]):

| Detail | Changes | Does not change |
|---|---|---|
| Age | calories; protein from age 65; calcium only at stages 1–2 (a transplant kidney included) | sodium, potassium, phosphorus, fluid on dialysis |
| Sex used in formulas | calories; calcium at stages 1–2; the eGFR estimate | protein per kg, sodium, potassium, phosphorus |
| Height and weight | the weight used for protein and calories | sodium, potassium, phosphorus |
| Activity | calories | everything else |
| Stage and dialysis | protein, potassium ceiling, phosphorus, fluid | sodium |
| Diabetes | protein floor of 0.8 g/kg at stages 3–5 without dialysis; carbohydrate per meal | sodium, potassium, phosphorus |
| Blood potassium | potassium only | everything else |
| Blood phosphate | phosphorus only | everything else |
| Urine output (dialysis) | fluid only | everything else |
| Low albumin, weight loss, frailty | can raise calories and protein | sodium, potassium, phosphorus |
| A1c, CGM numbers, UACR, bicarbonate | nothing: they add notes only | all targets |

**Labs matter more than age or sex** for potassium and phosphorus. Sex never changes protein per kg,
sodium, potassium or phosphorus ([design note 05][NOTE05]).

Each suggested number has a **Why this number?** link with the rule behind it, its source and grade; rules
that are partly the app's own choice carry an **Expert opinion** badge. When a new lab result would change a
suggestion, the app shows **Review suggested targets**. It never changes your saved targets by itself.

!!! warning "Do not use Suggest targets if you are pregnant, under 18 or newly transplanted"
    Nutrition needs are very different if you are pregnant or breastfeeding, younger than 18, or in
    the first 12 weeks after a kidney transplant. Your nephrologist, transplant team or a specialist
    dietitian sets your numbers then
    ([Sex, fertility and pregnancy](../living/sex-fertility-pregnancy.md);
    [After a transplant](../stages/after-transplant.md)). Tick **Pregnant or breastfeeding**, add your
    birth month, or add your transplant date in your profile: the app then shows why it does not suggest
    targets and fills in no numbers. Type in your team's numbers instead ([design note 05][NOTE05]).

## What to do

- [ ] Fill in weight, height, stage, dialysis and diabetes, then **Save profile**.
- [ ] Copy in your team's targets, or use **Suggest targets** and save.
- [ ] On hemodialysis, tick your dialysis days and enter your fluid allowance in mL
      (1 cup = 240 mL; 32 oz is about 950 mL). The app has no field for your weight-gain limit:
      write that one in your notebook ([Fluid](../eat/fluid.md)).
- [ ] On peritoneal dialysis, choose **Peritoneal** so the app uses PD starting points.
- [ ] After a transplant, set **Dialysis** to None, add your **Kidney transplant date** and the stage of
      your new kidney.
- [ ] Update your weight and stage when they change, then check **Suggest targets** again.

## Ask your care team

1. "What are my daily limits for potassium, phosphorus, sodium and protein?"
2. "Should I limit potassium at all, given my last blood potassium?"
3. "How many grams of carbohydrate should I aim for at each meal?"
4. "What is my dry weight, my fluid allowance and my weight-gain limit between sessions?"
5. "Which weight should I use for protein: my scale weight or another one?"

## Get help now if…

!!! danger "Call 911 (or your local emergency number)"
    Your lab potassium is **6.5 mmol/L or more** ([KDIGO 2024][K24], Table 28), or you have fainting,
    chest pain, a very slow, weak or irregular pulse, or sudden severe weakness, especially if your
    potassium has been high ([MedlinePlus][MEDLINE-K]).

!!! warning "Call your care team today"
    A lab potassium of **6.0–6.4 mmol/L**: if you feel unwell, go to hospital **now** to be checked and
    treated; if you feel well, call your team today for a repeat test within 24 hours
    ([KDIGO 2024][K24], Table 28). **Lab results** shows a red banner for a potassium of 6.0 or more.
    Full list: [Get help now](../get-help-now.md).

## Related pages

- [Targets and warnings](targets-and-warnings.md) · [Logging food](logging.md) · [Install the app](install.md)
- [Eating well](../eat/index.md) · [Your stage, day to day](../stages/index.md) · [Lab results](../labs/index.md)

## Sources

- [Design note 05: personalised targets][NOTE05] (fact-checked 2026-10-05): which factors change which target.
- [Design note 07: accounts][NOTE07]; [NIST SP 800-63B-4][NIST-63B4]: password rules.
- [Project architecture contract][ARCH]: profile fields and "Suggest targets".
- [KDOQI 2020 nutrition guideline][Q20]; [KDIGO 2024 CKD guideline][K24]; [ADA Standards of Care 2026, section 11][A26-11]
  (protein, Rec 11.3) and [section 5][A26-5] (no ideal carbohydrate share, Rec 5.13).
- [MedlinePlus: high potassium level][MEDLINE-K]: warning signs.
