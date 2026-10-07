"""Note 06 §6.6 insight vectors TV-I1 … TV-I5 and the other end-of-day and period rules of §4.8."""
from __future__ import annotations

import fixtures as fx
from app.guidance import insights
from app.guidance import messages as M
from app.guidance.state import HistoryEntry, Prefs, Profile
from app.guidance.vectors import make_food

BREAD = make_food(id=20, name="Bread, white", category="Grains & Breads", serving_desc="1 slice (29 g)", serving_g=29,
                  nutrients=fx.nutrients(14.3, 2.6, 37, 28, 137, 0))


def tv_i1_context(**kw):
    fs = {**fx.foods(), 20: BREAD}
    chicken = fs[3]
    day = (
        fx.entry(fs[11], "breakfast", 2.0), fx.entry(BREAD, "breakfast", 2.0),  # OJ 1 cup (500 K, 26 g)
        fx.entry(fs[6], "lunch"), fx.entry(fs[1], "lunch"), fx.entry(chicken, "lunch"),
        fx.entry(fs[2], "dinner"), fx.entry(chicken, "dinner"), fx.entry(fs[5], "dinner"), fx.entry(fs[1], "dinner"),
        fx.entry(fs[10], "snack", purpose="hypo"), fx.entry(fs[11], "snack", purpose="hypo"),
    )
    return fx.context(food_map=fs, day=day, history=(), **kw)


def by_id(result):
    return {i["id"]: i for i in result["insights"]}


def test_tv_i1_day_messages_word_for_word():
    r = insights.day_insights(tv_i1_context())
    got = by_id(r)
    assert got["day.potassium_mg.over"]["message"] == (
        "Potassium was 2,809 mg today, 112 % of your 2,500 mg limit. Most came from potato (33 %) and orange juice (27 %).")
    assert got["day.carbs.meal_off"]["message"] == (
        "Lunch had 72 g and dinner 87 g of carbs, more than 10 g above your usual 60 g.")  # breakfast 54.6 g is within
    assert got["day.hypo.logged"]["message"] == (
        "You logged 2 low-glucose treatments (29 g carbs, 250 mg potassium). They are not counted in the meal carb "
        "check. Glucose tablets, 4 (1 × 4 tablets, 16 g carbs) would treat the same low with 0 mg potassium.")
    assert got["day.high_k.count"]["message"] == (
        "You had 5 high-potassium portions today: orange juice, banana, chicken breast (2) and potato.")
    # Severity order (warning > attention > info > good), then nutrient priority.
    assert [i["id"] for i in r["insights"]][:2] == ["day.potassium_mg.over", "day.high_k.count"]
    assert got["day.high_k.count"]["severity"] == "attention"  # potassium is over today
    assert got["day.potassium_mg.over"]["sources"][0] == {"name": "Potato, baked", "short_name": "potato",
                                                         "value": 925, "share_pct": 33}
    assert got["day.hypo.logged"]["handbook"][0]["url"] == "/learn/t1d/treating-a-low/"
    assert r["planned_excluded"] == 0


def test_low_treatments_are_never_warned_against():
    r = insights.day_insights(tv_i1_context())
    hypo = by_id(r)["day.hypo.logged"]
    assert hypo["severity"] == "info"
    for i in r["insights"]:
        if i["id"] != "day.hypo.logged":
            assert "low-glucose" not in i["message"] and "treatment" not in i["message"]


def tv_i2_entries() -> list[HistoryEntry]:
    base = [(1, "Rice, white, cooked", 68), (3, "Chicken breast, roasted", 196), (20, "Bread, white", 56),
            (21, "Egg, scrambled", 101), (5, "Green beans, boiled", 18), (22, "Apple, raw", 20), (23, "Pasta, cooked", 72),
            (24, "Milk, 1%", 232)]
    out = []
    for d in ("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"):
        for fid, name, p in base:
            out.append(HistoryEntry(date=d, meal="lunch", food_id=fid, name=name, servings=1,
                                    nutrients=fx.nutrients(10, 5, 50, p, 50, 0), purpose=None))
        if d in ("2026-09-28", "2026-09-30", "2026-10-02", "2026-10-03"):  # Mon, Wed, Fri, Sat
            out.append(HistoryEntry(date=d, meal="dinner", food_id=30, name="Cheese, cheddar", servings=1,
                                    nutrients=fx.nutrients(0, 7, 30, 381, 180, 0), purpose=None))
            out.append(HistoryEntry(date=d, meal="snack", food_id=31, name="Cola", servings=1,
                                    nutrients=fx.nutrients(39, 0, 8, 66, 10, 0), purpose=None,
                                    flags=frozenset({"phosphate_additive"})))
    return out


def test_tv_i2_weekly_phosphorus_and_additives():
    r = insights.period_insights(Profile(targets=fx.TARGETS), Prefs(), "2026-09-28", "2026-10-04", tv_i2_entries())
    got = by_id(r)
    p = got["period.phosphorus_mg.average_over"]
    assert p["severity"] == "attention"
    assert p["message"] == ("Phosphorus averaged 1,018 mg a day on the 7 days you logged, above your 1,000 mg target. "
                            "It was above target on 4 of 7 days; the main sources were milk and cheese.")
    assert p["numbers"] == {"average": 1018, "target": 1000, "days_above": 4, "logged_days": 7}
    assert [(s["short_name"], s["value"], s["share_pct"]) for s in p["sources"]] == [
        ("milk", 1624, 23), ("cheese", 1524, 21), ("chicken breast", 1372, 19)]
    assert p["handbook"][0]["url"] == "/learn/eat/phosphorus/"
    assert got["period.additives"]["message"] == "Phosphate-additive foods were eaten on 4 of 7 days: cola (4 times)."
    assert (r["logged_days"], r["days"]) == (7, 7) and "period.coverage" not in got


def test_tv_i3_fewer_than_three_logged_days():
    entries = [e for e in tv_i2_entries() if e.date in ("2026-09-28", "2026-09-29")]
    r = insights.period_insights(Profile(targets=fx.TARGETS), Prefs(), "2026-09-28", "2026-10-04", entries)
    assert [i["message"] for i in r["insights"]] == ["Log at least 3 days to see weekly insights."]
    assert r["logged_days"] == 2


def test_tv_i4_short_names_use_the_full_name_when_heads_clash():
    entries = [HistoryEntry(date="2026-10-01", meal="lunch", food_id=i, name=name, servings=1,
                            nutrients=fx.nutrients(0, 7, 30, p, 100, 0), purpose=None)
               for i, name, p in ((1, "Cheese, cheddar", 400), (2, "Cheese, Swiss", 300), (3, "Milk, 1%", 250))]
    assert [s["short_name"] for s in insights.sources(entries, "phosphorus_mg")] == ["cheese, cheddar", "cheese, swiss", "milk"]


def test_tv_i5_only_planned_entries_give_no_insights():
    fs = fx.foods()
    ctx = fx.context(day=(fx.entry(fs[2], "dinner", status="planned"), fx.entry(fs[6], "lunch", status="planned")))
    r = insights.day_insights(ctx)
    assert r["insights"] == [] and r["planned_excluded"] == 2


def test_sources_keep_shares_of_ten_percent_or_more_at_most_three():
    entries = [HistoryEntry(date="2026-10-01", meal="lunch", food_id=i, name=f"Food {i}", servings=1,
                            nutrients=fx.nutrients(0, 0, k, 0, 0, 0), purpose=None)
               for i, k in ((1, 400), (2, 300), (3, 150), (4, 100), (5, 50))]
    rows = insights.sources(entries, "potassium_mg")
    assert [r["short_name"] for r in rows] == ["food 1", "food 2", "food 3"]  # 40 %, 30 %, 15 %; 10 % is the 4th
    long = [HistoryEntry(date="2026-10-01", meal="lunch", food_id=9, name="x" * 200, servings=1,
                         nutrients=fx.nutrients(0, 0, 10, 0, 0, 0), purpose=None)]
    assert len(insights.sources(long, "potassium_mg")[0]["name"]) == 60  # untrusted names are truncated


def test_dialysis_protein_low_unknown_values_and_additives():
    fs = fx.foods()
    nameless = make_food(id=40, name="Soup from a label", category="Prepared & Fast Food", serving_desc="1 cup",
                         serving_g=240, nutrients=fx.nutrients(10, 3, None, None, 600, 200), source="custom")
    fs = {**fs, 40: nameless}
    day = (fx.entry(fs[8], "lunch"), fx.entry(nameless, "lunch"), fx.entry(fs[1], "dinner"))
    ctx = fx.context(food_map=fs, day=day, history=(), dialysis="peritoneal",
                     targets={**fx.TARGETS, "protein_g": {"min": 70, "max": 84}})
    got = by_id(insights.day_insights(ctx))
    assert got["day.protein.low"]["message"] == (
        "Protein was 12 g, below your 70 g minimum. On dialysis your body needs more protein, not less.")
    assert got["day.unknown"]["message"] == "1 food had no potassium or phosphorus value, so today's total may be low."
    assert got["day.additives"]["message"] == (
        "1 food today had phosphate additives: cheese. Additive phosphorus is almost fully absorbed.")


def test_interdialytic_and_energy_insights():
    fs = fx.foods()
    kcal_rice = make_food(id=50, name="Rice, white, cooked", category="Grains & Breads", serving_desc="1 cup", serving_g=158,
                          nutrients={**fx.nutrients(45, 4, 55, 70, 0, 0), "calories_kcal": 205})
    fs = {**fs, 50: kcal_rice}
    history = (fx.hist(fs[2], "2026-10-03", "dinner", 7.0),)  # Saturday, after Friday's session: 6,475 mg
    day = tuple(fx.entry(kcal_rice, m) for m in ("breakfast", "lunch", "dinner"))
    ctx = fx.context(food_map=fs, day=day, history=history, dialysis="hemodialysis", dialysis_days=(0, 2, 4),
                     date="2026-10-04", targets={**fx.TARGETS, "fluid_ml": 1500})
    got = by_id(insights.day_insights(ctx))
    inter = got["day.interdialytic"]
    assert inter["message"] == "Since dialysis on Friday, potassium adds up to 6,640 mg of 7,500 mg for 3 days."
    assert inter["severity"] == "attention"
    assert inter["handbook"][0]["slug"] == "dialysis-days"
    assert got["day.energy.low"]["message"] == (
        "Calories were 615 kcal, 29 % of your 2,100 kcal goal. Eating too little can cause muscle loss; fats such as "
        "olive oil add calories without potassium or phosphorus.")


def test_all_good_and_consistent_carbs():
    fs = fx.foods()
    day = (fx.entry(fs[1], "breakfast", 1.25), fx.entry(fs[1], "lunch", 1.25), fx.entry(fs[7], "lunch"))
    got = by_id(insights.day_insights(fx.context(day=day, history=())))
    assert got["day.carbs.consistent"]["message"] == "All 2 meals were within 10 g of your 60 g carb goal."
    r = insights.day_insights(fx.context(day=day, history=()))
    assert [i["severity"] for i in r["insights"]].count("good") == 1  # at most one "good", always last
    assert r["insights"][-1]["id"] == "day.carbs.consistent"
    no_carb_goal = insights.day_insights(fx.context(day=day, history=(), diabetes="none"))
    assert [i["message"] for i in no_carb_goal["insights"]] == [
        "Potassium, phosphorus and sodium all stayed within your targets today."]


def test_period_rules_days_over_weekend_hypo_count_change():
    def day_rows(d, k, hypo=False):
        return HistoryEntry(date=d, meal="snack" if hypo else "dinner", food_id=99 if hypo else 2,
                            name="Glucose tablets, 4" if hypo else "Potato, baked", servings=1,
                            nutrients=fx.nutrients(16 if hypo else 37, 0, 0 if hypo else k, 0, 0, 0),
                            purpose="hypo" if hypo else None)

    week = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    entries = [day_rows(d, 3000 if d in ("2026-10-03", "2026-10-04") else 1000) for d in week]
    entries += [day_rows(d, 0, hypo=True) for d in week[:3]]
    previous = [day_rows(d, 2000) for d in ("2026-09-21", "2026-09-22", "2026-09-23")]
    r = insights.period_insights(Profile(targets=fx.TARGETS), Prefs(), week[0], week[-1], entries, previous)
    got = by_id(r)
    over = got["period.potassium_mg.days_over"]
    assert over["severity"] == "attention"
    assert over["message"] == ("Potassium was over your limit on 2 of 7 days (Sat, Sun). The main source was potato. "
                               "Mostly at the weekend.")
    assert got["period.hypo.count"]["message"] == (
        "You logged 3 low-glucose treatments this week. Your diabetes team may want to know.")
    assert got["period.change.potassium_mg"]["message"] == "Potassium averaged 21 % less than the week before."
    assert len(r["insights"]) <= 6


def test_period_bounds_default_to_the_seven_days_ending_yesterday():
    assert insights.period_bounds(None, None, "2026-10-05") == ("2026-09-28", "2026-10-04", "2026-09-21", "2026-09-27")
    assert insights.period_bounds("2026-10-01", None, "2026-10-05")[:2] == ("2026-10-01", "2026-10-07")
    assert insights.period_bounds(None, "2026-10-01", "2026-10-05")[:2] == ("2026-09-25", "2026-10-01")


# --------------------------------------------------------------------------- #
# v0.3.0 review: the better low treatment names its portion; unknown values are never "within"
# --------------------------------------------------------------------------- #


def _hypo_day(foods, dose: float, exclude: frozenset[int] = frozenset()):
    oj = next(f for f in foods.values() if f.name.startswith("Orange juice"))
    ctx = fx.context(food_map=foods, day=(fx.entry(oj, "snack", 2.0, purpose="hypo"),), history=(),
                     prefs=Prefs(hypo_dose_g=dose, exclude_food_ids=exclude), dialysis="hemodialysis",
                     targets={**fx.TARGETS, "potassium_mg": 3000})
    return by_id(insights.day_insights(ctx))["day.hypo.logged"]


def test_the_better_low_treatment_names_the_portion_that_reaches_the_dose():
    """Note 06 F5 (never under-dose): "Glucose gel would treat the same low" read as one tube."""
    foods = fx.real_foods()
    gel_and_shot = frozenset(f.id for f in foods.values() if f.hypo and ("gel" in f.name_fold or "shot" in f.name_fold))
    for dose in (15, 20, 30):
        for exclude in (frozenset(), gel_and_shot):
            item = _hypo_day(foods, dose, exclude)
            best = insights.best_hypo_food(foods, Prefs(hypo_dose_g=dose, exclude_food_ids=exclude))
            assert best is not None
            food, servings, _k = best
            portion = f"{M.fmt_servings(servings)} × "
            assert f"{food.name} ({portion}" in item["message"], item["message"]
            carbs = (food.carbs or 0.0) * servings
            assert carbs >= dose and f", {M.fmt_g(carbs)} g carbs) would treat the same low" in item["message"]
            assert item["numbers"]["better_food_id"] == food.id and item["numbers"]["better_servings"] == servings
    tablets = _hypo_day(foods, 20, gel_and_shot)["message"]
    assert "Glucose tablet (4 g carb) (5 × 1 tablet, 20 g carbs) would treat the same low" in tablets


def test_all_good_never_includes_a_nutrient_with_unknown_values():
    fs = fx.foods()
    label = make_food(id=41, name="Crackers from a label", category="Snacks", serving_desc="5 crackers (30 g)", serving_g=30,
                      nutrients=fx.nutrients(19, 2, None, None, 230, 0), source="custom")
    day = (fx.entry(label, "lunch"), fx.entry(label, "lunch"), fx.entry(label, "dinner"))
    got = by_id(insights.day_insights(fx.context(food_map={**fs, 41: label}, day=day, history=(), diabetes="none")))
    assert got["day.unknown"]["message"] == "1 food had no potassium or phosphorus value, so today's total may be low."
    assert got["day.all_good"]["message"] == "Sodium stayed within your target today."  # not potassium, not phosphorus
    nothing = make_food(id=42, name="Mystery soup", category="Soups", serving_desc="1 cup", serving_g=240,
                        nutrients=fx.nutrients(10, 3, None, None, None, 0), source="custom")
    got = by_id(insights.day_insights(fx.context(food_map={**fs, 42: nothing}, day=(fx.entry(nothing, "lunch"),), history=(),
                                                 diabetes="none")))
    assert "day.all_good" not in got and got["day.unknown"]["numbers"]["nutrients"] == ["potassium_mg", "phosphorus_mg", "sodium_mg"]


def test_a_period_with_unknown_values_says_so_and_claims_nothing_for_them():
    week = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]

    def row(d, k, na, food_id=50, name="Soda from a scan"):
        return HistoryEntry(date=d, meal="lunch", food_id=food_id, name=name, servings=1,
                            nutrients=fx.nutrients(30, 0, k, 10, na, 0), purpose=None)

    entries = [row(d, None, None) for d in week]  # nothing known about potassium or sodium
    r = insights.period_insights(Profile(targets=fx.TARGETS), Prefs(), week[0], week[-1], entries)
    got = by_id(r)
    assert "period.all_good" not in got
    assert got["period.unknown"]["message"] == (
        "1 food had no potassium or sodium value (on 7 of 7 days), so these totals and averages may be low.")
    assert got["period.unknown"]["numbers"] == {"count": 1, "days": 7, "logged_days": 7,
                                                "nutrients": ["potassium_mg", "sodium_mg"]}
    # Sodium known every day, potassium missing on two: only sodium may be "within".
    mixed = [row(d, 500 if d not in week[:2] else None, 300) for d in week]
    got = by_id(insights.period_insights(Profile(targets=fx.TARGETS), Prefs(), week[0], week[-1], mixed))
    assert got["period.all_good"]["message"] == "Sodium stayed within your limit on all 7 days you logged."
    assert got["period.unknown"]["message"].endswith("(on 2 of 7 days), so these totals and averages may be low.")
    # "Less than the week before" could just be "not listed": no change insight for that nutrient.
    previous = [row(d, 2000, 300) for d in ("2026-09-21", "2026-09-22", "2026-09-23")]
    got = by_id(insights.period_insights(Profile(targets=fx.TARGETS), Prefs(), week[0], week[-1], mixed, previous))
    assert "period.change.potassium_mg" not in got
    known = [row(d, 500, 300) for d in week]
    got = by_id(insights.period_insights(Profile(targets=fx.TARGETS), Prefs(), week[0], week[-1], known, previous))
    assert got["period.change.potassium_mg"]["message"] == "Potassium averaged 75 % less than the week before."
    assert "period.unknown" not in got
