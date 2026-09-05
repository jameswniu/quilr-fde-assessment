# Quilr FDE assessment

Four tasks from the Forward Deployed Engineer brief. One project, one test suite, no network.

```
make install     # uv sync, Python 3.13
make test        # the whole pytest suite, all four tasks
make lint        # ruff check, ruff format check, mypy strict
make bench       # task 3 timings and memory
make run-task1   # MCP server on stdio
make run-task2   # MCP security gateway on 8080, mock downstream on 8081
make run-task3   # streaming PII guardrail on 8082
make run-task4   # model router demo, prints every routing outcome
```

## Task 1, MCP server with strict validation

`src/task1_mcp_server`. Two tools over stdio on the official `mcp` SDK. Pydantic models are the single source
of truth for the advertised schema and the runtime check, strict, unknown fields rejected. Bad arguments
return `-32602 Invalid params`. Both handlers are registered directly on the low level server to get that
code, because the SDK's `call_tool` decorator turns every exception into an `isError` result. An unknown
customer is a domain failure, so it stays an `isError` result.

Stdout carries JSON-RPC only. The transport takes the real stdout handle once and `sys.stdout` then points at
stderr, so a stray `print` cannot reach the wire. The test drives the server as a subprocess, asserts every
stdout line is JSON-RPC, and forces a print to prove it lands there.

## Task 2, MCP security gateway

`src/task2_mcp_gateway`. A JSON-RPC reverse proxy. The bearer token resolves to admin or viewer, and
`tools/list` forwards untouched. On `tools/call`, a name starting with `admin_` requires admin, and a viewer
gets `-32001 Unauthorized Tool Call` with the downstream never contacted, which the tests confirm from its
log. Unusable credentials return 401 with `-32002`, malformed payloads 400. The mock downstream ships with it,
so `make run-task2` is the whole system.

## Task 3, streaming PII redaction

`src/task3_stream_guard`. `POST /v1/generate` streams the response back with emails, US social security
numbers and Luhn cards replaced by `[REDACTED]`. The hard case is a value split across chunk boundaries. The
redactor emits only text that can no longer change, cutting outside the nearest token, so prose holds a few
characters. Bounded patterns give the hold a ceiling independent of response size. `make bench` prints the
numbers.

## Task 4, rate limiting and model failover

`src/task4_model_router`. A token aware sliding window limiter, 50,000 tokens per minute per tenant key, every
charge a row in an on disk sqlite file, so the window really slides. Each connection is per thread and
admission runs inside `BEGIN IMMEDIATE`, so two requests for one key cannot both spend it. A 429, or a call
still running after 3000 ms, fails over to the secondary. Rows are keyed by a digest of the tenant key, not
the key. Failures become one payload with a fixed message and a request id, upstream text staying in the log
and the charge released.

## What is not covered

The brief's overview says five tasks but only four are written, so this repo has four. Task 1 debits the
balance so a replay cannot spend it twice, but the brief pins the arguments, so there is no idempotency key.
Task 2 reads tokens from a static map rather than signed ones, and refuses JSON-RPC batches. Task 3 is bounded
at the RFC address limits, so a longer address, or a quoted local part, is not matched, which is tested rather
than hidden. Task 4 charges an estimated token count, never reconciled against reported usage. Nothing talks
to a real model or identity provider, so the suite needs no network.
