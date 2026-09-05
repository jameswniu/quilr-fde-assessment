"""Task 3: the gateway endpoint streams, applies back pressure, and redacts in flight."""

from __future__ import annotations

import asyncio
import time

from task3_stream_guard.gateway import create_app
from task3_stream_guard.upstream import DEMO_RESPONSE, ScriptedUpstream, chunk_text
from tests import asgi_driver

CLEAN_TEXT = "All of the account details look fine and there is nothing sensitive in this reply at all. "


async def test_endpoint_streams_redacted_text() -> None:
    upstream = ScriptedUpstream(chunk_text(DEMO_RESPONSE, 11))
    result = await asgi_driver.post(create_app(upstream), "/v1/generate", {"prompt": "summarise"})

    assert result.status == 200
    assert result.headers["x-guardrail"] == "pii-redaction"
    assert len(result.chunks) > 1, "response arrived as a single blob rather than a stream"

    body = result.body
    assert "ada@example.com" not in body
    assert "grace.hopper+billing@mail.example.co.uk" not in body
    assert "123-45-6789" not in body
    assert "4111 1111 1111 1111" not in body
    assert "5500-0000-0000-0004" not in body
    assert body.count("[REDACTED]") == 5
    assert "4111111111111112" in body, "the number that fails Luhn should survive"
    assert body.endswith("Nothing else in this reply is sensitive.")


async def test_time_to_first_token_does_not_wait_for_the_whole_response() -> None:
    """The first redacted bytes leave the gateway while the upstream is still generating."""
    delay = 0.02
    chunks = chunk_text(CLEAN_TEXT * 4, 16)
    upstream = ScriptedUpstream(chunks, delay_seconds=delay)

    started = time.perf_counter()
    first_chunk_at: list[float] = []

    async def record(_: bytes) -> None:
        if not first_chunk_at:
            first_chunk_at.append(time.perf_counter() - started)

    result = await asgi_driver.post(create_app(upstream), "/v1/generate", {"prompt": "hello"}, on_chunk=record)
    total = time.perf_counter() - started

    assert result.status == 200
    assert len(chunks) >= 20
    assert total > delay * 15, "the upstream should have taken real time to finish"
    assert first_chunk_at[0] < delay * 5, f"first chunk took {first_chunk_at[0]:.3f}s of a {total:.3f}s response"


async def test_back_pressure_keeps_the_gateway_from_running_ahead() -> None:
    """A slow reader slows the upstream pull, it does not fill a buffer in the gateway."""
    chunks = chunk_text(CLEAN_TEXT * 6, 32)
    upstream = ScriptedUpstream(chunks)
    observed: list[tuple[int, int]] = []

    async def slow_reader(_: bytes) -> None:
        observed.append((len(observed) + 1, upstream.chunks_yielded))
        await asyncio.sleep(0.005)

    result = await asgi_driver.post(create_app(upstream), "/v1/generate", {"prompt": "hello"}, on_chunk=slow_reader)

    assert result.status == 200
    assert len(observed) > 5
    for received, yielded in observed:
        assert yielded <= received + 2, f"gateway read {yielded} upstream chunks after sending {received}"


async def test_a_value_at_the_very_end_is_redacted_by_the_flush() -> None:
    upstream = ScriptedUpstream(chunk_text("final contact ada@example.com", 5))
    result = await asgi_driver.post(create_app(upstream), "/v1/generate", {"prompt": "hello"})
    assert result.body == "final contact [REDACTED]"


async def test_empty_upstream_response() -> None:
    result = await asgi_driver.post(create_app(ScriptedUpstream([])), "/v1/generate", {"prompt": "hello"})
    assert result.status == 200
    assert result.body == ""


async def test_invalid_json_body() -> None:
    result = await asgi_driver.post(create_app(), "/v1/generate", raw_body=b"{not json")
    assert result.status == 400
    assert result.json()["error"]["code"] == "invalid_request"


async def test_missing_prompt() -> None:
    result = await asgi_driver.post(create_app(), "/v1/generate", {"model": "gpt-x"})
    assert result.status == 400
    assert result.json()["error"]["code"] == "invalid_request"
