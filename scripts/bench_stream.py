"""Measure the Task 3 guardrail: time to first token, and held text as responses grow.

    uv run python scripts/bench_stream.py

Every number the README refers to comes from this script. It uses the scripted upstream,
so there is no network call and the timings are the guardrail's own overhead.
"""

from __future__ import annotations

import asyncio
import time
import tracemalloc

from task3_stream_guard.gateway import redacted_stream
from task3_stream_guard.redactor import MAX_BUFFERED_CHARS, StreamRedactor
from task3_stream_guard.upstream import DEMO_RESPONSE, ScriptedUpstream, chunk_text

CHUNK_SIZE = 12
UPSTREAM_DELAY_SECONDS = 0.01


async def _time_to_first_token(guarded: bool) -> tuple[float, float]:
    """Return (time to first chunk, total time) in seconds."""
    upstream = ScriptedUpstream(chunk_text(DEMO_RESPONSE, CHUNK_SIZE), delay_seconds=UPSTREAM_DELAY_SECONDS)
    started = time.perf_counter()
    first: float | None = None

    if guarded:
        async for _ in redacted_stream(upstream, "summarise the account"):
            if first is None:
                first = time.perf_counter() - started
    else:
        async for _ in upstream.stream("summarise the account"):
            if first is None:
                first = time.perf_counter() - started

    return first or 0.0, time.perf_counter() - started


def _peak_for(chunk_count: int) -> tuple[int, int]:
    """Return (peak held characters, peak traced bytes) for a response of N chunks."""
    redactor = StreamRedactor()
    tracemalloc.start()
    for _ in range(chunk_count):
        redactor.feed("all clear here, nothing to see at all. ")
    redactor.feed(" ada@example.com")
    redactor.flush()
    traced = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return redactor.peak_buffered_chars, traced


async def main() -> None:
    raw_first, raw_total = await _time_to_first_token(guarded=False)
    guarded_first, guarded_total = await _time_to_first_token(guarded=True)

    print("time to first token")
    print(f"  upstream alone        {raw_first * 1000:8.2f} ms   total {raw_total * 1000:8.2f} ms")
    print(f"  through the guardrail {guarded_first * 1000:8.2f} ms   total {guarded_total * 1000:8.2f} ms")
    print(f"  guardrail adds        {(guarded_first - raw_first) * 1000:8.2f} ms to first token")

    print("\npeak held text, by response length")
    print(f"  hard ceiling {MAX_BUFFERED_CHARS} characters, whatever the response length")
    for chunk_count in (100, 1_000, 10_000, 100_000):
        held, traced = _peak_for(chunk_count)
        response_chars = chunk_count * 39
        print(f"  {response_chars:>9,} char response   held {held:>4} chars   traced peak {traced / 1024:8.1f} KiB")


if __name__ == "__main__":
    asyncio.run(main())
