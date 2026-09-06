# The four tasks

What each task does, and the decision inside it that a reviewer is most likely to ask about. The numbers behind any of this are in [REFEREE.md](REFEREE.md), one card each.

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

The `admin_` prefix is the rule the brief specifies, and it is a deny list. A downstream that grew a
privileged method under some other name would not be covered by it, so a gateway owning a real policy would
carry an explicit per method allow list instead of inferring privilege from a name.

## Task 3, streaming PII redaction

`src/task3_stream_guard`. `POST /v1/generate` streams the response back with emails, US social security
numbers and Luhn cards replaced by `[REDACTED]`. The hard case is a value split across chunk boundaries. The
redactor emits only text that can no longer change, cutting outside the nearest token, so a reply opening in
prose holds a few characters and starts as fast as the upstream does. A reply that opens mid pattern waits for
that pattern to resolve instead, and what it costs tracks how long the leading value is rather than which
kind of value it is. A 15 character address, a 19 character card or an 11 character social security number
costs one extra chunk. The longest legal address, at 320 characters, costs 26. The worst case costs 53, that
same address buried inside a longer token so no safe cut turns up for another 320 characters, which is a
little under 600 ms at the bench's 10 ms per chunk. Bounded patterns give both the held text and that wait a
ceiling independent of response size. `make bench` prints a first token row for every one of those shapes and
names the worst.

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

Task 1 speaks stdio and the gateway proxies HTTP, so the thing behind the gateway in this repo is the mock
downstream that ships with task 2, not task 1. The two are separate tasks in the brief and they are separate
here.
