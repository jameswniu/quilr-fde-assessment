"""Task 3: redaction correctness, including patterns split across chunk boundaries."""

from __future__ import annotations

import re
import tracemalloc

import pytest

from task3_stream_guard.patterns import MAX_MATCH_LENGTH, luhn_ok
from task3_stream_guard.redactor import (
    CHUNK_SLICE_CHARS,
    MAX_BUFFERED_CHARS,
    StreamRedactor,
    redact_text,
)
from task3_stream_guard.upstream import chunk_text

REDACTED = "[REDACTED]"


def run_stream(chunks: list[str]) -> tuple[str, int]:
    """Feed chunks through a redactor and return the output plus the peak held size."""
    redactor = StreamRedactor()
    output = "".join(redactor.feed(chunk) for chunk in chunks)
    output += redactor.flush()
    return output, redactor.peak_buffered_chars


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("write to ada@example.com please", f"write to {REDACTED} please"),
        ("a.b+tag@sub.example.co.uk done", f"{REDACTED} done"),
        ("ssn 123-45-6789 filed", f"ssn {REDACTED} filed"),
        ("ssn 123 45 6789 filed", f"ssn {REDACTED} filed"),
        ("ssn 123456789 filed", f"ssn {REDACTED} filed"),
        ("card 4111111111111111 ok", f"card {REDACTED} ok"),
        ("card 4111-1111-1111-1111 ok", f"card {REDACTED} ok"),
        ("card 5500 0000 0000 0004 ok", f"card {REDACTED} ok"),
        ("nothing sensitive at all", "nothing sensitive at all"),
        ("version 1.2.3 build 42", "version 1.2.3 build 42"),
    ],
)
def test_whole_string_redaction(text: str, expected: str) -> None:
    assert redact_text(text) == expected


def test_pattern_split_across_two_chunks() -> None:
    output, _ = run_stream(["the billing contact is ada@exa", "mple.com, thanks"])
    assert output == f"the billing contact is {REDACTED}, thanks"


def test_pattern_split_across_three_chunks() -> None:
    output, _ = run_stream(["mail ada@ex", "am", "ple.com now"])
    assert output == f"mail {REDACTED} now"


def test_ssn_split_across_three_chunks() -> None:
    output, _ = run_stream(["ssn 123-", "45-", "6789 filed"])
    assert output == f"ssn {REDACTED} filed"


def test_card_split_across_four_chunks() -> None:
    output, _ = run_stream(["card 4111 ", "1111 ", "1111 ", "1111 end"])
    assert output == f"card {REDACTED} end"


@pytest.mark.parametrize("size", list(range(1, 25)))
def test_every_chunk_size_gives_the_same_answer(size: int) -> None:
    """A boundary can fall anywhere, so sweep it across every position."""
    text = "to ada@example.com ssn 123-45-6789 card 4111-1111-1111-1111 end"
    output, _ = run_stream(chunk_text(text, size))
    assert output == f"to {REDACTED} ssn {REDACTED} card {REDACTED} end"


def test_single_character_chunks() -> None:
    output, _ = run_stream(list("email ada@example.com end"))
    assert output == f"email {REDACTED} end"


def test_card_failing_luhn_is_left_alone() -> None:
    """4111111111111112 is a 16 digit number with a bad checksum, so it is not a card."""
    assert not luhn_ok("4111111111111112")
    output, _ = run_stream(["invoice 41111111", "11111112 is fine"])
    assert output == "invoice 4111111111111112 is fine"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("card 4111 1111 1111 1111 123 end", f"card {REDACTED} 123 end"),
        ("card 4111-1111-1111-1111-123 end", f"card {REDACTED}-123 end"),
        ("ref 123 4111 1111 1111 1111 end", f"ref 123 {REDACTED} end"),
        ("amex 3782 822463 10005 end", f"amex {REDACTED} end"),
    ],
)
def test_a_card_beside_other_digits_is_still_redacted(text: str, expected: str) -> None:
    """A card with a security code after it fails Luhn as one run, and must not slip through."""
    assert redact_text(text) == expected
    assert redact_text(text) == expected  # stable, no state carried between calls


def test_a_card_split_across_chunks_with_a_security_code_after_it() -> None:
    output, _ = run_stream(chunk_text("card 4111 1111 1111 1111 123 end", 5))
    assert output == f"card {REDACTED} 123 end"


def test_luhn_valid_card_next_to_an_invalid_one() -> None:
    output, _ = run_stream(chunk_text("good 4111111111111111 bad 4111111111111112 end", 7))
    assert output == f"good {REDACTED} bad 4111111111111112 end"


def test_ssn_ranges_that_are_never_issued_are_not_redacted() -> None:
    assert redact_text("ticket 000-12-3456 and 666-12-3456") == "ticket 000-12-3456 and 666-12-3456"


def test_adjacent_values_are_both_redacted() -> None:
    output, _ = run_stream(chunk_text("ada@example.com 123-45-6789", 4))
    assert output == f"{REDACTED} {REDACTED}"


def test_nothing_is_emitted_before_it_is_settled() -> None:
    """A partial email must never be forwarded, even if the stream ends mid value."""
    redactor = StreamRedactor()
    emitted = redactor.feed("write to ada@exa")
    assert "ada@exa" not in emitted
    assert redactor.feed("mple.com now") + redactor.flush() == f"{REDACTED} now"


def test_buffer_never_grows_with_response_length() -> None:
    """Peak held text is set by the longest token in the text, not by the response length."""
    filler = "the quick brown fox jumps over the lazy dog. "
    short = f"start {filler * 2} ada@example.com end"
    long = f"start {filler * 4000} ada@example.com end"
    longest_token = max(len(run) for run in re.findall(r"[A-Za-z0-9._%+@-]+", long))

    _, short_peak = run_stream(chunk_text(short, 16))
    long_output, long_peak = run_stream(chunk_text(long, 16))

    assert len(long) > 100 * len(short)
    assert short_peak <= longest_token
    assert long_peak <= longest_token
    assert long_peak <= MAX_BUFFERED_CHARS
    assert long_output.endswith(f"{REDACTED} end")
    assert "ada@example.com" not in long_output


def test_peak_memory_does_not_track_response_length() -> None:
    """Measured, not asserted: stream megabytes through and watch the heap stay in kilobytes.

    The chunks are generated lazily so the measurement covers the redactor rather than a test
    fixture that would itself be linear in the response length. The ceiling is far above what
    this actually peaks at, because the claim under test is the shape rather than a number.
    `make bench` prints the number across four response sizes.
    """
    chunk = "all clear here, nothing to see at all. "
    chunk_count = 200_000
    heap_ceiling_bytes = 64 * 1024

    redactor = StreamRedactor()
    tracemalloc.start()
    for _ in range(chunk_count):
        redactor.feed(chunk)  # output is dropped, as a forwarding proxy would
    redactor.feed(" ada@example.com")
    output = redactor.flush()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    streamed_bytes = chunk_count * len(chunk)
    assert streamed_bytes > 5_000_000
    assert peak < heap_ceiling_bytes, f"peaked at {peak} bytes on a {streamed_bytes} byte response"
    assert peak < streamed_bytes / 100
    assert output.endswith(REDACTED)


def test_held_text_is_bounded_even_by_one_enormous_token() -> None:
    """A pathological token longer than any pattern still cannot grow the buffer."""
    redactor = StreamRedactor()
    for chunk in chunk_text("x" * 50_000, 128):
        redactor.feed(chunk)
        assert redactor.buffered_chars <= MAX_BUFFERED_CHARS
    redactor.flush()
    assert redactor.peak_buffered_chars <= MAX_MATCH_LENGTH


@pytest.mark.parametrize("local_part_length", [1, 20, 41, 63, 64])
def test_emails_up_to_the_rfc_local_part_limit_are_redacted(local_part_length: int) -> None:
    """The pattern is bounded at the RFC 5321 limits, so no legal address falls outside it."""
    text = "write to " + "a" * local_part_length + "@example.com now"
    assert redact_text(text) == f"write to {REDACTED} now"


def test_a_deep_subdomain_chain_is_redacted_whole() -> None:
    assert redact_text("mail a@one.two.three.example.co.uk end") == f"mail {REDACTED} end"


def test_the_documented_boundary_is_an_illegal_address() -> None:
    """A 65 character local part is longer than RFC 5321 allows, and is not matched.

    Recorded here rather than hidden: the pattern is bounded on purpose, because an
    unbounded one would remove the guarantee that the hold window has a ceiling.
    """
    oversized = "a" * 65 + "@example.com"
    assert oversized in redact_text(f"write to {oversized} now")


def test_a_long_email_still_respects_the_buffer_ceiling() -> None:
    text = "contact " + "a" * 64 + "@" + ".".join(["label"] * 8) + ".example.com now"
    output, peak = run_stream(chunk_text(text, 7))
    assert output == f"contact {REDACTED} now"
    assert peak <= MAX_BUFFERED_CHARS


@pytest.mark.parametrize("domain", ["example.xn--p1ai", "shop.xn--fiqs8s", "a.xn--80asehdb"])
def test_internationalised_domains_are_redacted(domain: str) -> None:
    """An IDN reaches the wire as a punycode label carrying digits, which a letters only
    top level domain class would miss, and a missed address is a leak."""
    assert redact_text(f"write to user@{domain} now") == f"write to {REDACTED} now"


def test_one_enormous_chunk_is_still_scanned_in_bounded_slices() -> None:
    """An upstream that coalesces its whole answer into one chunk must not become one scan."""
    redactor = StreamRedactor()
    text = ("all clear here, nothing to see. " * 40_000) + " ada@example.com"
    output = redactor.feed(text) + redactor.flush()

    assert len(text) > 1_000_000
    assert redactor.peak_scanned_chars <= CHUNK_SLICE_CHARS + MAX_BUFFERED_CHARS
    assert redactor.peak_buffered_chars <= MAX_BUFFERED_CHARS
    assert output.endswith(f"{REDACTED}")
    assert "ada@example.com" not in output


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail first/last@example.com now", f"mail {REDACTED} now"),
        ("mail o'brien@example.com now", f"mail {REDACTED} now"),
        ("mail a+b=c@example.com now", f"mail {REDACTED} now"),
        ("mail user!tag@example.com now", f"mail {REDACTED} now"),
    ],
)
def test_rfc_local_part_characters_are_covered(text: str, expected: str) -> None:
    """Missing one of these redacts part of an address and leaves the rest readable."""
    assert redact_text(text) == expected


def test_ordinary_text_that_looks_a_little_like_an_address_is_left_alone() -> None:
    assert redact_text("version 1.2.3, cost 4.50, see https://example.com/a/b") == (
        "version 1.2.3, cost 4.50, see https://example.com/a/b"
    )


@pytest.mark.parametrize(
    "address",
    ["user@bücher.de", "josé@example.com", "用户@例え.jp", "user@example.xn--p1ai"],
)
def test_internationalised_addresses_are_redacted(address: str) -> None:
    """An assistant writes bücher.de, not its punycode form, so both have to be covered."""
    assert redact_text(f"write to {address} now") == f"write to {REDACTED} now"


def test_an_internationalised_address_split_across_chunks() -> None:
    output, _ = run_stream(["write to user@büc", "her.de now"])
    assert output == f"write to {REDACTED} now"


def test_ordinary_accented_prose_is_left_alone() -> None:
    assert redact_text("we met at the café before the crèche run") == "we met at the café before the crèche run"


@pytest.mark.parametrize(
    "text",
    [
        "order 4111111111111111123 shipped",
        "order 41111111111111111234 shipped",
    ],
    ids=["card-and-code-with-no-separator", "run-longer-than-nineteen-digits"],
)
def test_the_two_documented_card_residuals(text: str) -> None:
    """Pinned rather than hidden. Closing these costs more than it buys, see _redact_card_run.

    Scanning arbitrary windows would catch these and would also partly redact ordinary
    sixteen digit invoice numbers, because Luhn accepts roughly one random string in ten.
    """
    assert redact_text(text) == text


def test_the_precision_those_residuals_buy() -> None:
    """The same rule that leaves those two alone is what keeps ordinary numbers intact."""
    for number in ["4111111111111112", "9876543210987654", "1234567890123456"]:
        assert redact_text(f"invoice {number} paid") == f"invoice {number} paid"
