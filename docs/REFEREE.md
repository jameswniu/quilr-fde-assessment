# Referee cards

One card per number a reviewer sees, written from the code and from live runs rather than from the README. Audited on `master` at `0308589`, working tree clean, no remote. Two exceptions are the time to first token card and the held text by content shape card below, both of which describe a fix to `scripts/bench_stream.py` landing after `0308589` rather than the script as it stood there, and are audited against that fixed worktree instead. `make bench` at `0308589` alone still prints the old total time line and has no content shape table. The time to first token card has since been audited a second time, against the multi shape first token bench landing in this change, because through `0592102` that bench measured only the safe prose shape and reported its near zero result as if it were the whole story. That same change is what finally builds an input that nearly reaches the 640 character ceiling, so the hard ceiling card's Sibling and Bound lines are audited here too.

This repo quotes almost nothing. The whole reader-facing surface is `README.md`, the ten Makefile help lines, the module docstrings, and what `make test`, `make lint`, `make bench` and `make run-task4` print. The claim harvester finds three number-shaped claims in the README, two of which are specifications lifted from the brief. The Task 3 paragraph adds the first token costs, and every one of those is a cell `make bench` prints, the chunk counts in its waits column and the fixture lengths in its row labels. Beyond those the README carries only JSON-RPC error codes and the three port numbers, all of which sit in the table below. Every measurement a reviewer sees is printed by a command they run themselves.

## Untraceable numbers

None. Every number on every surface traces to a constant in `src/`, a line in the brief, or a command in the Makefile.

## What produced the live numbers

Mac17,8, Apple M5 Pro, 18 cores, 64 GB, macOS 26.6 build 25G72. CPython 3.13.11 in the uv-managed `.venv`. One minute load average was between 5.3 and 12.9 on 18 cores across the session, which is a shared box under other work, so every timing here is an upper-ish reading rather than a quiet-box best case. Five `make test` runs, ten `make bench` runs, one `make lint`, one `make run-task4`. The time to first token re-audit added five more `make bench` runs on the same box, 14.10 to 14.17 seconds of wall clock each now that the bench times seven leading shapes, one minute load average 5.8 as they finished, and those five are the ones its Sibling line quotes.

## Specifications from the brief, not measurements

These need a citation, not a confidence interval. Each row is the brief's own wording, the constant that holds it, and the test that pins the constant.

| Value | Brief line | Code | Test |
| --- | --- | --- | --- |
| `CUST-XXXXX` | Task 1, "customer_id string formatted as CUST-XXXXX" | `models.py:16` `CUSTOMER_ID_PATTERN` | `test_task1_mcp_server.py`, invalid-id cases |
| reason length 10 | Task 1, "reason string with minimum length of 10" | `models.py:18` `REASON_MIN_LENGTH` | `test_task1_mcp_server.py`, short-reason cases |
| `-32602` | Task 1, "standard MCP JSON-RPC error codes" | `server.py:125`, `server.py:166` | `test_task1_mcp_server.py`, invalid-params cases |
| `-32001` | Task 2, "return a JSON-RPC Error (-32001: Unauthorized Tool Call)" | `jsonrpc.py:16` | `test_viewer_is_blocked_from_admin_tools` |
| `429` failover | Task 4, "returns a 429 Too Many Requests status" | `router.py`, `ProviderRateLimited` branch | `test_failover_on_a_429` |
| five tasks | Overview, "consists of 5 practical technical tasks" | README line 55 says four are written | none, and the brief body stops at Task 4 |

`-32002` (401 for unusable credentials), `-32700` and `-32600` (400 for malformed payloads), ports 8080, 8081 and 8082, `CHARS_PER_TOKEN` 4, `BUSY_TIMEOUT_MS` 5000 and `CHUNK_SLICE_CHARS` 4096 are none of the above. They are this repo's own design choices, and no line of the brief asks for any of them.

## Cards

### 50,000 tokens per minute per tenant key

```
Claim     50,000 tokens a minute per tenant API key (README line 46, rate_limiter.py line 31 DEFAULT_LIMIT_TOKENS, Makefile has no number)
Unit      the sum of the token charges written for one key digest inside the half open interval (now minus 60 seconds, now], counted in estimated tokens, not provider-reported ones
Match     admission compares that running sum plus the new charge against 50,000, so a request that lands exactly on the limit is admitted and one token more is refused, and a charge made at t is still counted at t plus 59.999 and gone at t plus 60.0 exactly
Set       this is the brief's own example figure, "e.g., maximum 50,000 tokens/minute per tenant API key", so it is a default argument rather than a measured capacity, and callers pass their own
Command   make run-task4 exercises it, the constant is asserted by test_the_brief_default_is_fifty_thousand_tokens_a_minute, the boundary by test_the_window_boundary_is_exact
Sibling   the same limiter under contention: twenty threads racing for ten 5,000 token slots admit exactly ten and leave tokens_in_window at 50,000, and twelve concurrent router calls against a 280 token budget serve four and refuse eight
Bound     it bounds estimated tokens only, at four characters per token, never reconciled against what a provider actually bills, and the eviction test shows rows leaving the table, not the estimate being right
Knob      the limit_tokens argument, and beneath it CHARS_PER_TOKEN, since a lower divisor charges more per prompt and the same 50,000 admits fewer requests
```

### 3000 ms primary timeout

```
Claim     3000 ms (README line 49, router.py line 38 DEFAULT_TIMEOUT_MS)
Unit      milliseconds from dispatching the primary provider call to giving up on it and starting the secondary, per request
Match     the timeout races the primary rather than always firing, so a primary answering inside the window is used and the secondary is never called, and a timed out call is cancelled rather than left running, which the test asserts through primary.completed_calls == 0
Set       the brief's own figure, "times out after 3000ms", so it is a default argument and not a measured latency budget
Command   make run-task4 for the demo, tests in test_task4_router.py, the constant pinned by test_the_brief_default_timeout_is_three_seconds
Sibling   nothing in this repo ever runs a live race at 3000 ms: every timing test uses FAST_TIMEOUT_MS 60 and the demo in __main__.py uses 300, both shortened so the suite does not sit and wait
Bound     one test asserts the integer equals 3000 and no test asserts behaviour at 3000, so the number is pinned as a value and exercised only as a shape
Knob      the timeout_ms argument, lower and a slow but healthy primary is abandoned, higher and a hung primary holds the request longer before failover
```

### 199 tests pass

```
Claim     "199 passed" from make test, and README line 3, "one test suite"
Unit      pytest cases collected under tests/, which is 109 test functions expanded by parametrize into 199 cases: task 1 gets 42 cases from 18 functions, task 2 gets 24 from 13, task 3 gets 85 from 37 (7 endpoint, 78 redactor), task 4 gets 48 from 41 (22 limiter, 26 router)
Match     a case counts when pytest reports it green under pyproject.toml, testpaths tests, asyncio_mode auto, and there are no skips, xfails or quarantined specs in the run
Set       every fixture is inside the repo and the assertions are the labels, so this scores the suite against the code, never against an outside corpus, and the suite touches no network: task 1 drives a real subprocess over stdio, task 2 and task 3 drive the ASGI apps in process
Command   make test, which is uv run pytest, counts from uv run pytest --collect-only -q
Sibling   counted by function rather than by case the same suite is 109, and counted as coverage of the code it is nothing at all, because coverage is never measured in this repo
Bound     a green suite says the written cases hold and says nothing about the ones nobody wrote, and with no coverage number there is no way to bound what is unwritten
Knob      one extra tuple in an existing parametrize decorator moves 199 without testing a single new behaviour, which is why the function count sits beside it
```

### Suite wall time, 2.28 to 2.54 seconds

```
Claim     the suite finishes in a couple of seconds, printed as "199 passed in 2.54s" by make test
Unit      seconds of wall clock for one full make test on a warm environment, collection included, uv sync excluded
Match     the instrument is pytest's own summary line, cross checked with /usr/bin/time -p wrapped around make test, which adds the uv and interpreter start
Set       five consecutive runs on the box named above, one minute load average between 7.7 and 11.7 on 18 cores while they ran
Command   make test, and /usr/bin/time -p make test for the wall figure
Sibling   pytest reported 2.54, 2.41, 2.42, 2.28 and 2.39 seconds, shell wall time for the same five was 2.82, 2.65, 2.66, 2.48 and 2.62, so the harness costs roughly 0.25 seconds on top
Bound     five runs on one loaded laptop, no cold cache run, no CI run, no second machine, so this says the suite is cheap here and nothing about anywhere else
Knob      the two threaded sqlite tests and the task 1 subprocess dominate, so a slower disk or a busier box moves this more than any code change would
```

### Held text stays at 15 characters as the response grows a thousandfold

```
Claim     "held 15 chars" on all four rows of make bench, from a 3,900 character response to a 3,900,000 character one
Unit      peak_buffered_chars, the largest number of characters the redactor was ever holding back at one time, over one whole response
Match     the instrument is the redactor's own counter, updated on every emit at redactor.py line 111, read after flush by _peak_for_length in scripts/bench_stream.py lines 120 to 135
Set       a synthetic response built by repeating one 39 character prose chunk, then appending the same 16 character tail " ada@example.com" at the end of every one of the four sizes
Command   make bench, which runs uv run python scripts/bench_stream.py
Sibling   make bench now prints a second table beside this one, at a fixed response size near 100,000 characters. Pure prose with no partial pattern peaks at 5, this same mid email ending peaks at 15, and one unbroken 100,000 character token peaks at exactly 320. Two more points measured outside the script and not printed by it, the 428 character DEMO_RESPONSE peaks at 36 and a 316 character legal email split into 7 character chunks peaks at 314
Bound     the flatness in this table is real, and it is only half the claim. The other half, now printed beside it, is that content shape is what actually moves the number, from 5 for plain prose up to 320 for the longest possible match, with this fixture's 15 in between. Neither table alone would support the claim that this is a content property rather than a length property, together they do
Knob      the longest token in the text, not the length of the text, so a longer trailing token raises this number and a longer response does not
```

Ten `make bench` runs, forty readings, every one of them 15. The same ten runs read the content shape table thirty times, every one of them 5, 15 and 320.

### Hard ceiling 640 characters

```
Claim     "hard ceiling 640 characters, whatever the response length" (make bench, redactor.py line 22 MAX_BUFFERED_CHARS)
Unit      characters, the most the redactor can ever hold back, for any input, at any chunking
Match     this is derived, not measured. 640 is 2 times MAX_MATCH_LENGTH 320, and 320 is the longest match any pattern can produce: an email at the RFC 5321 limits, a 64 character local part plus "@" plus a 255 character domain. The cut is never further back than 320, and a match straddling that cut can pull it back 320 more, which is the doubling
Set       the three patterns in patterns.py, all written with bounded quantifiers so the worst case length is computable: email 320, card 37 (19 digits with 18 separators), SSN 11
Command   make bench prints it, the derivation is patterns.py line 61 and redactor.py line 22, and the tests that hold it are test_buffer_never_grows_with_response_length, test_held_text_is_bounded_even_by_one_enormous_token and test_one_enormous_chunk_is_still_scanned_in_bounded_slices
Sibling   the highest value observed here is 636, four short of the ceiling, held while the first token bench streams its last shape, a 320 character address followed by "_" and 320 more token characters in 12 character chunks. That 636 is measured out of band and not printed, because the first token table reports timings only. The highest figure the bench does print is 320, from the 100,000 character unbroken run in the content shape table
Bound     640 is still an analytic bound with no exact witness, but the gap is four characters rather than half the number. The bench now builds the straddling case that reaches 636, so the doubling is seen happening and only the last four characters rest on reading the code
Knob      _EMAIL_DOMAIN_MAX at 255 and _EMAIL_LOCAL_MAX at 64. Tighten either and the ceiling drops, at the cost of silently missing a legal address, which is the trade the boundary test records
```

### Guardrail adds about 0 ms to first token on safe prose, about 582 ms worst case

```
Claim     the seven row first token table from make bench, headlined by "worst case, the guardrail adds 582.32 ms to first token, on a response opening with a 320 char email inside a token". The old single figure, the 0.02 ms safe prose row with its "the range straddles zero" note, is now the best row of that table rather than the whole claim
Unit      milliseconds from starting the stream to receiving the first non-empty chunk, the median of ten paired differences per leading content shape, each pair a back to back reading of the raw upstream and the guarded one, beside the same cost counted in upstream chunks held
Match     the instrument is time.perf_counter, wrapped by _first_token_seconds and run in pairs by _paired_trials in scripts/bench_stream.py lines 41 to 70, against a scripted upstream with a 10 ms per chunk delay and 12 character chunks, so no network is involved and the figure is the guardrail's own overhead. Each reading stops at the first chunk rather than draining the whole response, which is what keeps seventy pairs inside a fourteen second bench. The cost is always whole chunk delays, because nothing can be emitted while the opening of the response could still be part of a pattern, so the waits column counts them directly at lines 104 to 117 and reads 0 for safe prose, 1 for each of the three short values, 26 for the 320 character address and again for the 1,000 character token, since each runs past the window and then ends at a space, and 53 for the buried one
Set       seven responses differing only in their opening, built by _leading_shapes at lines 72 to 101. The 428 character DEMO_RESPONSE for safe prose, then the same prose tail behind "ada@example.com", behind "4111 1111 1111 1111", behind "123-45-6789", behind the longest legal address the pattern matches at 320 characters, behind 1,000 "x" characters, and behind that same address followed by "_" and 320 "z" characters. Ten paired trials each, one prompt, no warm up iteration
Command   make bench, scripts/bench_stream.py lines 41 to 70 for the instrument and 163 to 199 for the table
Sibling   five make bench runs read safe prose at 0.02, 0.01, 0.02, 0.06 and 0.03 ms with every range straddling zero, and read the worst shape at 582.32, 582.69, 582.29, 583.84 and 583.45 ms with no range near zero. Between them the three short values cost 11.02 to 11.17 ms, and the 320 character address and the 1,000 character token, the two that wait 26, cost 284.84 to 286.44 ms. The waits column read the same seven integers in all five runs. A sixth run read safe prose at 0.00 to 0.99 ms and printed no straddling note at all, so that note is a property of the run rather than a guarantee. The best row and the worst row of the same bench differ by four orders of magnitude, which is why quoting only the prose row was the defect this card records
Bound     one chunk size and one upstream cadence on one loaded laptop. The wait is whole chunk delays, so a provider sending larger chunks clears the same window in fewer of them and a slower provider pays more, and no real provider is measured here. The last shape is the worst this design allows rather than a shape drawn from real traffic, since a match can only pull the cut back to its own start while fewer than 640 characters have arrived, and nothing here says how often any of the seven shapes occurs
Knob      UPSTREAM_DELAY_SECONDS at 0.01 and CHUNK_SIZE at 12, which together set what one chunk of waiting costs, MAX_MATCH_LENGTH at 320, which sets how many chunks the last three shapes wait, and TRIAL_COUNT at 10, where more trials narrow the ranges at the cost of a bench that already takes fourteen seconds
```

### Traced peak stays in kilobytes on a 3.9 million character response

```
Claim     "traced peak 2.0 KiB" on the largest bench row, beside a 3,900,000 character response
Unit      kibibytes, tracemalloc's peak traced allocation across feeding the whole response, Python heap only
Match     the instrument is tracemalloc.start, feed the response, read get_traced_memory()[1], in _peak_for_length at scripts/bench_stream.py lines 120 to 135, with the redactor's output dropped as a forwarding proxy would drop it
Set       the same synthetic response as the held-text card, four sizes from 3,900 to 3,900,000 characters
Command   make bench
Sibling   the permanent test is test_peak_memory_does_not_track_response_length, which streams 7.8 million characters and asserts the peak is under 64 KiB and under one hundredth of the streamed size
Bound     across ten runs this row read 2.0 to 6.6 KiB and the 39,000 character row read 3.0 to 11.2 KiB, so the small rows sometimes exceed the large ones and the reading is dominated by allocator noise, which means it shows the absence of growth and not a memory figure worth quoting
Knob      tracemalloc measures Python allocations, so it never sees interpreter or OS resident memory, and nothing here reports RSS
```

## What a reviewer could check that this repo does not prove

- No exact witness for the 640 character ceiling. The first token bench's last shape does construct the straddling case and holds 636 of the 640 at 12 character chunks, so what is unproven is the last four characters rather than the whole second half, and that 636 is measured out of band rather than printed.
- No throughput or CPU number anywhere. The bench reports latency and held state, never characters per second, and every timing it prints is the scripted 10 ms chunk delay multiplied by how many chunks were held, so nothing here measures how fast the redactor itself runs.
- No memory number outside tracemalloc. Resident set size is never read, so a claim about real process memory has no support here.
- No recall or precision for the redactor. There is no labeled PII corpus and no denominator, so every redaction result is example based and the suite cannot say what fraction of real PII would be caught.
- The 3000 ms timeout is never raced live. Every timing test runs at 60 ms and the demo at 300 ms.
- The sqlite limiter is proven across threads in one process, never across processes, and never on a network filesystem, where its locking behaviour differs.
- Task 1 is proven against this repo's own stdio client, not against a real MCP client such as the Inspector or a desktop host, so protocol compliance is asserted rather than demonstrated against a third party.
- No coverage measurement exists, so the 199 has no complement.
- Nothing is measured on a second machine or in CI, so every timing here is one loaded 18-core laptop.
- Two counts in `make lint` output look inconsistent and are not. Ruff says 35 files formatted because ruff 0.16 formats Markdown as well, so it counts README.md and docs/REFEREE.md on top of the 33 Python files. Mypy says 33 source files because it counts only the Python.
