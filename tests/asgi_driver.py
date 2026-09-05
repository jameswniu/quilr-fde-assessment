"""Drive an ASGI app directly, one response chunk at a time.

httpx's ASGITransport joins the whole response body before handing it back, which hides
exactly the property Task 3 is about. Talking to the app through the raw ASGI interface
keeps each ``http.response.body`` message separate and lets a test apply real back
pressure by being slow inside ``send``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

OnChunk = Callable[[bytes], Awaitable[None]]


@dataclass
class AsgiResult:
    """What the app sent back."""

    status: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    chunks: list[bytes] = field(default_factory=list)

    @property
    def body(self) -> str:
        return b"".join(self.chunks).decode()

    def json(self) -> Any:
        return json.loads(self.body)


async def post(
    app: Callable[..., Awaitable[None]],
    path: str,
    payload: Any = None,
    *,
    raw_body: bytes | None = None,
    on_chunk: OnChunk | None = None,
) -> AsgiResult:
    """POST to an ASGI app and collect the response chunks in order."""
    body = raw_body if raw_body is not None else json.dumps(payload).encode()
    scope = {
        "type": "http",
        # spec_version 2.4 tells Starlette the server reports disconnects through
        # send() rather than a parallel receive() task, which keeps this driver simple.
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    result = AsgiResult()
    request_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            result.status = message["status"]
            result.headers = {k.decode(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            part = message.get("body", b"")
            if part:
                result.chunks.append(part)
                if on_chunk is not None:
                    await on_chunk(part)

    await app(scope, receive, send)
    return result
