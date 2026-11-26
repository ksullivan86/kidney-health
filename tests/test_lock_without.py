"""scripts/lock_without.py: the iPhone app's jobs build the handbook on a Mac without watchdog, which `mkdocs build` never uses
and which has no macOS wheel for Python 3.14 (CI on 2026-11-26)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lock_without", ROOT / "scripts" / "lock_without.py")
lw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lw)

LOCK = """# header
mkdocs==1.6.1 \\
    --hash=sha256:aa
    # via -r requirements.in
watchdog==6.0.0 \\
    --hash=sha256:bb \\
    --hash=sha256:cc
    # via mkdocs
zipp==3.0 \\
    --hash=sha256:dd
"""


def test_only_the_named_package_and_its_lines_go():
    out = "".join(lw.without(LOCK.splitlines(keepends=True), {"watchdog"}))
    assert "watchdog" not in out and "sha256:bb" not in out and "sha256:cc" not in out
    assert "mkdocs==1.6.1 \\\n    --hash=sha256:aa\n    # via -r requirements.in\n" in out and "zipp==3.0 \\\n    --hash=sha256:dd\n" in out


def test_a_name_not_in_the_file_is_an_error(tmp_path):
    src = tmp_path / "r.lock"
    src.write_text(LOCK, encoding="utf-8")
    assert lw.main(["x", str(src), str(tmp_path / "o.lock"), "nosuch"]) == 1
    assert lw.main(["x", str(src), str(tmp_path / "o.lock"), "watchdog"]) == 0


def test_the_real_lock_still_has_watchdog_and_both_mac_jobs_leave_it_out():
    assert "\nwatchdog==" in (ROOT / "handbook" / "requirements.lock").read_text(encoding="utf-8")
    for wf in ("ci.yml", "testflight.yml"):
        text = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
        assert 'python ../scripts/lock_without.py requirements.lock "$RUNNER_TEMP/handbook.lock" watchdog' in text, wf
