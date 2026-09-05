"""Task 2: role based tool filtering in front of a mock MCP server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette

from task2_mcp_gateway import jsonrpc
from task2_mcp_gateway.downstream import create_downstream_app
from task2_mcp_gateway.gateway import create_gateway_app

ADMIN = "Bearer tok-admin-9f3c2d"
VIEWER = "Bearer tok-viewer-41ab77"

LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


def call(name: str, request_id: int = 2) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": name, "arguments": {}}}


@pytest.fixture
def downstream() -> Starlette:
    return create_downstream_app()


@pytest.fixture
async def client(downstream: Starlette) -> AsyncIterator[httpx.AsyncClient]:
    """A client pointed at the gateway, which is itself pointed at the in-process downstream."""
    downstream_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=downstream), base_url="http://downstream")
    gateway = create_gateway_app(downstream_url="http://downstream/mcp", client=downstream_client)
    async with (
        downstream_client,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://gateway") as gateway_client,
    ):
        yield gateway_client


async def test_tools_list_is_forwarded_for_a_viewer(client: httpx.AsyncClient, downstream: Starlette) -> None:
    response = await client.post("/mcp", json=LIST_TOOLS, headers={"Authorization": VIEWER})
    assert response.status_code == 200
    names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert "admin_reset_key" in names
    assert downstream.state.received == [LIST_TOOLS]


async def test_tools_list_is_forwarded_for_an_admin(client: httpx.AsyncClient, downstream: Starlette) -> None:
    response = await client.post("/mcp", json=LIST_TOOLS, headers={"Authorization": ADMIN})
    assert response.status_code == 200
    assert response.json()["result"]["tools"]
    assert len(downstream.state.received) == 1


async def test_admin_may_call_an_admin_tool(client: httpx.AsyncClient, downstream: Starlette) -> None:
    response = await client.post("/mcp", json=call("admin_reset_key"), headers={"Authorization": ADMIN})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 2
    assert "admin_reset_key executed downstream for role admin" in body["result"]["content"][0]["text"]
    assert len(downstream.state.received) == 1


async def test_viewer_may_call_a_normal_tool(client: httpx.AsyncClient, downstream: Starlette) -> None:
    response = await client.post("/mcp", json=call("get_customer_record"), headers={"Authorization": VIEWER})
    assert response.status_code == 200
    assert "role viewer" in response.json()["result"]["content"][0]["text"]
    assert len(downstream.state.received) == 1


@pytest.mark.parametrize("tool", ["admin_reset_key", "admin_delete_tenant"])
async def test_viewer_is_blocked_from_admin_tools(client: httpx.AsyncClient, downstream: Starlette, tool: str) -> None:
    response = await client.post("/mcp", json=call(tool), headers={"Authorization": VIEWER})
    assert response.status_code == 200
    error = response.json()["error"]
    assert error["code"] == jsonrpc.UNAUTHORIZED_TOOL_CALL == -32001
    assert error["message"] == "Unauthorized Tool Call"
    assert error["data"] == {"tool": tool, "role": "viewer", "required_role": "admin"}
    assert response.json()["id"] == 2


async def test_blocked_call_never_reaches_the_downstream_server(
    client: httpx.AsyncClient, downstream: Starlette
) -> None:
    await client.post("/mcp", json=call("admin_reset_key"), headers={"Authorization": VIEWER})
    assert downstream.state.received == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer tok-not-issued"},
        {"Authorization": "tok-admin-9f3c2d"},
        {"Authorization": "Basic tok-admin-9f3c2d"},
        {"Authorization": "Bearer "},
    ],
    ids=["missing", "unknown-token", "no-scheme", "wrong-scheme", "empty-token"],
)
async def test_unusable_credentials_are_rejected(
    client: httpx.AsyncClient, downstream: Starlette, headers: dict[str, str]
) -> None:
    response = await client.post("/mcp", json=LIST_TOOLS, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == jsonrpc.UNAUTHENTICATED == -32002
    assert downstream.state.received == []


async def test_malformed_json_body(client: httpx.AsyncClient, downstream: Starlette) -> None:
    response = await client.post(
        "/mcp",
        content=b'{"jsonrpc": "2.0", "id": 1,',
        headers={"Authorization": ADMIN, "content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == jsonrpc.PARSE_ERROR
    assert downstream.state.received == []


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"jsonrpc": "1.0", "id": 1, "method": "tools/list"}, jsonrpc.INVALID_REQUEST),
        ({"id": 1, "method": "tools/list"}, jsonrpc.INVALID_REQUEST),
        ({"jsonrpc": "2.0", "id": 1}, jsonrpc.INVALID_REQUEST),
        ({"jsonrpc": "2.0", "id": 1, "method": ""}, jsonrpc.INVALID_REQUEST),
        ([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], jsonrpc.INVALID_REQUEST),
        ("just a string", jsonrpc.INVALID_REQUEST),
        ({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": 7}, jsonrpc.INVALID_PARAMS),
    ],
    ids=["bad-version", "no-version", "no-method", "empty-method", "batch", "not-an-object", "params-not-object"],
)
async def test_malformed_envelopes_are_rejected(
    client: httpx.AsyncClient, downstream: Starlette, payload: Any, code: int
) -> None:
    response = await client.post("/mcp", json=payload, headers={"Authorization": ADMIN})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    assert downstream.state.received == []


async def test_tools_call_without_a_name(client: httpx.AsyncClient, downstream: Starlette) -> None:
    payload = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"arguments": {}}}
    response = await client.post("/mcp", json=payload, headers={"Authorization": ADMIN})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == jsonrpc.INVALID_PARAMS
    assert downstream.state.received == []


async def test_client_bearer_token_is_not_forwarded(client: httpx.AsyncClient, downstream: Starlette) -> None:
    """The gateway terminates client auth. The downstream sees the decided role instead."""
    response = await client.post("/mcp", json=call("get_customer_record"), headers={"Authorization": ADMIN})
    assert "role admin" in response.json()["result"]["content"][0]["text"]


async def test_unknown_method_is_forwarded_and_downstream_decides(
    client: httpx.AsyncClient, downstream: Starlette
) -> None:
    payload = {"jsonrpc": "2.0", "id": 4, "method": "resources/list", "params": {}}
    response = await client.post("/mcp", json=payload, headers={"Authorization": VIEWER})
    assert response.json()["error"]["code"] == jsonrpc.METHOD_NOT_FOUND
    assert len(downstream.state.received) == 1


async def test_a_downstream_outage_keeps_the_request_id_and_says_what_happened() -> None:
    """A dependency failure is not the caller's bad request, and the caller's id survives it."""

    def refuse(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    outage_client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    gateway = create_gateway_app(downstream_url="http://downstream/mcp", client=outage_client)
    async with (
        outage_client,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://gateway") as client,
    ):
        response = await client.post("/mcp", json=LIST_TOOLS, headers={"Authorization": ADMIN})

    assert response.status_code == 502
    body = response.json()
    assert body["id"] == 1
    assert body["error"]["code"] == jsonrpc.DOWNSTREAM_UNAVAILABLE == -32003
