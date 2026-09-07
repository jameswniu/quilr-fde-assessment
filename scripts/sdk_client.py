"""Drive Task 1 with the official SDK client, not this repo's own raw stdio client.

    uv run python scripts/sdk_client.py

``tests/test_task1_sdk_client.py`` is this same walk under pytest: ``StdioServerParameters``,
``stdio_client``, ``ClientSession``, ``initialize``, then a call that succeeds, one that fails
validation, and one that moves money. This script exists so a reviewer can watch that walk happen
and read the exchange, one JSON line per step, rather than take the test's word for it.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta
from typing import Any, Final

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, TextContent

SERVER: Final = StdioServerParameters(command=sys.executable, args=["-m", "task1_mcp_server"], env=dict(os.environ))

KNOWN_CUSTOMER_ID: Final = "CUST-10042"
MALFORMED_CUSTOMER_ID: Final = "CUST-1"
REFUND_AMOUNT_USD: Final = 25.5
REFUND_REASON: Final = "duplicate charge"

#: The SDK's own default is an unbounded wait, so a server that starts but never answers would
#: hang this script rather than fail it. Bounded at the same ceiling tests/stdio_client.py reads at.
READ_TIMEOUT_SECONDS: Final = 20.0


def _emit(step: str, payload: dict[str, Any]) -> None:
    """Print one JSON line for a step, the step name first so the output can be grepped."""
    print(json.dumps({"step": step, **payload}))


def _tool_result_json(result: CallToolResult) -> dict[str, Any]:
    """The JSON body of a tool result's first text block, the same shape the SDK test reads."""
    block = result.content[0]
    if not isinstance(block, TextContent):
        raise TypeError(f"expected a text content block, got {block.type}")
    parsed: dict[str, Any] = json.loads(block.text)
    return parsed


async def run() -> None:
    """Complete the handshake, then run the three calls the brief asks this script to show."""
    timeout = timedelta(seconds=READ_TIMEOUT_SECONDS)
    async with (
        stdio_client(SERVER) as (read, write),
        ClientSession(read, write, read_timeout_seconds=timeout) as session,
    ):
        initialized = await session.initialize()
        server_info = initialized.serverInfo
        _emit("initialize", {"server_name": server_info.name, "server_version": server_info.version})

        listed = await session.list_tools()
        _emit("list_tools", {"tools": [tool.name for tool in listed.tools]})

        record = await session.call_tool("get_customer_record", {"customer_id": KNOWN_CUSTOMER_ID})
        _emit("get_customer_record", _tool_result_json(record))

        try:
            await session.call_tool("get_customer_record", {"customer_id": MALFORMED_CUSTOMER_ID})
        except McpError as error:
            _emit(
                "get_customer_record_invalid_params",
                {"customer_id": MALFORMED_CUSTOMER_ID, "code": error.error.code, "message": error.error.message},
            )

        refund = await session.call_tool(
            "trigger_refund",
            {"customer_id": KNOWN_CUSTOMER_ID, "amount": REFUND_AMOUNT_USD, "reason": REFUND_REASON},
        )
        _emit("trigger_refund", _tool_result_json(refund))


def main() -> None:
    """Console entry point: ``uv run python scripts/sdk_client.py``."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
