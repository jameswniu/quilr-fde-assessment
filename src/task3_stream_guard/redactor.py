"""Redact sensitive values from a text stream without buffering the whole response.

The hard case is a value split across chunk boundaries, for example ``ada@exa`` arriving
in one chunk and ``mple.com`` in the next. The redactor solves it by emitting only the
part of the buffer that can no longer change, and holding the tail.

How much tail. A match is at most :data:`~task3_stream_guard.patterns.MAX_MATCH_LENGTH`
characters long, so anything further back than that is settled. Inside that window the
cut is moved to the nearest point that is not in the middle of a token, so the redactor
usually holds only the few characters of the word being typed, which keeps time to first
token close to the upstream's own. The buffer never exceeds twice the longest pattern,
whatever the length of the response.
"""

from __future__ import annotations

from typing import Final

from task3_stream_guard.patterns import MAX_MATCH_LENGTH, PATTERN, is_constituent, replacement_for

#: Hard ceiling on held text. The extra window covers a match straddling the cut point.
MAX_BUFFERED_CHARS: Final = 2 * MAX_MATCH_LENGTH

#: An upstream chunk is not a safety boundary. A provider that coalesces its stream, or a
#: proxy that buffers it, can hand over one very large chunk, so a chunk bigger than this is
#: fed through in slices and the text ever scanned at once stays bounded either way.
CHUNK_SLICE_CHARS: Final = 4096


def _hold_start(text: str, limit: int) -> int:
    """Walk back from the end of ``text`` to the first point safe to cut at.

    Safe means not inside a token that a pattern could still be matching. The walk stops
    at ``limit``, so the returned index is never further back than the caller allows.
    """
    index = len(text)
    while index > limit:
        char = text[index - 1]
        if is_constituent(char):
            index -= 1
            continue
        # A space only counts as part of a token when it sits between digits, which is
        # how grouped card numbers and spaced SSNs are written. Prose spaces stop here.
        before_is_digit = index >= 2 and text[index - 2].isdigit()
        after_is_digit = index == len(text) or text[index].isdigit()
        if char == " " and before_is_digit and after_is_digit:
            index -= 1
            continue
        break
    return index


class StreamRedactor:
    """Feed it stream chunks, get back redacted text that is safe to forward."""

    def __init__(self) -> None:
        self._pending = ""
        self.peak_buffered_chars = 0
        self.peak_scanned_chars = 0

    @property
    def buffered_chars(self) -> int:
        """How much text is being held back right now."""
        return len(self._pending)

    def feed(self, chunk: str) -> str:
        """Take one upstream chunk and return the text that is now safe to send.

        The returned string is as long as the safe part of the chunk, which is the caller's
        own data coming back. What stays bounded regardless of chunk size is the held state
        and the window scanned in one pass, which is what ``peak_scanned_chars`` records.
        """
        if len(chunk) <= CHUNK_SLICE_CHARS:
            return self._feed_slice(chunk)
        return "".join(
            self._feed_slice(chunk[index : index + CHUNK_SLICE_CHARS])
            for index in range(0, len(chunk), CHUNK_SLICE_CHARS)
        )

    def _feed_slice(self, text: str) -> str:
        self._pending += text
        return self._emit(final=False)

    def flush(self) -> str:
        """Called once the upstream is done. Returns whatever is still held."""
        return self._emit(final=True)

    def _emit(self, *, final: bool) -> str:
        buffer = self._pending
        self.peak_scanned_chars = max(self.peak_scanned_chars, len(buffer))
        cut = len(buffer) if final else _hold_start(buffer, max(0, len(buffer) - MAX_MATCH_LENGTH))

        parts: list[str] = []
        position = 0
        for match in PATTERN.finditer(buffer):
            if match.start() >= cut:
                break
            if match.end() > cut:
                # The match runs into the held tail and could still grow. Hold all of it.
                cut = match.start()
                break
            replacement = replacement_for(match)
            if replacement == match.group(0):
                continue  # nothing sensitive here, the text is copied by the slice below
            parts.append(buffer[position : match.start()])
            parts.append(replacement)
            position = match.end()
        parts.append(buffer[position:cut])

        self._pending = buffer[cut:]
        self.peak_buffered_chars = max(self.peak_buffered_chars, len(self._pending))
        return "".join(parts)


def redact_text(text: str) -> str:
    """Redact a complete string. Used for tests and for comparing against the stream path."""
    redactor = StreamRedactor()
    return redactor.feed(text) + redactor.flush()
