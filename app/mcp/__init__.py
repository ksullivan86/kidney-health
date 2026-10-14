"""The assistant's MCP server (assistant step 1, part B): ``POST /mcp``, read-only tools for a chat assistant.

* :mod:`app.mcp.server`: the Streamable HTTP endpoint and the JSON-RPC 2.0 methods (``initialize``, ``ping``,
  ``tools/list``, ``tools/call``, notifications), the switch, the bearer token and the per-token limit.
* :mod:`app.mcp.tools`: ``get_today``, ``search_foods``, ``check_meal`` and ``safety_check``; every number comes
  from the app's own functions (``app.log``, ``app.foods``, ``app.nutrients``, ``app.guidance.hypo``).
* :mod:`app.mcp.measures`: servings, grams and the household measures a food lists.

Spec: ``docs/dev/plans/assistant-step1.md`` part B; contract: ARCHITECTURE.md "Assistant MCP server"; guide:
``docs/assistant.md``.
"""
from .server import router

__all__ = ["router"]
