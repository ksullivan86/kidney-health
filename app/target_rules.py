"""Data behind the personalised targets: the rule catalogue, ladders, equations and note texts.

Data only, no logic (note 05 §4.7). :mod:`app.targets` applies it; every number here is traceable
to the source named in :data:`RULES` (note 05 §4.4) or in the comment next to it. When a guideline
changes, change it here, regenerate ``tests/data/targets_vectors.json`` and update the browser twin
(``app/static/js/engine/targets.js``) until ``node tests/js/run_vectors.mjs`` passes.

Marking (note 05 "Marking used in this note"): ``grade`` quotes the source's own grade (KDOQI/KDIGO
``1``/``2`` + ``A``–``D``, ``OPINION``, ``PP``; ADA ``A``/``B``/``C``/``E``; ESPEN ``B``…; DRIs have
none, shown as ``"DRI"``; ``"–"`` = ungraded). ``opinion`` is True when part of the rule is this
project's own choice, and ``opinion_note`` says which part (the UI shows an "expert opinion" badge).
"""
from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# Sources (note 05 §9)
# --------------------------------------------------------------------------- #

URL_KDOQI_2020 = "https://doi.org/10.1053/j.ajkd.2020.05.006"
URL_KDIGO_2024 = "https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf"
URL_KDIGO_2022 = "https://kdigo.org/wp-content/uploads/2023/12/KDIGO-2022-Diabetes-Guideline.pdf"
URL_ADA_2026_S5 = "https://pmc.ncbi.nlm.nih.gov/articles/PMC12690188"
URL_ADA_2026_S11 = "https://pmc.ncbi.nlm.nih.gov/articles/PMC12690176"
URL_NASEM_2023_ENERGY = "https://doi.org/10.17226/26818"
URL_IOM_2011_CALCIUM = "https://www.nationalacademies.org/read/13050/chapter/2"
URL_ESPEN_2022 = "https://doi.org/10.1016/j.clnu.2022.01.024"
URL_GLIM_2019 = "https://doi.org/10.1016/j.clnu.2018.08.002"
URL_CARI_2010 = "https://doi.org/10.1111/j.1440-1797.2010.01238.x"
URL_FANTUZZI_2022 = "https://doi.org/10.33393/gcnd.2022.2365"
URL_KDOQI_2003_BONE = "https://www.kidney.org/sites/default/files/docs/boneguidelines.pdf"
URL_AKF_POTASSIUM = "https://www.kidneyfund.org/living-kidney-disease/healthy-eating-activity/kidney-friendly-eating-plan/potassium"
URL_DAVITA_FLUID = "https://www.davita.com/diet-nutrition/articles/basics/fluid-management-for-dialysis-patients"
URL_INKER_2021 = "https://doi.org/10.1056/NEJMoa2102953"


def _rule(source: str, grade: str, url: str, opinion_note: str | None = None) -> dict[str, Any]:
    return {"source": source, "grade": grade, "opinion": opinion_note is not None, "opinion_note": opinion_note, "url": url}


# The rule catalogue (note 05 §4.4). Keys are rule ids; "P-2d"/"P-2n" are the two variants of P-2
# (returned with id "P-2"). Order of application: S → W → N → E → P → K → PH → NA → CA → F → C → FB → L.
RULES: dict[str, dict[str, Any]] = {
    "S-1": _rule("KDIGO 2024 (pregnancy outside its scope); NASEM 2023 pregnancy energy equations", "–", URL_KDIGO_2024,
                 "refusal is project policy"),
    "S-2": _rule("KDIGO 2024 PP 3.3.1.4, PP 3.3.2.2, PP 1.2.4.3", "PP", URL_KDIGO_2024,
                 "age counted from the last day of the birth month"),
    "S-3": _rule("CARI 2010 (about 1.4 g/kg for 4 weeks); KDOQI 2020 \"metabolically stable\" definition", "–", URL_CARI_2010,
                 "the 12-week cut-off"),
    "W-1": _rule("KDOQI 2020 1.1.6", "OPINION", URL_KDOQI_2020),
    "W-2": _rule("KDOQI 2020 1.1.6", "OPINION", URL_KDOQI_2020),
    "W-3": _rule("KDOQI 2020 Table 5 (adjusted body weight, Karkeck)", "– (not validated in CKD)", URL_KDOQI_2020,
                 "using it above BMI 25"),
    "W-4": _rule("KDOQI 2020 Table 5 (KDOQI 2000 adjusted oedema-free body weight)", "–", URL_KDOQI_2020,
                 "using it below BMI 18.5"),
    "N-1": _rule("GLIM 2019; ISRNM 2008; KDIGO 2024 PP 3.3.1.5", "consensus / PP", URL_GLIM_2019,
                 "used as a risk flag, not a diagnosis"),
    "E-1": _rule("NASEM 2023 DRI Energy Table S-1; KDOQI 2020 3.1.1", "DRI; 1C (range)", URL_NASEM_2023_ENERGY,
                 "combining the energy equation with the kidney range"),
    "E-2": _rule("KDOQI 2020 3.1.1", "1C (range)", URL_KDOQI_2020, "30 kcal/kg, the middle of the range"),
    "E-3": _rule("ESPEN 2022 R1; KDOQI 2020 3.1.1 rationale", "B", URL_ESPEN_2022, "applying the 30 kcal/kg floor in CKD"),
    "E-4": _rule("Grodstein 1981; EBPG and ESPEN via Fantuzzi 2022", "–", URL_FANTUZZI_2022, "the 20 kcal/kg floor"),
    "P-1": _rule("RDA 0.8 g/kg; KDIGO 2024 PP 3.3.1.1 (avoid more than 1.3 g/kg)", "PP", URL_KDIGO_2024, "the 1.0 g/kg ceiling"),
    "P-2d": _rule("ADA 2026 Rec 11.3; KDIGO 2022 Rec 3.1.1; KDIGO 2024 Rec 3.3.1.1 (KDOQI 2020 3.0.2's 0.6 g/kg needs close "
                  "supervision)", "A / 2C / 2C", URL_ADA_2026_S11),
    "P-2n": _rule("KDOQI 2020 3.0.1; KDIGO 2024 Rec 3.3.1.1, PP 3.3.1.3", "1A (supervised) / 2C / PP", URL_KDOQI_2020,
                  "the 0.6 g/kg lower bound (listed for clinical review)"),
    "P-3": _rule("KDOQI 2020 3.0.3 (no diabetes), 3.0.4 (diabetes); KDIGO 2022 PP 3.1.2; ADA 2026 Rec 11.3",
                 "3.0.3: 1C (HD) / OPINION (PD); 3.0.4: OPINION; PP; B", URL_KDOQI_2020),
    "P-5": _rule("KDIGO 2024 PP 3.3.1.5 and rationale; ADA 2026 Rec 13.11a; ESPEN 2022 R2; PROT-AGE 2013 (incl. its eGFR < 30 "
                 "exception)", "PP / B / B / consensus", URL_KDIGO_2024, "the numbers"),
    "P-6": _rule("KDOQI 2000; KDOQI 2020 3.0.4", "– / OPINION", URL_KDOQI_2020, "1.2–1.3 g/kg with nutrition risk"),
    "P-7": _rule("CARI 2010; KDOQI 2020 \"metabolically stable\" definition", "–", URL_CARI_2010, "0.8–1.0 g/kg"),
    "K-0": _rule("v0.2 ladder (K/DOQI 2004; Kalantar-Zadeh & Fouque, NEJM 2017; AKF)", "–", URL_AKF_POTASSIUM, "the ladder"),
    "K-1": _rule("KDOQI 2020 6.4.2", "2D", URL_KDOQI_2020),
    "K-2": _rule("KDOQI 2020 6.4.1; KDIGO 2024 PP 3.11.5.2", "OPINION / PP", URL_KDOQI_2020, "relaxing by one step"),
    "K-2h": _rule("KDIGO 2024 PP 3.11.5.2", "PP", URL_KDIGO_2024),
    "K-3": _rule("KDIGO 2024 (CKD-PC definition, over 5.0 mmol/L); AKF (no more than 3000 mg)", "–", URL_KDIGO_2024, "3000 mg"),
    "K-4": _rule("KDIGO 2024 Figure 32; AKF (aim for 2500 mg)", "–", URL_KDIGO_2024, "2500 mg"),
    "K-5": _rule("KDIGO 2024 Table 28", "–", URL_KDIGO_2024, "2000 mg"),
    "PH-0": _rule("KDOQI 2003 Guideline 4.1 (800–1000 mg)", "OPINION / EVIDENCE", URL_KDOQI_2003_BONE, "the number picked in the range"),
    "PH-T": _rule("KDOQI 2020 6.3.3", "OPINION", URL_KDOQI_2020, "the graft-stage cut"),
    "PH-1": _rule("KDOQI 2020 6.3.3 (transplant)", "OPINION", URL_KDOQI_2020),
    "PH-2": _rule("KDOQI 2020 6.3.1", "1B", URL_KDOQI_2020, "1000 mg"),
    "PH-3": _rule("KDOQI 2020 6.3.1; KDOQI 2003 4.1; KDIGO 2017 4.1.2, 4.1.8", "1B / OPINION–EVIDENCE / 2C / 2D", URL_KDOQI_2020,
                  "the low end of the range"),
    "NA-1": _rule("KDIGO 2024 Rec 3.3.2.1; KDOQI 2020 6.5.1", "2C; 1B/1C", URL_KDIGO_2024),
    "CA-0": _rule("IOM (NASEM) 2011 Dietary Reference Intakes, RDA for ages 19–50", "DRI", URL_IOM_2011_CALCIUM),
    "CA-1": _rule("KDOQI 2020 6.2.1 (not taking active vitamin D)", "2B", URL_KDOQI_2020),
    "CA-2": _rule("KDOQI 2020 6.2.2 (CKD 5D; no KDOQI statement covers stage 5 without dialysis)", "OPINION", URL_KDOQI_2020,
                  "stage 5 without dialysis"),
    "CA-3": _rule("IOM (NASEM) 2011 Dietary Reference Intakes, Table S-1", "DRI", URL_IOM_2011_CALCIUM),
    "F-0": _rule("ESPEN 2022 R61 and its commentary", "B", URL_ESPEN_2022, "the stage G1–G3b cut"),
    "F-0o": _rule("ESPEN 2022 R61 and its commentary", "B", URL_ESPEN_2022, "the stage G1–G3b cut"),
    "F-1": _rule("Dialysis-unit convention (DaVita, AKF)", "–", URL_DAVITA_FLUID, "the convention"),
    "F-2": _rule("Dialysis-unit convention (DaVita, AKF)", "–", URL_DAVITA_FLUID, "the convention"),
    "F-3": _rule("Individualised (no graded number)", "–", URL_KDOQI_2020, "2000 mL"),
    "F-4": _rule("Individualised (no graded number)", "–", URL_KDOQI_2020, "urine plus ultrafiltration"),
    "C-1": _rule("ADA (individualise carbohydrate)", "–", URL_ADA_2026_S5, "45 % of calories (v0.2)"),
    "FB-1": _rule("ADA 2026 Rec 5.24; IOM 2005", "B", URL_ADA_2026_S5),
    "L-ALB": _rule("KDOQI 2020 1.2.1, 1.2.2, 4.1.1", "OPINION / 1A / 2D", URL_KDOQI_2020),
    "L-BIC22": _rule("KDOQI 2020 6.1.1 (CKD 1–4), 6.1.2–6.1.3 (CKD 3–5D)", "2C / 1C / OPINION", URL_KDOQI_2020),
    "L-BIC18": _rule("KDIGO 2024 PP 3.10.1", "PP", URL_KDIGO_2024),
    "L-UACR-A1": _rule("KDIGO 2024 Table 3; KDOQI 2020 6.5.2", "definition", URL_KDIGO_2024),
    "L-UACR-A2": _rule("KDIGO 2024 Table 3; KDOQI 2020 6.5.2", "definition", URL_KDIGO_2024),
    "L-UACR-A3": _rule("KDIGO 2024 Table 3; KDOQI 2020 6.5.2", "definition", URL_KDIGO_2024),
    "L-A1C": _rule("KDIGO 2022 PP 2.1.2", "PP", URL_KDIGO_2022),
    "G-1": _rule("KDIGO 2024 Rec 1.2.4.1, Rec 1.2.2.1, PP 1.2.4.2, PP 1.1.3.2; CKD-EPI 2021 (Inker 2021)", "1D / 1C / PP", URL_INKER_2021),
}

RULE_ORDER: tuple[str, ...] = ("S", "W", "N", "E", "P", "K", "PH", "NA", "CA", "F", "C", "FB", "L")

# --------------------------------------------------------------------------- #
# Numbers (note 05 §4.3)
# --------------------------------------------------------------------------- #

MODES: tuple[str, ...] = ("ckd", "transplant", "hemodialysis", "peritoneal")
EARLY_STAGES: frozenset[str] = frozenset({"1", "2"})  # G1–G2
STAGES_TO_3B: frozenset[str] = frozenset({"1", "2", "3a", "3b"})  # G1–G3b (F-0o, PH-T)
STAGES_1_TO_4: frozenset[str] = frozenset({"1", "2", "3a", "3b", "4"})  # KDOQI 6.1.1 scope (L-BIC22 fruit sentence)

ADULT_AGE = 18
OLDER_AGE = 65  # P-5, F-0o
GLIM_OLDER_AGE = 70  # low-BMI threshold switches from 20 to 22
EARLY_TRANSPLANT_DAYS = 84  # 12 weeks (S-3, OPINION)

BMI_LOW = 18.5  # W-4 below
BMI_HIGH = 25.0  # W-3 above
BMI_EPS = 1e-9  # exactly BMI 25 / 18.5 counts as inside the band despite float noise
ADJUST_FRACTION = 0.25  # Karkeck above, KDOQI 2000 below

LOW_BMI = {"under_70": 20.0, "from_70": 22.0}  # GLIM 2019
WEIGHT_LOSS_PCT = 5.0  # GLIM 2019: more than 5 % in 6 months
LOW_ALBUMIN_G_DL = 3.8  # ISRNM 2008

KCAL_PER_KG_MIN = 25.0  # KDOQI 2020 3.1.1
KCAL_PER_KG_MAX = 35.0
KCAL_PER_KG_DEFAULT = 30.0  # E-2
KCAL_PER_KG_RISK_FLOOR = 30.0  # E-3
PD_FOOD_FLOOR_KCAL_PER_KG = 20.0  # E-4
CALORIE_STEP = 10

# NASEM 2023 DRI for Energy, Table S-1 (adults): kcal/day = intercept + age·years + height·cm + weight·kg.
EER_COEFFICIENTS: dict[str, dict[str, tuple[float, float, float, float]]] = {
    "male": {
        "inactive": (753.07, -10.83, 6.50, 14.10),
        "low_active": (581.47, -10.83, 8.30, 14.94),
        "active": (1004.82, -10.83, 6.52, 15.91),
        "very_active": (-517.88, -10.83, 15.61, 19.11),
    },
    "female": {
        "inactive": (584.90, -7.01, 5.72, 11.71),
        "low_active": (575.77, -7.01, 6.60, 12.14),
        "active": (710.25, -7.01, 6.54, 12.34),
        "very_active": (511.83, -7.01, 9.07, 12.56),
    },
}
ACTIVITIES: tuple[str, ...] = ("inactive", "low_active", "active", "very_active")
ACTIVITY_LABELS: dict[str, str] = {
    "inactive": "inactive",
    "low_active": "low active",
    "active": "active",
    "very_active": "very active",
}
SEXES: tuple[str, ...] = ("female", "male", "unspecified")

# Protein g/kg (min, max).
PROTEIN_G_PER_KG: dict[str, tuple[float, float]] = {
    "dialysis": (1.0, 1.2),  # P-3
    "transplant": (0.8, 1.0),  # P-7
    "early": (0.8, 1.0),  # P-1, ckd G1–G2
    "late_diabetes": (0.8, 0.8),  # P-2d, never below 0.8 (fact-check H1)
    "late_no_diabetes": (0.6, 0.8),  # P-2n
    "older_early": (1.0, 1.2),  # P-5 at native or graft G1–G2
    "older_late": (0.8, 1.0),  # P-5 at native G3a–G5
    "dialysis_risk": (1.2, 1.3),  # P-6
}

# Potassium mg/day: the v0.2 ladder L and the one-step-relaxed ladder R (K-2); dialysis keyed by mode.
POTASSIUM_LADDER: dict[str, int] = {"1": 4000, "2": 4000, "3a": 4000, "3b": 3500, "4": 3000, "5": 2500,
                                    "hemodialysis": 2500, "peritoneal": 3500}
POTASSIUM_RELAXED: dict[str, int] = {"1": 4000, "2": 4000, "3a": 4000, "3b": 4000, "4": 3500, "5": 3000,
                                     "hemodialysis": 3000, "peritoneal": 4000}
POTASSIUM_LOW = 3.5  # K-1 below (mmol/L)
POTASSIUM_NORMAL_MAX = 5.0  # K-2 up to and including
POTASSIUM_HIGH_MAX = 5.5  # K-3 up to and including
POTASSIUM_VERY_HIGH = 6.0  # K-5 from (alert)
POTASSIUM_EMERGENCY = 6.5  # K-5 emergency from
POTASSIUM_CAPS: dict[str, int] = {"K-3": 3000, "K-4": 2500, "K-5": 2000}

# Phosphorus mg/day defaults D (PH-0) and lab thresholds (mg/dL; normal adult range 2.5–4.5).
PHOSPHORUS_DEFAULT: dict[str, int] = {"1": 1000, "2": 1000, "3a": 1000, "3b": 1000, "4": 1000, "5": 900,
                                      "hemodialysis": 1000, "peritoneal": 1000}
PHOSPHATE_LOW = 2.5
PHOSPHATE_HIGH = 4.5
PHOSPHORUS_NORMAL_MG = 1000  # PH-2
PHOSPHORUS_HIGH_MG = 800  # PH-3

SODIUM_MG = 2000  # NA-1
CALCIUM_MG = 1000  # CA-0, CA-1, CA-2
# IOM 2011 Table S-1 (RDA by sex) and the tolerable upper intake level (UL), by age group. The 14–18
# group only matters at age 18 (younger people are refused); "unspecified" uses the higher RDA.
CALCIUM_DRI: tuple[dict[str, int], ...] = (
    {"min_age": 14, "max_age": 18, "female": 1300, "male": 1300, "ul": 3000},
    {"min_age": 19, "max_age": 50, "female": 1000, "male": 1000, "ul": 2500},
    {"min_age": 51, "max_age": 70, "female": 1200, "male": 1000, "ul": 2000},
    {"min_age": 71, "max_age": 200, "female": 1200, "male": 1200, "ul": 2000},
)

FLUID_HD_BASE_ML = 1000  # F-2: 1000 + urine
FLUID_HD_DEFAULT_ML = 1500  # F-1: assumes about 500 mL urine
FLUID_PD_DEFAULT_ML = 2000  # F-3
FLUID_STEP_ML = 50
FLUID_FLOOR_TEXT: dict[str, str] = {"female": "1.6 L", "male": "2.0 L", "unspecified": "1.6 L (women) or 2.0 L (men)"}

CARB_FRACTION = 0.45  # C-1 (v0.2)
CARBS_PER_MEAL_MIN_G = 15
CARBS_PER_MEAL_STEP_G = 5
FIBER_G_PER_1000_KCAL = 14  # FB-1

BICARBONATE_LOW = 22.0  # L-BIC22
BICARBONATE_VERY_LOW = 18.0  # L-BIC18

# --------------------------------------------------------------------------- #
# Note texts (note 05 §4.5; str.format placeholders, kg with :g, kcal/mg/mL/g as integers)
# --------------------------------------------------------------------------- #

POTASSIUM_NOTE = "Only restrict potassium if your blood potassium is high; your care team sets the number."

NOTES: dict[str, str] = {
    "W-1": "Weight basis: {w:g} kg is in the healthy BMI range (BMI {bmi:.1f}) for {h:g} cm, so your actual weight is used for "
           "calories and protein.",
    "W-2": "Weight basis: without a saved height your actual weight ({w:g} kg) is used. Add your height so the app can adjust "
           "for a weight above or below the healthy range.",
    "W-3": "Weight basis: at BMI {bmi:.1f}, calories and protein use an adjusted weight of {ref:g} kg: the weight at BMI 25 for "
           "{h:g} cm ({w25:g} kg) plus a quarter of the weight above it. Guidelines leave the choice of weight to your care "
           "team (KDOQI 2020 1.1.6); this is the app's default.",
    "W-4": "Weight basis: at BMI {bmi:.1f}, calories and protein use {ref:g} kg: your weight moved a quarter of the way toward "
           "the healthy range ({w185:g} kg at BMI 18.5), as in KDOQI's adjusted body weight. Gaining weight safely is a job "
           "for your renal dietitian.",
    "W-D": " Enter your dry weight, measured after a dialysis session.",
    "N-1": "Nutrition risk: {reasons}. The app moves protein and calories to the higher end. Ask your renal dietitian for a "
           "nutrition assessment and whether oral nutrition supplements would help (KDOQI 2020 4.1.1).",
    "N-1.low_bmi": "BMI {bmi:.1f} is below {thr:g}",
    "N-1.weight_loss": "you have lost {pct:.1f} % of your weight in 6 months",
    "N-1.low_albumin": "blood albumin {alb:.1f} g/dL is below 3.8",
    "N-1.frailty": "frailty or low muscle mass is marked in your profile",
    "E-1": "Calories: {kcal} kcal/day, the energy estimate for your age, sex, height, {ref:g} kg and activity "
           "(\"{activity_label}\") from the 2023 Dietary Reference Intakes ({kpk:.1f} kcal/kg), kept inside the kidney "
           "guideline range of 25–35 kcal/kg (KDOQI 2020 3.1.1).",
    "E-1.clamped": " The estimate was {raw:.1f} kcal/kg, so it was set to {edge} kcal/kg.",
    "E-1.unspecified": " Sex is not set, so the average of the female and male equations is used.",
    "E-2": "Calories: 30 kcal/kg × {ref:g} kg = {kcal} kcal/day, the middle of the guideline range of 25–35 kcal/kg "
           "(KDOQI 2020 3.1.1). Add your birth month, sex, height and activity for a personal estimate.",
    "E-3": "Calories were raised to 30 kcal/kg because of the nutrition risk above (ESPEN 2022; KDOQI 2020: 30–35 kcal/kg "
           "keeps protein balance).",
    "E-4": "Peritoneal dialysis: {pdk} kcal/day absorbed from dialysis fluid was subtracted, so food calories are {kcal} of "
           "{total} kcal.",
    # Project wording for the 20 kcal/kg floor of E-4 (the subtraction would leave less).
    "E-4.floor": "Peritoneal dialysis: about {pdk} kcal/day is absorbed from dialysis fluid, but food calories are kept at "
                 "20 kcal/kg × {ref:g} kg, so they are {kcal} of {total} kcal. Ask your renal dietitian about this.",
    # Appended only with diabetes (without it no insulin is involved).
    "E-4.insulin": " That glucose also needs insulin; your diabetes team plans for it.",
    # Project wording: appended to E-1/E-2 on peritoneal dialysis while pd_dialysate_kcal is not set (v0.2 said this too).
    "E-PD.missing": " On peritoneal dialysis, add the calories your body absorbs from the dialysis fluid (ask your PD nurse) "
                    "so the app can subtract them from food calories.",
    "P-1": "Protein: {min}–{max} g/day (0.8–1.0 g/kg × {ref:g} kg). At stages 1–2 guidelines only ask you to avoid more than "
           "1.3 g/kg (KDIGO 2024).",
    "P-2d": "Protein: about {max} g/day (0.8 g/kg × {ref:g} kg) for CKD stages 3–5 with diabetes (KDIGO 2022 Rec 3.1.1; "
            "KDIGO 2024 Rec 3.3.1.1; ADA 2026 Rec 11.3). With diabetes, eating less than 0.8 g/kg is not recommended "
            "(ADA 2026): it risks muscle loss and low blood sugar. A lower amount (KDOQI 2020 3.0.2: 0.6–0.8) is only for "
            "people under close supervision by their care team. Avoid more than 1.3 g/kg (KDIGO 2024).",
    "P-2n": "Protein: {min}–{max} g/day (0.6–0.8 g/kg × {ref:g} kg) for CKD stages 3–5. KDIGO 2024 Rec 3.3.1.1 suggests "
            "0.8 g/kg. Going below 0.8 (KDOQI 2020 3.0.1: 0.55–0.6) needs close supervision by your care team, and is not "
            "for anyone who is unwell, in hospital recently or losing weight (KDIGO 2024 PP 3.3.1.3). Avoid more than "
            "1.3 g/kg (KDIGO 2024).",
    "P-3": "Protein: {min}–{max} g/day (1.0–1.2 g/kg × {ref:g} kg) on {mode_label} (KDOQI 2020 3.0.3/3.0.4). Dialysis removes "
           "protein, so more is needed, not less.",
    "P-5a": "Protein raised to {lo}–{hi} g/kg ({min}–{max} g/day) because {why}: in older adults and people at risk of "
            "malnutrition, losing muscle is often the bigger danger (KDIGO 2024 PP 3.3.1.5; ADA 2026 Rec 13.11a: at least "
            "0.8 g/kg). If your kidney function is falling fast, your team may still prefer a lower range.",
    "P-5a.older": "you are 65 or older",
    "P-5a.risk": "of the nutrition risk above",
    "P-5a.both": "you are 65 or older and at nutrition risk",
    "P-6": "Protein raised to 1.2–1.3 g/kg ({min}–{max} g/day) because of the nutrition risk above (KDOQI 2000: 1.2 on "
           "hemodialysis, 1.2–1.3 on peritoneal dialysis).",
    "P-7": "Protein: {min}–{max} g/day (0.8–1.0 g/kg × {ref:g} kg) for a working kidney transplant. No guideline sets a "
           "long-term number; low-protein diets are not used with anti-rejection medicines.",
    "P-7.graft": " It is not raised further for age because your transplant's function is at stage {stage}; ask your team.",
    "K-0": "Potassium: {k_mg} mg/day is a review ceiling for {stage_label}, not a prescription; no blood potassium from the "
           "last {days} days is saved. {potassium_note}",
    # Project wording when the admin turned lab-based rules off (note 05 §4.9 targets.lab_rules_enabled).
    "K-0.labs_off": "Potassium: {k_mg} mg/day is a review ceiling for {stage_label}, not a prescription; this server does not "
                    "change it for blood test results. {potassium_note}",
    "K-1": "Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is low, so no potassium limit is set. Ask your care "
           "team whether to eat more potassium-rich foods or take a supplement (KDOQI 2020 6.4.2). {potassium_note}",
    "K-2": "Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is normal, so the review ceiling is relaxed one step to "
           "{k_mg} mg/day. While it stays normal there is no need to cut fruit and vegetables (KDOQI 2020 6.4.1; KDIGO 2024). "
           "{potassium_note}",
    "K-2h": "Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is normal, but you have had high potassium before or "
            "take a potassium binder, so the ceiling stays at {k_mg} mg/day; processed foods with potassium additives matter "
            "most (KDIGO 2024 PP 3.11.5.2). {potassium_note}",
    "K-3": "Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is above normal (over 5.0), so the ceiling is {k_mg} "
           "mg/day. Check processed foods with potassium additives, salt substitutes and large portions first; your team may "
           "also review medicines (KDIGO 2024 Figure 32). {potassium_note}",
    "K-4": "Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is high (over 5.5), so the ceiling is {k_mg} mg/day. "
           "Tell your care team; they may change medicines or start a potassium binder. {potassium_note}",
    "K-5": "Potassium: {k:.1f} mmol/L on {date} is dangerously high. {urgency} The ceiling is set to {k_mg} mg/day until your "
           "team gives you a number. {potassium_note}",
    "K-5.urgent": "Contact your care team today: this result should be repeated within 24 hours, and if you feel unwell "
                  "(weakness, palpitations or an irregular pulse) get urgent medical care now (KDIGO 2024 Table 28).",
    "K-5.emergency": "Get urgent medical care now, especially with weakness, palpitations or an irregular pulse (KDIGO 2024 "
                     "Table 28).",
    # The safety alert (suggested targets and POST /api/labs) carries the same urgency text.
    "K-5.alert": "Potassium {k:.1f} mmol/L on {date} is dangerously high. {urgency}",
    "PH-0": "Phosphorus: {p_mg} mg/day (guideline range 800–1000 mg when phosphate runs high); no phosphate result from the "
            "last {days} days is saved. Avoiding phosphate additives matters more than the total because additive phosphorus "
            "is almost fully absorbed.",
    "PH-0.labs_off": "Phosphorus: {p_mg} mg/day (guideline range 800–1000 mg when phosphate runs high); this server does not "
                     "change it for blood test results. Avoiding phosphate additives matters more than the total because "
                     "additive phosphorus is almost fully absorbed.",
    "PH-T": "Phosphorus: not limited after a kidney transplant unless your phosphate is high; low phosphate is common in the "
            "first months (KDOQI 2020 6.3.3).",
    "PH-1": "Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is low, so no phosphorus limit is set. Ask your team whether "
            "to eat more phosphorus or take a supplement (KDOQI 2020 6.3.3).",
    "PH-2": "Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is normal; {p_mg_or_none} is a review ceiling. Keep avoiding "
            "phosphate additives (KDOQI 2020 6.3.1–6.3.2).",
    # PH-2 for a transplant at graft G1–G3b, where no limit is set (the {p_mg_or_none} "none" case).
    "PH-2.none": "Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is normal, so no phosphorus limit is set after a kidney "
                 "transplant. Keep avoiding phosphate additives (KDOQI 2020 6.3.1–6.3.2).",
    "PH-3": "Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is above normal (over 4.5), so the target is 800 mg/day, the "
            "low end of the 800–1000 mg range (KDOQI 2003; KDIGO 2017). Cut phosphate additives first and take binders with "
            "meals as prescribed. On dialysis keep protein up by choosing foods with little phosphorus per gram of protein "
            "(egg whites, fresh meat and fish).",
    "NA-1": "Sodium: 2000 mg/day for every adult with CKD, whatever the age or sex (KDIGO 2024; KDOQI 2020 6.5.1: under "
            "2300 mg).",
    "CA-0": "Calcium: 1000 mg/day. Add your birth month and sex for the amount recommended for your age.",
    "CA-1": "Calcium: at most 1000 mg/day in total, counting calcium-based binders and supplements (KDOQI 2020 6.2.1: "
            "800–1000 mg at stages 3–4 when not taking active vitamin D such as calcitriol). At these stages it does not "
            "change with age or sex.",
    "CA-2": "Calcium: 1000 mg/day in total as a starting point; at stage 5 and on dialysis your team adjusts it to avoid high "
            "calcium, counting binders and vitamin D medicines (KDOQI 2020 6.2.2 covers dialysis; for stage 5 without "
            "dialysis this is the app's default).",
    "CA-3": "Calcium: {rda}–{ul} mg/day: the general recommendation for your age and sex ({rda} mg) up to the safe upper "
            "limit ({ul} mg) (Dietary Reference Intakes 2011).",
    "F-0": "Fluid: no limit without dialysis unless your care team sets one.",
    "F-0o": "Fluid: no limit without dialysis unless your care team sets one. Thirst fades with age: unless your team limits "
            "fluid, or you have heart failure or swelling, aim for at least {floor} of drinks a day (ESPEN 2022).",
    "F-1": "Fluid: 1000 mL plus your 24-hour urine volume; 1500 mL assumes about 500 mL of urine. Enter your urine volume or "
           "ask your dialysis unit for your allowance.",
    "F-2": "Fluid: 1000 mL + your {u} mL of urine = {fluid} mL/day, the usual hemodialysis allowance; your unit may set a "
           "different number.",
    "F-3": "Fluid: about 2000 mL/day on peritoneal dialysis. Enter your daily urine volume and ultrafiltration for a personal "
           "number.",
    "F-4": "Fluid: urine {u} mL + ultrafiltration {uf} mL = {fluid} mL/day, about what your body removes each day. Check it "
           "with your PD nurse.",
    # C-1: the v0.2 carbohydrate notes, unchanged.
    "C-1": "Carbohydrate: 45 % of calories ÷ 4 kcal/g = {carbs} g/day.",
    "C-1.diabetes": "Carbohydrate: 45 % of calories ÷ 4 kcal/g = {carbs} g/day, about {per_meal} g per meal for carb "
                    "counting; your insulin-to-carb ratio decides the real per-meal number.",
    "FB-1": "Fibre: at least {fib} g/day (14 g per 1000 kcal, ADA 2026). When potassium is limited, get it from low-potassium "
            "fruit, vegetables and grains.",
    "L-ALB": "Low albumin can also come from inflammation or protein lost in urine, not only from diet (KDOQI 2020 1.2.1). "
             "Labs measure albumin in different ways; ask your team whether this result counts as low for your lab.",
    "L-BIC22": "Bicarbonate {b:.1f} mmol/L is below 22: acid builds up as kidneys fail. {fv}Your team may prescribe bicarbonate "
               "(KDOQI 2020 6.1.2).",
    "L-BIC22.fv": "More fruit and vegetables lower the acid load (KDOQI 2020 6.1.1){k_caveat}. ",
    "L-BIC22.k_caveat": " (your potassium is high, so ask your team first)",
    "L-BIC18": "Bicarbonate {b:.1f} mmol/L is below 18. KDIGO 2024 says treatment should be considered at this level "
               "(practice point 3.10.1); tell your care team.",
    "L-UACR": "Urine albumin {uacr:.1f} {unit} (as entered) is category {cat} ({cat_label}). It does not change food targets "
              "but is a reason to keep sodium low (KDOQI 2020 6.5.2).",
    "L-UACR.a3_low_albumin": " With low blood albumin this can mean protein is lost in urine; your team may set protein "
                             "differently.",
    "L-A1C": "A1c and CGM readings do not change these food targets; in advanced CKD A1c is less reliable (KDIGO 2022 PP "
             "2.1.2).",
    "END": "These are starting points only — confirm every target with your nephrologist and renal dietitian.",
}

# Refusals (422): code -> (rule, message). Note 05 §4.5, word for word.
REFUSALS: dict[str, tuple[str, str]] = {
    "out_of_scope_pregnancy": (
        "S-1",
        "Targets are not suggested during pregnancy or breastfeeding: needs for energy, protein, calcium and fluid change, "
        "and kidney disease in pregnancy needs specialist care. Ask your kidney and maternity teams for targets; you can "
        "still enter them by hand.",
    ),
    "out_of_scope_under_18": (
        "S-2",
        "Targets are not suggested for people under 18: children need more protein and energy to grow, and kidney "
        "guidelines for children are different. Ask your child's kidney team; you can still enter targets by hand.",
    ),
    "out_of_scope_early_transplant": (
        "S-3",
        "Your kidney transplant was less than 12 weeks ago. In the first weeks your transplant team sets a recovery diet, "
        "usually higher in protein, so the app does not suggest targets yet. You can still enter targets by hand.",
    ),
}

ALERT_CODE_POTASSIUM = "potassium_very_high"

# Inputs that personalise the suggestion when they are set (``missing_inputs``, in this order).
MISSING_INPUT_ORDER: tuple[str, ...] = (
    "height_cm", "birth_month", "sex", "activity", "urine_output_ml", "pd_uf_ml", "pd_dialysate_kcal",
)
