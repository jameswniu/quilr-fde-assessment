"""The one error shape this gateway ever returns to a caller.

Upstream providers fail in their own vocabulary: HTTP bodies, vendor error codes, socket
errors, tracebacks. None of that crosses the boundary. Every failure is mapped onto a
fixed set of codes with messages written here, and the detail is logged locally against a
request id the caller can quote.
"""

from __future__ import annotations

import logging
import uuid
from enum import StrEnum
from typing import Any, Final

logger = logging.getLogger("task4_model_router")


class GatewayErrorCode(StrEnum):
    """The complete set of codes a caller can see."""

    INVALID_REQUEST = "invalid_request"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    INTERNAL_ERROR = "internal_error"


#: Caller facing text. Fixed strings, so nothing from an upstream can reach a client.
MESSAGES: Final[dict[GatewayErrorCode, str]] = {
    GatewayErrorCode.INVALID_REQUEST: "The request was not valid.",
    GatewayErrorCode.RATE_LIMITED: "Token rate limit exceeded for this API key.",
    GatewayErrorCode.UPSTREAM_UNAVAILABLE: "No model provider was able to serve this request.",
    GatewayErrorCode.INTERNAL_ERROR: "The gateway could not complete this request.",
}

STATUS_CODES: Final[dict[GatewayErrorCode, int]] = {
    GatewayErrorCode.INVALID_REQUEST: 400,
    GatewayErrorCode.RATE_LIMITED: 429,
    GatewayErrorCode.UPSTREAM_UNAVAILABLE: 502,
    GatewayErrorCode.INTERNAL_ERROR: 500,
}


def new_request_id() -> str:
    """A short id that ties a caller facing error to the local log line about it."""
    return f"req_{uuid.uuid4().hex[:16]}"


class GatewayError(Exception):
    """A failure that is safe to serialise and hand back to a caller."""

    def __init__(
        self,
        code: GatewayErrorCode,
        *,
        request_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.code = code
        self.request_id = request_id or new_request_id()
        self.retry_after_seconds = retry_after_seconds
        super().__init__(MESSAGES[code])

    @property
    def status_code(self) -> int:
        return STATUS_CODES[self.code]

    @property
    def message(self) -> str:
        return MESSAGES[self.code]

    def to_payload(self) -> dict[str, Any]:
        """The standardised body. Nothing here is derived from an upstream response."""
        error: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
            "request_id": self.request_id,
        }
        if self.retry_after_seconds is not None:
            error["retry_after_seconds"] = round(self.retry_after_seconds, 3)
        return {"error": error}


def sanitize(exc: BaseException, code: GatewayErrorCode = GatewayErrorCode.UPSTREAM_UNAVAILABLE) -> GatewayError:
    """Turn any exception into a gateway error, keeping the detail in the local log only."""
    error = GatewayError(code)
    logger.error(
        "request %s failed: %s: %s",
        error.request_id,
        type(exc).__name__,
        exc,
        exc_info=exc,
    )
    return error
