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
