"""Task 4: failover on 429 and on timeout, and error payloads that leak nothing."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

import pytest

from task4_model_router.errors import GatewayError, GatewayErrorCode
from task4_model_router.providers import (
    CompletionRequest,
    ProviderRateLimited,
    ProviderUnavailable,
    ScriptedProvider,
)
from task4_model_router.rate_limiter import RateLimitDecision, SlidingWindowRateLimiter
from task4_model_router.router import DEFAULT_TIMEOUT_MS, ModelRouter, estimate_tokens

KEY = "tenant-key-abc123"
FAST_TIMEOUT_MS = 60

#: A provider failure carrying everything that must never reach a caller.
LEAKY_MESSAGE = (
    "Traceback (most recent call last): urllib3 POST https://api.internal-8.vpc.local/v1/chat "
    "failed with 500, Authorization: Bearer sk-live-7f3c9a, /opt/gateway/router.py line 214"
)


def request(prompt: str = "summarise the quarter") -> CompletionRequest:
    return CompletionRequest(api_key=KEY, prompt=prompt, max_output_tokens=64)


@pytest.fixture
def limiter(tmp_path: Path) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(tmp_path / "router.sqlite3", limit_tokens=50_000, window_seconds=60.0)


def build(limiter: SlidingWindowRateLimiter, primary: ScriptedProvider, secondary: ScriptedProvider) -> ModelRouter:
    return ModelRouter(primary, secondary, limiter, timeout_ms=FAST_TIMEOUT_MS)


def test_the_brief_default_timeout_is_three_seconds() -> None:
    assert DEFAULT_TIMEOUT_MS == 3000


def test_token_estimate_covers_prompt_and_requested_output() -> None:
    assert estimate_tokens("a" * 400, 100) == 200
    assert estimate_tokens("", 0) == 1


async def test_healthy_primary_serves_the_request(limiter: SlidingWindowRateLimiter) -> None:
    primary = ScriptedProvider("openai", "gpt-4o-mini", reply="primary answer")
    secondary = ScriptedProvider("anthropic", "claude-haiku", reply="secondary answer")

    result = await build(limiter, primary, secondary).complete(request())

    assert result.text == "primary answer"
    assert result.provider == "openai"
    assert result.failed_over is False
    assert secondary.calls == 0


async def test_failover_on_a_429(limiter: SlidingWindowRateLimiter) -> None:
    primary = ScriptedProvider("openai", "gpt-4o-mini", error=ProviderRateLimited("openai", 30.0))
    secondary = ScriptedProvider("anthropic", "claude-haiku", reply="secondary answer")

    result = await build(limiter, primary, secondary).complete(request())

    assert result.text == "secondary answer"
    assert result.provider == "anthropic"
    assert result.failed_over is True
    assert primary.calls == 1
    assert secondary.calls == 1


async def test_failover_on_a_timeout(limiter: SlidingWindowRateLimiter) -> None:
    primary = ScriptedProvider("openai", "gpt-4o-mini", latency_seconds=FAST_TIMEOUT_MS / 1000 * 10)
    secondary = ScriptedProvider("anthropic", "claude-haiku", reply="secondary answer")

    started = time.perf_counter()
    result = await build(limiter, primary, secondary).complete(request())
    elapsed = time.perf_counter() - started

    assert result.provider == "anthropic"
    assert result.failed_over is True
    assert elapsed < primary.latency_seconds, "the router waited for the primary instead of timing out"
    assert primary.completed_calls == 0, "the timed out call should have been cancelled"


async def test_the_timeout_races_the_response_rather_than_always_firing(
    limiter: SlidingWindowRateLimiter,
) -> None:
    """A primary that answers just inside the timeout is used, not failed over."""
    primary = ScriptedProvider("openai", "gpt-4o-mini", latency_seconds=FAST_TIMEOUT_MS / 1000 / 4)
    secondary = ScriptedProvider("anthropic", "claude-haiku")

    result = await build(limiter, primary, secondary).complete(request())

    assert result.provider == "openai"
    assert result.failed_over is False
    assert secondary.calls == 0


async def test_a_primary_that_recovers_is_used_again(limiter: SlidingWindowRateLimiter) -> None:
    primary = ScriptedProvider("openai", "gpt-4o-mini", error=ProviderRateLimited("openai"), fail_times=1)
    secondary = ScriptedProvider("anthropic", "claude-haiku")
    router = build(limiter, primary, secondary)

    assert (await router.complete(request())).failed_over is True
    assert (await router.complete(request())).failed_over is False


async def test_both_providers_down_gives_one_standard_error(limiter: SlidingWindowRateLimiter) -> None:
    primary = ScriptedProvider("openai", "gpt-4o-mini", error=ProviderRateLimited("openai"))
    secondary = ScriptedProvider("anthropic", "claude-haiku", error=ProviderUnavailable(LEAKY_MESSAGE))

    with pytest.raises(GatewayError) as caught:
        await build(limiter, primary, secondary).complete(request())

    error = caught.value
    assert error.code is GatewayErrorCode.UPSTREAM_UNAVAILABLE
    assert error.status_code == 502
    assert error.to_payload() == {
        "error": {
            "code": "upstream_unavailable",
            "message": "No model provider was able to serve this request.",
            "request_id": error.request_id,
        }
    }


@pytest.mark.parametrize(
    "leak",
    ["Traceback", "sk-live-7f3c9a", "internal-8.vpc.local", "/opt/gateway/router.py", "urllib3", "500"],
)
async def test_error_payloads_leak_no_upstream_detail(limiter: SlidingWindowRateLimiter, leak: str) -> None:
    primary = ScriptedProvider("openai", "gpt-4o-mini", error=ProviderUnavailable(LEAKY_MESSAGE))
    secondary = ScriptedProvider("anthropic", "claude-haiku", error=ProviderUnavailable(LEAKY_MESSAGE))

    with pytest.raises(GatewayError) as caught:
        await build(limiter, primary, secondary).complete(request())

    payload = caught.value.to_payload()
    # The request id is random hex, so any short digit run can appear inside it by chance.
    # The leak check is about the message and code, which is where an upstream detail would land.
    payload["error"].pop("request_id")
    serialised = json.dumps(payload)
    assert leak not in serialised


async def test_an_unexpected_provider_error_is_not_failed_over(limiter: SlidingWindowRateLimiter) -> None:
    """Only a 429 or a timeout is a routing signal. Anything else is reported, not retried."""
    primary = ScriptedProvider("openai", "gpt-4o-mini", error=ProviderUnavailable("bad gateway"))
    secondary = ScriptedProvider("anthropic", "claude-haiku")

    with pytest.raises(GatewayError):
        await build(limiter, primary, secondary).complete(request())
    assert secondary.calls == 0


async def test_exhausting_the_budget_returns_a_429_payload_and_calls_nobody(tmp_path: Path) -> None:
    # One request is estimated at 70 tokens, so a 100 token budget fits exactly one.
    limiter = SlidingWindowRateLimiter(tmp_path / "small.sqlite3", limit_tokens=100, window_seconds=60.0)
    primary = ScriptedProvider("openai", "gpt-4o-mini")
    secondary = ScriptedProvider("anthropic", "claude-haiku")
    router = ModelRouter(primary, secondary, limiter, timeout_ms=FAST_TIMEOUT_MS)

    assert (await router.complete(request())).provider == "openai"
    with pytest.raises(GatewayError) as caught:
        await router.complete(request())

    error = caught.value
    assert error.code is GatewayErrorCode.RATE_LIMITED
    assert error.status_code == 429
    payload = error.to_payload()["error"]
    assert payload["retry_after_seconds"] > 0
    assert primary.calls == 1, "a rate limited request must not reach a provider"
    assert secondary.calls == 0


async def test_concurrent_requests_share_one_budget(tmp_path: Path) -> None:
    """Twelve requests in flight at once against a 280 token budget, which fits four of them."""
    limiter = SlidingWindowRateLimiter(tmp_path / "concurrent.sqlite3", limit_tokens=280, window_seconds=60.0)
    primary = ScriptedProvider("openai", "gpt-4o-mini", latency_seconds=0.005)
    secondary = ScriptedProvider("anthropic", "claude-haiku")
    router = ModelRouter(primary, secondary, limiter, timeout_ms=FAST_TIMEOUT_MS)

    outcomes = await asyncio.gather(*(router.complete(request()) for _ in range(12)), return_exceptions=True)

    served = [item for item in outcomes if not isinstance(item, BaseException)]
    limited = [item for item in outcomes if isinstance(item, GatewayError)]
    assert len(served) == 4
    assert len(limited) == 8
    assert primary.calls == 4


@pytest.mark.parametrize(
    "bad", [CompletionRequest(api_key="", prompt="hello"), CompletionRequest(api_key=KEY, prompt="")]
)
async def test_invalid_requests_are_rejected_before_anything_else(
    limiter: SlidingWindowRateLimiter, bad: CompletionRequest
) -> None:
    primary = ScriptedProvider("openai", "gpt-4o-mini")
    with pytest.raises(GatewayError) as caught:
        await build(limiter, primary, ScriptedProvider("anthropic", "claude-haiku")).complete(bad)
    assert caught.value.code is GatewayErrorCode.INVALID_REQUEST
    assert caught.value.status_code == 400
    assert primary.calls == 0


def test_every_error_code_has_a_message_and_a_status() -> None:
    for code in GatewayErrorCode:
        error = GatewayError(code)
        assert error.message
        assert 400 <= error.status_code <= 599
        assert error.to_payload()["error"]["request_id"].startswith("req_")


async def test_a_request_that_produced_nothing_does_not_spend_the_budget(tmp_path: Path) -> None:
    """Both providers down means the tenant gets its tokens back, not a minute of 429s."""
    limiter = SlidingWindowRateLimiter(tmp_path / "refund.sqlite3", limit_tokens=100, window_seconds=60.0)
    primary = ScriptedProvider("openai", "gpt-4o-mini", error=ProviderRateLimited("openai"))
    secondary = ScriptedProvider("anthropic", "claude-haiku", error=ProviderUnavailable("down"))
    router = ModelRouter(primary, secondary, limiter, timeout_ms=FAST_TIMEOUT_MS)

    with pytest.raises(GatewayError):
        await router.complete(request())

    assert limiter.tokens_in_window(KEY) == 0
    assert limiter.rows_for(KEY) == 0
    assert (await ModelRouter(ScriptedProvider("openai", "m"), secondary, limiter).complete(request())).text == "ok"


async def test_an_unexpected_primary_error_also_returns_the_budget(tmp_path: Path) -> None:
    limiter = SlidingWindowRateLimiter(tmp_path / "unexpected.sqlite3", limit_tokens=100, window_seconds=60.0)
    primary = ScriptedProvider("openai", "gpt-4o-mini", error=ProviderUnavailable("bad gateway"))
    router = ModelRouter(primary, ScriptedProvider("anthropic", "claude-haiku"), limiter, timeout_ms=FAST_TIMEOUT_MS)

    with pytest.raises(GatewayError):
        await router.complete(request())
    assert limiter.tokens_in_window(KEY) == 0


async def test_a_successful_failover_still_spends_the_budget(limiter: SlidingWindowRateLimiter) -> None:
    """Tokens were really spent at the secondary, so they stay charged."""
    primary = ScriptedProvider("openai", "gpt-4o-mini", error=ProviderRateLimited("openai"))
    result = await build(limiter, primary, ScriptedProvider("anthropic", "claude-haiku")).complete(request())
    assert result.failed_over is True
    assert limiter.tokens_in_window(KEY) == result.estimated_tokens


async def test_a_rate_limiter_failure_leaves_by_the_same_door(
    limiter: SlidingWindowRateLimiter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A locked database must not escape as a raw sqlite error carrying local detail."""

    def explode(*_: object, **__: object) -> RateLimitDecision:
        raise sqlite3.OperationalError("database is locked: /var/lib/gateway/secrets/rate_limit.sqlite3")

    monkeypatch.setattr(limiter, "try_consume", explode)
    primary = ScriptedProvider("openai", "gpt-4o-mini")

    with pytest.raises(GatewayError) as caught:
        await build(limiter, primary, ScriptedProvider("anthropic", "claude-haiku")).complete(request())

    error = caught.value
    assert error.code is GatewayErrorCode.INTERNAL_ERROR
    assert error.status_code == 500
    assert "sqlite" not in json.dumps(error.to_payload())
    assert "/var/lib/gateway" not in json.dumps(error.to_payload())
    assert primary.calls == 0


async def test_a_negative_output_budget_is_rejected_rather_than_clamped(
    limiter: SlidingWindowRateLimiter,
) -> None:
    """Clamping to zero would let a caller be charged for the prompt alone."""
    bad = CompletionRequest(api_key=KEY, prompt="summarise", max_output_tokens=-100_000)
    primary = ScriptedProvider("openai", "gpt-4o-mini")

    with pytest.raises(GatewayError) as caught:
        await build(limiter, primary, ScriptedProvider("anthropic", "claude-haiku")).complete(bad)

    assert caught.value.code is GatewayErrorCode.INVALID_REQUEST
    assert primary.calls == 0
    assert limiter.tokens_in_window(KEY) == 0


def test_estimate_tokens_refuses_a_negative_output_budget() -> None:
    with pytest.raises(ValueError, match="max_output_tokens"):
        estimate_tokens("hello", -1)
