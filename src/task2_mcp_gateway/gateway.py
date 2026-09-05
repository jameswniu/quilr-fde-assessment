"""An MCP security gateway: a JSON-RPC reverse proxy with method level authorization.

Request handling, in order:

1. Resolve the role from the ``Authorization: Bearer <token>`` header. No usable token
   means HTTP 401 with JSON-RPC error -32002 and no downstream call.
2. Parse the JSON-RPC envelope. A malformed body means HTTP 400 with -32700 or -32600
   and no downstream call.
3. For ``tools/call``, read ``params.name``. A name starting with ``admin_`` requires the
   admin role. A viewer asking for one gets HTTP 200 with JSON-RPC error -32001, again
   with no downstream call. The prefix is the rule the brief specifies. It is a deny list,
   so a downstream that grows a privileged method under some other name would not be
   covered by it, and a gateway that owned a real policy would carry an explicit per method
   allow list instead of inferring privilege from a name.
4. Anything else, including ``tools/list``, is forwarded to the downstream server and the
   downstream status code and body are returned unchanged. A downstream that cannot be
   reached becomes HTTP 502 with JSON-RPC error -32003, carrying the caller's own request
   id so a client can still correlate the failure with what it sent.

The client's bearer token is not forwarded. The gateway terminates client auth and tells
the downstream server the decided role in ``X-Gateway-Role``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final, cast

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from task2_mcp_gateway import jsonrpc
from task2_mcp_gateway.auth import Role, resolve_role, tool_requires_admin

logger = logging.getLogger("task2_mcp_gateway")

DEFAULT_DOWNSTREAM_URL: Final = "http://127.0.0.1:8081/mcp"
DOWNSTREAM_TIMEOUT_SECONDS: Final = 10.0


def _client(app: Starlette) -> httpx.AsyncClient:
    """Return the shared downstream client, creating one if the lifespan did not run."""
    existing = getattr(app.state, "client", None)
    if existing is None:
        existing = httpx.AsyncClient(timeout=DOWNSTREAM_TIMEOUT_SECONDS)
        app.state.client = existing
        app.state.owns_client = True
    return cast(httpx.AsyncClient, existing)


async def _forward(request: Request, role: Role, body: bytes, request_id: Any) -> Response:
    """Send the untouched request body downstream and hand the answer back."""
    app = request.app
    try:
        response = await _client(app).post(
            cast(str, app.state.downstream_url),
            content=body,
            headers={"content-type": "application/json", "x-gateway-role": role.value},
        )
    except httpx.HTTPError:
        logger.exception("downstream call failed")
        return JSONResponse(
            jsonrpc.error(request_id, jsonrpc.DOWNSTREAM_UNAVAILABLE, "Downstream MCP server is unavailable"),
            status_code=502,
        )
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/json"),
    )


async def _handle(request: Request) -> Response:
    role = resolve_role(request.headers.get("authorization"))
    if role is None:
        logger.warning("rejected request with missing or unknown bearer token")
        return JSONResponse(
            jsonrpc.error(None, jsonrpc.UNAUTHENTICATED, "Missing or invalid Authorization bearer token"),
            status_code=401,
        )

    body = await request.body()
    try:
        payload: Any = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse(jsonrpc.error(None, jsonrpc.PARSE_ERROR, "Request body is not valid JSON"), status_code=400)

    try:
        request_id, method, params = jsonrpc.parse_request(payload)
    except jsonrpc.InvalidEnvelope as exc:
        return JSONResponse(jsonrpc.error(None, exc.code, exc.message), status_code=400)

    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return JSONResponse(
                jsonrpc.error(request_id, jsonrpc.INVALID_PARAMS, 'tools/call requires a string "params.name"'),
                status_code=400,
            )
        if tool_requires_admin(name) and role is not Role.ADMIN:
            logger.warning("blocked %s for role %s", name, role.value)
            return JSONResponse(
                jsonrpc.error(
                    request_id,
                    jsonrpc.UNAUTHORIZED_TOOL_CALL,
                    "Unauthorized Tool Call",
                    data={"tool": name, "role": role.value, "required_role": Role.ADMIN.value},
                )
            )

    logger.info("forwarding %s for role %s", method, role.value)
    return await _forward(request, role, body, request_id)


def create_gateway_app(
    *,
    downstream_url: str = DEFAULT_DOWNSTREAM_URL,
    client: httpx.AsyncClient | None = None,
) -> Starlette:
    """Build the gateway.

    Args:
        downstream_url: where ``tools/list`` and permitted ``tools/call`` requests go.
        client: an HTTP client to reuse. Tests pass one wired to the mock downstream app.
            When omitted the gateway owns its own client and closes it on shutdown.
    """

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            owned = getattr(app.state, "client", None) if getattr(app.state, "owns_client", False) else None
            if owned is not None:
                await cast(httpx.AsyncClient, owned).aclose()

    app = Starlette(routes=[Route("/mcp", _handle, methods=["POST"])], lifespan=lifespan)
    app.state.downstream_url = downstream_url
    app.state.client = client
    app.state.owns_client = client is None
    return app
