# The four tasks

What each task does, and the decision inside it worth arguing about. Every number here has a card in [REFEREE.md](REFEREE.md).

## Task 1, MCP server with strict validation

`src/task1_mcp_server`. Two tools over stdio on the official `mcp` SDK. One Pydantic model per tool is both the advertised schema and the runtime check, strict, with unknown fields rejected.

An argument failure is a protocol error and a missing customer is a domain failure, so the two leave by different doors.

| What went wrong | What the caller gets |
| --- | --- |
| Bad arguments, or an unknown tool name | `-32602 Invalid params` |
| No such customer, or too small a balance | A normal result with `isError` set |

Getting the first row needs both handlers registered directly on the low level server. The SDK's `call_tool` decorator turns every exception into an `isError` result, which would swallow the code.

Stdout carries JSON-RPC only. The transport takes the real stdout handle once and `sys.stdout` then points at stderr, so a stray `print` cannot reach the wire. The test drives the server as a subprocess and forces a print to prove where it lands.

## Task 2, MCP security gateway

`src/task2_mcp_gateway`. A JSON-RPC reverse proxy that decides before it forwards. The bearer token resolves to admin or viewer, and a tool whose name starts with `admin_` needs admin.

| Request | Answer | Downstream called |
| --- | --- | --- |
| `tools/list`, either role | Whatever the downstream says | Yes |
| `tools/call` on `admin_*` as admin | Whatever the downstream says | Yes |
| `tools/call` on `admin_*` as viewer | 200 with `-32001 Unauthorized Tool Call` | No |
| Missing or unknown bearer token | 401 with `-32002` | No |
| Malformed body | 400 with `-32700` or `-32600` | No |
| Downstream unreachable | 502 with `-32003` | Attempted |

The tests read the mock downstream's own request log to prove the denied call never reached it. That mock ships with the gateway, so `make run-task2` is the whole system.

The `admin_` prefix is the rule the brief specifies, and it is a deny list. A downstream that grew a privileged method under another name would not be covered, so a gateway owning a real policy would carry a per method allow list instead.

## Task 3, streaming PII redaction

`src/task3_stream_guard`. `POST /v1/generate` streams the response back with emails, US social security numbers and Luhn cards replaced by `[REDACTED]`.

The hard case is a value split across chunk boundaries. The redactor cannot emit text that might still turn out to be part of a pattern. It emits only what can no longer change, cutting outside the nearest token. A reply opening mid pattern waits for that pattern to resolve. The worst case doubles that. A whole 320 character match at the front pulls the cut back to its own start, for another 320 characters. That is where the 640 character ceiling comes from.

The wait is whole upstream chunks, which is the unit that survives a change of machine. The milliseconds beside each row are that count times the upstream's own cadence, and they are on the README panel and in `reports/bench_report.json`.

| Response opens with | Chunks held |
| --- | --- |
| Safe prose | 0 |
| A 15 char email | 1 |
| A 19 char Luhn card | 1 |
| An 11 char SSN | 1 |
| A 320 char email | 26 |
| A 1,000 char unbroken token | 26 |
| A 320 char email inside a token | 53 |

The cost tracks the length of the leading value. A 19 character card and a 15 character email both clear in one chunk, while the 320 character address takes 26. `make bench` prints a row for each of these and names the worst.

## Task 4, rate limiting and model failover

`src/task4_model_router` writes every charge as one row in an on disk sqlite file, which is what makes the window really slide instead of resetting on a boundary. Admission control sits in front of two providers.

| Knob | Value | Where it comes from |
| --- | --- | --- |
| Token budget | 50,000 per minute per tenant key | The brief's own figure |
| Window | 60 seconds, sliding | Usage is the sum of the rows inside it |
| Primary timeout | 3000 ms | The brief's own figure |
| Failover trigger | A 429, or that timeout | A routing signal rather than a failure |

Each connection is per thread and admission runs inside `BEGIN IMMEDIATE`, so two requests for one key cannot both spend it. Rows are keyed by a digest of the tenant key rather than the key itself.

Failures become one payload with a fixed message and a request id. Upstream text stays in the local log, and the charge is released, since a request that produced no completion should not spend a tenant's budget for the next minute.

## What is not covered

The brief's overview says five tasks and its body stops at four, so this repo has four.

| Task | What it does not do |
| --- | --- |
| Task 1 | No idempotency key, because the brief pins the three arguments. The balance debit is what stops a replay |
| Task 2 | Tokens come from a static map rather than signed ones, and JSON-RPC batches are refused |
| Task 3 | Bounded at the RFC address limits, so a longer address or a quoted local part is not matched, which is tested rather than hidden |
| Task 4 | Charges an estimated token count, never reconciled against reported usage |

Task 1 speaks stdio and the gateway proxies HTTP, so the thing behind the gateway here is task 2's own mock downstream, not task 1. They are separate tasks in the brief and they are separate here.

Nothing talks to a real model or identity provider, so the suite needs no network.
