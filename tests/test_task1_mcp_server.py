"""Task 1: strict validation, JSON-RPC error mapping, and stdout purity."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from mcp.types import INVALID_PARAMS, LATEST_PROTOCOL_VERSION
from pydantic import ValidationError

from task1_mcp_server.models import GetCustomerRecordInput, TriggerRefundInput
from task1_mcp_server.store import RefundRejection, apply_refund, find_customer, reset_store, to_cents
from tests.stdio_client import StdioServerProcess

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": LATEST_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "assessment-test-client", "version": "0.1.0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def call(tool: str, arguments: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


@pytest.fixture(scope="module")
def session() -> Any:
    """One server subprocess driven through a full protocol exchange.

    Everything the server wrote is captured, so the assertions below can look at the raw
    stdout lines rather than at parsed SDK objects.
    """
    with StdioServerProcess(env_overrides={"MCP_SERVER_EMIT_STRAY_PRINT": "1"}) as proc:
        responses: dict[str, dict[str, Any]] = {}
        responses["initialize"] = proc.request(INITIALIZE)
        proc.send(INITIALIZED)
        responses["tools_list"] = proc.request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        responses["record_ok"] = proc.request(call("get_customer_record", {"customer_id": "CUST-10042"}, 3))
        responses["record_bad_id"] = proc.request(call("get_customer_record", {"customer_id": "CUST-1"}, 4))
        responses["record_missing"] = proc.request(call("get_customer_record", {"customer_id": "CUST-ZZZZZ"}, 5))
        responses["refund_ok"] = proc.request(
            call("trigger_refund", {"customer_id": "CUST-10042", "amount": 25.5, "reason": "duplicate charge"}, 6)
        )
        responses["refund_bad"] = proc.request(
            call("trigger_refund", {"customer_id": "cust-10042", "amount": -1, "reason": "oops"}, 7)
        )
        responses["refund_extra_field"] = proc.request(
            call(
                "trigger_refund",
                {"customer_id": "CUST-10042", "amount": 1.0, "reason": "duplicate charge", "approver": "root"},
                8,
            )
        )
        responses["unknown_tool"] = proc.request(call("admin_reset_key", {}, 9))
        # CUST-2A9F1 has a refundable balance of 250, so the second of these must be refused.
        responses["refund_drain_1"] = proc.request(
            call("trigger_refund", {"customer_id": "CUST-2A9F1", "amount": 200.0, "reason": "billing error"}, 10)
        )
        responses["refund_drain_2"] = proc.request(
            call("trigger_refund", {"customer_id": "CUST-2A9F1", "amount": 200.0, "reason": "billing error"}, 11)
        )
        responses["refund_sub_cent"] = proc.request(
            call("trigger_refund", {"customer_id": "CUST-10042", "amount": 0.001, "reason": "billing error"}, 12)
        )
        exit_code = proc.close()
        yield {
            "responses": responses,
            "stdout_lines": list(proc.stdout_lines),
            "stderr": proc.stderr,
            "exit_code": exit_code,
        }


def test_server_exits_cleanly_when_the_client_closes_stdin(session: dict[str, Any]) -> None:
    assert session["exit_code"] == 0


def test_every_stdout_line_is_a_json_rpc_message(session: dict[str, Any]) -> None:
    """The scored property: stdout carries JSON-RPC and nothing else."""
    assert session["stdout_lines"], "server wrote nothing to stdout"
    for line in session["stdout_lines"]:
        message = json.loads(line)  # raises if anything non-JSON leaked onto the wire
        assert message["jsonrpc"] == "2.0"
        assert "id" in message
        assert ("result" in message) ^ ("error" in message)


def test_logs_and_stray_prints_go_to_stderr(session: dict[str, Any]) -> None:
    """A print() inside the server process must not reach the protocol stream."""
    stderr = session["stderr"]
    assert "stray print that would corrupt the JSON-RPC stream" in stderr
    assert "starting on stdio" in stderr
    for line in session["stdout_lines"]:
        assert "stray print" not in line


def test_initialize_and_tools_list(session: dict[str, Any]) -> None:
    init = session["responses"]["initialize"]["result"]
    assert init["serverInfo"]["name"] == "quilr-customer-ops"
    assert "tools" in init["capabilities"]

    tools = session["responses"]["tools_list"]["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["get_customer_record", "trigger_refund"]
    refund_schema = tools[1]["inputSchema"]
    assert refund_schema["properties"]["amount"]["minimum"] == 0.01
    assert refund_schema["properties"]["amount"]["maximum"] == 1_000_000.0
    assert refund_schema["properties"]["amount"]["multipleOf"] == 0.01
    assert refund_schema["properties"]["reason"]["minLength"] == 10
    assert refund_schema["properties"]["customer_id"]["pattern"] == r"^CUST-[A-Z0-9]{5}$"
    assert refund_schema["additionalProperties"] is False


def test_the_advertised_schema_matches_what_the_runtime_enforces(session: dict[str, Any]) -> None:
    """A client generating calls from the schema must not be able to build one that fails.

    Every value the published constraints accept is checked against the model, and every
    value they reject is checked too, so the two cannot drift apart.
    """
    schema = session["responses"]["tools_list"]["result"]["tools"][1]["inputSchema"]
    amount = schema["properties"]["amount"]
    reason = schema["properties"]["reason"]

    def schema_accepts(value: float, text: str) -> bool:
        cents = round(value / amount["multipleOf"])
        return (
            amount["minimum"] <= value <= amount["maximum"]
            and abs(cents * amount["multipleOf"] - value) < 1e-9
            and len(text) >= reason["minLength"]
            and re.search(reason["pattern"], text) is not None
        )

    cases = [
        (0.001, "duplicate charge"),
        (1.005, "duplicate charge"),
        (0.01, "duplicate charge"),
        (25.5, "duplicate charge"),
        (25.5, "short"),
        (25.5, "            "),
        (12.34, "0123456789"),
    ]
    for value, text in cases:
        runtime_ok = True
        try:
            TriggerRefundInput.model_validate({"customer_id": "CUST-10042", "amount": value, "reason": text})
        except ValidationError:
            runtime_ok = False
        assert schema_accepts(value, text) is runtime_ok, f"schema and runtime disagree on {value!r} {text!r}"


def test_valid_calls_return_results(session: dict[str, Any]) -> None:
    record = session["responses"]["record_ok"]["result"]
    assert record["isError"] is False
    assert record["structuredContent"]["customer_id"] == "CUST-10042"

    refund = session["responses"]["refund_ok"]["result"]
    assert refund["isError"] is False
    assert refund["structuredContent"]["refund_id"].startswith("RFND-")
    assert refund["structuredContent"]["status"] == "accepted"


@pytest.mark.parametrize(
    ("key", "expected_fragment"),
    [
        ("record_bad_id", "customer_id"),
        ("refund_bad", "amount"),
        ("refund_extra_field", "approver"),
    ],
)
def test_validation_failures_map_to_invalid_params(session: dict[str, Any], key: str, expected_fragment: str) -> None:
    error = session["responses"][key]["error"]
    assert error["code"] == INVALID_PARAMS == -32602
    assert expected_fragment in error["message"]
    assert error["data"]["errors"]


def test_invalid_refund_reports_every_bad_field_at_once(session: dict[str, Any]) -> None:
    fields = {item["field"] for item in session["responses"]["refund_bad"]["error"]["data"]["errors"]}
    assert fields == {"customer_id", "amount", "reason"}


def test_unknown_tool_is_a_protocol_error(session: dict[str, Any]) -> None:
    error = session["responses"]["unknown_tool"]["error"]
    assert error["code"] == INVALID_PARAMS
    assert "Unknown tool: admin_reset_key" in error["message"]


def test_domain_failure_is_a_result_not_a_protocol_error(session: dict[str, Any]) -> None:
    """An unknown customer is a business outcome, so it is isError, not -32602."""
    response = session["responses"]["record_missing"]
    assert "error" not in response
    assert response["result"]["isError"] is True
    assert "No customer found" in response["result"]["content"][0]["text"]


@pytest.mark.parametrize(
    "customer_id",
    ["CUST-1004", "CUST-100422", "cust-10042", "CUST_10042", "10042", "", "CUST-1004!"],
)
def test_customer_id_pattern_rejects_malformed_ids(customer_id: str) -> None:
    with pytest.raises(ValidationError):
        GetCustomerRecordInput(customer_id=customer_id)


@pytest.mark.parametrize(
    "arguments",
    [
        {"customer_id": "CUST-10042", "amount": 0, "reason": "duplicate charge"},
        {"customer_id": "CUST-10042", "amount": -0.01, "reason": "duplicate charge"},
        {"customer_id": "CUST-10042", "amount": float("nan"), "reason": "duplicate charge"},
        {"customer_id": "CUST-10042", "amount": float("inf"), "reason": "duplicate charge"},
        {"customer_id": "CUST-10042", "amount": "25.50", "reason": "duplicate charge"},
        {"customer_id": "CUST-10042", "amount": 25.5, "reason": "too short"},
        {"customer_id": "CUST-10042", "amount": 25.5, "reason": "            "},
        {"customer_id": "CUST-10042", "amount": 0.001, "reason": "duplicate charge"},
        {"customer_id": "CUST-10042", "amount": 0.009, "reason": "duplicate charge"},
        {"customer_id": "CUST-10042", "amount": 1.005, "reason": "duplicate charge"},
        {"customer_id": "CUST-10042", "amount": 1e308, "reason": "duplicate charge"},
        {"customer_id": "CUST-10042", "amount": 1_000_000.01, "reason": "duplicate charge"},
        {"customer_id": "CUST-10042", "reason": "duplicate charge"},
    ],
)
def test_refund_rejects_malformed_arguments(arguments: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TriggerRefundInput.model_validate(arguments)


def test_refund_accepts_an_integer_amount() -> None:
    """JSON has no float type, so an integer literal must still be accepted."""
    assert (
        TriggerRefundInput.model_validate(
            {"customer_id": "CUST-10042", "amount": 25, "reason": "duplicate charge"}
        ).amount
        == 25.0
    )


def test_a_repeated_refund_cannot_spend_the_same_balance_twice(session: dict[str, Any]) -> None:
    """The balance is debited when the refund is approved, so a replay hits the new balance."""
    first = session["responses"]["refund_drain_1"]["result"]
    second = session["responses"]["refund_drain_2"]["result"]
    assert first["isError"] is False
    assert first["structuredContent"]["remaining_refundable_usd"] == 50.0
    assert second["isError"] is True
    assert "exceeds the refundable balance of 50.00" in second["content"][0]["text"]


def test_apply_refund_debits_the_balance() -> None:
    reset_store()
    try:
        outcome = apply_refund("CUST-2A9F1", 250.0)
        assert outcome.rejection is None
        assert outcome.record is not None
        assert outcome.record.refundable_balance_usd == 0.0
        assert apply_refund("CUST-2A9F1", 0.01).rejection is RefundRejection.INSUFFICIENT_BALANCE
        assert apply_refund("CUST-ZZZZZ", 1.0).rejection is RefundRejection.UNKNOWN_CUSTOMER
        record = find_customer("CUST-2A9F1")
        assert record is not None
        assert record.refundable_balance_usd == 0.0
    finally:
        reset_store()


def test_a_sub_cent_refund_is_rejected_at_the_protocol_level(session: dict[str, Any]) -> None:
    """A positive float that rounds away to nothing would otherwise be a free refund."""
    error = session["responses"]["refund_sub_cent"]["error"]
    assert error["code"] == INVALID_PARAMS
    assert "amount" in error["message"]


@pytest.mark.parametrize(
    ("amount", "expected_cents"), [(0.01, 1), (0.07, 7), (25.5, 2550), (1200.0, 120_000), (12345678.91, 1234567891)]
)
def test_dollar_amounts_convert_to_exact_cents(amount: float, expected_cents: int) -> None:
    assert to_cents(amount) == expected_cents


def test_a_sub_cent_refund_never_reaches_the_balance() -> None:
    """apply_refund is public, so it guards the floor itself rather than trusting its caller."""
    reset_store()
    try:
        before = find_customer("CUST-10042")
        assert before is not None
        for _ in range(1000):
            assert apply_refund("CUST-10042", 0.001).rejection is RefundRejection.BELOW_MINIMUM
        after = find_customer("CUST-10042")
        assert after is not None
        assert after.refundable_balance_cents == before.refundable_balance_cents
    finally:
        reset_store()
