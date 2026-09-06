<p align="center">
  <img src="assets/hero.svg" alt="Four tasks from the Forward Deployed Engineer brief, an MCP server, a security gateway, a streaming PII guardrail and a model router. 263 tests, 0 skips, no coverage measured, and a 640 char hold ceiling with 636 of it seen." width="100%">
</p>

*`make check` exits nonzero when a badge or a committed figure stops matching the report behind it.*

# Quilr FDE assessment

<p align="center">
  <img src="https://img.shields.io/badge/tests-263_green-18181b" alt="tests 263 green">
  <img src="https://img.shields.io/badge/held_text-640_char_ceiling-1b5e3f" alt="held text 640 char ceiling">
  <img src="https://img.shields.io/badge/python-3.13-52525b" alt="python 3.13">
</p>

- Four tasks from the brief in one project, and the hard one is task 3.
- A value to redact can arrive split across two chunks of a stream. The guardrail emits only the text that can no longer change, and holds the rest.
- Bounded patterns cap what it holds at 640 characters, whatever the response is.
- One test suite covers all four, with no network and no API key. The provider behind it is scripted on purpose, and pointing task 3 at a real one is one environment variable and one command.

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

## What each task owns

<p align="center">
  <img src="assets/system-map.svg" alt="System map of the four tasks. Task 1 puts two tools on stdio, task 2 is a gateway on 8080 in front of a mock downstream on 8081, task 3 is a streaming guardrail on 8082 with a 640 character hold ceiling, and task 4 is a sqlite token limiter in front of a primary and a secondary provider" width="100%">
</p>

Where a request stops, and the one place it is only held.

```mermaid
%%{init: {"flowchart": {"rankSpacing": 18, "nodeSpacing": 12, "curve": "linear", "padding": 6}}}%%
flowchart TD
  classDef gate fill:#fafafa,stroke:#3f3f46,color:#111111
  classDef pass fill:#ffffff,stroke:#a1a1aa,color:#111111
  classDef stop fill:#18181b,stroke:#18181b,color:#ffffff
  classDef hold fill:#1b5e3f,stroke:#1b5e3f,color:#ffffff

  B["A tools/call.<br/>Token resolves to a role"]
  B -->|"viewer wants admin_"| B1["Refused, -32001.<br/>No downstream call"]
  B -->|"otherwise"| C["Arguments match the schema"]
  C -->|"no"| C1["Refused, -32602"]
  C -->|"yes"| C2["Handler runs"]

  C2 ~~~ E
  E["A completion.<br/>Room in the 60 s window"]
  E -->|"no"| E1["Refused, 429"]
  E -->|"yes"| F["Primary answers inside 3000 ms"]
  F -->|"429 or timeout"| G["Secondary tries"]
  F -->|"yes"| H["Reply returns"]
  G --> H
  G -->|"it fails too"| G1["One error shape"]

  H ~~~ K
  K["A response chunk.<br/>Could still be part of a pattern"]
  K -->|"yes"| K1["Held, not refused.<br/>640 chars at most"]
  K1 --> K
  K -->|"no"| K2["Emitted, redacted"]

  class B,C,E,F,K gate
  class C2,G,H,K2 pass
  class B1,C1,E1,G1 stop
  class K1 hold
```

`src/task1_mcp_server` puts two tools on stdio. One Pydantic model per tool does double duty as the advertised schema and the runtime check.

`src/task2_mcp_gateway` decides before it forwards. Ask it for an `admin_` tool as a viewer and the downstream never hears about it.

`src/task3_stream_guard` redacts emails, social security numbers and card numbers mid stream, including a value that arrives in two pieces.

`src/task4_model_router` is admission control plus failover, with the token budget in sqlite.

Tasks 3 and 4 both define a protocol for their provider, and `http_upstream.py` and `http_provider.py` are real implementations of it that speak the OpenAI chat completions shape. Export `LLM_API_KEY`, run `make run-live`, and a real completion streams through the same redactor. Unset, that command names the missing variable and stops.

[The four tasks](docs/TASKS.md) has the decision inside each one that is worth arguing about.

## What the guardrail costs

<p align="center">
  <img src="assets/first-token.svg" alt="Bar chart of the time to first token the guardrail adds, by what the response opens with. Under 1 ms on safe prose, about 11 ms on a short email, card or social security number, about a third of a second on a 320 character email or a 1,000 character token, and about 0.6 s on a 320 character email buried inside a token" width="100%">
</p>

A reply opening mid pattern waits for that pattern to finish arriving. The worst case doubles that. A whole
320 character match at the front, with no safe cut behind it, holds close to 640 characters before anything
leaves. That is the 53 chunks on the last bar. A longer response never costs more than that.

## What this does not prove

The brief's overview says five tasks and its body stops at four, so this repo has four.

| Number on the page | What it does not cover |
| --- | --- |
| 263 tests green | No coverage is measured, so it says what was written and nothing about what was not |
| The live provider path | Its parsing and its failures are tested, and nothing here has been run against a production provider |
| 640 char hold ceiling | Derived from the pattern lengths, and the closest witness the bench builds holds 636 |
| Every timing here | One loaded laptop against a scripted upstream, so no real provider is measured |

[The referee cards](docs/REFEREE.md) carry one card per number, saying what it measures, on what set, and what
it does not support.

## Figures and claims

No number in a figure here can go stale without a command failing.

| Command | What it does |
| --- | --- |
| `make bench` | Re-measures task 3 and writes `reports/bench_report.json` |
| `make claims` | Reruns the suite into `reports/test_report.json`, and fails when a badge above stops matching it |
| `make figures` | Redraws the three SVGs from those two reports and from the constants in `src/` |
| `make figures-check` | Redraws and compares against what is committed |

Neither one reads the prose here, which repeats some of the same numbers. Those get their accounting in the
referee cards. Re-running `make bench` re-measures, so redraw the figures after it.
