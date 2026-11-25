"""More on the iPhone's own AI (the owner, 2026-11-25; design note 39 §6.6).

* tests/js/phone_ai_more.mjs drives the page with a stand-in app: plate and label photos on the iPhone's model, meal ideas and AI
  recipes on the own key and on the iPhone's model, all with the server's checks.
* The Swift side (read as text): the guessed iOS 27 image call is only compiled with KH_ONDEVICE_IMAGES, which CI probes first;
  the answer shapes are the server's schemas; no network, nothing kept, never a dosing task.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from app.ai import schemas

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "ios" / "KidneyHealth" / "Services"
ON_DEVICE = (SERVICES / "OnDeviceAI.swift").read_text(encoding="utf-8")
VISION = (SERVICES / "OnDeviceVision.swift").read_text(encoding="utf-8")


def _code(text: str) -> str:
    return re.sub(r"//[^\n]*", "", text)


def test_the_page_with_a_stand_in_app() -> None:
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "phone_ai_more.mjs")], capture_output=True, text=True, timeout=300,
                          check=False)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-4000:]
    assert "checks passed" in done.stdout


def test_the_guessed_image_call_never_breaks_the_build() -> None:
    """The one guessed iOS 27 API (a CGImage in a Prompt) compiles only with the flag; CI probes it and builds without it if not."""
    code = _code(VISION)
    flagged = code[code.index("#if KH_ONDEVICE_IMAGES"):code.index("#endif", code.index("#if KH_ONDEVICE_IMAGES"))]
    assert "Prompt {" in flagged and "if #available(iOS 27.0, *)" in flagged
    assert code.count("Prompt {") == 1 and "Prompt {" not in _code(ON_DEVICE)
    assert "#if canImport(FoundationModels) && KH_ONDEVICE_IMAGES" in code
    project = (ROOT / "ios" / "KidneyHealth.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
    assert "KH_ONDEVICE_IMAGES" not in project  # off until the CI probe shows the guess compiles
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci[ci.index("  ios-app:"):ci.index("  lint:")]
    assert "build-for-testing" in job and "KH_ONDEVICE_IMAGES" in job and '${flags[@]+"${flags[@]}"}' in job
    for word in ("URLSession", "UserDefaults", ".write(to:", "Keychain", "print(", "NSLog"):
        assert word not in VISION, word  # the photo stays on the phone and is not kept


def test_the_answer_shapes_are_the_servers_schemas() -> None:
    """Each @Generable reply has the fields of the server's wire schema, in its order, and the JSON the page gets uses its keys."""
    def fields(struct: str) -> list[str]:
        body = ON_DEVICE[ON_DEVICE.index(f"struct {struct} {{"):]
        body = body[: body.index("\n}\n")]
        return [f for f in re.findall(r"^    var (\w+): ", body, flags=re.M) if f != "json"]

    plate = schemas.plate_schema()
    assert fields("PlateReply") == list(plate["properties"])
    assert fields("PlateItem") == list(plate["properties"]["items"]["items"]["properties"])
    label = schemas.read_label_schema()
    assert fields("LabelReply") == list(label["properties"])
    assert fields("LabelValues") == list(label["properties"]["per_serving"]["properties"])
    assert fields("LabelPercentDV") == list(label["properties"]["percent_dv"]["properties"])
    ideas = schemas.ideas_schema([1], ["potassium"])
    assert fields("IdeasReply") == list(ideas["properties"])
    assert fields("IdeaReply") == list(ideas["properties"]["ideas"]["items"]["properties"])
    assert fields("FoodQuarters") == ["food_id", "quarters"]
    recipe = schemas.recipes_schema([1], steps=False)["properties"]["recipes"]["items"]["properties"]
    assert fields("RecipeReply") == [k for k in recipe if k != "steps"]  # no steps from AI on the phone: always an empty list
    assert '"steps": [String]()' in ON_DEVICE
    enums = {
        "PlateStatus": plate["properties"]["status"]["enum"], "PlateConfidence": ["low", "medium", "high"],
        "LabelStatus": label["properties"]["status"]["enum"], "LabelBasis": label["properties"]["basis"]["enum"],
        "LabelStyle": label["properties"]["label_style"]["enum"], "IdeaTheme": list(schemas.THEMES),
        "ReasonCode": list(schemas.REASON_CODES), "IdeasRefusal": ["none", "outside_scope", "no_fit"],
        "RecipeDish": list(schemas.RECIPE_DISHES),
    }
    for name, values in enums.items():
        block = ON_DEVICE[ON_DEVICE.index(f"enum {name}: String {{"):]
        case = re.search(r"case ([^\n]+)", block).group(1)
        assert [c.strip() for c in case.split(",")] == values, name
    code = _code(ON_DEVICE).lower()
    for word in ("insulin", "dose", "dosing", "bolus"):
        assert word not in code, word


def test_the_ai_meal_vectors_are_current() -> None:
    """tests/data/ai_meal_vectors.json is what the server's code gives now (tests/js/run_vectors.mjs replays it on the twin)."""
    done = subprocess.run([sys.executable, str(ROOT / "tests" / "data" / "gen_ai_meal_vectors.py"), "--check"], capture_output=True,
                          text=True, timeout=600, check=False, cwd=ROOT)
    assert done.returncode == 0, done.stderr[-3000:]


def test_the_twins_constants_and_texts_are_the_servers() -> None:
    from app.ai import guard, prompts
    from app.ai import recipes as AR

    twin = (ROOT / "app" / "static" / "js" / "engine" / "aimeal.js").read_text(encoding="utf-8")

    def js_list(name: str) -> list[str]:
        m = re.search(rf"const {name} = \[([^\]]*)\];", twin)
        assert m, name
        return re.findall(r"'([^']*)'", m.group(1))

    assert js_list("THEMES") == list(schemas.THEMES)
    assert js_list("REASON_CODES") == list(schemas.REASON_CODES)
    assert js_list("AI_HANDBOOK_SLUGS") == list(prompts.AI_HANDBOOK_SLUGS)
    assert set(js_list("COOK_LATER")) == AR.COOK_LATER
    assert set(js_list("SHOWN_FLAGS")) == prompts.SHOWN_FLAGS
    assert js_list("TARGET_KEYS") == list(prompts.TARGET_KEYS) and js_list("TOTAL_KEYS") == list(prompts.TOTAL_KEYS)
    assert js_list("DAY_JUDGED") == list(prompts.DAY_JUDGED) and js_list("WEEK_JUDGED") == list(prompts.WEEK_JUDGED)
    assert f"const AI_RECIPE_FOODS_MAX = {AR.AI_RECIPE_FOODS_MAX};" in twin
    assert f"const AI_RECIPE_INGREDIENTS_MIN = {AR.AI_RECIPE_INGREDIENTS_MIN};" in twin
    assert f"const HEARTY_KCAL = {guard.HEARTY_KCAL};" in twin
    assert AR.NEVER_ADD.pattern in twin
    for text in (guard.REFUSED_TEXT, guard.NO_FIT_TEXT, guard.PORTION_LOWERED_TEXT, guard.PORTIONS_LOWERED_TEXT, AR.NO_FIT_TEXT,
                 AR.DROPPED_ALL_TEXT, AR.FOOD_SWAPPED_TEXT, AR.PORTION_LOWERED_TEXT, AR.PORTIONS_LOWERED_TEXT, AR.NOT_SENT_TEXT):
        assert text.replace("'", "\\'") in twin + (ROOT / "app" / "static" / "js" / "mock" / "ai.js").read_text(encoding="utf-8"), text
    for code, text in guard.REASON_TEXT.items():
        assert f"{code}: '{text}'" in twin, code
    for theme, text in guard.THEME_TITLE.items():
        assert f"{theme}: '{text}'" in twin, theme
    assert "`AI idea · ${label} · ${model} · checked against your targets · not medical advice`" in twin
    assert guard.NOTICE == "AI idea · {label} · {model} · checked against your targets · not medical advice"


def test_the_iphone_data_budget_fits_its_window() -> None:
    """js/mock/ai.js cuts the iPhone model's data block to DATA_CHARS.iphone characters. With the longest rules and a reply of
    about 1,000 tokens that stays inside the model's 4,096 tokens, counting 3 characters a token (JSON reads at fewer than prose)."""
    from app.ai import prompts

    mock = (ROOT / "app" / "static" / "js" / "mock" / "ai.js").read_text(encoding="utf-8")
    m = re.search(r"const DATA_CHARS = \{ own: (\d+), iphone: (\d+) \};", mock)
    assert m
    iphone = int(m.group(2))
    rules = max(len(prompts.system_prompt(None)), len(prompts.recipe_system_prompt(None)))
    assert (rules + iphone + 400) / 3 + 1000 <= 4096
    assert iphone <= 8000  # OnDeviceAI.swift maxTextChars
