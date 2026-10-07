"""The personalised-targets and lab-results UI (note 05 §4.8) stays wired to the server it fronts.

Static checks of ``app/static`` (no browser): every v0.3 profile field has a labelled control in the
Profile form, the choices offered match the server's enums, the Labs view offers every analyte, the
demo API (``js/mock/*``) answers every targets/labs route the server has, its field list matches the
model, and the admin settings list every ``targets.*`` key. The numbers themselves are checked by the
parity vectors (``tests/test_targets_vectors.py`` + ``node tests/js/run_vectors.mjs``); the flows by
``tools/e2e/parity.py`` (section 11), ``regress.py`` and ``sandbox.py``.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from app import labs, models, settings_registry, units
from app import profile as profile_module
from app import target_rules as R

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
JS = {p.relative_to(STATIC).as_posix(): p.read_text(encoding="utf-8") for p in (STATIC / "js").rglob("*.js")}


class _Form(HTMLParser):
    """Collects controls (tag, attrs) and label targets inside one element subtree."""

    def __init__(self) -> None:
        super().__init__()
        self.controls: list[dict[str, str]] = []
        self.label_for: set[str] = set()
        self.options: dict[str, list[str]] = {}
        self._select: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag in ("input", "select", "textarea"):
            self.controls.append({"tag": tag, **a})
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag == "select":
            self._select = a.get("id")
            self.options[self._select or ""] = []
        if tag == "option" and self._select is not None:
            self.options[self._select].append(a.get("value", ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._select = None


def _section(start: str, end: str) -> str:
    i = INDEX.index(start)
    return INDEX[i:INDEX.index(end, i)]


def _parse(html: str) -> _Form:
    form = _Form()
    form.feed(html)
    return form


PROFILE = _parse(_section('<section id="view-profile"', '<section class="card profile-settings"'))
LABS_HTML = _section('<section id="view-labs"', "</section>\n\n  <!-- =====")
LABS = _parse(LABS_HTML)


def test_every_v03_profile_field_has_a_labelled_control() -> None:
    names = {c.get("name") for c in PROFILE.controls}
    for field in models.PROFILE_V03_FIELDS:
        assert field in names, f"no control named {field!r} in the Profile form"
    for c in PROFILE.controls:
        if c.get("type") in ("radio",) or not c.get("id"):
            continue
        assert c["id"] in PROFILE.label_for, f"control #{c['id']} has no <label for>"


def test_profile_choices_match_the_server() -> None:
    assert PROFILE.options["pf-sex"] == list(R.SEXES[::-1][:1]) + ["female", "male"]  # "unspecified" first, then the two formulas
    assert sorted(PROFILE.options["pf-sex"]) == sorted(R.SEXES)
    radios = [c["value"] for c in PROFILE.controls if c.get("name") == "activity"]
    assert radios == ["", *R.ACTIVITIES]  # "" = not chosen (null): the server's default applies
    # each activity radio has a visible description (NASEM 2023 Table 7-1 in plain words)
    for value in R.ACTIVITIES:
        assert re.search(rf'<label class="choice" for="pf-act-{value}">.*?<span class="hint">[^<]+</span>', INDEX), value
    # the sex help text of note 05 §4.2, linked to the select
    assert 'aria-describedby="pf-sex-help"' in INDEX and "ask your clinician which to use" in INDEX


def test_conditional_treatment_fields_start_hidden_and_are_driven_by_dialysis() -> None:
    for field_id in ("pf-urine-field", "pf-uf-field", "pf-pdkcal-field", "pf-dialysis-days-field"):
        assert re.search(rf'id="{field_id}"[^>]*\bhidden\b', INDEX), field_id
    view = JS["js/views/profile.js"]
    for rule in ("$('#pf-dialysis-days-field').hidden = dialysis !== 'hemodialysis';", "$('#pf-urine-field').hidden = dialysis === 'none';",
                 "$('#pf-uf-field').hidden = dialysis !== 'peritoneal';", "$('#pf-pdkcal-field').hidden = dialysis !== 'peritoneal';",
                 "$('#pf-transplant-field').hidden = dialysis !== 'none';"):
        assert rule in view, rule
    assert "Dry weight (kg, after dialysis)" in view  # note 05 §4.2: weight relabelled on dialysis


def test_targets_editor_has_ranges_and_the_fiber_goal() -> None:
    assert 'data-range-min="protein_g"' in INDEX and 'data-range-max="protein_g"' in INDEX
    assert 'data-range-min="calcium_mg"' in INDEX and 'data-range-max="calcium_mg"' in INDEX  # CA-3 {RDA, UL}
    assert 'data-target-goal="fiber_g"' in INDEX  # FB-1: a goal, never "over"
    view = JS["js/views/profile.js"]
    assert "targets[inp.dataset.targetGoal] = v == null ? null : { min: v };" in view
    today = JS["js/views/today.js"]
    assert "if (st.target == null && st.min != null) return goalBar(key, st);" in today
    assert "about ${fmtNum(st.target, key)}" in today  # protein min = max reads "about X"


def test_labs_view_offers_every_analyte_and_unit() -> None:
    view = JS["js/views/labs.js"]
    order = re.search(r"const ANALYTE_ORDER = \[([^\]]+)\]", view).group(1)
    assert sorted(re.findall(r"'([a-z0-9_]+)'", order)) == sorted(units.ANALYTE_KEYS)
    for analyte in units.ANALYTE_KEYS:
        assert re.search(rf"\b{analyte}: '/learn/labs/[a-z0-9-]+/'", view), f"no handbook page for {analyte}"
        assert re.search(rf"\b{analyte}: '[^']+'", view[view.index("const ROLE"):view.index("const LEARN")]), f"no role line for {analyte}"
    for control in ("lab-analyte", "lab-value", "lab-unit", "lab-date", "lab-note"):
        assert control in LABS.label_for, control
    assert 'id="lab-echo" class="lab-echo" aria-live="polite"' in LABS_HTML  # the conversion is announced, not only shown
    assert 'id="labs-alert" class="lab-alerts" role="alert"' in LABS_HTML


def test_the_demo_answers_every_targets_and_labs_route() -> None:
    mocks = "\n".join(text for name, text in JS.items() if name.startswith("js/mock/"))
    registered = set(re.findall(r"route\('([A-Z*]+)', '([^']+)'", mocks))
    server = {(m, r.path) for r in labs.router.routes for m in r.methods} | {
        (m, r.path) for r in profile_module.router.routes for m in r.methods}
    for method, path in server:
        demo_path = re.sub(r"\{[a-z_]+\}", "{id}", path)
        assert (method, demo_path) in registered or ("*", demo_path) in registered, f"no demo route for {method} {path}"


def test_demo_profile_fields_match_the_model() -> None:
    mock = JS["js/mock/profile.js"]
    fields = re.search(r"const V03_FIELDS = \[([^\]]+)\]", mock).group(1)
    assert re.findall(r"'([a-z0-9_]+)'", fields) == list(models.PROFILE_V03_FIELDS)
    assert re.findall(r"'([a-z_]+)'", re.search(r"const LAB_FIELDS = \[([^\]]+)\]", JS["js/mock/labs.js"]).group(1)) == list(
        models.LabCreate.model_fields)


def test_admin_settings_list_every_targets_key_and_preferences_offer_lab_units() -> None:
    settings_js = JS["js/views/settings.js"]
    group = settings_js[settings_js.index("['Personalised targets and lab results'"):]
    group = group[:group.index("]],")]
    keys = [d.key for d in settings_registry.all_settings() if d.key.startswith("targets.")]
    assert keys and all(f"'{k}'" in group for k in keys)
    assert '<select id="set-lab-units"' in INDEX and "'user.units.labs': sel.value" in settings_js


def test_the_demo_ships_with_lab_rules_off() -> None:
    """Note 05 §7 C10: until the clinical review, public demo instances run with targets.lab_rules_enabled off. The
    preview and ?mock=1 demo are the project's public demo (contract item 15): its admin starts with the switch off
    (and may turn it on like any admin); the very-high-potassium alert does not depend on it."""
    import json
    import shutil
    import subprocess

    assert shutil.which("node"), "Node.js 22 is needed to run the demo's settings (CLAUDE.md, Parity)"
    script = r"""
const fs = require('fs'); const vm = require('vm'); const path = require('path');
const root = process.argv[1];
const ctx = vm.createContext({ console });
vm.runInContext('globalThis.window = globalThis;', ctx);
for (const rel of ['app/static/js/engine/rules.js', 'app/static/js/engine/settings.js', 'app/static/js/mock/core.js', 'app/static/js/mock/settings.js'])
  vm.runInContext(fs.readFileSync(path.join(root, rel), 'utf8'), ctx, { filename: rel });
const KH = vm.runInContext('globalThis.KH', ctx);
const api = Object.create(KH.mock.MockApi.prototype);
const off = api._effectiveSetting('targets.lab_rules_enabled', 1);
api._settingsState().instance['targets.lab_rules_enabled'] = undefined;
delete api._settingsState().instance['targets.lab_rules_enabled'];
const reset = api._effectiveSetting('targets.lab_rules_enabled', 1);
console.log(JSON.stringify({ off, reset }));
"""
    out = subprocess.run(["node", "-e", script, str(ROOT)], capture_output=True, text=True, timeout=60, check=True).stdout
    got = json.loads(out)
    assert got["off"]["value"] is False and got["off"]["source"] == "instance", got
    assert got["reset"]["value"] is True, "back to the default (an admin's choice) the rules are on, as on a server"
    assert settings_registry.REGISTRY["targets.lab_rules_enabled"].default is True  # a real server's default is unchanged
    # The demo's suggestion reads the setting (and the alert is computed regardless, js/engine/targets.js).
    assert "lab_rules_enabled: !!get('targets.lab_rules_enabled')" in JS["js/mock/profile.js"]
    assert "The safety alert does not depend on targets.lab_rules_enabled" in JS["js/engine/targets.js"]
    # tools/e2e/parity.py section 11 compares the shipped values, then puts both sides at the default.
    parity = (ROOT / "tools" / "e2e" / "parity.py").read_text(encoding="utf-8")
    assert '"lab rules as shipped: on for a server, off for the demo", [True, False]' in parity
