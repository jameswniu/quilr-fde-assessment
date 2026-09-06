# Quilr FDE assessment

Four tasks from the FDE brief, in Python, and `make check` runs all of it.

## Run it

```bash
make install     # uv sync, Python 3.13
make test        # the whole suite, all four tasks
make check       # lint, claim check, figure check, then the suite
make bench       # what the task 3 guardrail costs
make run-task1   # MCP server on stdio
make run-task2   # security gateway on 8080, mock downstream on 8081
make run-task3   # streaming PII guardrail on 8082
make run-task4   # model router demo, prints every routing outcome
make run-live    # the same guardrail against a real provider, needs LLM_API_KEY
```

## Task 1, MCP server

Two tools over stdio on the official `mcp` SDK, one Pydantic model per tool as both schema and validator.

The SDK's `call_tool` decorator turns every exception into an `isError` result, bad arguments included. I wanted `-32602`, so both handlers sit on the low level server instead. A missing customer still gets `isError`, because that one is a domain answer.

`src/task1_mcp_server`, both handlers in `server.py`.

## Task 2, security gateway

A JSON-RPC reverse proxy, where a viewer calling any `admin_` tool gets `-32001` back before the downstream hears about it.

The `admin_` prefix is the brief's rule, and it is a deny list. A privileged method added downstream under another name sails through, so anything real gets a per method allow list. I built what was asked for.

`src/task2_mcp_gateway`.

## Task 3, streaming PII redaction

`POST /v1/generate` streams the reply back with emails, SSNs and Luhn valid card numbers replaced by `[REDACTED]`, split values included.

The redactor emits only text that can no longer change. Every pattern has a bounded length, the longest a 320 character email at the RFC 5321 limits, so it never holds more than twice that, 640 characters. A reply opening in plain prose costs under 1 ms at the first token, the median of ten paired trials against a scripted upstream. Put a 320 character email buried inside a longer token at the front and the same ten trials read about 583 ms, 53 chunks held before anything leaves.

`src/task3_stream_guard`, `redactor.py` for the hold, `patterns.py` for the bounds, and `assets/first-token.svg` for the cost by opening.

## Task 4, rate limiting and failover

A token budget, then failover on a 429 or a timeout, every charge one sqlite row on disk so the window slides.

A request that produced no completion hands its tokens back, so a failed call does not spend the tenant's next minute. I know the objection. Endless failures then cost nothing, and a production gateway would count them against an abuse budget.

`src/task4_model_router`, `rate_limiter.py` and `router.py`.

More on each in [docs/TASKS.md](docs/TASKS.md).

## What is not proven

- All 263 tests under `tests/` run with no network and no key, by choice, and I never measured coverage.
- The live path, `http_upstream.py` and `http_provider.py`, parses the provider's stream format under test against a stubbed transport, and has never met a production one.
- The 3000 ms primary timeout is a constant one test reads back, and nothing races it, since every timing test runs at 60 ms.
- The limiter serialises across threads in one process, and nothing tests it across processes.
- Task 1 has only met this repo's own stdio client, never a real MCP host.

Every number above has its unit and its set in [docs/REFEREE.md](docs/REFEREE.md).
