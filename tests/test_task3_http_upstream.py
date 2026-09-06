"""Task 3: the live provider parses server sent events, and never leaks the key.

Nothing here opens a socket. The event stream is fed in as lines, or served by an httpx
transport that answers from memory, which is what keeps the suite at no network and no key
while still exercising the code that would talk to a real provider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest

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
    completions_url,
    iter_sse_deltas,
    sanitized_target,
    text_delta,
)
from task3_stream_guard.upstream import Upstream
from tests import asgi_driver
from tests.import_probe import import_without_environment

KEY = "sk-not-a-real-key-0123456789"


def delta_event(text: str) -> str:
    return 'data: {"choices":[{"delta":{"content":"' + text + '"}}]}'


async def lines_of(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


async def collect(lines: AsyncIterator[str]) -> str:
    return "".join([delta async for delta in iter_sse_deltas(lines)])


def sse_transport(body: str, status: int = 200) -> httpx.MockTransport:
    """An httpx transport that answers every request with one canned event stream."""
    return httpx.MockTransport(
        lambda _request: httpx.Response(status, text=body, headers={"content-type": "text/event-stream"})
    )


async def test_deltas_arrive_in_order() -> None:
    text = await collect(lines_of(delta_event("Hello"), "", delta_event(" world"), "", "data: [DONE]", ""))
    assert text == "Hello world"


async def test_the_opening_role_event_and_a_usage_tail_carry_no_text() -> None:
    text = await collect(
        lines_of(
            'data: {"choices":[{"delta":{"role":"assistant"}}]}',
            "",
            delta_event("hi"),
            "",
            'data: {"choices":[],"usage":{"total_tokens":9}}',
            "",
            "data: [DONE]",
            "",
        )
    )
    assert text == "hi"


async def test_nothing_after_done_is_read() -> None:
    text = await collect(lines_of(delta_event("kept"), "", "data: [DONE]", "", delta_event("dropped"), ""))
    assert text == "kept"


async def test_a_comment_line_is_a_keep_alive() -> None:
    text = await collect(lines_of(": ping", "", delta_event("still here"), "", "data: [DONE]", ""))
    assert text == "still here"


async def test_two_data_lines_in_one_event_join_with_a_newline() -> None:
    """The spec allows a split payload. OpenAI does not send one, and a parser that assumed
    otherwise would break on the first provider that does."""
    text = await collect(lines_of('data: {"choices":[{"delta":', 'data: {"content":"split"}}]}', ""))
    assert text == "split"


async def test_an_event_with_no_trailing_blank_line_is_still_delivered() -> None:
    assert await collect(lines_of(delta_event("last"))) == "last"


async def test_a_carriage_return_at_the_end_of_a_line_is_ignored() -> None:
    assert await collect(lines_of(delta_event("crlf") + "\r", "\r")) == "crlf"


async def test_a_field_that_is_not_data_is_ignored() -> None:
    text = await collect(lines_of("event: message", "id: 7", delta_event("only this"), ""))
    assert text == "only this"


async def test_a_data_line_that_is_not_json_is_refused() -> None:
    with pytest.raises(UpstreamProtocolError) as raised:
        await collect(lines_of("data: <html>gateway timeout</html>", ""))
    assert "not JSON" in str(raised.value)
    assert "gateway timeout" not in str(raised.value), "model output must not reach the message"


async def test_an_error_reported_part_way_through_is_refused() -> None:
    with pytest.raises(UpstreamProtocolError):
        await collect(lines_of(delta_event("start"), "", 'data: {"error":{"message":"boom"}}', ""))


@pytest.mark.parametrize(
    "payload",
    ['{"choices":"not a list"}', '{"choices":[]}', '{"choices":[{"delta":{"content":42}}]}', "[]", '{"choices":[7]}'],
)
def test_a_shape_the_parser_does_not_recognise_yields_no_text(payload: str) -> None:
    assert text_delta(payload) == ""


async def test_a_body_with_no_data_line_is_not_an_event_stream() -> None:
    """A proxy answering 200 with a page, or a server ignoring the stream flag, must not read
    as an empty completion that succeeded."""
    with pytest.raises(UpstreamProtocolError) as raised:
        await collect(lines_of("<html>", "  <body>service unavailable</body>", "</html>"))
    assert "no event stream data" in str(raised.value)


async def test_a_whole_json_answer_instead_of_a_stream_is_refused() -> None:
    with pytest.raises(UpstreamProtocolError):
        await collect(lines_of('{"choices":[{"message":{"content":"not a stream"}}]}'))


async def test_an_empty_body_is_not_an_error() -> None:
    """Nothing arrived, which the gateway forwards as nothing. Only content without data lines
    is a protocol failure."""
    assert await collect(lines_of()) == ""


async def test_a_stream_that_only_says_done_is_not_an_error() -> None:
    assert await collect(lines_of("data: [DONE]", "")) == ""


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://api.openai.com/v1", "https://api.openai.com/v1/chat/completions"),
        ("https://api.openai.com/v1/", "https://api.openai.com/v1/chat/completions"),
        ("https://api.openai.com", "https://api.openai.com/chat/completions"),
        (
            "https://host/openai/deployments/gpt-4o?api-version=2026-01-01",
            "https://host/openai/deployments/gpt-4o/chat/completions?api-version=2026-01-01",
        ),
    ],
)
def test_the_endpoint_is_built_on_the_path_so_a_query_string_survives(base: str, expected: str) -> None:
    """String concatenation would push /chat/completions inside the query and send the request
    to the base path instead."""
    assert str(completions_url(base)) == expected


async def test_a_query_string_on_the_base_url_reaches_the_provider() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="data: [DONE]\n\n")

    upstream = HttpUpstream(
        "https://host/openai/deployments/gpt-4o?api-version=2026-01-01",
        "some-model",
        KEY,
        transport=httpx.MockTransport(handler),
    )
    assert [chunk async for chunk in upstream.stream("hello")] == []
    assert str(seen[0].url) == "https://host/openai/deployments/gpt-4o/chat/completions?api-version=2026-01-01"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.openai.com/v1/chat/completions", "https://api.openai.com/v1/chat/completions"),
        ("https://host/v1/chat/completions?key=sk-secret", "https://host/v1/chat/completions"),
        ("https://user:sk-secret@host/v1/chat/completions", "https://host/v1/chat/completions"),
        ("http://localhost:11434/v1/chat/completions", "http://localhost:11434/v1/chat/completions"),
    ],
)
def test_the_printable_target_drops_userinfo_and_query_string(url: str, expected: str) -> None:
    assert sanitized_target(url) == expected
    assert "sk-secret" not in sanitized_target(url)


def test_from_env_names_the_missing_variable() -> None:
    with pytest.raises(MissingSetting) as raised:
        HttpUpstream.from_env({})
    assert raised.value.name == API_KEY_VAR
    assert API_KEY_VAR in str(raised.value)


def test_a_blank_key_counts_as_missing() -> None:
    with pytest.raises(MissingSetting):
        HttpUpstream.from_env({API_KEY_VAR: "   "})


def test_from_env_defaults_the_base_url_and_the_model() -> None:
    upstream = HttpUpstream.from_env({API_KEY_VAR: KEY})
    assert upstream.base_url == DEFAULT_BASE_URL
    assert upstream.model == DEFAULT_MODEL


def test_from_env_takes_the_base_url_and_the_model_when_they_are_set() -> None:
    upstream = HttpUpstream.from_env(
        {API_KEY_VAR: KEY, BASE_URL_VAR: "http://localhost:11434/v1/", MODEL_VAR: "llama3.1"}
    )
    assert upstream.endpoint == "http://localhost:11434/v1/chat/completions"
    assert upstream.model == "llama3.1"


def test_importing_the_module_reads_nothing_from_the_environment() -> None:
    """A key read at import time would be read on every `make test`, on every machine."""
    probe = import_without_environment("task3_stream_guard.http_upstream")
    assert probe.returncode == 0, probe.stderr


def test_the_live_upstream_satisfies_the_protocol_the_gateway_asks_for() -> None:
    upstream: Upstream = HttpUpstream(DEFAULT_BASE_URL, DEFAULT_MODEL, KEY)
    assert callable(upstream.stream)


async def test_the_request_carries_the_model_the_prompt_and_the_stream_flag() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="data: [DONE]\n\n")

    upstream = HttpUpstream("https://provider.test/v1", "some-model", KEY, transport=httpx.MockTransport(handler))
    assert [chunk async for chunk in upstream.stream("summarise the account")] == []

    request = seen[0]
    assert str(request.url) == "https://provider.test/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.read())
    assert body["stream"] is True
    assert body["model"] == "some-model"
    assert body["messages"] == [{"role": "user", "content": "summarise the account"}]
    assert KEY not in request.read().decode(), "the key belongs in the header, not the payload"


async def test_a_refused_request_names_the_status_and_not_the_key() -> None:
    upstream = HttpUpstream(
        f"https://user:{KEY}@provider.test/v1", DEFAULT_MODEL, KEY, transport=sse_transport("no", status=401)
    )
    with pytest.raises(UpstreamProtocolError) as raised:
        [chunk async for chunk in upstream.stream("hello")]
    assert "401" in str(raised.value)
    assert KEY not in str(raised.value)


async def test_the_gateway_redacts_a_value_split_across_two_deltas_from_the_live_upstream() -> None:
    """The whole path in one test: event stream in, redacted stream out, no socket."""
    stream = "".join(
        f"{delta_event(part)}\n\n"
        for part in ["The billing contact is ada@", "example.com and the card is 4111 1111 ", "1111 1111 today."]
    )
    upstream = HttpUpstream(
        "https://provider.test/v1", DEFAULT_MODEL, KEY, transport=sse_transport(stream + "data: [DONE]\n\n")
    )

    result = await asgi_driver.post(create_app(upstream), "/v1/generate", {"prompt": "summarise"})

    assert result.status == 200
    assert "ada@example.com" not in result.body
    assert "4111 1111 1111 1111" not in result.body
    assert result.body.count("[REDACTED]") == 2
    assert result.body.endswith("today.")


async def test_the_default_app_is_still_the_scripted_upstream() -> None:
    """The live path is opt in. A default `create_app()` must never reach for a key."""
    assert not isinstance(create_app().state.upstream, HttpUpstream)
