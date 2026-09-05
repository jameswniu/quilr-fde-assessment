"""An MCP server that exposes two strictly validated tools over stdio.

Two properties matter here and both are deliberate.

Stdout purity. The stdio transport uses stdout as the JSON-RPC wire. This module grabs
the real stdout handle once, hands it to the transport, and then rebinds ``sys.stdout``
to stderr, so an accidental ``print`` anywhere in this process or in a dependency lands
on stderr instead of corrupting the protocol stream. Logging is configured to stderr for
the same reason.

Error mapping. Argument validation failures are protocol errors and come back as
JSON-RPC ``-32602 Invalid params``. To get that, the ``tools/call`` handler is registered
directly on the low level server: the SDK's ``@server.call_tool()`` convenience decorator
catches every exception and converts it into an ``isError`` result, which would hide the
error code. Domain failures such as an unknown customer are not protocol errors, so those
still come back as a normal result with ``isError`` set, which is what the MCP spec asks for.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from io import TextIOWrapper
from typing import Any, Final, TextIO

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from pydantic import BaseModel, ValidationError

from task1_mcp_server.models import (
    GetCustomerRecordInput,
    TriggerRefundInput,
    format_validation_error,
    validation_error_data,
)
from task1_mcp_server.store import RefundRejection, apply_refund, find_customer

SERVER_NAME: Final = "quilr-customer-ops"
SERVER_VERSION: Final = "0.1.0"

logger = logging.getLogger(SERVER_NAME)

TOOLS: Final[list[types.Tool]] = [
    types.Tool(
        name="get_customer_record",
        description="Look up a single customer record by customer id.",
        inputSchema=GetCustomerRecordInput.model_json_schema(),
    ),
    types.Tool(
        name="trigger_refund",
        description="Issue a refund against a customer's refundable balance.",
        inputSchema=TriggerRefundInput.model_json_schema(),
    ),
]

TOOL_MODELS: Final[dict[str, type[BaseModel]]] = {
    "get_customer_record": GetCustomerRecordInput,
    "trigger_refund": TriggerRefundInput,
}


def _ok(payload: dict[str, Any]) -> types.CallToolResult:
    """A successful tool result carrying both text and structured content."""
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, indent=2))],
        structuredContent=payload,
        isError=False,
    )


def _domain_error(message: str) -> types.CallToolResult:
    """A business failure. Not a protocol error, so it is a result with isError set."""
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], isError=True)


def _get_customer_record(args: GetCustomerRecordInput) -> types.CallToolResult:
    record = find_customer(args.customer_id)
    if record is None:
        return _domain_error(f"No customer found with id {args.customer_id}")
    logger.info("served customer record %s", args.customer_id)
    return _ok(dict(record.as_dict()))


def _trigger_refund(args: TriggerRefundInput) -> types.CallToolResult:
    outcome = apply_refund(args.customer_id, args.amount)
    if outcome.rejection is RefundRejection.UNKNOWN_CUSTOMER:
        return _domain_error(f"No customer found with id {args.customer_id}")
    if outcome.rejection is RefundRejection.BELOW_MINIMUM:
        return _domain_error(f"Refund of {args.amount} is below the smallest refundable amount")
    if outcome.rejection is RefundRejection.INSUFFICIENT_BALANCE:
        assert outcome.record is not None
        return _domain_error(
            f"Refund of {args.amount:.2f} exceeds the refundable balance of "
            f"{outcome.record.refundable_balance_usd:.2f} for {args.customer_id}"
        )
    assert outcome.record is not None
    refund_id = f"RFND-{uuid.uuid4().hex[:10].upper()}"
    logger.info("issued refund %s for %s", refund_id, args.customer_id)
    return _ok(
        {
            "refund_id": refund_id,
            "customer_id": args.customer_id,
            "amount": args.amount,
            "reason": args.reason,
            "status": "accepted",
            "remaining_refundable_usd": outcome.record.refundable_balance_usd,
        }
    )


async def _handle_list_tools(_request: types.ListToolsRequest) -> types.ServerResult:
    return types.ServerResult(types.ListToolsResult(tools=TOOLS))


async def _handle_call_tool(request: types.CallToolRequest) -> types.ServerResult:
    """Validate arguments, then run the named tool.

    Raises:
        McpError: with code -32602 when the tool name or the arguments are invalid.
    """
    name = request.params.name
    arguments = request.params.arguments or {}

    model = TOOL_MODELS.get(name)
    if model is None:
        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message=f"Unknown tool: {name}",
                data={"known_tools": sorted(TOOL_MODELS)},
            )
        )

    try:
        parsed = model.model_validate(arguments)
    except ValidationError as exc:
        logger.warning("rejected %s: %s", name, exc.error_count())
        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message=format_validation_error(name, exc),
                data={"errors": validation_error_data(exc)},
            )
        ) from exc

    if isinstance(parsed, GetCustomerRecordInput):
        return types.ServerResult(_get_customer_record(parsed))
    if isinstance(parsed, TriggerRefundInput):
        return types.ServerResult(_trigger_refund(parsed))
    raise McpError(  # pragma: no cover - unreachable while TOOL_MODELS and the branches agree
        types.ErrorData(code=types.INTERNAL_ERROR, message="Tool is registered but has no implementation")
    )


def build_server() -> Server[object, object]:
    """Build the server with both request handlers registered."""
    server: Server[object, object] = Server(SERVER_NAME, version=SERVER_VERSION)
    # Both handlers are registered directly rather than through the @server.list_tools()
    # and @server.call_tool() decorators. The call_tool decorator catches every exception
    # and turns it into an isError result, which would swallow the -32602 code this server
    # is meant to return. Registering the pair the same way keeps them symmetrical, and
    # the server still advertises the tools capability because the handler is present.
    server.request_handlers[types.ListToolsRequest] = _handle_list_tools
    server.request_handlers[types.CallToolRequest] = _handle_call_tool
    return server


def configure_logging() -> None:
    """Send every log record to stderr. Stdout belongs to the protocol."""
    level = os.environ.get("MCP_SERVER_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def isolate_stdout() -> TextIO | None:
    """Take the real stdout for the protocol and point ``sys.stdout`` at stderr.

    Returns the captured stdout handle, or ``None`` when stdout has no binary buffer
    (as under a test harness that replaces it), in which case nothing is rebound.
    """
    real = sys.stdout
    if getattr(real, "buffer", None) is None:
        return None
    sys.stdout = sys.stderr
    return real


async def serve() -> None:
    """Run the server over stdio until the client closes the connection."""
    protocol_stdout = isolate_stdout()
    configure_logging()

    if os.environ.get("MCP_SERVER_EMIT_STRAY_PRINT") == "1":
        # Test hook. Proves the stdout guard: this print must not reach the wire.
        print("stray print that would corrupt the JSON-RPC stream")

    stdout_stream = None
    if protocol_stdout is not None:
        stdout_stream = anyio.wrap_file(TextIOWrapper(protocol_stdout.buffer, encoding="utf-8"))

    logger.info("%s %s starting on stdio", SERVER_NAME, SERVER_VERSION)
    server = build_server()
    async with stdio_server(stdout=stdout_stream) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
    logger.info("%s stopped", SERVER_NAME)


def main() -> None:
    """Console entry point."""
    anyio.run(serve)
