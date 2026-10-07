"""docs/guidance.md and the contract stay in step with the engine (note 06 §7 "Docs")."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from app import settings_registry
from app.guidance import rules as R
from app.guidance.api import router

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "guidance.md").read_text(encoding="utf-8")
CONTRACT = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")


def _script():
    spec = importlib.util.spec_from_file_location("guidance_rules_doc", ROOT / "scripts" / "guidance_rules_doc.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_rules_table_in_the_docs_is_current():
    script = _script()
    assert script.render(DOC) == DOC, "docs/guidance.md is stale: run python3 scripts/guidance_rules_doc.py"
    assert f"Rules version **{R.RULES_VERSION}**" in DOC


def test_every_engine_constant_is_documented_or_structural():
    names = {n for n in vars(R) if n.isupper() and not n.startswith("_")}
    documented = {name for name, _ in R.RULE_DOCS}
    assert names <= documented | R.STRUCTURAL, sorted(names - documented - R.STRUCTURAL)
    assert all(note.strip() for _, note in R.RULE_DOCS)
    assert len(documented) == len(R.RULE_DOCS)  # no name twice


def test_docs_and_contract_name_every_route_and_setting():
    for route in router.routes:
        path = route.path  # type: ignore[attr-defined]
        assert path.replace("{food_id}", "") .split("?")[0].rstrip("/") in CONTRACT, path
    assert "POST /api/log/batch" in CONTRACT and "client_id" in CONTRACT
    for key in ("guidance.enabled", "guidance.pool_per_role", "guidance.beam_width"):
        settings_registry.get(key)
        assert key in DOC and key in CONTRACT
    for field in settings_registry.GuidancePreferences.model_fields:
        assert field in DOC, field
