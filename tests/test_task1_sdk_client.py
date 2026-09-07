"""Task 1 through the official SDK client, so the server has met a client it did not write.

``tests/test_task1_mcp_server.py`` drives the server with this repo's own raw stdio client and
reads the bytes off stdout. These tests use ``mcp.client.stdio`` and ``ClientSession`` from the
same SDK the server is built on, which parses those bytes the way a real host would, so a framing
or schema mistake the raw client tolerates would fail here.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Final

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_PARAMS

from task1_mcp_server.models import GetCustomerRecordInput, TriggerRefundInput

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "task1_mcp_server"], env=dict(os.environ))

#: The SDK's own default is an unbounded wait, so a server that starts but never answers would
#: hang this test rather than fail it. Bounded at the same ceiling tests/stdio_client.py reads at.
READ_TIMEOUT_SECONDS: Final = 20.0


@asynccontextmanager
async def sdk_session() -> AsyncIterator[ClientSession]:
    """A fresh server subprocess behind an initialised SDK session, bounded against a hang."""
    timeout = timedelta(seconds=READ_TIMEOUT_SECONDS)
    async with (
        stdio_client(SERVER) as (read, write),
        ClientSession(read, write, read_timeout_seconds=timeout) as session,
    ):
        await session.initialize()
        yield session


def first_text(result: Any) -> dict[str, Any]:
    """The JSON body of a tool result's first text block."""
    block = result.content[0]
    assert block.type == "text"
    parsed: dict[str, Any] = json.loads(block.text)
    return parsed


async def test_the_sdk_client_completes_the_handshake_and_lists_both_tools() -> None:
    async with sdk_session() as session:
        listed = await session.list_tools()
    by_name = {tool.name: tool for tool in listed.tools}
    assert set(by_name) == {"get_customer_record", "trigger_refund"}
    assert by_name["get_customer_record"].inputSchema == GetCustomerRecordInput.model_json_schema()
    assert by_name["trigger_refund"].inputSchema == TriggerRefundInput.model_json_schema()


async def test_the_sdk_client_gets_a_record_and_a_refund_back() -> None:
    async with sdk_session() as session:
        record = await session.call_tool("get_customer_record", {"customer_id": "CUST-10042"})
        refund = await session.call_tool(
            "trigger_refund", {"customer_id": "CUST-10042", "amount": 25.5, "reason": "duplicate charge"}
        )
    assert record.isError is False
    assert first_text(record)["customer_id"] == "CUST-10042"
    assert refund.isError is False
    assert first_text(refund)["amount"] == 25.5


async def test_bad_arguments_reach_the_sdk_client_as_invalid_params() -> None:
    async with sdk_session() as session:
        with pytest.raises(McpError) as caught:
            await session.call_tool("get_customer_record", {"customer_id": "CUST-1"})
    assert caught.value.error.code == INVALID_PARAMS
    assert "customer_id" in caught.value.error.message


async def test_a_missing_customer_is_a_domain_answer_not_a_protocol_error() -> None:
    async with sdk_session() as session:
        missing = await session.call_tool("get_customer_record", {"customer_id": "CUST-ZZZZZ"})
    assert missing.isError is True
    block = missing.content[0]
    assert block.type == "text"
    assert "CUST-ZZZZZ" in block.text
