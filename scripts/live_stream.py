"""Stream one completion from a real provider through the task 3 guardrail.

    make run-live

The suite never runs this. It exists so the answer to "has any of this spoken to a real
provider" is a command a reviewer runs rather than a claim they take on trust. Export
``LLM_API_KEY`` and it streams. Leave it unset and it says which variable is missing and
stops, rather than sitting there looking like it is working.

An optional argument replaces the prompt:

    uv run python scripts/live_stream.py "write two sentences about anything"
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from typing import Any, Final

import httpx

from task3_stream_guard.gateway import create_app
from task3_stream_guard.http_upstream import (
    API_KEY_VAR,
    BASE_URL_VAR,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    MODEL_VAR,
    HttpUpstream,
    MissingSetting,
    UpstreamProtocolError,
)

#: Three public test values, so the terminal shows three redactions rather than a promise of
#: them. The card is the one every payment vendor publishes for exactly this.
DEFAULT_PROMPT: Final = (
    "Reply with this sentence and nothing else. "
    "The billing contact is ada@example.com, the taxpayer id is 123-45-6789, "
    "and the card on file is 4111 1111 1111 1111."
)


async def drive(app: Callable[..., Awaitable[None]], prompt: str) -> int:
    """POST to the gateway and print each response chunk the moment it arrives.

    Raw ASGI rather than httpx's ASGI transport, which joins the whole body before handing it
    back. That would hide the one property this command exists to show.
    """
    body = json.dumps({"prompt": prompt}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/generate",
        "raw_path": b"/v1/generate",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 50000),
        "server": ("localhost", 80),
    }
    status = 0
    request_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])
        elif message["type"] == "http.response.body" and message.get("body"):
            sys.stdout.write(message["body"].decode())
            sys.stdout.flush()

    await app(scope, receive, send)
    return status


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # httpx logs the request URL at INFO, and a base URL is allowed to carry a key in its
    # query string, so that logger stays quiet and the sanitised target below is what prints.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        upstream = HttpUpstream.from_env()
    except MissingSetting as missing:
        print(missing)
        print(f"  export {API_KEY_VAR}=...   the only one without a default")
        print(f"  export {BASE_URL_VAR}=...  optional, defaults to {DEFAULT_BASE_URL}")
        print(f"  export {MODEL_VAR}=...     optional, defaults to {DEFAULT_MODEL}")
        return 2

    prompt = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROMPT
    print(f"streaming from {upstream.target} using {upstream.model}\n")
    try:
        status = asyncio.run(drive(create_app(upstream), prompt))
    except UpstreamProtocolError as error:
        print(f"\n{error}")
        return 1
    except httpx.HTTPError as error:
        print(f"\nthe provider could not be reached, {type(error).__name__}")
        return 1
    print(f"\n\nstatus {status}, and every value above went through the same redactor the suite tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
