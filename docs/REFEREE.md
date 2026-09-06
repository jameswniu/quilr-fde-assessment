# Referee cards

One card per number a reviewer sees, written from the code and from live runs rather than from the README.

Audited on `master` at `0308589`, working tree clean, no remote. Two cards are exceptions, the time to first token card and the held text by content shape card. Both describe a fix to `scripts/bench_stream.py` that landed after `0308589`, and both are audited against that fixed worktree instead. `make bench` at `0308589` still prints the old total time line and has no content shape table.

The time to first token card has since been audited a second time, against the seven shape bench. Through `0592102` that bench measured only the safe prose shape and reported its near zero result as if it were the whole story. The same change finally builds an input that nearly reaches the 640 character ceiling, so the hard ceiling card's Sibling and Bound lines are audited here too. The landing page figures, `tools/draw_figures.py`, `tools/check_claims.py` and the two reports they read all landed after `17d269d`. Cards that mention them are audited against this working tree.

The reader-facing surface is `README.md` with its three figures, `docs/TASKS.md`, the thirteen Makefile help lines, the module docstrings, and what `make test`, `make lint`, `make bench` and `make run-task4` print.

The three SVGs carry no number that was typed by hand. `tools/draw_figures.py` reads every value it draws from `reports/bench_report.json`, from `reports/test_report.json`, or from the constant in `src/` that defines it. That last route is where the system map gets the ports, the error codes, the 50,000 token budget and the 3000 ms timeout. `make figures-check` redraws and compares against what is committed, so a figure cannot drift from its generator.

The refusal map under the system map is the exception, because it is hand written mermaid and `figures-check` never sees it. `make claims` reads its node labels back out of the README and fails when any of the six numbers in them stops matching the constant it came from.

The badges and the prose are the parts typed by hand, so `make claims` checks them. It collects the suite for the case and function counts, then runs it for the outcome counts. It rereads `MAX_BUFFERED_CHARS` and `.python-version`, then fails when the three badges, the hero band or the hero alt text stops matching. It runs the suite rather than only collecting it, because collection cannot see a skipped test and the hero band claims a skip count. `make check` puts it before `figures-check` so the figures get compared against a report from this run.

What it does not read is the body prose, which repeats several of the same numbers. A stale figure there is caught by reading rather than by a command. Every measurement a reviewer sees is printed by a command they run themselves.

## Untraceable numbers

None. Every number on every surface traces to a constant in `src/`, a line in the brief, or a command in the Makefile.

## What produced the live numbers

Mac17,8, Apple M5 Pro, 18 cores, 64 GB, macOS 26.6 build 25G72. CPython 3.13.11 in the uv-managed `.venv`.

One minute load average ran between 5.3 and 12.9 on 18 cores across the session. That is a shared box under other work, so every timing here is an upper-ish reading rather than a quiet-box best case. Five `make test` runs, ten `make bench` runs, one `make lint`, one `make run-task4`.

The first token re-audit added five more `make bench` runs on the same box, 14.10 to 14.17 seconds of wall clock each now that the bench times seven shapes. Load average was 5.8 as they finished. Those five are the runs its Sibling line quotes.

## Specifications from the brief, not measurements

These need a citation, not a confidence interval. Each row is the brief's own wording, the constant that holds it, and the test that pins the constant.

| Value | Brief line | Code | Test |
| --- | --- | --- | --- |
| `CUST-XXXXX` | Task 1, "customer_id string formatted as CUST-XXXXX" | `models.py:16` `CUSTOMER_ID_PATTERN` | `test_task1_mcp_server.py`, invalid-id cases |
| Reason length 10 | Task 1, "reason string with minimum length of 10" | `models.py:18` `REASON_MIN_LENGTH` | `test_task1_mcp_server.py`, short-reason cases |
| `-32602` | Task 1, "standard MCP JSON-RPC error codes" | `server.py:125`, `server.py:166` | `test_task1_mcp_server.py`, invalid-params cases |
| `-32001` | Task 2, "return a JSON-RPC Error (-32001: Unauthorized Tool Call)" | `jsonrpc.py:16` | `test_viewer_is_blocked_from_admin_tools` |
| `429` failover | Task 4, "returns a 429 Too Many Requests status" | `router.py`, `ProviderRateLimited` branch | `test_failover_on_a_429` |
| Five tasks | Overview, "consists of 5 practical technical tasks" | `docs/TASKS.md`, "What is not covered", says four are written | None, and the brief body stops at Task 4 |

Several other numbers are ours, not the brief's. `-32002` for unusable credentials, `-32700` and `-32600` for malformed payloads, ports 8080, 8081 and 8082, `CHARS_PER_TOKEN` 4, `BUSY_TIMEOUT_MS` 5000 and `CHUNK_SLICE_CHARS` 4096 are all this repo's own design choices. No line of the brief asks for any of them.

## Cards

### 50,000 tokens per minute per tenant key

```
Claim     50,000 tokens a minute per tenant API key. It shows up in docs/TASKS.md under Task
          4, and in the system map's limiter card, which reads DEFAULT_LIMIT_TOKENS out of
          rate_limiter.py line 31 at draw time.
Unit      Estimated tokens, summed over the charges written for one key digest inside the
          half open interval from 60 seconds ago to now. These are our own estimates, and no
          provider reported them.
Match     Admission adds the new charge to that running sum and compares it to 50,000. A
          request landing exactly on the limit is admitted, and one token more is refused. A
          charge made at t still counts at t plus 59.999 and is gone at t plus 60.0.
Set       The brief's own example figure, "e.g., maximum 50,000 tokens/minute per tenant API
          key". So it is a default argument rather than a capacity anyone measured, and
          callers pass their own.
Command   make run-task4 exercises it. The constant is asserted by
          test_the_brief_default_is_fifty_thousand_tokens_a_minute, and the boundary by
          test_the_window_boundary_is_exact.
Sibling   The same limiter under contention. Twenty threads race for ten 5,000 token slots,
          exactly ten get in, and tokens_in_window lands on 50,000. Twelve concurrent router
          calls against a 280 token budget serve four and refuse eight.
Bound     It bounds estimated tokens at four characters per token. Nothing reconciles that
          against what a provider actually bills. The eviction test shows rows leaving the
          table, which is a different thing from the estimate being right.
Knob      The limit_tokens argument, and under it CHARS_PER_TOKEN. Lower that divisor and
          each prompt charges more, so the same 50,000 admits fewer requests.
```

### 3000 ms primary timeout

```
Claim     3000 ms. It appears in the README under What each task owns, and in docs/TASKS.md
          under Task 4. The system map's router card reads DEFAULT_TIMEOUT_MS out of
          router.py line 38 at draw time.
Unit      Milliseconds from dispatching the primary provider call to giving up on it and
          starting the secondary, counted per request.
Match     The timeout races the primary instead of always firing. A primary that answers
          inside the window is used and the secondary is never called. A timed out call is
          cancelled, which the test asserts through primary.completed_calls == 0.
Set       The brief's own figure, "times out after 3000ms". A default argument, and not a
          latency budget anyone here measured.
Command   make run-task4 for the demo, tests in test_task4_router.py, the constant pinned by
          test_the_brief_default_timeout_is_three_seconds.
Sibling   Nothing in this repo ever runs a live race at 3000 ms. Every timing test uses
          FAST_TIMEOUT_MS 60 and the demo in __main__.py uses 300, both shortened so the
          suite does not sit and wait.
Bound     One test asserts the integer equals 3000. No test asserts behaviour at 3000, so
          the number is pinned as a value and exercised only as a shape.
Knob      The timeout_ms argument. Lower it and a slow but healthy primary gets abandoned.
          Raise it and a hung primary holds the request longer before failover.
```

### 199 tests pass

```
Claim     "199 passed" from make test. On the page it is the tests badge, the hero band's
          first tile, the hero alt text and the system map's stat box.
Unit      pytest cases collected under tests/. That is 109 test functions, which parametrize
          expands into 199 cases. The split by task is in the table below.
Match     A case counts when pytest reports it green under pyproject.toml, testpaths tests,
          asyncio_mode auto. make claims counts skips, xfails and xpasses separately. It
          fails when the hero band's skip count stops matching the run, so the "0 skips"
          beside the 199 is measured.
Set       Every fixture is inside the repo and the assertions are the labels, so this scores
          the suite against the code and never against an outside corpus. Nothing touches
          the network. Task 1 drives a real subprocess over stdio, and tasks 2 and 3 drive
          their ASGI apps in process.
Command   make test, which is uv run pytest. make claims collects and then runs the suite,
          writes both counts to reports/test_report.json, and fails when the badge, the hero
          band or the hero alt text disagrees with that run.
Sibling   Counted by function the same suite is 109. Counted as coverage of the code it is
          nothing at all, because coverage is never measured here.
Bound     A green suite says the written cases hold. It says nothing about the cases nobody
          wrote, and with no coverage number there is no way to bound what is missing.
Knob      One extra tuple in an existing parametrize decorator moves 199 without testing a
          single new behaviour, which is why the function count sits beside it. A skip
          marker moves it the other way, which is what the skip count is for.
```

| Task | Cases | Functions |
| --- | --- | --- |
| Task 1, MCP server | 42 | 18 |
| Task 2, gateway | 24 | 13 |
| Task 3, stream guard | 85 | 37, being 7 endpoint and 78 redactor |
| Task 4, model router | 48 | 41, being 22 limiter and 26 router |

### Suite wall time, 2.28 to 2.54 seconds

```
Claim     The suite finishes in a couple of seconds, printed as "199 passed in 2.54s" by
          make test.
Unit      Seconds of wall clock for one full make test on a warm environment, collection
          included and uv sync excluded.
Match     The instrument is pytest's own summary line. It is cross checked with
          /usr/bin/time -p wrapped around make test, which adds the uv and interpreter
          start.
Set       Five consecutive runs on the box named above, load average between 7.7 and 11.7 on
          18 cores while they ran.
Command   make test, and /usr/bin/time -p make test for the wall figure.
Sibling   pytest reported 2.54, 2.41, 2.42, 2.28 and 2.39 seconds. Shell wall time for the
          same five was 2.82, 2.65, 2.66, 2.48 and 2.62, so the harness costs roughly 0.25
          seconds on top.
Bound     Five runs on one loaded laptop. No cold cache run, no CI run, no second machine.
          This says the suite is cheap here and nothing about anywhere else.
Knob      The two threaded sqlite tests and the task 1 subprocess dominate, so a slower disk
          or a busier box moves this more than any code change would.
```

### Held text stays at 15 characters as the response grows a thousandfold

```
Claim     "held 15 chars" on all four rows of make bench, from a 3,900 character response to
          a 3,900,000 character one.
Unit      peak_buffered_chars, the most characters the redactor was ever holding back at one
          time over one whole response.
Match     The instrument is the redactor's own counter, updated on every emit at redactor.py
          line 111. _peak_for_length reads it after flush, in scripts/bench_stream.py lines
          120 to 135.
Set       A synthetic response built by repeating one 39 character prose chunk, then
          appending the same 16 character tail " ada@example.com" at the end of all four
          sizes.
Command   make bench, which runs uv run python scripts/bench_stream.py.
Sibling   make bench prints a second table beside this one, at a fixed size near 100,000
          characters. Pure prose with no partial pattern peaks at 5. This same mid email
          ending peaks at 15. One unbroken 100,000 character token peaks at exactly 320. Two
          more points are measured outside the script and never printed. The 428 character
          DEMO_RESPONSE peaks at 36. A 316 character legal email split into 7 character
          chunks peaks at 314.
Bound     The flatness in this table is real and it is only half the claim. The other half,
          printed beside it, is that content shape moves the number, from 5 for plain prose
          up to 320 for the longest possible match. Neither table alone would show that this
          is a property of the content and not of the length. Together they do.
Knob      The longest token in the text. A longer trailing token raises this number and a
          longer response does not.
```

Ten `make bench` runs, forty readings, every one of them 15. The same ten runs read the content shape table thirty times, every one of them 5, 15 and 320.

### Hard ceiling 640 characters

```
Claim     "hard ceiling 640 characters, whatever the response length", from make bench and
          redactor.py line 22 MAX_BUFFERED_CHARS.
Unit      Characters. The most the redactor can ever hold back, for any input, at any
          chunking.
Match     This one is derived rather than measured. 640 is 2 times MAX_MATCH_LENGTH 320.
          That 320 is the longest match any pattern can produce. It is an email at the RFC
          5321 limits, a 64 character local part plus "@" plus a 255 character domain. The
          cut is never further back than 320, and a match straddling that cut can pull it
          back 320 more, which is where the doubling comes from.
Set       The three patterns in patterns.py, all written with bounded quantifiers so the
          worst case length is computable. Email 320, card 37 for 19 digits with 18
          separators, SSN 11.
Command   make bench prints it. The derivation is patterns.py line 61 and redactor.py line
          22. The tests that hold it are test_buffer_never_grows_with_response_length,
          test_held_text_is_bounded_even_by_one_enormous_token and
          test_one_enormous_chunk_is_still_scanned_in_bounded_slices.
Sibling   The highest value seen here is 636, four short of the ceiling. It is held while
          the first token bench streams its last shape, a 320 character address followed by
          "_" and 320 more token characters in 12 character chunks. make bench prints that
          636 under the ceiling line and writes it to reports/bench_report.json, so the hero
          band quotes it and make claims fails if the alt text stops matching. The other
          figure the bench prints is 320, from the unbroken 100,000 character run in the
          content shape table.
Bound     640 is still an analytic bound with no exact witness. The gap is four characters
          rather than half the number, since the bench builds the straddling case that
          reaches 636. The doubling is seen happening, and only those last four characters
          rest on reading the code.
Knob      _EMAIL_DOMAIN_MAX at 255 and _EMAIL_LOCAL_MAX at 64. Tighten either and the
          ceiling drops, at the cost of silently missing a legal address, which is the trade
          the boundary test records.
```

### Guardrail adds about 0 ms to first token on safe prose, about 582 ms worst case

```
Claim     The seven row first token table from make bench. Its headline reads "worst case,
          the guardrail adds 582.32 ms to first token, on a response opening with a 320 char
          email inside a token". The 0.02 ms safe prose row, with its "the range straddles
          zero" note, is the best row of that table rather than the whole claim. On the page
          the same table is assets/first-token.svg, one bar per shape, and its worst and
          best rows are the hero band's middle tile.
Unit      Milliseconds from starting the stream to the first non-empty chunk. Each figure is
          the median of ten paired differences for one leading content shape. A pair is one
          back to back reading of the raw upstream and the guarded one. Beside it sits the
          same cost counted in upstream chunks held.
Match     The instrument is time.perf_counter, wrapped by _first_token_seconds and run in
          pairs by _paired_trials, at scripts/bench_stream.py lines 41 to 70. The upstream
          is scripted, with a 10 ms per chunk delay and 12 character chunks, so no network
          is involved and what is left is the guardrail's own overhead. Each reading stops
          at the first chunk instead of draining the response, which is what keeps seventy
          pairs inside a fourteen second bench. The cost is always whole chunk delays,
          because nothing can leave while the opening of the response could still be part of
          a pattern. The waits column counts those delays at lines 104 to 117, and reads 0,
          1, 1, 1, 26, 26 and 53 down the seven shapes. docs/TASKS.md carries the same
          column beside its labels.
Set       Seven responses differing only in their opening, built by _leading_shapes at lines
          72 to 101. Ten paired trials each, one prompt, no warm up. The seven openings:
            1  the 428 character DEMO_RESPONSE, which is safe prose
            2  "ada@example.com"
            3  "4111 1111 1111 1111"
            4  "123-45-6789"
            5  the longest legal address the pattern matches, 320 characters
            6  1,000 "x" characters
            7  that same address, then "_", then 320 "z" characters
          Openings 2 to 7 each sit in front of the same prose tail.
Command   make bench, with the instrument and the table both in scripts/bench_stream.py.
          Then make figures redraws assets/first-token.svg and the hero band from
          reports/bench_report.json.
Sibling   Five runs, in the table below. The waits column read the same seven integers in
          all five. A sixth run read safe prose at 0.00 to 0.99 ms and printed no straddling
          note at all. That note is a property of the run, and not a guarantee. The best row
          and the worst row of one bench differ by four orders of magnitude, which is why
          quoting only the prose row was the defect this card records.
Bound     One chunk size and one upstream cadence on one loaded laptop. The figure and the
          hero tile show whatever the last make bench measured. So the milliseconds move by
          a few between runs while the waits column does not, and make figures-check reports
          that move as drift. The wait is whole chunk delays, so a provider sending larger
          chunks clears the same window in fewer of them and a slower provider pays more. No
          real provider is measured here. The last shape is the worst this design allows
          rather than one drawn from real traffic, and nothing here says how often any of
          the seven occurs.
Knob      UPSTREAM_DELAY_SECONDS at 0.01 and CHUNK_SIZE at 12, which together set what one
          chunk of waiting costs. MAX_MATCH_LENGTH at 320 sets how many chunks the last
          three shapes wait. TRIAL_COUNT at 10 narrows the ranges if raised, on a bench that
          already takes fourteen seconds.
```

| Response opens with | Five readings, ms |
| --- | --- |
| Safe prose | 0.02, 0.01, 0.02, 0.06, 0.03, every range straddling zero |
| Any of the three short values | 11.02 to 11.17 |
| A 320 char email, or a 1,000 char token | 284.84 to 286.44 |
| A 320 char email inside a token | 582.32, 582.69, 582.29, 583.84, 583.45 |

### Traced peak stays in kilobytes on a 3.9 million character response

```
Claim     "traced peak 2.0 KiB" on the largest bench row, beside a 3,900,000 character
          response.
Unit      Kibibytes. tracemalloc's peak traced allocation across feeding the whole response,
          Python heap only.
Match     Start tracemalloc, feed the response, read get_traced_memory()[1]. That happens in
          _peak_for_length at scripts/bench_stream.py lines 120 to 135, with the redactor's
          output dropped the way a forwarding proxy would drop it.
Set       The same synthetic response as the held text card, four sizes from 3,900 to
          3,900,000 characters.
Command   make bench.
Sibling   The permanent test is test_peak_memory_does_not_track_response_length. It streams
          7.8 million characters and asserts the peak is under 64 KiB, and under one
          hundredth of the streamed size.
Bound     Across ten runs this row read 2.0 to 6.6 KiB and the 39,000 character row read 3.0
          to 11.2 KiB. The small rows sometimes exceed the large ones, so allocator noise
          dominates the reading. It shows the absence of growth and is not a memory figure
          worth quoting.
Knob      tracemalloc measures Python allocations, so it never sees interpreter or OS
          resident memory. Nothing here reports RSS.
```

## What a reviewer could check that this repo does not prove

- No exact witness for the 640 character ceiling. The bench's last shape builds the straddling case and holds 636 of the 640 at 12 character chunks, so what is unproven is four characters rather than half the number.
- No throughput or CPU number anywhere. The bench reports latency and held state, never characters per second. Every timing it prints is the scripted 10 ms chunk delay times how many chunks were held, so nothing measures how fast the redactor itself runs.
- No memory number outside tracemalloc. Resident set size is never read, so a claim about real process memory has no support here.
- No recall or precision for the redactor. There is no labeled PII corpus and no denominator, so every redaction result is example based, and the suite cannot say what fraction of real PII would be caught.
- The 3000 ms timeout is never raced live. Every timing test runs at 60 ms and the demo at 300 ms.
- The sqlite limiter is proven across threads in one process. Never across processes, and never on a network filesystem, where its locking behaviour differs.
- Task 1 is proven against this repo's own stdio client. It has not been run against a real MCP client such as the Inspector or a desktop host, so protocol compliance is asserted rather than demonstrated against a third party.
- No coverage measurement exists, so the 199 has no complement.
- Nothing is measured on a second machine or in CI, so every timing here is one loaded 18-core laptop.
- Two counts in `make lint` output look inconsistent and are not. Ruff says 38 files formatted because ruff 0.16 formats Markdown too, so it counts README.md, docs/REFEREE.md and docs/TASKS.md on top of the 35 Python files. Mypy says 35 because it counts only the Python.
