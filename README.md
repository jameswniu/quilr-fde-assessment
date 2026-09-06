# Quilr FDE assessment

Four tasks from the FDE brief.

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

Why task 1 is not behind the gateway.

![The four tasks, one card each, and where the gateway's downstream is the mock](assets/system-map.svg)

## Task 1, MCP server

Two tools over stdio, one Pydantic model each as schema and validator.

The SDK's `call_tool` decorator turns every exception into an `isError` result, bad arguments included. I wanted `-32602`, so both handlers sit on the low level server. A missing customer still gets `isError`, because that is a domain answer.

## Task 2, gateway

A viewer calling any `admin_` tool gets `-32001` back before the downstream hears about it.

The `admin_` prefix is the brief's rule and a deny list. A privileged method added under another name sails through, so anything real gets a per method allow list.

## Task 3, stream guard

`POST /v1/generate` streams the reply with emails, SSNs and Luhn valid cards replaced by `[REDACTED]`, split values included.

The redactor emits only text that can no longer change. Every pattern has a bounded length, the longest a 320 character email at the RFC 5321 limits, so it never holds more than twice that, 640 characters.

Plain prose at the front costs under 1 ms at the first token, and the 320 character email inside a longer token costs 583 ms, 53 chunks held. Both are medians of ten paired trials against a scripted upstream.

What sets the cost at the first token.

![Time to first token the guardrail adds, one bar per opening](assets/first-token.svg)

## Task 4, model router

Every charge is one sqlite row on disk, so the window slides, and a 429 or a timeout on the primary fails over.

A request that produced no completion hands its tokens back rather than spending the tenant's next minute. The objection is that endless failures then cost nothing, and production would count them against an abuse budget.

## What I left out, and why

- All 263 tests, cases from 155 functions, run with no network and no key, because the scripted upstream and provider keep them deterministic.
- Every timing test runs at 60 ms to stay quick, so the 3000 ms timeout is never raced live, and the real number would need a fake clock.
- Admission runs before any provider has counted, so the limiter charges four characters a token and nothing reconciles the estimate against the bill.
- Twenty threads race the limiter and no two processes do, because each thread holds its own connection, so the lock between workers is inferred, not proven.
- Task 1 has met only this repo's stdio client, which reads raw bytes off stdout the SDK client would parse away.

More in [docs/REFEREE.md](docs/REFEREE.md).
