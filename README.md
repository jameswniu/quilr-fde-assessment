<p align="center">
  <img src="assets/hero.svg" alt="Where does a bad request stop? Four tasks from the FDE brief, each a gate with one refusal to prove. The schema gate asks whether the arguments fit the schema and refuses with -32602. The role gate asks whether this role may call this tool and refuses with -32001 before anything is forwarded. The hold gate asks whether this text can still change and holds it, 640 characters at most. The budget gate asks whether there is budget and whether the primary is up, refuses with rate_limited, and fails over on a 429 or 3000 ms." width="100%">
</p>

<div align="center">

<b><font size="6">Quilr FDE assessment</font></b>

<br/>

<img alt="267 tests, no network and no key" src="https://img.shields.io/badge/tests-267_%C2%B7_no_network,_no_key-CC785C?style=flat-square&labelColor=141413">
<img alt="held at most 640 chars, 636 seen" src="https://img.shields.io/badge/held_at_most-640_chars_%C2%B7_636_seen-6B645A?style=flat-square&labelColor=141413">
<img alt="first token under 1 ms on prose, 583 ms worst" src="https://img.shields.io/badge/first_token-under_1_ms_on_prose_%C2%B7_583_ms_worst-6B645A?style=flat-square&labelColor=141413">
<img alt="MIT license" src="https://img.shields.io/badge/license-MIT-6B645A?style=flat-square&labelColor=141413">

<br/><br/>

<strong>Four tasks from the FDE brief, and one refusal per task that a test can reproduce with no network and no key.</strong><br/>
An MCP server, a security gateway, a streaming PII guardrail and a model router, on the official MCP SDK.

<br/>

<code>-32602 · -32001 · [REDACTED] · rate_limited</code>

</div>

```bash
make install     # uv sync, Python 3.13
make test        # 267 tests, no network, no key
make check       # lint, then every number on this page reread from the code and the reports
make bench       # what the task 3 guardrail costs at the first token
make run-task1   # MCP server on stdio
make run-task2   # security gateway on 8080, mock downstream on 8081
make run-task3   # streaming PII guardrail on 8082
make run-task4   # model router demo, prints every routing outcome
make run-client  # the official SDK client against task 1
make inspector   # MCP Inspector's web UI against task 1, needs npx
make run-live    # the guardrail against a real provider, needs LLM_API_KEY
```

---

## The gates, and why refusal is the unit

Each task in the brief has a place where a bad request must stop, so I built each one around that refusal and made it the thing the tests pin. A gate that says no correctly is easy to show and easy to argue about, and everything else the task does hangs off that one decision.

| | The question it answers | Where the proof is | When it says no |
|:---|:---|:---|:---|
| **Schema**, task 1 | Do the arguments fit the advertised schema? | The server run as a subprocess over stdio, with the schema and the validator checked against each other case by case | `-32602`, every bad field named at once |
| **Role**, task 2 | May this role call this tool? | The mock downstream's own request log, still empty after a viewer calls `admin_reset_key` | `-32001`, and nothing is forwarded |
| **Hold**, task 3 | Can this text still change? | `make bench`, seven openings at ten paired trials each | Held, 640 characters at most, then `[REDACTED]` |
| **Budget**, task 4 | Is there budget, and is the primary up? | One sqlite row per charge, read back by the limiter tests | `rate_limited` with a retry time, or the secondary |

```mermaid
%% drawn by tools/draw_figures.py, edit the generator
%%{init: {"theme": "base", "themeVariables": {"primaryColor": "#1F1E1D", "primaryTextColor": "#F4F1EA", "primaryBorderColor": "#3A3734", "lineColor": "#B8B0A4", "textColor": "#F4F1EA", "clusterBkg": "#141413", "clusterBorder": "#3A3734", "titleColor": "#B8B0A4", "edgeLabelBackground": "#141413", "fontSize": "16px"}, "flowchart": {"curve": "linear", "nodeSpacing": 14, "rankSpacing": 22, "padding": 6, "diagramPadding": 8, "subGraphTitleMargin": {"top": 6, "bottom": 14}}}}%%
flowchart TB
  subgraph S2["02 role gate, task 2"]
    direction LR
    B2["admin_ tool<br/>as viewer?"] -- yes --> B3["-32001<br/>not forwarded"]
    B2 -- no --> B4["forwarded to<br/>the downstream"]
  end
  subgraph S1["01 schema gate, task 1"]
    direction LR
    A2["arguments fit<br/>the schema?"] -- no --> A3["-32602<br/>Invalid params"]
    A2 -- yes --> A4["handler runs"]
  end
  subgraph S4["04 budget gate, task 4"]
    direction LR
    D2["budget in the<br/>last 60 s?"] -- no --> D3["rate_limited<br/>retry_after_seconds"]
    D2 -- yes --> D4["primary first,<br/>secondary on a 429<br/>or after 3000 ms"]
  end
  subgraph S3["03 hold gate, task 3"]
    direction LR
    C2["could this text<br/>still change?"] -- yes --> C3["held, 640 chars<br/>at most"]
    C2 -- no --> C4["emitted, PII<br/>as [REDACTED]"]
  end
  S1 ~~~ S3
  S2 ~~~ S4
  Z["<br/><br/>"]
  S3 ~~~ Z
  S4 ~~~ Z
  classDef stop fill:#1F1E1D,stroke:#CC785C,stroke-width:2px,color:#F4F1EA
  classDef hold fill:#1F1E1D,stroke:#B8B0A4,stroke-width:2px,color:#F4F1EA
  class A3,B3,D3 stop
  class C3 hold
  classDef spacer fill:none,stroke:none,color:transparent
  class Z spacer
```

## How it is built

Four small services that share a style and not a process. Task 1 speaks stdio and the gateway proxies HTTP, so in this repo the gateway's downstream is a mock server and not task 1. I would rather say that than draw an arrow the code does not have. Each tool has one Pydantic model that is both the advertised schema and the runtime validator, so the two cannot drift.

The limiter keeps every charge as one sqlite row on disk, so the 60 second window slides instead of resetting and survives a restart. The router gives the primary 3000 ms, fails over to the secondary on a 429 or a timeout, and retries nothing else.

<p align="center">
  <img src="assets/system-map.svg" alt="System map of what each of the four tasks owns, and where two of them are not wired together" width="100%">
</p>

## The guardrail, and what it costs

The redactor emits only text that can no longer change. Every pattern has a bounded length, the longest a 320 character email at the RFC 5321 limits, so the buffer never holds more than twice that, 640 characters. A match that crosses the cut pulls the cut back to its own start, which is how `ada@exa` followed by `mple.com` becomes one `[REDACTED]`. A sweep of chunk sizes from 1 to 24 shows the answer does not depend on how the upstream splits the text.

The cost is measured, not estimated. `make bench` runs seven openings at ten paired trials each against a scripted upstream sending 12 character chunks every 10 ms. Plain prose adds under 1 ms to the first token. A 320 character email inside a longer token is the worst case at 583 ms, with 53 chunks held before the guardrail could be sure.

<p align="center">
  <img src="assets/first-token.svg" alt="Time to first token that the guardrail adds, by what the response opens with" width="100%">
</p>

## The server, and the clients it met

The SDK's `call_tool` decorator turns every exception into an `isError` result, bad arguments included. I wanted bad arguments back as a JSON-RPC `-32602`, so both handlers sit on the low level server. A missing customer still gets `isError`, because that is a domain answer. A refund checks and debits the balance in one step under a lock. Stdout is rebound to stderr before the server starts, so a stray `print` cannot break the stream.

It has met three clients. The repo's own raw stdio client reads the bytes off stdout, and the official `ClientSession` over `stdio_client` gets the same schema and the same `-32602` as an `McpError`. MCP Inspector 2.5.0 made the calls by hand through `make inspector`. The first screenshot is the refusal on purpose, `customer_id` sent as `CUST-1`, and the second is a refund for `CUST-10042` at 25.50, accepted.

<p align="center"><img src="assets/inspector-invalid-params.png" alt="MCP Inspector showing the -32602 Invalid params refusal for CUST-1"></p>

<p align="center"><img src="assets/inspector-refund.png" alt="MCP Inspector showing the accepted refund for CUST-10042"></p>

## Decisions worth flagging

- The `admin_` prefix is the brief's rule and a deny list, so a privileged method under another name would sail through, and anything real gets a per method allow list.
- Admission charges four characters a token before any provider has counted, against 50,000 tokens in the trailing minute, and nothing reconciles the estimate with the bill.
- A request that produced no completion hands its tokens back, and the objection I would raise myself is that endless failures then cost nothing.
- Twenty threads racing one key win exactly ten of ten 5,000 token slots, because the loser waits on `BEGIN IMMEDIATE` rather than overspending.
- The client's bearer never reaches the downstream, the decided role travels as one header, and a downstream outage comes back as a 502 with the caller's own request id.
- Cards are checked with Luhn over runs of whole digit groups, longest first, so `4111 1111 1111 1111 123` loses the card and keeps the three digit code.

## The suite

All 267 tests, cases from 159 functions, run with no network and no key, because a scripted upstream and a scripted provider keep them deterministic. Every timing test races at 60 ms so the suite stays quick. `make claims` reruns it, rereads the constants from `src/` and the measurements from `reports/bench_report.json`, and fails when a number on this page has drifted. When it is happy it prints one line, quoted here exactly.

```
claims ok, 267 passed and 0 skipped from 159 functions, 640 chars held at most, worst first token 583 ms, Python 3.13
```

## What I left out, and why

- The 3000 ms timeout is never raced live, since every timing test runs at 60 ms, and proving the real number would need a fake clock.
- Twenty threads race the limiter and no two processes do, so the lock between separate workers is inferred from sqlite's behaviour rather than proven here.
- Task 1 has met a raw client, the SDK client and Inspector, and no host such as Claude Desktop yet.

More in [docs/TASKS.md](docs/TASKS.md), and a card for every number above in [docs/REFEREE.md](docs/REFEREE.md).
