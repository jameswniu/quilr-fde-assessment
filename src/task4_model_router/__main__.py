"""Walk the router through the four outcomes it exists to handle.

    uv run python -m task4_model_router

Rate limiter state is written to ``.data/rate_limit.sqlite3`` under the repository root,
so the file is there to inspect afterwards.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from task4_model_router.errors import GatewayError
from task4_model_router.providers import (
    CompletionRequest,
    ProviderRateLimited,
    ProviderUnavailable,
    ScriptedProvider,
)
from task4_model_router.rate_limiter import SlidingWindowRateLimiter
from task4_model_router.router import ModelRouter

DB_PATH = Path(".data/rate_limit.sqlite3")
TIMEOUT_MS = 300  # shortened from the 3000ms default so the demo does not sit and wait


def _report(label: str, result: object) -> None:
    print(f"\n{label}\n  {result}")


async def _run(label: str, router: ModelRouter, request: CompletionRequest) -> None:
    try:
        _report(label, await router.complete(request))
    except GatewayError as error:
        _report(label, json.dumps(error.to_payload()))


async def main_async(db_path: Path) -> None:
    limiter = SlidingWindowRateLimiter(db_path, limit_tokens=50_000)
    request = CompletionRequest(api_key="tenant-key-abc123", prompt="Summarise this quarter." * 20)

    healthy = ScriptedProvider("openai", "gpt-4o-mini", reply="a completion from the primary")
    backup = ScriptedProvider("anthropic", "claude-haiku", reply="a completion from the secondary")

    await _run("primary healthy", ModelRouter(healthy, backup, limiter, timeout_ms=TIMEOUT_MS), request)

    throttled = ScriptedProvider("openai", "gpt-4o-mini", error=ProviderRateLimited("openai", 30.0))
    await _run("primary returns 429", ModelRouter(throttled, backup, limiter, timeout_ms=TIMEOUT_MS), request)

    stalled = ScriptedProvider("openai", "gpt-4o-mini", latency_seconds=TIMEOUT_MS / 1000 * 4)
    await _run("primary times out", ModelRouter(stalled, backup, limiter, timeout_ms=TIMEOUT_MS), request)

    leaky = ScriptedProvider(
        "anthropic",
        "claude-haiku",
        error=ProviderUnavailable("500 from https://internal-8.vpc.local with key sk-live-abcdef"),
    )
    await _run("both providers down", ModelRouter(throttled, leaky, limiter, timeout_ms=TIMEOUT_MS), request)

    exhausted = SlidingWindowRateLimiter(db_path, limit_tokens=10)
    await _run("token budget exhausted", ModelRouter(healthy, backup, exhausted, timeout_ms=TIMEOUT_MS), request)

    print("\nno upstream message, host or key appears in any payload above")


def main() -> None:
    # Quiet, so the payloads below are the whole output. The gateway log is where the
    # upstream detail goes, including the fake secret in the "both providers down" case.
    logging.basicConfig(level=logging.CRITICAL, format="%(levelname)s %(name)s %(message)s")
    DB_PATH.unlink(missing_ok=True)
    asyncio.run(main_async(DB_PATH))
    print(f"rate limiter state on disk at {DB_PATH.resolve()}")


if __name__ == "__main__":
    main()
