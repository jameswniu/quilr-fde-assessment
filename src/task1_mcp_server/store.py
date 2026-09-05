"""A tiny in-memory customer store so the two tools have something real to return.

Balances are held in whole cents, because a float balance debited by a float amount can be
rounded back to where it started, which would let a stream of tiny refunds be approved for
free. The refund path mutates the store under a lock, so a repeated call cannot approve the
same money twice. The brief fixes ``trigger_refund`` at three arguments, so there is no
idempotency key: a real tool would take one and de-duplicate client retries, rather than
relying on the balance alone to stop a replay.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Final


@dataclass(frozen=True)
class CustomerRecord:
    """One customer, as returned by ``get_customer_record``."""

    customer_id: str
    name: str
    email: str
    plan: str
    lifetime_value_usd: float
    refundable_balance_cents: int

    @property
    def refundable_balance_usd(self) -> float:
        """The balance in dollars, for display and for the tool response."""
        return self.refundable_balance_cents / CENTS_PER_USD

    def as_dict(self) -> dict[str, str | float]:
        return {
            "customer_id": self.customer_id,
            "name": self.name,
            "email": self.email,
            "plan": self.plan,
            "lifetime_value_usd": self.lifetime_value_usd,
            "refundable_balance_usd": self.refundable_balance_usd,
        }


class RefundRejection(StrEnum):
    """Why a refund was not applied."""

    UNKNOWN_CUSTOMER = "unknown_customer"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    BELOW_MINIMUM = "below_minimum"


@dataclass(frozen=True)
class RefundOutcome:
    """The result of one refund attempt."""

    record: CustomerRecord | None
    rejection: RefundRejection | None


CENTS_PER_USD: Final = 100

_SEED: Final[tuple[CustomerRecord, ...]] = (
    CustomerRecord("CUST-10042", "Ada Lovelace", "ada@example.com", "enterprise", 48200.0, 120_000),
    CustomerRecord("CUST-2A9F1", "Grace Hopper", "grace@example.com", "growth", 9100.0, 25_000),
    CustomerRecord("CUST-77Z12", "Alan Turing", "alan@example.com", "starter", 640.0, 0),
)

_LOCK: Final = threading.Lock()
_CUSTOMERS: Final[dict[str, CustomerRecord]] = {record.customer_id: record for record in _SEED}


def find_customer(customer_id: str) -> CustomerRecord | None:
    """Return the record for ``customer_id``, or None when there is no such customer."""
    with _LOCK:
        return _CUSTOMERS.get(customer_id)


def to_cents(amount: float) -> int:
    """Convert a dollar amount to whole cents, rounding halves up as money conventionally does."""
    return int(Decimal(str(amount)).scaleb(2).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def apply_refund(customer_id: str, amount: float) -> RefundOutcome:
    """Check the balance and debit it in one step, so a retry cannot spend it twice."""
    cents = to_cents(amount)
    with _LOCK:
        record = _CUSTOMERS.get(customer_id)
        if record is None:
            return RefundOutcome(None, RefundRejection.UNKNOWN_CUSTOMER)
        if cents < 1:
            return RefundOutcome(record, RefundRejection.BELOW_MINIMUM)
        if cents > record.refundable_balance_cents:
            return RefundOutcome(record, RefundRejection.INSUFFICIENT_BALANCE)
        updated = replace(record, refundable_balance_cents=record.refundable_balance_cents - cents)
        _CUSTOMERS[customer_id] = updated
        return RefundOutcome(updated, None)


def reset_store() -> None:
    """Put the seed data back. Used by tests."""
    with _LOCK:
        _CUSTOMERS.clear()
        _CUSTOMERS.update({record.customer_id: record for record in _SEED})
