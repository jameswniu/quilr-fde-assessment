"""Task 4: the live provider maps HTTP answers onto the errors the router routes around.

Nothing here opens a socket. Answers come from an httpx transport that replies from memory,
which is what keeps the suite at no network and no key while still exercising the code that
would talk to a real provider.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from task4_model_router.http_provider import (
    API_KEY_VAR,
    BASE_URL_VAR,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    MODEL_VAR,
    HttpProvider,
    MissingSetting,
    completions_url,
    message_content,
    retry_after_seconds,
)
from task4_model_router.providers import (
    CompletionRequest,
    Provider,
    ProviderRateLimited,
    ProviderUnavailable,
    ScriptedProvider,
)
from task4_model_router.rate_limiter import SlidingWindowRateLimiter
from task4_model_router.router import ModelRouter
from tests.import_probe import import_without_environment

KEY = "sk-not-a-real-key-0123456789"
REQUEST = CompletionRequest(api_key="tenant-key-abc123", prompt="summarise this quarter")


def answering(status: int, payload: object = None, *, headers: dict[str, str] | None = None) -> httpx.MockTransport:
    """A transport that answers every request the same way, from memory."""
    body = "" if payload is None else json.dumps(payload)
    return httpx.MockTransport(lambda _request: httpx.Response(status, text=body, headers=headers))


def completion(text: str) -> dict[str, object]:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def provider(transport: httpx.MockTransport, name: str = "primary") -> HttpProvider:
    return HttpProvider(name, "some-model", "https://provider.test/v1", KEY, transport=transport)


async def test_a_completion_comes_back_as_text() -> None:
    assert await provider(answering(200, completion("a real answer"))).complete(REQUEST) == "a real answer"


async def test_the_request_carries_the_model_the_prompt_and_the_output_budget() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=json.dumps(completion("ok")))

    live = provider(httpx.MockTransport(handler))
    await live.complete(CompletionRequest(api_key="tenant-key-abc123", prompt="hello", max_output_tokens=64))

    request = seen[0]
    assert str(request.url) == "https://provider.test/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.read())
    assert body["model"] == "some-model"
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["max_tokens"] == 64
    assert KEY not in request.read().decode(), "the key belongs in the header, not the payload"


async def test_a_zero_output_budget_sends_no_ceiling_at_all() -> None:
    """Providers reject max_tokens of zero, and zero means unset rather than none allowed."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=json.dumps(completion("ok")))

    live = provider(httpx.MockTransport(handler))
    await live.complete(CompletionRequest(api_key="tenant-key-abc123", prompt="hello", max_output_tokens=0))
    assert "max_tokens" not in json.loads(seen[0].read())


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://api.openai.com/v1", "https://api.openai.com/v1/chat/completions"),
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
        return httpx.Response(200, text=json.dumps(completion("ok")))

    live = HttpProvider(
        "primary",
        "some-model",
        "https://host/openai/deployments/gpt-4o?api-version=2026-01-01",
        KEY,
        transport=httpx.MockTransport(handler),
    )
    await live.complete(REQUEST)
    assert str(seen[0].url) == "https://host/openai/deployments/gpt-4o/chat/completions?api-version=2026-01-01"


async def test_a_429_becomes_the_error_the_router_fails_over_on() -> None:
    with pytest.raises(ProviderRateLimited) as raised:
        await provider(answering(429, headers={"retry-after": "30"})).complete(REQUEST)
    assert raised.value.provider == "primary"
    assert raised.value.retry_after_seconds == 30.0


@pytest.mark.parametrize("header", [None, "Wed, 21 Oct 2026 07:28:00 GMT", ""])
def test_a_retry_after_this_code_cannot_read_becomes_nothing(header: str | None) -> None:
    assert retry_after_seconds(header) is None


async def test_a_500_becomes_unavailable_and_names_no_url() -> None:
    with pytest.raises(ProviderUnavailable) as raised:
        await provider(answering(500, {"error": "internal"})).complete(REQUEST)
    assert "500" in str(raised.value)
    assert "provider.test" not in str(raised.value)
    assert KEY not in str(raised.value)


async def test_a_body_that_is_not_json_becomes_unavailable() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text="<html>hello</html>"))
    with pytest.raises(ProviderUnavailable) as raised:
        await provider(transport).complete(REQUEST)
    assert "not JSON" in str(raised.value)


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"message": {}}]}, {"choices": [{}]}, []])
def test_an_answer_with_no_message_text_becomes_unavailable(payload: object) -> None:
    with pytest.raises(ProviderUnavailable):
        message_content(payload, "primary")


async def test_a_transport_failure_becomes_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(ProviderUnavailable) as raised:
        await provider(httpx.MockTransport(handler)).complete(REQUEST)
    assert "could not be reached" in str(raised.value)


def test_from_env_names_the_missing_variable() -> None:
    with pytest.raises(MissingSetting) as raised:
        HttpProvider.from_env("primary", {})
    assert raised.value.name == API_KEY_VAR
    assert API_KEY_VAR in str(raised.value)


def test_a_blank_key_counts_as_missing() -> None:
    with pytest.raises(MissingSetting):
        HttpProvider.from_env("primary", {API_KEY_VAR: "   "})


def test_from_env_defaults_the_base_url_and_the_model() -> None:
    live = HttpProvider.from_env("primary", {API_KEY_VAR: KEY})
    assert live.base_url == DEFAULT_BASE_URL
    assert live.model == DEFAULT_MODEL
    assert live.name == "primary"


def test_from_env_takes_the_base_url_and_the_model_when_they_are_set() -> None:
    live = HttpProvider.from_env(
        "secondary", {API_KEY_VAR: KEY, BASE_URL_VAR: "http://localhost:11434/v1/", MODEL_VAR: "llama3.1"}
    )
    assert live.base_url == "http://localhost:11434/v1"
    assert live.model == "llama3.1"


def test_importing_the_module_reads_nothing_from_the_environment() -> None:
    """A key read at import time would be read on every `make test`, on every machine."""
    probe = import_without_environment("task4_model_router.http_provider")
    assert probe.returncode == 0, probe.stderr


def test_the_live_provider_satisfies_the_protocol_the_router_asks_for() -> None:
    live: Provider = provider(answering(200, completion("ok")))
    assert (live.name, live.model) == ("primary", "some-model")


async def test_the_router_fails_over_from_a_live_primary_that_is_throttled(tmp_path: Path) -> None:
    """The mapping earns its place here: a 429 off the wire drives the brief's own failover."""
    limiter = SlidingWindowRateLimiter(tmp_path / "limits.sqlite3", limit_tokens=50_000)
    backup = ScriptedProvider("secondary", "backup-model", reply="from the secondary")
    router = ModelRouter(provider(answering(429)), backup, limiter)

    result = await router.complete(REQUEST)

    assert (result.text, result.provider, result.failed_over) == ("from the secondary", "secondary", True)
