#!/usr/bin/env python3
"""Speak MCP to a real server: the assistant's read-only tools at ``POST /mcp``, end to end.

    python tools/e2e/mcp_smoke.py                     # port 8073, work directory in the system temp dir
    python tools/e2e/mcp_smoke.py --port 8073 --out /tmp/kh-mcp

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with the built-in food list (``khserver.Server``), finishes
first-run setup as the first admin, switches assistant access on through the admin settings API
(``PATCH /api/admin/settings``), makes an assistant token through ``POST /api/me/tokens``, and then talks to
``/mcp`` the way a chat client does, over plain HTTP with only the bearer token (no cookie, no CSRF header):

* ``initialize`` (version 2025-06-18), ``notifications/initialized`` (202), ``tools/list`` (the four tools);
* ``get_today``; ``check_meal`` for "banana" and "white rice 1 cup" (both found in the built-in list, the cup read
  from the food's own serving); ``safety_check("I feel shaky and low")`` (the Treating a low card);
* and the refusals: no token (401), ``GET`` (405), a foreign ``Origin`` (403).

Nothing leaves the machine: no USDA key, Open Food Facts off, no AI. Prints PASS / FAIL lines, writes
``<out>/report.json``; exit status 1 on any failure. The server is always stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

import httpx2

import khserver
from khserver import Server, first_admin

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "mcp_smoke"
PORT = 8073
PROTOCOL = "2025-06-18"
TOOLS = {"get_today", "search_foods", "check_meal", "safety_check"}
RESULTS: list[dict[str, Any]] = []


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


class Mcp:
    """A minimal MCP client over Streamable HTTP (JSON answers): one POST per message, the bearer token only."""

    def __init__(self, base: str, token: str) -> None:
        self.client = httpx2.Client(base_url=base, trust_env=False, timeout=60, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"})
        self.next_id = 0
        self.version: str | None = None

    def post(self, message: dict[str, Any]) -> httpx2.Response:
        headers = {"MCP-Protocol-Version": self.version} if self.version else {}
        return self.client.post("/mcp", json=message, headers=headers)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.next_id += 1
        r = self.post({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        if r.status_code != 200:
            raise RuntimeError(f"{method}: HTTP {r.status_code} {r.text[:300]}")
        body = r.json()
        if body.get("id") != self.next_id or "error" in body:
            raise RuntimeError(f"{method}: {body}")
        return body["result"]

    def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        result = self.request("tools/call", {"name": tool, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"{tool}: {result['content'][0]['text']}")
        data = result["structuredContent"]
        if json.loads(result["content"][0]["text"]) != data:
            raise RuntimeError(f"{tool}: the text content is not the structured content")
        return data

    def close(self) -> None:
        self.client.close()


def run(server: Server) -> None:
    admin = first_admin(server, "mcp-smoke")
    try:
        settings = admin.json("PATCH", "/api/admin/settings", {"assistant.enabled": True})["settings"]
        check("the admin switches assistant access on", settings["assistant.enabled"]["value"] is True)
        made = admin.json("POST", "/api/me/tokens", {"name": "MCP smoke", "expires_in_days": 30})
        token = made["token"]
        check("a token is made once, kha_ + 43 characters", token.startswith("kha_") and len(token) == 47)
    finally:
        admin.close()

    bare = httpx2.Client(base_url=server.base, trust_env=False, timeout=30)
    try:
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        r = bare.post("/mcp", json=ping)
        check("no token: 401 with a Bearer challenge", r.status_code == 401 and r.headers.get("www-authenticate", "").startswith("Bearer"))
        r = bare.get("/mcp", headers={"Authorization": f"Bearer {token}"})
        check("GET /mcp: 405 (no SSE stream)", r.status_code == 405 and r.headers.get("allow") == "POST")
        r = bare.post("/mcp", json=ping, headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"})
        check("a foreign Origin: 403", r.status_code == 403)
    finally:
        bare.close()

    mcp = Mcp(server.base, token)
    try:
        init = mcp.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                          "clientInfo": {"name": "mcp_smoke", "version": "1"}})
        mcp.version = init.get("protocolVersion")
        check("initialize answers 2025-06-18 with the tools capability",
              init.get("protocolVersion") == PROTOCOL and "tools" in init.get("capabilities", {})
              and init.get("serverInfo", {}).get("name") == "kidney-health", json.dumps(init)[:300])
        r = mcp.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        check("notifications/initialized: 202 without a body", r.status_code == 202 and not r.content)

        tools = mcp.request("tools/list")["tools"]
        check("tools/list has the four read-only tools", {t["name"] for t in tools} == TOOLS
              and all(t["annotations"]["readOnlyHint"] for t in tools), str([t["name"] for t in tools]))

        today = mcp.call("get_today")
        check("get_today answers today's numbers", today.get("is_today") is True and "potassium_mg" in today["nutrients"]
              and today.get("source") == "kidney-health" and today["entries"] == {"eaten": 0, "planned": 0},
              json.dumps(today)[:300])

        meal = mcp.call("check_meal", items=[{"food": "banana"}, {"food": "white rice 1 cup"}], meal="lunch")
        names = [i["matched"]["name"] for i in meal["items"]]
        check("check_meal finds banana and white rice in the built-in list",
              len(names) == 2 and names[0].startswith("Banana") and "white" in names[1].lower() and not meal["unresolved"],
              json.dumps(meal.get("unresolved"))[:300])
        rice = meal["items"][1] if len(meal["items"]) == 2 else {}
        check("1 cup of rice is one serving of its own 1 cup measure",
              rice.get("amount", {}).get("servings") == 1.0 and rice.get("serving", {}).get("description", "").startswith("1 cup"),
              json.dumps(rice.get("amount")))
        potassium = meal["totals"]["potassium_mg"]
        expected = sum(i["nutrients"]["potassium_mg"] for i in meal["items"])
        check("check_meal totals the items and saves nothing",
              potassium == {"value": expected, "not_listed_by": 0} and meal["saved"] is False
              and mcp.call("get_today")["entries"] == {"eaten": 0, "planned": 0}, json.dumps(potassium))
        check("check_meal projects the day", meal["day_with_these_items"]["potassium_mg"]["total"]["value"] == expected)

        safety = mcp.call("safety_check", message="I feel shaky and low")
        card = (safety.get("cards") or [{}])[0]
        check("safety_check: a low comes first, with the Treating a low card",
              safety.get("action") == "treat_low_first" and card.get("title") == "Treating a low"
              and "15 g of fast carbs" in " ".join(card.get("lines", [])), json.dumps(safety)[:300])
        neutral = mcp.call("safety_check", message="What could I have for lunch?")
        check("safety_check: an ordinary question is none", neutral.get("action") == "none")
    finally:
        mcp.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=PORT, help=f"uvicorn port (default {PORT})")
    ap.add_argument("--out", type=Path, default=OUT, help=f"work directory: data, server log, report (default {OUT})")
    ap.add_argument("--server-python", default=sys.executable, help="interpreter that runs the server (default: this one)")
    args = ap.parse_args(argv)
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    server = Server(args.port, out / "data", log_path=out / "server.log", python=args.server_python)
    try:
        server.start()
        run(server)
    except Exception as exc:  # report and stop
        check("finished", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        server.stop()
    leaked = [line for line in server.log().splitlines() if "kha_" in line and "kha_[REDACTED]" not in line]
    check("the server log never shows a token", not leaked, leaked[0][:200] if leaked else "")
    failed = [r for r in RESULTS if not r["ok"]]
    (out / "report.json").write_text(json.dumps({"failed": len(failed), "results": RESULTS}, indent=2), encoding="utf-8")
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
