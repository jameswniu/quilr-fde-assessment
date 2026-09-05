"""An LLM gateway endpoint that redacts sensitive values while the response streams.

``POST /v1/generate`` with ``{"prompt": "..."}`` returns ``text/plain`` streamed back as
the upstream produces it. Chunks are pushed through :class:`~task3_stream_guard.redactor.StreamRedactor`,
so the client sees redacted text as it arrives rather than after the response completes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from task3_stream_guard.redactor import StreamRedactor
from task3_stream_guard.upstream import DEMO_RESPONSE, ScriptedUpstream, Upstream, chunk_text

logger = logging.getLogger("task3_stream_guard")


async def redacted_stream(upstream: Upstream, prompt: str) -> AsyncIterator[str]:
    """Pull from the upstream and yield redacted text.

    Pull based on purpose: the next upstream chunk is only requested once the client has
    taken the previous one, so a slow reader slows the whole chain instead of filling a
    buffer in the gateway.
    """
    redactor = StreamRedactor()
    async for chunk in upstream.stream(prompt):
        safe = redactor.feed(chunk)
        if safe:
            yield safe
    tail = redactor.flush()
    if tail:
        yield tail
    logger.info("stream complete, peak held %d chars", redactor.peak_buffered_chars)


async def _generate(request: Request) -> Response:
    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        return JSONResponse({"error": {"code": "invalid_request", "message": "Body is not valid JSON"}}, 400)
    if not isinstance(payload, dict) or not isinstance(payload.get("prompt"), str) or not payload["prompt"]:
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": 'Field "prompt" must be a non-empty string'}}, 400
        )

    upstream: Upstream = request.app.state.upstream
    return StreamingResponse(
        redacted_stream(upstream, payload["prompt"]),
        media_type="text/plain; charset=utf-8",
        headers={"x-guardrail": "pii-redaction"},
    )


def create_app(upstream: Upstream | None = None) -> Starlette:
    """Build the gateway. Without an upstream it serves a fixed demo response."""
    app = Starlette(routes=[Route("/v1/generate", _generate, methods=["POST"])])
    app.state.upstream = upstream or ScriptedUpstream(chunk_text(DEMO_RESPONSE, 12), delay_seconds=0.02)
    return app
