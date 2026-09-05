"""A mock MCP server that sits behind the gateway.

It speaks just enough of the protocol for the gateway to be exercised end to end with no
external process: ``tools/list`` and ``tools/call``. Every request it receives is recorded
on ``app.state.received`` so a test can prove the gateway did not forward a denied call.
"""

from __future__ import annotations

import json
from typing import Any, Final

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from task2_mcp_gateway import jsonrpc

TOOLS: Final[list[dict[str, Any]]] = [
    {"name": "get_customer_record", "description": "Read one customer record."},
    {"name": "search_orders", "description": "Search orders for a customer."},
    {"name": "admin_reset_key", "description": "Rotate a tenant API key. Admin only."},
    {"name": "admin_delete_tenant", "description": "Delete a tenant. Admin only."},
]

TOOL_NAMES: Final[frozenset[str]] = frozenset(tool["name"] for tool in TOOLS)


async def _handle(request: Request) -> Response:
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse(jsonrpc.error(None, jsonrpc.PARSE_ERROR, "Invalid JSON"), status_code=400)

    request.app.state.received.append(payload)

    try:
        request_id, method, params = jsonrpc.parse_request(payload)
    except jsonrpc.InvalidEnvelope as exc:
        return JSONResponse(jsonrpc.error(None, exc.code, exc.message), status_code=400)

    if method == "tools/list":
        return JSONResponse(jsonrpc.result(request_id, {"tools": TOOLS}))

    if method == "tools/call":
        name = params.get("name")
        if name not in TOOL_NAMES:
            return JSONResponse(jsonrpc.error(request_id, jsonrpc.INVALID_PARAMS, f"Unknown tool: {name}"))
        role = request.headers.get("x-gateway-role", "unknown")
        text = f"{name} executed downstream for role {role}"
        return JSONResponse(jsonrpc.result(request_id, {"content": [{"type": "text", "text": text}], "isError": False}))

    return JSONResponse(jsonrpc.error(request_id, jsonrpc.METHOD_NOT_FOUND, f"Method not found: {method}"))


def create_downstream_app() -> Starlette:
    """Build the mock downstream MCP server."""
    app = Starlette(routes=[Route("/mcp", _handle, methods=["POST"])])
    app.state.received = []
    return app
