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
             "journey.py", "upgrade.py", "replay_app.py", "mcp_smoke.py", "ask.py", "menuplan.py", "ask_voice.py", "symptoms.py",
             "visitprep.py", "fallback.py", "demo_local.py", "prefs.py", "import_walk.py", "body_import.py", "lab_pdf.py", "body.py",
             "readme_shots.py", "push.py", "cloud_env.py", "reliability.py", "a11y.py")


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


def a11y_functions(*names):
    """Functions of a11y.py that need no browser (the module itself imports Playwright, which pytest does not have)."""
    import zlib
    from typing import Any

    tree = ast.parse((E2E / "a11y.py").read_text(encoding="utf-8"))
    found = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    space = {"zlib": zlib, "Any": Any}
    exec(compile(ast.Module(body=found, type_ignores=[]), "a11y.py", "exec"), space)  # noqa: S102 - the repository's own code
    return [space[n] for n in names]


def test_a11y_reads_the_pixels_of_a_browser_picture():
    """The edge of a checkbox the browser draws is measured on its pixels; every PNG row filter must decode."""
    import zlib

    png_pixels, ratio = a11y_functions("png_pixels", "ratio")
    rows = [[(255, 255, 255), (118, 118, 118), (21, 101, 192)], [(0, 0, 0), (10, 200, 30), (250, 5, 128)],
            [(1, 2, 3), (4, 5, 6), (7, 8, 9)], [(118, 118, 118), (255, 255, 255), (60, 60, 60)], [(9, 9, 9), (200, 100, 50), (50, 100, 200)]]

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else b if pb <= pc else c

    raw, prev = b"", bytes(9)
    for kind, row in enumerate(rows):  # filters 0 to 4, one per row
        line = bytes(v for px in row for v in px)
        enc = bytearray()
        for i, x in enumerate(line):
            a, b, c = (line[i - 3] if i >= 3 else 0), prev[i], (prev[i - 3] if i >= 3 else 0)
            enc.append((x - (0, a, b, (a + b) // 2, paeth(a, b, c))[kind]) & 255)
        raw += bytes([kind]) + bytes(enc)
        prev = line

    def chunk(tag, body):
        return len(body).to_bytes(4, "big") + tag + body + zlib.crc32(tag + body).to_bytes(4, "big")

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", (3).to_bytes(4, "big") + (5).to_bytes(4, "big") + bytes([8, 2, 0, 0, 0]))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    assert png_pixels(png) == [px for row in rows for px in row]
    assert round(ratio((118, 118, 118), (255, 255, 255)), 2) == 4.54  # Chromium's checkbox edge on white
    assert round(ratio((215, 219, 226), (255, 255, 255)), 2) == 1.39  # the old field edge


def test_sandbox_waits_for_the_trends_charts_without_reading_null():
    """Pressing 7 d changes the title at once and draws the charts a moment later. The wait read the first chart before it was
    there and threw "Cannot read properties of null", which the walk reported as a page error on Trends."""
    text = (E2E / "sandbox.py").read_text(encoding="utf-8")
    waits = [line for line in text.splitlines() if "querySelectorAll('.hit').length === d" in line]
    assert waits and all("#charts .chart-card svg')?.querySelectorAll" in line for line in waits)


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
