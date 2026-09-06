"""Measure the Task 3 guardrail: time to first token, and how much text it ever holds back.

    uv run python scripts/bench_stream.py

Every number the README refers to comes from this script. It uses the scripted upstream,
so there is no network call and the timings are the guardrail's own overhead.

Time to first token is measured once per leading content shape rather than once overall,
because the leading content is what decides it. A reply opening in safe prose leaves on the
first chunk and the guardrail costs nothing worth measuring. A reply opening mid pattern is
held until the pattern resolves, and that is a real wait a user sees.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
import tracemalloc
from pathlib import Path
from typing import Any, Final

from task3_stream_guard.gateway import redacted_stream
from task3_stream_guard.patterns import MAX_MATCH_LENGTH
from task3_stream_guard.redactor import MAX_BUFFERED_CHARS, StreamRedactor
from task3_stream_guard.upstream import DEMO_RESPONSE, ScriptedUpstream, chunk_text

CHUNK_SIZE = 12
UPSTREAM_DELAY_SECONDS = 0.01
TRIAL_COUNT = 10
CONTENT_SHAPE_CHARS = 100_000
LEADING_TOKEN_CHARS = 1_000

#: Where every number this script measures is written, so the README figures and the claim
#: check read a file rather than a person retyping a table out of the terminal.
REPORT_PATH: Final = Path(__file__).resolve().parent.parent / "reports" / "bench_report.json"

PROSE_SENTENCE = "all clear here, nothing to see at all. "
PROSE_TAIL = "and the rest of the reply is ordinary prose with nothing sensitive left in it."

#: The longest address the email pattern can match, which is MAX_MATCH_LENGTH characters. A 64
#: character local part, "@", and a 255 character domain whose last label sits at the 24
#: character top level domain cap. Written out rather than derived, because the caps that
#: produce it are private to patterns.py.
MAX_EMAIL = "a" * 64 + "@" + ("b" * 63 + ".") * 3 + "d" * 38 + "." + "e" * 24


async def _first_token_seconds(response: str, *, guarded: bool) -> float:
    """Return the time from stream start to the first emitted chunk, in seconds.

    Stops reading as soon as that first chunk arrives, so a trial costs only the chunk delays
    the guardrail needs before it can emit anything, rather than the whole response. This
    measures time to first token only, which is the guardrail property in question, not total
    response time.
    """
    upstream = ScriptedUpstream(chunk_text(response, CHUNK_SIZE), delay_seconds=UPSTREAM_DELAY_SECONDS)
    started = time.perf_counter()
    stream = redacted_stream(upstream, "summarise the account") if guarded else upstream.stream("summarise the account")
    async for _ in stream:
        return time.perf_counter() - started
    return 0.0


async def _paired_trials(response: str, trial_count: int) -> list[tuple[float, float]]:
    """Run trial_count back to back (upstream alone, through the guardrail) pairs, in seconds.

    Each pair is measured back to back so the two readings that make up one difference are
    close together in time. A single pair is noise, not a measurement, since a guardrail
    costing a fraction of a millisecond is well inside the jitter of one perf_counter read.
    """
    pairs: list[tuple[float, float]] = []
    for _ in range(trial_count):
        raw = await _first_token_seconds(response, guarded=False)
        guarded = await _first_token_seconds(response, guarded=True)
        pairs.append((raw, guarded))
    return pairs


def _leading_shapes() -> list[tuple[str, str]]:
    """Responses that differ in what their first characters are, which is what sets first token.

    The redactor cannot emit text that might still turn out to be part of a pattern, so the
    only question is how long the opening of the response stays ambiguous. Safe prose is never
    ambiguous. Every other shape here is ambiguous until the value that opens it resolves, so
    the cost tracks how long that leading value is and not what kind of value it is. Every
    label carries the length of its own fixture for that reason, since one short address says
    nothing about a long one.

    The last shape is the worst this design allows, and it is the same case that doubles the
    held text ceiling. A whole longest possible match sits at character 0 with no safe cut
    anywhere after it, so the match keeps pulling the cut back to its own start until the
    window has moved a second MAX_MATCH_LENGTH beyond it. The "_" is what makes that address
    legal, since it ends the domain without ending the token.
    """
    email = "ada@example.com"
    card = "4111 1111 1111 1111"
    ssn = "123-45-6789"
    token = "x" * LEADING_TOKEN_CHARS
    return [
        ("safe prose", DEMO_RESPONSE),
        (f"a {len(email)} char email", f"{email} {PROSE_TAIL}"),
        (f"a {len(card)} char Luhn card", f"{card} {PROSE_TAIL}"),
        (f"an {len(ssn)} char SSN", f"{ssn} {PROSE_TAIL}"),
        (f"a {len(MAX_EMAIL)} char email", f"{MAX_EMAIL} {PROSE_TAIL}"),
        (f"a {len(token):,} char unbroken token", f"{token} {PROSE_TAIL}"),
        (f"a {len(MAX_EMAIL)} char email inside a token", _straddling_response()),
    ]


def _straddling_response() -> str:
    """The worst case fixture, used for both its first token cost and its peak held text.

    A whole longest possible match sits at character 0 and nothing after it is a safe cut for
    another MAX_MATCH_LENGTH characters, which is the case that doubles the held text ceiling.
    Built once here so the timing row and the held text figure describe the same string.
    """
    return f"{MAX_EMAIL}_{'z' * MAX_MATCH_LENGTH} {PROSE_TAIL}"


def _chunks_waited(response: str) -> int:
    """How many extra upstream chunks the guardrail holds before it can emit anything.

    Deterministic, so it is counted once rather than once per trial, and it is the added cost
    in the one unit that survives a change of machine. The milliseconds beside it in the table
    are this count times whatever cadence the upstream happens to have. The condition here,
    emit on the first non-empty feed, is the same one redacted_stream yields on, so a reader
    can cross check the two columns against each other.
    """
    redactor = StreamRedactor()
    for count, chunk in enumerate(chunk_text(response, CHUNK_SIZE), start=1):
        if redactor.feed(chunk):
            return count - 1
    return len(chunk_text(response, CHUNK_SIZE))


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


async def _report_first_token() -> list[dict[str, Any]]:
    """Print one row per leading content shape, then the worst case across all of them."""
    print(f"time to first token, by leading content shape, median of {TRIAL_COUNT} paired trials each")
    header = f"{'waits':>6}{'upstream':>12}{'guarded':>12}{'guardrail adds':>17}   range over trials"
    print(f"  {'response opens with':<32}{header}")

    rows: list[dict[str, Any]] = []
    straddling: list[str] = []
    for label, response in _leading_shapes():
        pairs = await _paired_trials(response, TRIAL_COUNT)
        raw_ms = [raw * 1000 for raw, _ in pairs]
        guarded_ms = [guarded * 1000 for _, guarded in pairs]
        diffs_ms = [(guarded - raw) * 1000 for raw, guarded in pairs]
        added = statistics.median(diffs_ms)
        if min(diffs_ms) <= 0 <= max(diffs_ms):
            straddling.append(label)
        rows.append(
            {
                "label": label,
                "waits": _chunks_waited(response),
                "upstream_ms": round(statistics.median(raw_ms), 2),
                "guarded_ms": round(statistics.median(guarded_ms), 2),
                "added_ms": round(added, 2),
                "min_ms": round(min(diffs_ms), 2),
                "max_ms": round(max(diffs_ms), 2),
            }
        )
        print(
            f"  {label:<32}{_chunks_waited(response):>6}{statistics.median(raw_ms):>9.2f} ms"
            f"{statistics.median(guarded_ms):>9.2f} ms{added:>14.2f} ms"
            f"   {min(diffs_ms):.2f} to {max(diffs_ms):.2f} ms"
        )
    worst = max(rows, key=lambda row: float(row["added_ms"]))
    worst_added, worst_label = float(worst["added_ms"]), str(worst["label"])

    print("  safe prose is the demo reply, the other six put one leading value in front of the same prose tail")
    print("  waits counts the extra upstream chunks held before the first token, so the cost tracks how long")
    print("  that leading value is rather than which kind of value it is")
    headline = f"the guardrail adds {worst_added:.2f} ms to first token, on a response opening with {worst_label}"
    print(f"\n  worst case, {headline}")
    if straddling:
        joined = ", ".join(straddling)
        print(f"  the range straddles zero for {joined}, where the added cost sits below this instrument's resolution")
    print("  the redactor cannot emit text that might still turn out to be part of a pattern, so a response")
    print("  that opens mid pattern waits for it to resolve. That wait is bounded the way the held text is,")
    print(f"  by the {MAX_MATCH_LENGTH} character longest match, doubled to {MAX_BUFFERED_CHARS} when a whole match")
    print("  opens the response, and it is paid at whatever rate the upstream sends chunks")
    return rows


async def main() -> None:
    first_token = await _report_first_token()

    print("\npeak held text, by response length, content shape held fixed")
    by_length: list[dict[str, Any]] = []
    for chunk_count in (100, 1_000, 10_000, 100_000):
        held, traced = _peak_for_length(chunk_count)
        response_chars = chunk_count * len(PROSE_SENTENCE)
        by_length.append({"response_chars": response_chars, "held_chars": held, "traced_kib": round(traced / 1024, 1)})
        print(f"  {response_chars:>9,} char response   held {held:>4} chars   traced peak {traced / 1024:8.1f} KiB")
    print("  flat across a thousandfold change in length, so length alone does not move this number")

    print(f"\npeak held text, by content shape, response length held fixed near {CONTENT_SHAPE_CHARS:,} chars")
    by_shape: list[dict[str, Any]] = []
    for text, label in _content_shapes():
        held = _peak_for_text(text)
        by_shape.append({"label": label, "response_chars": len(text), "held_chars": held})
        print(f"  {len(text):>9,} char {label:<32} held {held:>4} chars")
    print("  the held figure tracks the shape of the trailing content, not the length of the response")

    straddle_held = _peak_for_text(_straddling_response())
    print(
        f"\n  hard ceiling {MAX_BUFFERED_CHARS} chars, twice the longest possible match "
        f"({MAX_MATCH_LENGTH} chars, an email at the RFC 5321 limits, a 64 character local part "
        f"and a 255 character domain), since a match straddling the cut can pull the window back "
        f"a second time"
    )
    print(
        f"  the closest witness this bench builds holds {straddle_held} of those {MAX_BUFFERED_CHARS} chars, "
        f"the worst case shape above fed in {CHUNK_SIZE} character chunks, so the last "
        f"{MAX_BUFFERED_CHARS - straddle_held} rest on reading the pattern lengths"
    )

    _write_report(first_token, by_length, by_shape, straddle_held)
    print(f"\nwrote {REPORT_PATH.relative_to(REPORT_PATH.parent.parent)}")


def _write_report(
    first_token: list[dict[str, Any]],
    by_length: list[dict[str, Any]],
    by_shape: list[dict[str, Any]],
    straddle_held: int,
) -> None:
    """Write every measurement to one JSON file, so no figure has to be typed by hand.

    The README figures are drawn from this file and the claim check reads it, which is what
    makes a stale number a diff rather than something a reader has to notice.
    """
    worst = max(first_token, key=lambda row: float(row["added_ms"]))
    report = {
        "source": "scripts/bench_stream.py",
        "chunk_size_chars": CHUNK_SIZE,
        "upstream_delay_ms": UPSTREAM_DELAY_SECONDS * 1000,
        "trials_per_shape": TRIAL_COUNT,
        "max_match_chars": MAX_MATCH_LENGTH,
        "max_buffered_chars": MAX_BUFFERED_CHARS,
        "first_token": first_token,
        "worst_first_token": worst,
        "held_by_length": by_length,
        "held_by_shape": by_shape,
        "straddling_worst_case_held_chars": straddle_held,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
