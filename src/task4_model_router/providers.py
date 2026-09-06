"""Model providers and the failures the router has to route around.

``ScriptedProvider`` stands in for a real vendor client so the whole router runs with no
network and no API key. A real provider implements the same two attributes and one method,
and ``http_provider.HttpProvider`` is one, off by default.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """Base class for anything a provider can fail with."""


class ProviderRateLimited(ProviderError):
    """The provider answered HTTP 429."""

    def __init__(self, provider: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(f"{provider} returned 429 Too Many Requests")
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds


class ProviderUnavailable(ProviderError):
    """The provider failed in some other way, for example a 5xx or a connection error."""


@dataclass(frozen=True)
class CompletionRequest:
    """One completion asked for by one tenant."""

    api_key: str
    prompt: str
    max_output_tokens: int = 256


@dataclass(frozen=True)
class CompletionResult:
    """A completion, plus how it was served.

    ``estimated_tokens`` is what the limiter was charged, which is an estimate rather than
    the provider's own count. See ``CHARS_PER_TOKEN`` in the router.
    """

    text: str
    provider: str
    model: str
    estimated_tokens: int
    failed_over: bool


class Provider(Protocol):
    """What the router needs from a model provider."""

    name: str
    model: str

    async def complete(self, request: CompletionRequest) -> str: ...


class ScriptedProvider:
    """A provider whose behaviour a test sets up front.

    Args:
        name: provider name reported on the result.
        model: model name reported on the result.
        reply: the text returned on success.
        latency_seconds: how long the call takes. Used to drive the timeout path.
        error: raised instead of returning, once ``latency_seconds`` has elapsed.
        fail_times: raise ``error`` for this many calls, then start succeeding.
    """

    def __init__(
        self,
        name: str,
        model: str,
        *,
        reply: str = "ok",
        latency_seconds: float = 0.0,
        error: Exception | None = None,
        fail_times: int | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.reply = reply
        self.latency_seconds = latency_seconds
        self.error = error
        self.fail_times = fail_times
        self.calls = 0
        self.completed_calls = 0
        self.last_request: CompletionRequest | None = None

    async def complete(self, request: CompletionRequest) -> str:
        self.calls += 1
        self.last_request = request
        if self.latency_seconds:
            await asyncio.sleep(self.latency_seconds)
        if self.error is not None and (self.fail_times is None or self.calls <= self.fail_times):
            raise self.error
        self.completed_calls += 1
        return self.reply
