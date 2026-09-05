"""Routing a completion: check the token budget, try the primary, fail over if it stalls.

Order of business for one request:

1. Estimate the tokens the request will spend and ask the rate limiter for room. No room
   means a 429 shaped gateway error carrying ``retry_after_seconds``, and no upstream call.
2. Call the primary provider under a timeout. A 429 from it, or a call that runs past the
   timeout, is a routing signal rather than a failure.
3. On either of those, call the secondary provider under the same timeout.
4. Anything that still fails becomes one standardised error payload. Upstream messages and
   tracebacks are logged locally and never serialised to the caller, and the token charge is
   handed back, since a request that produced no completion should not spend a tenant's
   budget for the next minute.

The limiter is synchronous sqlite work, so it runs on a worker thread and does not block
the event loop while other requests are in flight.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Final

from task4_model_router.errors import GatewayError, GatewayErrorCode, sanitize
from task4_model_router.providers import (
    CompletionRequest,
    CompletionResult,
    Provider,
    ProviderRateLimited,
)
from task4_model_router.rate_limiter import RateLimitDecision, SlidingWindowRateLimiter

logger = logging.getLogger("task4_model_router")

#: The brief's number: fail over once the primary has had this long.
DEFAULT_TIMEOUT_MS: Final = 3000

#: Characters per token. A stand in for the provider's tokenizer, see the README.
CHARS_PER_TOKEN: Final = 4


def estimate_tokens(prompt: str, max_output_tokens: int) -> int:
    """Budget the prompt plus the requested output, since both are billed.

    A negative output budget would silently undercharge, so the router rejects one before
    this is reached and this asserts the same floor rather than quietly clamping it.
    """
    if max_output_tokens < 0:
        raise ValueError("max_output_tokens must not be negative")
    return max(1, math.ceil(len(prompt) / CHARS_PER_TOKEN)) + max_output_tokens


class ModelRouter:
    """Admission control and failover in front of two model providers."""

    def __init__(
        self,
        primary: Provider,
        secondary: Provider,
        limiter: SlidingWindowRateLimiter,
        *,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self.primary = primary
        self.secondary = secondary
        self.limiter = limiter
        self.timeout_seconds = timeout_ms / 1000

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        """Serve one completion.

        Raises:
            GatewayError: the only exception a caller ever sees from this method.
        """
        if not request.api_key or not request.prompt or request.max_output_tokens < 0:
            raise GatewayError(GatewayErrorCode.INVALID_REQUEST)

        tokens = estimate_tokens(request.prompt, request.max_output_tokens)
        try:
            decision = await asyncio.to_thread(self.limiter.try_consume, request.api_key, tokens)
        except Exception as exc:
            # A locked or missing database is an internal failure, and it has to leave by the
            # same door as everything else. Without this it would escape as a raw sqlite error.
            raise sanitize(exc, GatewayErrorCode.INTERNAL_ERROR) from exc
        if not decision.allowed:
            logger.info(
                "rate limited key ending %s, %d of %d tokens used",
                request.api_key[-4:],
                decision.tokens_in_window,
                decision.limit_tokens,
            )
            raise GatewayError(GatewayErrorCode.RATE_LIMITED, retry_after_seconds=decision.retry_after_seconds)

        served = False
        try:
            try:
                text = await self._call(self.primary, request)
            except (ProviderRateLimited, TimeoutError) as reason:
                logger.warning("failing over from %s: %s", self.primary.name, type(reason).__name__)
            except Exception as exc:
                raise sanitize(exc) from exc
            else:
                served = True
                return CompletionResult(text, self.primary.name, self.primary.model, tokens, failed_over=False)

            try:
                text = await self._call(self.secondary, request)
            except Exception as exc:
                raise sanitize(exc) from exc
            served = True
            return CompletionResult(text, self.secondary.name, self.secondary.model, tokens, failed_over=True)
        finally:
            if not served:
                self._release(decision)

    def _release(self, decision: RateLimitDecision) -> None:
        """Hand back tokens charged for a request that produced no completion.

        Synchronous on purpose. This runs in a ``finally``, which is also the path a
        cancelled request takes when a client disconnects, and awaiting inside a cancelled
        task is not reliable. The delete is a single indexed sqlite statement, and this is a
        failure path rather than the hot path. Its own failure is logged and swallowed, so
        it can never replace the error the caller should be seeing.
        """
        if decision.charge_id is None:
            return
        try:
            self.limiter.release(decision.charge_id)
        except Exception:
            logger.warning("could not release charge %s", decision.charge_id, exc_info=True)

    async def _call(self, provider: Provider, request: CompletionRequest) -> str:
        """One provider call under the timeout. A timeout cancels the in flight call.

        Cancelling is local. A real provider may still finish the work and bill for it, so a
        failover after a timeout can cost two upstream calls for one client request. The
        brief asks for failover on timeout, so that is what this does, and the honest note is
        that a cost sensitive deployment would also reconcile against provider usage records.
        """
        return await asyncio.wait_for(provider.complete(request), timeout=self.timeout_seconds)
