"""A real model provider behind the same protocol the scripted one implements.

Off by default. The demo in ``__main__`` still wires two
:class:`~task4_model_router.providers.ScriptedProvider` instances, the suite never opens a
socket, and nothing here reads the environment until a caller asks it to.

The wire shape is the OpenAI chat completions call: ``POST {base}/chat/completions``,
answered with ``choices[0].message.content``. Plenty of providers that are not OpenAI speak
that same shape, among them Azure OpenAI, Groq, Together, Fireworks, OpenRouter, vLLM and
Ollama, so pointing ``LLM_BASE_URL`` at one of those is the whole change. Nothing streams
here. The router asks for a whole completion, and the streaming half of the same shape is
task 3's.

The failure mapping is the part the router cares about. A 429 becomes
:class:`~task4_model_router.providers.ProviderRateLimited`, so failover fires on the signal
the brief names, and everything else becomes
:class:`~task4_model_router.providers.ProviderUnavailable`. A key is never read at import
time, and no message this module raises carries a key or a URL.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Final

import httpx

from task4_model_router.providers import CompletionRequest, ProviderRateLimited, ProviderUnavailable

#: The same three names task 3's live upstream reads, so one export covers both. The two
#: tasks are separate deliverables in the brief and neither package imports the other, which
#: is why the names sit in both.
BASE_URL_VAR: Final = "LLM_BASE_URL"
MODEL_VAR: Final = "LLM_MODEL"
API_KEY_VAR: Final = "LLM_API_KEY"

#: Only the key has no default, because only the key cannot be guessed.
DEFAULT_BASE_URL: Final = "https://api.openai.com/v1"
DEFAULT_MODEL: Final = "gpt-4o-mini"

#: A backstop for a connection that never answers. The router's own timeout is shorter and is
#: the one that drives failover, so this only matters when a socket hangs open past it.
DEFAULT_TIMEOUT_SECONDS: Final = 60.0


class MissingSetting(RuntimeError):
    """A variable the live path needs is not set.

    Carries the name so a command can print one clear line naming it instead of a traceback.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is not set, so there is no real provider to call.")
        self.name = name


def completions_url(base_url: str) -> httpx.URL:
    """``{base}/chat/completions``, built on the path so a query string survives.

    A base URL is allowed to carry a query. Azure OpenAI puts an API version there and some
    gateways put a key there, and appending to the string would push the path inside the
    query instead of after it.
    """
    url = httpx.URL(base_url)
    return url.copy_with(path=f"{url.path.rstrip('/')}/chat/completions")


def retry_after_seconds(header: str | None) -> float | None:
    """A ``Retry-After`` header as seconds, when it is the numeric form.

    The spec also allows an HTTP date. Nothing speaking this shape sends one, and guessing a
    number from a header this code cannot read would be worse than saying nothing, so an
    unreadable header becomes ``None`` and the caller falls back to its own behaviour.
    """
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        return None


def message_content(payload: Any, provider: str) -> str:
    """The text of the first choice.

    Raises:
        ProviderUnavailable: the answer parsed but carried no message text. That is a provider
            failure the router should fail over on, rather than a crash it cannot route.
    """
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return str(message["content"])
    raise ProviderUnavailable(f"{provider} answered with no message content")


class HttpProvider:
    """A provider that calls a real HTTP endpoint.

    Args:
        name: the provider name reported on the result.
        model: the model name sent in the body and reported on the result.
        base_url: everything before ``/chat/completions``.
        api_key: sent as a bearer token, and never logged.
        timeout_seconds: a socket backstop under the router's own timeout.
        transport: an httpx transport. This is how the tests stub the wire without a socket.
    """

    def __init__(
        self,
        name: str,
        model: str,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._api_key = api_key
        self._transport = transport

    @classmethod
    def from_env(
        cls,
        name: str,
        environ: Mapping[str, str] | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> HttpProvider:
        """Build one from the environment, read now rather than at import time.

        Only one endpoint lives in those variables, and real failover needs two, so a second
        live provider is constructed directly with its own base URL and key.

        Raises:
            MissingSetting: the key variable is unset or empty.
        """
        env = os.environ if environ is None else environ
        api_key = env.get(API_KEY_VAR, "").strip()
        if not api_key:
            raise MissingSetting(API_KEY_VAR)
        return cls(
            name,
            env.get(MODEL_VAR, "").strip() or DEFAULT_MODEL,
            env.get(BASE_URL_VAR, "").strip() or DEFAULT_BASE_URL,
            api_key,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    async def complete(self, request: CompletionRequest) -> str:
        """One completion, or an error the router knows how to route around.

        Raises:
            ProviderRateLimited: the provider answered 429, which is the brief's own failover
                signal.
            ProviderUnavailable: anything else that went wrong, named without a URL.
        """
        body: dict[str, Any] = {"model": self.model, "messages": [{"role": "user", "content": request.prompt}]}
        if request.max_output_tokens > 0:
            # max_tokens rather than max_completion_tokens: the older name is the one every
            # server speaking this shape still accepts.
            body["max_tokens"] = request.max_output_tokens
        headers = {"authorization": f"Bearer {self._api_key}", "content-type": "application/json"}
        async with httpx.AsyncClient(transport=self._transport, timeout=self.timeout_seconds) as client:
            try:
                response = await client.post(completions_url(self.base_url), json=body, headers=headers)
            except httpx.HTTPError as error:
                raise ProviderUnavailable(f"{self.name} could not be reached, {type(error).__name__}") from error
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise ProviderRateLimited(self.name, retry_after_seconds(response.headers.get("retry-after")))
        if response.status_code != httpx.codes.OK:
            raise ProviderUnavailable(f"{self.name} answered {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderUnavailable(f"{self.name} answered with a body that is not JSON") from error
        return message_content(payload, self.name)
