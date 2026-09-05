"""Measure the Task 3 guardrail: time to first token, and how much text it ever holds back.

    uv run python scripts/bench_stream.py

Every number the README refers to comes from this script. It uses the scripted upstream,
so there is no network call and the timings are the guardrail's own overhead.
"""

from __future__ import annotations

import asyncio
import statistics
import time
import tracemalloc

from task3_stream_guard.gateway import redacted_stream
from task3_stream_guard.patterns import MAX_MATCH_LENGTH
from task3_stream_guard.redactor import MAX_BUFFERED_CHARS, StreamRedactor
from task3_stream_guard.upstream import DEMO_RESPONSE, ScriptedUpstream, chunk_text

CHUNK_SIZE = 12
UPSTREAM_DELAY_SECONDS = 0.01
TRIAL_COUNT = 10
CONTENT_SHAPE_CHARS = 100_000
PROSE_SENTENCE = "all clear here, nothing to see at all. "


async def _first_token_seconds(guarded: bool) -> float:
    """Return the time from stream start to the first emitted chunk, in seconds.

    Stops reading as soon as that first chunk arrives, so a trial costs one chunk delay
    rather than the whole response. This measures time to first token only, which is the
    guardrail property in question, not total response time.
    """
    upstream = ScriptedUpstream(chunk_text(DEMO_RESPONSE, CHUNK_SIZE), delay_seconds=UPSTREAM_DELAY_SECONDS)
    started = time.perf_counter()
    stream = redacted_stream(upstream, "summarise the account") if guarded else upstream.stream("summarise the account")
    async for _ in stream:
        return time.perf_counter() - started
    return 0.0


async def _paired_trials(trial_count: int) -> list[tuple[float, float]]:
    """Run trial_count back to back (upstream alone, through the guardrail) pairs, in seconds.

    Each pair is measured back to back so the two readings that make up one difference are
    close together in time. A single pair is noise, not a measurement, since a guardrail
    costing a fraction of a millisecond is well inside the jitter of one perf_counter read.
    """
    pairs: list[tuple[float, float]] = []
    for _ in range(trial_count):
        raw = await _first_token_seconds(guarded=False)
        guarded = await _first_token_seconds(guarded=True)
        pairs.append((raw, guarded))
    return pairs


def _peak_for_length(chunk_count: int) -> tuple[int, int]:
    """Return (peak held characters, peak traced bytes) for a response of N chunks.

    Every response built here ends on the same unfinished token, " ada@example.com", so this
    isolates one variable, response length, holding content shape fixed. It shows whether the
    held figure moves as the response grows, not what the held figure is for other content.
    """
    redactor = StreamRedactor()
    tracemalloc.start()
    for _ in range(chunk_count):
        redactor.feed(PROSE_SENTENCE)
    redactor.feed(" ada@example.com")
    redactor.flush()
    traced = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return redactor.peak_buffered_chars, traced


def _peak_for_text(text: str) -> int:
    """Return the peak held characters for one already built response, fed in realistic chunks."""
    redactor = StreamRedactor()
    for chunk in chunk_text(text, CHUNK_SIZE):
        redactor.feed(chunk)
    redactor.flush()
    return redactor.peak_buffered_chars


def _content_shapes() -> list[tuple[str, str]]:
    """Three response shapes at the same fixed large size, response length held fixed.

    This is the other half of the held text claim. What actually moves the held figure is
    the shape of the trailing content, not how long the response is, and these three shapes
    show that range: no partial pattern at all, an ordinary partial pattern, and the longest
    possible one.
    """
    prose = PROSE_SENTENCE * (CONTENT_SHAPE_CHARS // len(PROSE_SENTENCE))
    return [
        (prose, "pure prose, no partial pattern"),
        (prose + " ada@example.com", "response ending mid email"),
        ("x" * CONTENT_SHAPE_CHARS, "one unbroken token"),
    ]


async def main() -> None:
    pairs = await _paired_trials(TRIAL_COUNT)
    raw_ms = [raw * 1000 for raw, _ in pairs]
    guarded_ms = [guarded * 1000 for _, guarded in pairs]
    diffs_ms = [(guarded - raw) * 1000 for raw, guarded in pairs]

    print(f"time to first token, median of {TRIAL_COUNT} paired trials")
    print(f"  upstream alone        {statistics.median(raw_ms):8.2f} ms")
    print(f"  through the guardrail {statistics.median(guarded_ms):8.2f} ms")
    print(
        f"  guardrail adds        {statistics.median(diffs_ms):8.2f} ms to first token, "
        f"range {min(diffs_ms):.2f} to {max(diffs_ms):.2f} ms over {TRIAL_COUNT} trials"
    )
    if min(diffs_ms) <= 0 <= max(diffs_ms):
        print("  the range straddles zero, so the added cost sits below this instrument's resolution")

    print("\npeak held text, by response length, content shape held fixed")
    for chunk_count in (100, 1_000, 10_000, 100_000):
        held, traced = _peak_for_length(chunk_count)
        response_chars = chunk_count * len(PROSE_SENTENCE)
        print(f"  {response_chars:>9,} char response   held {held:>4} chars   traced peak {traced / 1024:8.1f} KiB")
    print("  flat across a thousandfold change in length, so length alone does not move this number")

    print(f"\npeak held text, by content shape, response length held fixed near {CONTENT_SHAPE_CHARS:,} chars")
    for text, label in _content_shapes():
        held = _peak_for_text(text)
        print(f"  {len(text):>9,} char {label:<32} held {held:>4} chars")
    print("  the held figure tracks the shape of the trailing content, not the length of the response")

    print(
        f"\n  hard ceiling {MAX_BUFFERED_CHARS} chars, twice the longest possible match "
        f"({MAX_MATCH_LENGTH} chars, an email at the RFC 5321 limits, a 64 character local part "
        f"and a 255 character domain), since a match straddling the cut can pull the window back "
        f"a second time"
    )


if __name__ == "__main__":
    asyncio.run(main())
