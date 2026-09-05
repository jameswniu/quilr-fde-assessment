"""A token aware sliding window rate limiter with its state in on disk sqlite.

Every charge is one row, so the window really slides: usage at time T is the sum of the
rows charged in the half open interval ``(T - window_seconds, T]``, not a count that
resets on a fixed boundary. A charge made at time t is therefore counted right up to
``t + window_seconds`` and has aged out at ``t + window_seconds`` exactly. Rows outside
the window are deleted on the way past, which keeps the table proportional to the traffic
inside one window rather than to all traffic ever.

Keys. The tenant API key is a credential, so it never reaches the file. Rows are keyed by a
blake2b digest of it, optionally peppered, which is enough to partition budgets and is not
something a leaked database file, backup or support bundle hands back to an attacker.

Concurrency. Each thread gets its own connection, writes run inside ``BEGIN IMMEDIATE``
so the read of current usage and the write of the new charge cannot interleave, and
``busy_timeout`` makes a contended writer wait rather than fail. Two requests for the same
key that arrive together are therefore serialised by sqlite, and cannot both be admitted
against the same remaining budget.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_LIMIT_TOKENS: Final = 50_000
DEFAULT_WINDOW_SECONDS: Final = 60.0
BUSY_TIMEOUT_MS: Final = 5_000

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS token_usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key_digest TEXT    NOT NULL,
    tokens     INTEGER NOT NULL,
    charged_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_token_usage_key_time ON token_usage (key_digest, charged_at);
"""

#: Digest size in bytes. 16 bytes is far more than enough to keep tenants apart.
KEY_DIGEST_BYTES: Final = 16


@dataclass(frozen=True)
class RateLimitDecision:
    """The outcome of one admission check."""

    allowed: bool
    requested_tokens: int
    tokens_in_window: int
    limit_tokens: int
    retry_after_seconds: float
    #: Row id of the charge, so a caller that got nothing for it can hand it back.
    charge_id: int | None = None

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.limit_tokens - self.tokens_in_window)


class SlidingWindowRateLimiter:
    """Token budget per tenant API key, backed by a sqlite file."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        limit_tokens: int = DEFAULT_LIMIT_TOKENS,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        key_pepper: bytes = b"",
    ) -> None:
        if limit_tokens < 1:
            raise ValueError("limit_tokens must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.db_path = Path(db_path)
        self.limit_tokens = limit_tokens
        self.window_seconds = window_seconds
        self._key_pepper = key_pepper
        self._local = threading.local()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def key_digest(self, api_key: str) -> str:
        """The value stored on disk in place of the raw key."""
        return hashlib.blake2b(
            api_key.encode(), digest_size=KEY_DIGEST_BYTES, key=self._key_pepper, person=b"ratelimit"
        ).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        """One connection per thread, since a sqlite connection is not shareable."""
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.db_path, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            self._local.connection = connection
        return connection

    def try_consume(self, api_key: str, tokens: int, *, now: float | None = None) -> RateLimitDecision:
        """Charge ``tokens`` to ``api_key`` if the window has room.

        Args:
            api_key: the tenant key the budget belongs to.
            tokens: how many tokens this request is expected to spend.
            now: the current time. Injected by tests so the window can be moved exactly.

        Returns:
            The decision. Nothing is written when the request is rejected.
        """
        if tokens < 0:
            raise ValueError("tokens must not be negative")
        moment = time.time() if now is None else now
        cutoff = moment - self.window_seconds
        digest = self.key_digest(api_key)
        connection = self._connect()

        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("DELETE FROM token_usage WHERE charged_at <= ?", (cutoff,))
            used = self._used(connection, digest, cutoff)
            if used + tokens > self.limit_tokens:
                retry_after = self._retry_after(connection, digest, cutoff, moment, used + tokens)
                connection.execute("ROLLBACK")
                return RateLimitDecision(False, tokens, used, self.limit_tokens, retry_after)
            cursor = connection.execute(
                "INSERT INTO token_usage (key_digest, tokens, charged_at) VALUES (?, ?, ?)",
                (digest, tokens, moment),
            )
            charge_id = cursor.lastrowid
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return RateLimitDecision(True, tokens, used + tokens, self.limit_tokens, 0.0, charge_id)

    def release(self, charge_id: int) -> bool:
        """Give a charge back, for a request that was admitted and then produced nothing.

        A failed upstream call should not spend a tenant's budget. Repeated failures are a
        separate concern: a production gateway would also count them against an abuse
        budget, so that an endless stream of failing requests still costs the caller
        something.
        """
        connection = self._connect()
        connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = connection.execute("DELETE FROM token_usage WHERE id = ?", (charge_id,))
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return cursor.rowcount > 0

    def tokens_in_window(self, api_key: str, *, now: float | None = None) -> int:
        """Tokens charged to this key inside the current window."""
        moment = time.time() if now is None else now
        return self._used(self._connect(), self.key_digest(api_key), moment - self.window_seconds)

    def rows_for(self, api_key: str) -> int:
        """How many charge rows are on disk for this key. Used to observe eviction."""
        cursor = self._connect().execute(
            "SELECT COUNT(*) FROM token_usage WHERE key_digest = ?", (self.key_digest(api_key),)
        )
        return int(cursor.fetchone()[0])

    def close(self) -> None:
        """Close this thread's connection."""
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    @staticmethod
    def _used(connection: sqlite3.Connection, key_digest: str, cutoff: float) -> int:
        cursor = connection.execute(
            "SELECT COALESCE(SUM(tokens), 0) FROM token_usage WHERE key_digest = ? AND charged_at > ?",
            (key_digest, cutoff),
        )
        return int(cursor.fetchone()[0])

    def _retry_after(
        self, connection: sqlite3.Connection, key_digest: str, cutoff: float, moment: float, needed: int
    ) -> float:
        """When enough of the oldest charges will have aged out for this request to fit."""
        overflow = needed - self.limit_tokens
        cursor = connection.execute(
            "SELECT tokens, charged_at FROM token_usage WHERE key_digest = ? AND charged_at > ? ORDER BY charged_at",
            (key_digest, cutoff),
        )
        freed = 0
        for tokens, charged_at in cursor:
            freed += int(tokens)
            if freed >= overflow:
                return max(0.0, float(charged_at) + self.window_seconds - moment)
        # The request cannot fit even in an empty window.
        return self.window_seconds
