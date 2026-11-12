"""The lines of a PDF page's own text (``app/static/js/engine/pdf_text.js``, ``KH.pdfText``; design note 36): the Node tests in
``tests/js/pdf_text.test.mjs``, and the file's place in the shell and the service worker."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_the_line_builder_node_tests_pass():
    assert shutil.which("node"), "Node.js is required for the PDF text tests"
    runner = Path(__file__).parent / "js" / "pdf_text.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_file_is_in_the_shell_before_the_lab_report_view_and_in_the_service_worker():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="([^"]+)"', index)
    assert scripts.index("js/engine/pdf_text.js") < scripts.index("js/views/lab_photo.js")
    shell = re.search(r"const SHELL_URLS = \[(.*?)\];", (STATIC / "sw.js").read_text(encoding="utf-8"), re.S).group(1)
    assert "'/js/engine/pdf_text.js'," in shell


def test_the_module_fetches_nothing_and_writes_no_html():
    source = (STATIC / "js" / "engine" / "pdf_text.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    for never in ("fetch(", "XMLHttpRequest", "import(", "innerHTML", "document.", "localStorage", "eval(", "new Function"):
        assert never not in code, never
    assert "MAX_CHARS: 20000" in source  # the server's limit (app/ai/lab_report.py MAX_TEXT_CHARS)
    from app.ai import lab_report

    assert lab_report.MAX_TEXT_CHARS == 20000
