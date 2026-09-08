# Where every number comes from

Every number on a page here, or in what a command prints, has a card below, taken from the code and from live runs. The heading is the number, each row answers one question about it, and the line under the table says where it appears.

## Cards

### 50,000 tokens a minute for each tenant key

| Question | Answer |
| --- | --- |
| What is claimed | 50,000 estimated tokens a minute for one tenant API key. |
| What is counted | Our token estimates for one key digest over the trailing 60 seconds, a charge counting through 59.999 s and gone at 60.0. |
| How a match is decided | The new charge joins that sum, exactly 50,000 is admitted, one token more is refused. |
| Where the data came from | The brief's example, "e.g., maximum 50,000 tokens/minute per tenant API key", a default argument callers replace, never a measured capacity. |
| Chosen before or after the result | Before. `DEFAULT_LIMIT_TOKENS` is the brief's own example written into the code at `src/task4_model_router/rate_limiter.py:31`, a constant with nothing to fit and no result to see first. |
| How to regenerate it | `make run-task4`, `test_the_brief_default_is_fifty_thousand_tokens_a_minute` for the constant, `test_the_window_boundary_is_exact` for the boundary. |
| The number that makes it look worse | Twenty threads win exactly ten of ten 5,000 token slots, reading 50,000, and twelve router calls on a 280 token budget serve four, refuse eight. |
| What this sample can and cannot say | Four characters count as one token, nothing checks that against a provider's bill, and eviction only shows rows leaving. |
| What moves it | `limit_tokens`, and under it `CHARS_PER_TOKEN`, where a smaller divisor charges more per prompt and admits fewer requests. |

Appears at Decisions worth flagging (the admission sentence), `docs/TASKS.md:63`, and `assets/system-map.svg` (from `src/task4_model_router/rate_limiter.py:31` at draw time), which How it is built embeds.

### 3000 ms before the router gives up on the primary

| Question | Answer |
| --- | --- |
| What is claimed | 3000 ms from sending the primary call to starting the secondary. |
| What is counted | Milliseconds per request, from dispatching the primary call to giving up on it. |
| How a match is decided | The timeout races the primary, an answer inside the window is used and the secondary never called, and a timed out call is cancelled (`primary.completed_calls==0`). |
| Where the data came from | The brief's "times out after 3000ms", a default argument, not a latency budget anyone measured. |
| Chosen before or after the result | Before. `DEFAULT_TIMEOUT_MS` is the brief's own number at `src/task4_model_router/router.py:38`, a constant with nothing to fit, and no run chose it. |
| How to regenerate it | `make run-task4`, `tests/test_task4_router.py`, and `test_the_brief_default_timeout_is_three_seconds` for the constant. |
| The number that makes it look worse | Nothing races 3000 ms live, since every timing test uses `FAST_TIMEOUT_MS` 60 and the demo in `__main__.py` uses 300. |
| What this sample can and cannot say | One test asserts the integer is 3000 and none asserts behaviour at 3000, so only the shape is exercised. |
| What moves it | `timeout_ms`, where lower abandons a slow but healthy primary and higher lets a hung one hold the request longer. |

Appears at How it is built (the failover sentence), What I left out (beside the 60 ms the tests race at), and the mermaid lanes under The gates, `docs/TASKS.md:65`, `assets/hero.svg` (the 4. Budget card, embedded above the README title), and `assets/system-map.svg` (from `src/task4_model_router/router.py:38` at draw time), which How it is built embeds.

### 267 tests pass

| Question | Answer |
| --- | --- |
| What is claimed | "267 passed", 0 skipped, from `make test`. |
| What is counted | pytest cases under `tests/`, 159 functions expanded by parametrize into 267 cases, split by task below. |
| How a match is decided | A case counts when pytest reports it green under `pyproject.toml` (testpaths `tests`, asyncio_mode auto), with skips, xfails and xpasses counted apart. |
| Where the data came from | Every fixture is inside the repo and the assertions are the labels, so the suite is scored against the code, never an outside corpus. |
| Chosen before or after the result | After, in the only sense that counts. The suite is the harness the code was built against, so it cannot be independent of the design. The two outside witnesses are the official SDK client in `tests/test_task1_sdk_client.py` and MCP Inspector, which met the server without knowing the tests and agreed with it. |
| How to regenerate it | `make test`, then `make claims`, which collects and runs the suite, writes both counts to `reports/test_report.json`, and fails when the README or this heading disagrees. |
| The number that makes it look worse | 159 by function, and nothing at all as coverage, which is never measured. |
| What this sample can and cannot say | A green suite says the written cases hold, nothing about the unwritten ones, and no coverage number bounds the gap. |
| What moves it | A parametrize tuple moves 267 with nothing new tested, hence the function count, and a skip marker moves it down, hence the skip count. |

| Task | Cases | Functions |
| --- | --- | --- |
| Task 1, MCP server | 46 | 22 |
| Task 2, gateway | 24 | 13 |
| Task 3, stream guard | 123, being 7 endpoint, 78 redactor and 38 live upstream | 65 |
| Task 4, model router | 74, being 22 limiter, 26 router and 26 live provider | 59 |

Appears at the tests badge under the README title, the `make test` line in the make block, The suite (its opening sentence and the quoted `make claims` line), this heading, and `assets/system-map.svg` (stat box, embedded in How it is built). The hero carries no count on this branch.

### No network and no API key anywhere in the suite

| Question | Answer |
| --- | --- |
| What is claimed | Zero sockets and no key read by `make test`, though the repo holds one path that opens a socket. |
| What is counted | Sockets opened by `make test`, so the number defended is a zero, not a measurement. |
| How a match is decided | By construction, one row per path below, never by a sandbox that fails the run on a socket. |
| Where the data came from | The whole suite, minus the live path, `src/task3_stream_guard/http_upstream.py` and `src/task4_model_router/http_provider.py`, reached by `scripts/live_stream.py`. |
| Chosen before or after the result | Before. It is a property the design enforces path by path, in the table below, not a sample anyone selected, so there was no result to pick it against. |
| How to regenerate it | `make test` opens nothing, and `make run-live`, the only command that opens a socket, names `LLM_API_KEY` and exits 2 without it. |
| The number that makes it look worse | 38 cases in `tests/test_task3_http_upstream.py` and 26 in `tests/test_task4_http_provider.py` cover the live path against a stubbed transport, below. |
| What this sample can and cannot say | No answer, transcript or fixture from a production provider exists, and `make run-live` ran only against a local server, proving wiring and no vendor. |
| What moves it | `LLM_API_KEY` turns the live path on, `LLM_BASE_URL` picks any OpenAI chat completions endpoint, `LLM_MODEL` the model, none read at import or by tests. |

| Path | Detail |
| --- | --- |
| Task 1 | A subprocess over stdio pipes |
| Tasks 2 and 3 | ASGI apps driven in process |
| Every httpx client under `tests/` | An explicit `ASGITransport` or `MockTransport`, and a grep for `AsyncClient` finds none without one |
| Keys | No test reads an environment variable, and two start a fresh interpreter whose `os.environ` raises on any read, then import the live modules |
| `tests/test_task3_http_upstream.py`, 38 stubbed cases | Event stream parsing, framing rules, refusals, the sanitised target |
| `tests/test_task4_http_provider.py`, 26 stubbed cases | Status mapping, including a 429 off the wire driving a real router failover |

Appears at the line under the title, the tests badge, the `make test` line in the make block, The suite, `docs/TASKS.md:85`, and `assets/system-map.svg` (stat card, embedded in How it is built).

### 2.52 to 2.77 seconds for the whole suite

| Question | Answer |
| --- | --- |
| What is claimed | "263 passed in 2.54s" from `make test`. |
| What is counted | Wall clock seconds for one full `make test`, warm, collection included, `uv sync` excluded. |
| How a match is decided | pytest's summary line, cross checked with `/usr/bin/time -p make test`, which adds the uv and interpreter start. |
| Where the data came from | Five consecutive runs at a load average of 10 to 11 on 18 cores, the same band as the earlier reading, so the two compare. |
| Chosen before or after the result | After. Five consecutive runs were kept out of roughly twenty because their load average matched the earlier reading, a choice made with the numbers already visible. The load average 120 row below is what the unkept ones looked like, and no page quotes this number. |
| How to regenerate it | `make test`, and `/usr/bin/time -p make test` for the wall figure. |
| The number that makes it look worse | Shell wall time for the same five was 3.01 to 3.34 s, so uv and the interpreter start cost roughly half a second on top. |
| What this sample can and cannot say | Five runs on one loaded laptop, no cold cache, CI or second machine, and load moves it further than code, as the last row shows. |
| What moves it | Five process spawns, the two threaded sqlite tests, the task 1 subprocess and the two import probes, so disk and load outweigh code. |

| Runs | Readings |
| --- | --- |
| pytest, 263 cases, five runs | 2.54, 2.52, 2.70, 2.77 and 2.60 s |
| Shell wall clock, the same five | 3.01, 3.08, 3.28, 3.34 and 3.19 s |
| pytest, 199 cases, minutes later on the same box | 2.65, 2.59 and 2.53 s, so the 64 live provider cases cost under a tenth of a second |
| pytest, 199 cases, before the live path landed | 2.28 to 2.54 s |
| pytest, load average near 120, earlier the same evening | 4.07 to 7.22 s |

Appears at the `make test` summary line only, on no page.

### 15 characters held, from 3,900 to 3,900,000 characters of response

| Question | Answer |
| --- | --- |
| What is claimed | "held 15 chars" on all four `make bench` rows, from 3,900 to 3,900,000 characters. |
| What is counted | `peak_buffered_chars`, the most the redactor held back at one moment across one whole response. |
| How a match is decided | A counter inside the redactor, raised on every emit (`src/task3_stream_guard/redactor.py:111`) and read after the final flush (`_peak_for_length`, `scripts/bench_stream.py:137-152`). |
| Where the data came from | One 39 character prose chunk repeated, then the same 16 character tail " ada@example.com" at all four sizes. |
| Chosen before or after the result | Before for the four length rows, whose repeated prose and " ada@example.com" tail were fixed in the script's first cut before any reading. The three shape rows below were added after that flat result, once it was clear the tail and not the length set the number. |
| How to regenerate it | `make bench`, which runs `uv run python scripts/bench_stream.py`. |
| The number that makes it look worse | Content shape, below, from 5 for pure prose to 320 for one unbroken 100,000 character token. |
| What this sample can and cannot say | The flat row is half the claim, and only beside the shape table does it show a property of content, not length. |
| What moves it | The longest token in the text, since a longer trailing token raises it and a longer response does not. |

| Response | Peak held |
| --- | --- |
| Pure prose near 100,000 characters, no partial pattern | 5 |
| The same prose, ending mid email | 15 |
| One unbroken 100,000 character token | 320 |
| The 428 character `DEMO_RESPONSE`, measured outside the script, never printed | 36 |
| A 316 character legal email in 7 character chunks, measured outside the script, never printed | 314 |

Appears at the `make bench` tables and `reports/bench_report.json` (`held_by_length`, `held_by_shape`), on no page.

### 640 characters held at most

| Question | Answer |
| --- | --- |
| What is claimed | "hard ceiling 640 chars" from `make bench`, and `MAX_BUFFERED_CHARS` at `src/task3_stream_guard/redactor.py:22`. |
| What is counted | Characters, the most the redactor can ever hold back, for any input at any chunking. |
| How a match is decided | Derived, not measured, as twice the 320 character longest match, since a match straddling the cut pulls it back another 320. |
| Where the data came from | The three patterns in `src/task3_stream_guard/patterns.py`, with bounded quantifiers so the worst match is computable, below. |
| Chosen before or after the result | Before. It is derived from the caps in `patterns.py`, so it was computable before any bench ran. The 636 beside it came after, from an input built on purpose to press the bound. |
| How to regenerate it | `make bench` prints it, `patterns.py:61` and `redactor.py:22` derive it, and `test_buffer_never_grows_with_response_length`, `test_held_text_is_bounded_even_by_one_enormous_token`, `test_one_enormous_chunk_is_still_scanned_in_bounded_slices` hold it. |
| The number that makes it look worse | 636 is the closest the bench gets, holding a 320 character address, "_" and 320 token characters in 12 character chunks. |
| What this sample can and cannot say | An analytic bound never reached exactly, the doubling watched happening and only the last four characters resting on reading the code. |
| What moves it | `_EMAIL_DOMAIN_MAX` 255 and `_EMAIL_LOCAL_MAX` 64, where tightening either lowers the bound and silently misses a legal address, as the boundary test records. |

| Pattern | Longest match |
| --- | --- |
| Email, a 64 character local part, "@" and a 255 character domain, the RFC 5321 limits | 320 |
| Card, 19 digits with 18 separators | 37 |
| SSN | 11 |

Appears at the held_at_most badge under the README title, the gate table and the mermaid lanes under The gates, The guardrail and what it costs, the `make claims` line under The suite, `docs/TASKS.md:41`, this heading, `assets/hero.svg` (the 3. Hold card, embedded above the README title), and `assets/system-map.svg` (embedded in How it is built).

### 583 ms worst case at the first token, under 1 ms on safe prose

| Question | Answer |
| --- | --- |
| What is claimed | The seven row `make bench` table, headlined by its worst row, 582.32 ms on a 320 character email inside a token. |
| What is counted | Milliseconds from stream start to the first non-empty chunk, the median of ten back to back raw and guarded pairs per opening, plus chunks held. |
| How a match is decided | A stopwatch around the first chunk, raw then guarded, back to back (`time.perf_counter` in `_first_token_seconds`, paired by `_paired_trials`, `scripts/bench_stream.py:49-77`), against the scripted upstream below. |
| Where the data came from | Seven responses differing only in their opening (`_leading_shapes`, `scripts/bench_stream.py:80-108`), ten paired trials each, one prompt, no warm up. |
| Chosen before or after the result | After. The seven openings were chosen to bracket the bound once exploration had shown where the cost lived, so 583 ms is the worst of a chosen set rather than a survey of traffic. Earlier cuts of `scripts/bench_stream.py` timed safe prose alone, and one held text row turned out to be its fixture rather than a property, before the seven landed with the worst case that is now the headline. |
| How to regenerate it | `make bench`, then `make figures` to redraw `assets/first-token.svg` from `reports/bench_report.json`, then `make claims` to rebuild the record rows from the same file. |
| The number that makes it look worse | Best and worst sit four orders of magnitude apart, so quoting only the prose row was wrong, and the straddling note belongs to one run. |
| What this sample can and cannot say | One chunk size, one cadence, one loaded laptop, no real provider, and the last shape is the worst the design allows, not one from traffic. |
| What moves it | `UPSTREAM_DELAY_SECONDS` 0.01 with `CHUNK_SIZE` 12 prices a chunk of waiting, `MAX_MATCH_LENGTH` 320 sets how many the last three shapes wait, `TRIAL_COUNT` 10 narrows ranges. |

| Opening | Text | Five readings, ms |
| --- | --- | --- |
| 1 | The 428 character `DEMO_RESPONSE`, safe prose | 0.02, 0.01, 0.02, 0.06, 0.03, every range straddling zero |
| 2 | `ada@example.com` | 11.02 to 11.17 across openings 2, 3 and 4 |
| 3 | `4111 1111 1111 1111` | As above |
| 4 | `123-45-6789` | As above |
| 5 | The longest legal address the pattern matches, 320 characters | 284.84 to 286.44 across openings 5 and 6 |
| 6 | 1,000 "x" characters | As above |
| 7 | That address, then "_", then 320 "z" characters | 582.32, 582.69, 582.29, 583.84, 583.45 |
| 2 to 7 | Each ahead of the same prose tail | |
| Waits | `_chunks_waited` (`scripts/bench_stream.py:121-134`), the column `docs/TASKS.md` carries | 0, 1, 1, 1, 26, 26 and 53, the same in all five runs |
| 1, a sixth run | Safe prose again | 0.00 to 0.99, and no straddling note printed |

| Detail | Value |
| --- | --- |
| Upstream | Scripted, 12 character chunks every 10 ms, no network, so the guardrail's own overhead is all that remains |
| One reading | Stops at the first chunk rather than draining, keeping seventy pairs inside a fourteen second bench |
| The cost | Whole chunk delays, since nothing leaves while the opening could still be part of a pattern |
| Between runs | Milliseconds move by a few and the waits do not, so `make figures-check` reports drift in the figures and `make claims` in the prose |
| What a page shows | Whatever the last `make bench` measured, in the figure, the README sentence and the record table below |
| Chunk size | Larger provider chunks clear the same window in fewer of them, and a slower provider pays more |
| Frequency | Nothing says how often any of the seven openings occurs in real traffic |

The full record, one row per opening, drawn from the same report as the chart on the README.

| Opening, from `make bench` | Chunks held | The guardrail adds | Range over ten pairs |
|:---|:---|:---|:---|
| Safe prose | 0 | Under 1 ms | -1 to 1 ms |
| A 15 char email | 1 | 11 ms | 10 to 16 ms |
| A 19 char Luhn card | 1 | 11 ms | 10 to 11 ms |
| An 11 char SSN | 1 | 11 ms | 10 to 15 ms |
| A 320 char email | 26 | 286 ms | 282 to 287 ms |
| A 1,000 char unbroken token | 26 | 286 ms | 283 to 288 ms |
| A 320 char email inside a token | 53 | 583 ms | 580 to 586 ms |

Appears at the first_token badge under the README title, The guardrail and what it costs (583 and under 1 ms, rounded from the committed `reports/bench_report.json`, which reads 582.76, above the embedded `assets/first-token.svg`), the `make claims` line under The suite, the record table above, whose every row `make claims` rebuilds from the same report, and `docs/TASKS.md:45-53` (chunks held). The hero carries no timing on this branch.

### 2.0 KiB traced peak on a 3.9 million character response

| Question | Answer |
| --- | --- |
| What is claimed | "traced peak 2.0 KiB" on the largest `make bench` row, beside 3,900,000 characters. |
| What is counted | Kibibytes of tracemalloc's peak traced allocation while feeding the whole response, Python heap only. |
| How a match is decided | Start tracemalloc, feed the response, read `get_traced_memory()[1]`, in `_peak_for_length` at `scripts/bench_stream.py:137-152`, dropping the output as a forwarding proxy would. |
| Where the data came from | The same synthetic response as the 15 character card, at four sizes from 3,900 to 3,900,000 characters. |
| Chosen before or after the result | Before, and nothing rests on it. The fixture and the four sizes were fixed in the script's first cut, and the 2.0 is whatever the committed run printed, inside the 2.0 to 6.6 KiB spread recorded below. |
| How to regenerate it | `make bench`, and `test_peak_memory_does_not_track_response_length`, which streams 7.8 million characters and asserts a peak under 64 KiB and under a hundredth of that. |
| The number that makes it look worse | Across ten runs this row read 2.0 to 6.6 KiB and the 39,000 character row 3.0 to 11.2 KiB, small rows sometimes above large ones. |
| What this sample can and cannot say | Allocator noise dominates, so it shows the absence of growth and is not a memory figure worth quoting. |
| What moves it | tracemalloc sees Python allocations only, never interpreter or OS resident memory, and nothing reports RSS. |

Appears at the `make bench` table and `reports/bench_report.json` (`held_by_length`), on no page.

## Numbers the brief set

The brief set these, so each has a citation and no confidence interval.

| Value | Brief line | Code | Test |
| --- | --- | --- | --- |
| `CUST-XXXXX` | Task 1, "customer_id string formatted as CUST-XXXXX" | `src/task1_mcp_server/models.py:16` `CUSTOMER_ID_PATTERN` | `test_task1_mcp_server.py`, invalid id cases |
| Reason length 10 | Task 1, "reason string with minimum length of 10" | `src/task1_mcp_server/models.py:18` `REASON_MIN_LENGTH` | `test_task1_mcp_server.py`, short reason cases |
| `-32602` | Task 1, "standard MCP JSON-RPC error codes" | `src/task1_mcp_server/server.py:125` and `:166` | `test_task1_mcp_server.py`, invalid params cases |
| `-32001` | Task 2, "return a JSON-RPC Error (-32001: Unauthorized Tool Call)" | `src/task2_mcp_gateway/jsonrpc.py:16` | `test_viewer_is_blocked_from_admin_tools` |
| `429` failover | Task 4, "returns a 429 Too Many Requests status" | `router.py`, the `ProviderRateLimited` branch | `test_failover_on_a_429` |
| Five tasks | Overview, "consists of 5 practical technical tasks" | `docs/TASKS.md`, "What is not covered", says four are written | None, and the brief body stops at Task 4 |

Ours, with no brief line asking for them, are `-32002` for unusable credentials, `-32700` and `-32600` for malformed payloads, and ports 8080, 8081 and 8082. So are `CHARS_PER_TOKEN` 4, `BUSY_TIMEOUT_MS` 5000 and `CHUNK_SLICE_CHARS` 4096.

## Numbers with no source

- None. Every number on every surface traces to a constant in `src/`, a line in the brief, or a Makefile command.

## What was run for the live numbers

Mac17,8, Apple M5 Pro, 18 cores, 64 GB, macOS 26.6 build 25G72, CPython 3.13.11 in the uv managed `.venv`. The box was shared with other work throughout, so every timing is a high side reading rather than a quiet box best case.

| What was run | What it printed | When |
| --- | --- | --- |
| `make test`, five runs | 263 passed in 2.52 to 2.77 s | Live provider pass, load average 10 to 11 |
| `make test`, roughly twenty runs | Not recorded | Live provider pass, load average 10 to 128 |
| `make test`, five runs at 199 cases | 2.28 to 2.54 s | First audit, load average 5.3 to 12.9 |
| `make bench`, ten runs | Held 15 on all forty length rows, and 5, 15 and 320 on all thirty shape rows | First audit, load average 5.3 to 12.9 |
| `make bench`, five runs of the seven shape bench | 14.10 to 14.17 s of wall clock each, the five readings in the first token card | First token re-audit, load average 5.8 at the end |
| `make lint`, once | 44 files formatted by ruff, 41 by mypy | First audit |
| `make run-task4`, once | Every routing outcome | First audit |
| `make check`, three runs | Not recorded | Live provider pass |
| `make run-live`, four runs | One completion through the guardrail, from a local server standing in for a provider | Live provider pass |

No `make bench` run was repeated in the live provider pass, so every timing in the first token and held text cards is the earlier one.

## Which tree each card was checked against

| Tree | Cards |
| --- | --- |
| `master` at `0308589`, working tree clean, no remote | Every card, except as below |
| The `scripts/bench_stream.py` fix after `0308589`, where `make bench` still printed the old total time line and had no content shape table | The first token card, and the held text by content shape rows |
| The seven shape bench, since through `0592102` the bench measured only safe prose and reported its near zero result as the whole story | The first token card again, and the 640 card's worse number and limits rows, since that change builds the straddling input |
| This working tree, since `17d269d` added the figures, `tools/draw_figures.py`, `tools/check_claims.py` and the two reports | Every card mentioning any of those |
| This working tree, since the live path landed after `17d269d` (`http_upstream.py`, `http_provider.py`, `scripts/live_stream.py`, two test files), taking the suite from 199 to 263 cases | Every card mentioning it |

## Which numbers a command rechecks

| Surface | Rechecked by |
| --- | --- |
| README prose (267, 159 functions, 640, 320, 583, under 1 ms, 53 chunks, 3000, 60, 429, four characters a token, twenty threads, 50,000 tokens, 8080, 8081, 8082, ten paired trials, `-32602`, `-32001`, Python 3.13) | `make claims`, which fails on any missing match |
| The four badges under the README title, each as its whole image URL, and the seven rows of the first token record table in this file | `make claims`, which builds both from the same sources and fails on a missing string |
| How `make claims` counts | It collects the suite, then runs it, since collection cannot see a skip, and rereads each constant from `src/` and each measurement from `reports/bench_report.json` |
| The 267 and 640 headings here, and the chunks held table in `docs/TASKS.md` | `make claims` |
| The three SVGs under `assets/`, which carry no typed number and read every value from the two reports or a constant in `src/`, and the mermaid block in the README | `make figures-check`, which redraws and compares, after `make claims` in `make check` |
| The timing rows here beyond the first token record table, and `docs/TASKS.md` beyond its chunk table | A reader, since no command reads them |
| The fourteen `make help` lines, the module docstrings, and what `make test`, `make lint`, `make bench`, `make run-task4` and `make run-live` print | A reader running them |

The README opens with `assets/hero.svg` before the title, then four shields.io badges, then the make block, then The gates, and why refusal is the unit, which carries the gate table and the mermaid lanes; How it is built, with `assets/system-map.svg`; The guardrail, and what it costs, with `assets/first-token.svg`; The server, and the clients it met, with the two Inspector screenshots; Decisions worth flagging; The suite, which quotes the `claims ok` line; and What I left out, and why. The seven row first token record table is no longer on that page, it now sits in the first token card above. The counts, the constants from `src/` and the bench measurements quoted in the sentences are pinned by `make claims`, and the diagram and the three figures are pinned by `make figures-check`. The HTTP statuses, the gateway's other JSON-RPC codes, the Inspector version, the refund amount in the screenshots and the chunk sweep range are typed by hand and held by their tests, not by the claims check, so a stale one of those would pass it.

## What a reader could check that this repo does not prove

- No exact 640 seen, since the bench's last shape holds 636 of it at 12 character chunks, leaving four characters unproven rather than half the number.
- No throughput or CPU number, since every timing is the scripted 10 ms chunk delay times chunks held, so nothing measures how fast the redactor itself runs.
- No memory number outside tracemalloc, so a claim about real process memory has no support here.
- No recall or precision for the redactor, since there is no labeled PII corpus and no denominator, only examples.
- The 3000 ms timeout is never raced live, with every timing test at 60 ms and the demo at 300 ms.
- The sqlite limiter is proven across threads in one process, never across processes or on a network filesystem, where locking differs.
- Task 1 has met this repo's own stdio client and the official SDK client in `tests/test_task1_sdk_client.py`, never the Inspector or a desktop host, so compliance with a third party is asserted. MCP Inspector 2.5.0's web UI, started with `make inspector`, connected over stdio, listed both tools and rendered the `-32602` refusal and an accepted refund, and the two screenshots under the schema gate come from that session. Its `--cli` mode failed on its own side, a `NameError` in a Python snippet it injects and then a 15 s connection timeout, so the UI run is the evidence and the CLI is not on the page.
- No coverage measurement exists, so the 267 has no complement.
- Nothing is measured on a second machine or in CI, so every timing is one loaded 18 core laptop.
- A live provider failure cannot change the HTTP status, since `/v1/generate` sends 200 before the first upstream chunk. A 401 or 500 reaches the client as a stream that stops early, and `make run-live` prints the error and exits nonzero.
- Nothing here has spoken to a production provider, so what is proven is the code that would. `make run-live` is where a reader with a key finds out the rest.
- `make lint` says 46 files formatted and 43 typed, and both are right. Ruff 0.16 formats Markdown too, so it counts `README.md`, `docs/REFEREE.md` and `docs/TASKS.md` on top of the 41 Python files mypy counts.
