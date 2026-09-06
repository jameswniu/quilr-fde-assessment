"""A stand in for the LLM provider, so the gateway and its tests need no network or key.

Deliberate, not a limitation. Every test in the suite runs against the scripted upstream
below, which is what keeps the suite deterministic and free. The real one lives beside it in
``http_upstream.py``, behind the same protocol, and ``make run-live`` is how it gets used.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Final, Protocol


class Upstream(Protocol):
    """Anything that can stream a completion back one chunk at a time."""

    def stream(self, prompt: str) -> AsyncIterator[str]: ...


class ScriptedUpstream:
    """Yields a fixed list of chunks, optionally with a delay between them.

    ``chunks_yielded`` is how a test proves the gateway is not racing ahead of the client,
    and ``last_prompt`` is how it proves the prompt reached the provider unchanged.
    """

    def __init__(self, chunks: Sequence[str], *, delay_seconds: float = 0.0) -> None:
        self.chunks = list(chunks)
        self.delay_seconds = delay_seconds
        self.chunks_yielded = 0
        self.last_prompt: str | None = None

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        self.last_prompt = prompt
        for chunk in self.chunks:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            self.chunks_yielded += 1
            yield chunk


def chunk_text(text: str, size: int) -> list[str]:
    """Split text into fixed size pieces, which is how a token stream tends to arrive."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [text[index : index + size] for index in range(0, len(text), size)]


#: The reply the demo server streams back, deliberately full of things that must not leak.
DEMO_RESPONSE: Final = (
    "Here is the account summary you asked for. The billing contact is ada@example.com "
    "and the backup contact is grace.hopper+billing@mail.example.co.uk. The taxpayer on "
    "file is recorded with SSN 123-45-6789 and the card we have on record is "
    "4111 1111 1111 1111 with a second card 5500-0000-0000-0004. Invoice 4111111111111112 "
    "is not a card number, it fails the checksum, so it is left alone. Nothing else in "
    "this reply is sensitive."
)
