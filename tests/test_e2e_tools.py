"""The end-to-end harnesses in tools/e2e/ (run by hand, see tools/e2e/README.md) stay runnable:
they parse the server's first-run setup line, carry no machine-specific paths and compile."""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.auth.bootstrap import setup_line

REPO = Path(__file__).resolve().parent.parent
E2E = REPO / "tools" / "e2e"
HARNESSES = ("khserver.py", "parity.py", "regress.py", "sandbox.py", "learn.py", "guidance_perf.py", "device.py",
             "journey.py", "upgrade.py", "replay_app.py")


def load_khserver():
    spec = importlib.util.spec_from_file_location("khserver", E2E / "khserver.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("public_url", [None, "https://food.example.net:8443"])
def test_harness_reads_the_setup_code_from_the_server_log(public_url):
    khserver = load_khserver()
    code = "ABCD-EF23-4567-WXYZ"
    settings = SimpleNamespace(public_origin=public_url, setup_code_ttl_minutes=60)
    line = "WARNING kidney_health.auth: " + setup_line(SimpleNamespace(settings=settings), code)
    assert khserver.SETUP_LINE.findall("INFO other line\n" + line + "\n") == [code]


def test_harness_password_passes_the_policy():
    from app.auth import policy

    khserver = load_khserver()
    assert policy.validate_new_password(khserver.DEFAULT_PASSWORD, username="parity", min_length=15) == []


@pytest.mark.parametrize("name", HARNESSES)
def test_harness_compiles_and_has_no_machine_paths(name):
    text = (E2E / name).read_text(encoding="utf-8")
    ast.parse(text, filename=name)
    assert not re.search(r"/home/\w|/tmp/claude|scratchpad|/root/", text), f"{name} hard-codes a local path"
    assert not re.search(r"^\s*(import httpx\b(?!2)|from httpx\b(?!2))", text, re.M), f"{name} imports httpx (use httpx2)"


def test_readme_documents_every_harness():
    readme = (E2E / "README.md").read_text(encoding="utf-8")
    for name in HARNESSES:
        assert name in readme


def test_work_directory_wipe_is_guarded(tmp_path):
    khserver = load_khserver()
    for refused in (REPO, REPO / "app", REPO / "data" / "x", REPO.parent, Path.home()):
        with pytest.raises(SystemExit):
            khserver.free_dir(refused)
    keep = tmp_path / "precious"
    keep.mkdir()
    (keep / "notes.txt").write_text("mine")
    with pytest.raises(SystemExit):
        khserver.free_dir(keep)  # not empty and not made by a harness
    assert (keep / "notes.txt").exists()
    work = khserver.free_dir(tmp_path / "work")
    (work / "data.db").write_text("x")
    assert khserver.free_dir(work) == work and not (work / "data.db").exists()  # a harness directory is reused


def test_replay_app_answers_usda_from_the_recorded_fixtures():
    """journey.py runs the app as ``replay_app:app``: FoodData Central answered from tests/fixtures/usda."""
    import sys

    import httpx2

    sys.path.insert(0, str(E2E))
    try:
        import replay_app
    finally:
        sys.path.remove(str(E2E))
    base = "https://api.nal.usda.gov/fdc/v1"
    found = replay_app.handle(httpx2.Request("GET", f"{base}/foods/search?query=00049000028911&dataType=Branded&pageSize=10"))
    assert found.status_code == 200 and found.json()["foods"]
    nothing = replay_app.handle(httpx2.Request("GET", f"{base}/foods/search?query=0099999999990&dataType=Branded&pageSize=10"))
    assert nothing.status_code == 200 and nothing.json()["foods"] == []
    assert replay_app.handle(httpx2.Request("GET", f"{base}/food/2742723")).status_code == 200
    assert replay_app.handle(httpx2.Request("GET", f"{base}/food/1")).status_code == 404
    client = replay_app.replay_client()
    assert client.get("/food/2742723").json()["description"].startswith("Diet Coke")


def test_upgrade_starting_points_exist():
    """upgrade.py unpacks these commits with git archive; they must stay reachable in the history."""
    import subprocess

    spec = importlib.util.spec_from_file_location("upgrade_harness", E2E / "upgrade.py")
    text = (E2E / "upgrade.py").read_text(encoding="utf-8")
    starts = dict(re.findall(r'"(v0\.2|v3)": "([0-9a-f]{7,40})"', text))
    assert set(starts) == {"v0.2", "v3"} and spec is not None
    for rev in starts.values():
        if subprocess.run(["git", "-C", str(REPO), "rev-parse", "--is-shallow-repository"], capture_output=True, text=True).stdout.strip() == "true":
            break  # a shallow CI checkout has no old commits; the harness is run by hand on a full clone
        assert subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{rev}^{{commit}}"]).returncode == 0, rev
