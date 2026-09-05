"""Pydantic schemas for the two tools this server exposes.

The models are the single source of truth: the same class produces the JSON Schema
advertised in ``tools/list`` and performs the validation done in ``tools/call``.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

#: The brief writes the customer id as ``CUST-XXXXX``. It is read here as the literal
#: prefix ``CUST-`` followed by exactly five uppercase alphanumeric characters.
CUSTOMER_ID_PATTERN: Final = r"^CUST-[A-Z0-9]{5}$"

REASON_MIN_LENGTH: Final = 10

#: Money is counted in whole cents, so this is both the smallest refund and the required
#: precision. Without it, an amount such as 0.001 is a positive float that rounds away to
#: nothing when it is debited, which would let a caller take an unlimited number of
#: accepted refunds that never touch the balance.
MIN_REFUND_USD: Final = 0.01
#: An upper bound keeps a refund sane and keeps the cents arithmetic away from the point
#: where a float times 100 becomes infinity, which is an internal error rather than a -32602.
MAX_REFUND_USD: Final = 1_000_000.0
CENTS_PER_USD: Final = 100

#: "At least ten non-whitespace characters", in a form both Python and JSON Schema read the
#: same way, so a client generating calls from the advertised schema cannot build one that
#: passes the schema and then fails validation.
REASON_PATTERN: Final = rf"^(?=(?:\s*\S){{{REASON_MIN_LENGTH}}})"

_STRICT: Final = ConfigDict(
    strict=True,  # no silent coercion, so "12.5" is not accepted for a float field
    extra="forbid",  # unknown argument names are a validation failure, not ignored
    allow_inf_nan=False,  # NaN and Infinity are not valid refund amounts
    # Pydantic's default Rust regex engine has no lookaround, and the reason rule needs one
    # to say "ten non-whitespace characters" in a form JSON Schema also understands.
    regex_engine="python-re",
)


class GetCustomerRecordInput(BaseModel):
    """Arguments for ``get_customer_record``."""

    model_config = _STRICT

    customer_id: str = Field(
        pattern=CUSTOMER_ID_PATTERN,
        description="Customer identifier formatted as CUST-XXXXX, for example CUST-10042.",
    )


class TriggerRefundInput(BaseModel):
    """Arguments for ``trigger_refund``."""

    model_config = _STRICT

    customer_id: str = Field(
        pattern=CUSTOMER_ID_PATTERN,
        description="Customer identifier formatted as CUST-XXXXX, for example CUST-10042.",
    )
    amount: float = Field(
        ge=MIN_REFUND_USD,
        le=MAX_REFUND_USD,
        json_schema_extra={"multipleOf": MIN_REFUND_USD},
        description=(
            f"Refund amount in USD, from {MIN_REFUND_USD} to {MAX_REFUND_USD:.0f}, finite, and a whole number of cents."
        ),
    )
    reason: str = Field(
        min_length=REASON_MIN_LENGTH,
        pattern=REASON_PATTERN,
        description=f"Why the refund is being issued. At least {REASON_MIN_LENGTH} non-whitespace characters.",
    )

    @field_validator("amount")
    @classmethod
    def _amount_must_be_whole_cents(cls, value: float) -> float:
        """Enforce the advertised multipleOf exactly.

        Pydantic's own ``multiple_of`` uses a float modulo, which reports 0.07 as not a
        multiple of 0.01, so the check is done here and only published there. Decimal rather
        than float arithmetic, so no input can overflow the check into an internal error.
        """
        try:
            cents = Decimal(str(value)) * CENTS_PER_USD
        except (ArithmeticError, InvalidOperation, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError("Input should be a decimal number of USD") from exc
        if cents != cents.to_integral_value():
            raise ValueError("Input should be a whole number of cents")
        return value


def format_validation_error(tool_name: str, error: ValidationError) -> str:
    """Render a Pydantic error into one line a caller can act on."""
    parts = []
    for detail in error.errors():
        location = ".".join(str(item) for item in detail["loc"]) or "<root>"
        parts.append(f"{location}: {detail['msg']}")
    return f"Invalid arguments for {tool_name}: " + "; ".join(parts)


def validation_error_data(error: ValidationError) -> list[dict[str, str]]:
    """Machine readable companion to :func:`format_validation_error`."""
    return [
        {
            "field": ".".join(str(item) for item in detail["loc"]) or "<root>",
            "message": detail["msg"],
            "type": detail["type"],
        }
        for detail in error.errors()
    ]
