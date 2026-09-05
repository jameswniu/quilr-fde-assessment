"""JSON-RPC 2.0 helpers shared by the gateway and the mock downstream server."""

from __future__ import annotations

from typing import Any, Final

JSONRPC_VERSION: Final = "2.0"

# Standard codes from the JSON-RPC 2.0 specification.
PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
METHOD_NOT_FOUND: Final = -32601
INVALID_PARAMS: Final = -32602

# Implementation defined codes, which the specification reserves the -32000 to -32099 block for.
UNAUTHORIZED_TOOL_CALL: Final = -32001
UNAUTHENTICATED: Final = -32002
DOWNSTREAM_UNAVAILABLE: Final = -32003


def error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    """Build a JSON-RPC error response object."""
    payload: dict[str, Any] = {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        payload["error"]["data"] = data
    return payload


def result(request_id: Any, value: Any) -> dict[str, Any]:
    """Build a JSON-RPC success response object."""
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": value}


class InvalidEnvelope(Exception):
    """Raised when a payload is not a well formed JSON-RPC request object."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_request(payload: Any) -> tuple[Any, str, dict[str, Any]]:
    """Validate a decoded payload and return ``(id, method, params)``.

    Raises:
        InvalidEnvelope: when the payload is not a single well formed request object.
    """
    if isinstance(payload, list):
        raise InvalidEnvelope(INVALID_REQUEST, "Batch requests are not supported by this gateway")
    if not isinstance(payload, dict):
        raise InvalidEnvelope(INVALID_REQUEST, "Request must be a JSON object")
    if payload.get("jsonrpc") != JSONRPC_VERSION:
        raise InvalidEnvelope(INVALID_REQUEST, 'Field "jsonrpc" must be exactly "2.0"')
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise InvalidEnvelope(INVALID_REQUEST, 'Field "method" must be a non-empty string')
    params = payload.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise InvalidEnvelope(INVALID_PARAMS, 'Field "params" must be an object')
    return payload.get("id"), method, params
