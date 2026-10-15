"""The storage layer of "Keep my data in this browser" (app/static/js/mock/persist.js, mock/export.js), run by Node against a
fake IndexedDB (tests/js/fake_idb.mjs): off by default and nothing opened outside the demo build, turning it on, saving after a
write (debounced), reading it back after a reload, a copy from a newer version left alone, two tabs, a full disk, a browser that
refuses storage, stopping, the empty start, and the shape of the export. See tests/js/demo_local_storage.mjs for the cases."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app import account

ROOT = Path(__file__).resolve().parents[1]


def test_the_storage_layer_against_a_fake_indexeddb():
    assert shutil.which("node"), "Node.js 22 is needed to run the storage tests (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "demo_local_storage.mjs")], capture_output=True, text=True, timeout=180, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "demo local storage:" in done.stdout and "checks passed" in done.stdout


def test_the_export_of_the_demo_has_the_servers_keys_in_the_servers_order():
    """The keys of export_data, read from its source: the demo's document (mock/export.js) must list the same, in the same order."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(account.export_data))
    returned = next(node for node in ast.walk(tree) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict))
    server_keys = [key.value for key in returned.value.keys if isinstance(key, ast.Constant)]
    js = (ROOT / "app" / "static" / "js" / "mock" / "export.js").read_text(encoding="utf-8")
    body = js[js.index("      return {\n        format: EXPORT_FORMAT"):js.index("    },\n  });")]
    import re

    demo_keys = re.findall(r"^ {8}([a-z_]+)(?::|,)", body, re.MULTILINE)  # `key: value,` and the shorthand `settings,`
    assert demo_keys == server_keys
