"""Keep the browser walk strict while recognizing Chromium's two XML-parser CSP message formats."""
import ast
from pathlib import Path

import pytest


@pytest.fixture
def matcher():
    # The harness imports optional Playwright; load just its pure matcher so normal pytest needs no browser package.
    path = Path(__file__).resolve().parents[1] / "tools" / "e2e" / "regress.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "xml_parser_style_error")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["xml_parser_style_error"]


@pytest.mark.parametrize("message", [
    'Refused to apply inline style because it violates the following Content Security Policy directive: "style-src \'self\'".',
    "Applying inline style violates the following Content Security Policy directive 'style-src 'self''. The action has been blocked.",
])
def test_known_xml_parser_style_errors_are_recognized(matcher, message):
    assert matcher(("error", message))
    assert not matcher(("warning", message))
    assert not matcher(("log", message))


@pytest.mark.parametrize("message", [
    "ReferenceError: lab importer failed",
    "Applying inline script violates the following Content Security Policy directive 'script-src 'self''.",
    "Refused to apply inline style because it violates style-src 'none'",
    "Applying inline style violates the following Content Security Policy directive 'style-src-elem 'self''.",
    "Something went wrong with style-src 'self'",
    "Refused to load the stylesheet because it violates style-src 'self'",
])
def test_unrelated_errors_still_fail_the_walk(matcher, message):
    assert not matcher(("error", message))
