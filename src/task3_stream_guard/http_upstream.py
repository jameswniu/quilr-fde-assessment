"""A real HTTP provider behind the same protocol the scripted upstream implements.

Off by default. :func:`~task3_stream_guard.gateway.create_app` still builds the scripted
upstream, the suite never opens a socket, and nothing here reads the environment until a
caller asks it to. The file exists so that "has any of this ever spoken to a real provider"
is a command a reviewer can run rather than a claim they have to take on trust.

The wire shape is the OpenAI chat completions stream: ``POST {base}/chat/completions`` with
``"stream": true``, answered as server sent events whose data lines carry
``choices[0].delta.content``. Plenty of providers that are not OpenAI speak that same shape,
among them Azure OpenAI, Groq, Together, Fireworks, OpenRouter, vLLM and Ollama, so pointing
``LLM_BASE_URL`` at one of those is the whole change.

Two rules this file keeps. A key is never read at import time, so importing the module on a
machine with nothing exported is safe. And a key never reaches a log line or an error
message: the base URL is sanitised before it is printed, because a provider is free to carry
credentials in the userinfo or the query string.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from typing import Any, Final

import httpx

#: The three variables the live path reads. Task 4's real provider reads the same three
#: names on purpose, so one export covers both. The two tasks are separate deliverables in
#: the brief and neither package imports the other, which is why the names sit in both.
BASE_URL_VAR: Final = "LLM_BASE_URL"
MODEL_VAR: Final = "LLM_MODEL"
API_KEY_VAR: Final = "LLM_API_KEY"

#: Only the key has no default, because only the key cannot be guessed.
DEFAULT_BASE_URL: Final = "https://api.openai.com/v1"
DEFAULT_MODEL: Final = "gpt-4o-mini"
DEFAULT_TIMEOUT_SECONDS: Final = 60.0

#: The payload that closes an OpenAI style stream. It is not JSON, which is why it is matched
#: before anything tries to parse it.
DONE_PAYLOAD: Final = "[DONE]"


class MissingSetting(RuntimeError):
    """A variable the live path needs is not set.

    Carries the name so a command can print one clear line naming it instead of a traceback.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is not set, so there is no real provider to stream from.")
        self.name = name


class UpstreamProtocolError(RuntimeError):
    """The provider answered with something that is not an OpenAI style event stream."""


def completions_url(base_url: str) -> httpx.URL:
    """``{base}/chat/completions``, built on the path so a query string survives.

    A base URL is allowed to carry a query. Azure OpenAI puts an API version there and some
    gateways put a key there, and appending to the string would push the path inside the
    query instead of after it.
    """
    url = httpx.URL(base_url)
    return url.copy_with(path=f"{url.path.rstrip('/')}/chat/completions")


def sanitized_target(url: str) -> str:
    """Scheme, host, port and path only, which is the form safe to print.

    Userinfo and the query string are dropped rather than trimmed for tidiness. A provider is
    free to carry its key in either, and this string ends up in log lines and error messages.
    """
    parsed = httpx.URL(url)
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{parsed.host}{port}{parsed.path}"


def text_delta(payload: str) -> str:
    """The text one event carries, or an empty string when it carries none.

    An event with no text is ordinary: the opening event announces the role, and a closing
    event can report usage. Both arrive on the same stream as the words.

    Raises:
        UpstreamProtocolError: the data line was not JSON, or the provider reported an error
            part way through. Neither message quotes the line, because the line is model
            output and keeping model output out of logs is what this package is for.
    """
    if not payload:
        return ""
    try:
        event: Any = json.loads(payload)
    except json.JSONDecodeError as error:
        raise UpstreamProtocolError("a data line in the response was not JSON") from error
    if not isinstance(event, dict):
        return ""
    if isinstance(event.get("error"), dict):
        raise UpstreamProtocolError("the provider reported an error part way through the stream")
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    delta = choices[0].get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


async def iter_sse_deltas(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Yield the text deltas carried by an OpenAI style event stream.

    Framing follows the event stream spec rather than the happy path. A line opening with a
    colon is a comment, which some providers send as a keep alive. ``data`` lines gather until
    a blank line closes the event, and several of them in one event join with a newline. The
    ``[DONE]`` payload ends the stream, and anything after it is not read. A stream that stops
    without a closing blank line still delivers its last event.

    A body that arrives with content but no ``data`` field at all is not an event stream, and
    that raises. Without it a proxy answering 200 with a page of HTML, or a server ignoring
    ``"stream": true`` and answering with one JSON object, would read as an empty completion
    that succeeded.

    Raises:
        UpstreamProtocolError: the body carried content but no data line, or a data line that
            could not be read.
    """
    gathered: list[str] = []
    saw_content = False
    saw_data = False
    async for raw in lines:
        line = raw.rstrip("\r")
        if line.startswith(":"):
            saw_content = True
            continue
        if line:
            saw_content = True
            field, _, value = line.partition(":")
            if field == "data":
                saw_data = True
                gathered.append(value.removeprefix(" "))
            continue
        payload = "\n".join(gathered)
        gathered.clear()
        if payload == DONE_PAYLOAD:
            return
        if delta := text_delta(payload):
            yield delta
    trailing = "\n".join(gathered)
    if trailing != DONE_PAYLOAD and (delta := text_delta(trailing)):
        yield delta
    if saw_content and not saw_data:
        raise UpstreamProtocolError("the response carried no event stream data")


class HttpUpstream:
    """Streams a completion from a real provider, one text delta at a time.

    Args:
        base_url: everything before ``/chat/completions``.
        model: the model name sent in the body.
        api_key: sent as a bearer token, and never logged.
        timeout_seconds: applies to connecting and to the gap between chunks.
        transport: an httpx transport. This is how the tests stub the wire without a socket.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._api_key = api_key
        self._transport = transport

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> HttpUpstream:
        """Build one from the environment, read now rather than at import time.

        Raises:
            MissingSetting: the key variable is unset or empty.
        """
        env = os.environ if environ is None else environ
        api_key = env.get(API_KEY_VAR, "").strip()
        if not api_key:
            raise MissingSetting(API_KEY_VAR)
        return cls(
            env.get(BASE_URL_VAR, "").strip() or DEFAULT_BASE_URL,
            env.get(MODEL_VAR, "").strip() or DEFAULT_MODEL,
            api_key,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    @property
    def endpoint(self) -> str:
        """The URL this posts to, credentials and all."""
        return str(completions_url(self.base_url))

    @property
    def target(self) -> str:
        """The same URL with anything credential shaped removed, which is the printable one."""
        return sanitized_target(self.endpoint)

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """Yield text deltas as the provider produces them.

        Raises:
            UpstreamProtocolError: the provider answered with a status other than 200, or with
                a body that is not an event stream.
        """
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        headers = {
            "authorization": f"Bearer {self._api_key}",
            "accept": "text/event-stream",
            "content-type": "application/json",
        }
        async with (
            httpx.AsyncClient(transport=self._transport, timeout=self.timeout_seconds) as client,
            client.stream("POST", self.endpoint, json=body, headers=headers) as response,
        ):
            if response.status_code != httpx.codes.OK:
                # Drain first. The body may carry the provider's own explanation, and it stays
                # out of the message on purpose, since a rejected request is echoed back by
                # some providers along with the header that carried the key.
                await response.aread()
                raise UpstreamProtocolError(f"{self.target} answered {response.status_code}")
            async for delta in iter_sse_deltas(response.aiter_lines()):
                yield delta
