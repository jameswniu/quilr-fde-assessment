"""Fail the build when a number on the page no longer matches what the repo measures.

    uv run python tools/check_claims.py

The README carries its numbers three ways: a badge wall under the title, a first token record
table, and a handful of sentences, covering how many test cases are green, the most text the
redactor ever holds back, what the guardrail adds to the first token on its best and worst
opening, and the constants those sentences lean on. A number nothing rechecks is a number that
drifts, so this reruns the suite, rereads each constant from source and each measurement from
``reports/bench_report.json``, and exits nonzero when a badge, a record row or the prose
disagrees with any of them. A badge is pinned as its whole image URL, built here from the same
sources, so a hand edit to one cannot survive a run. The
suite is run rather than only collected, because collection cannot see a skip, and a skipped case
would still be counted as one. Two numbers come from the tests rather than from ``src/``, the
shortened timeout the timing tests run at and the thread count the limiter is raced with, and
each is read out of its test file by name.

Two other pages repeat some of the same numbers. The card headings in ``docs/REFEREE.md`` carry
the test count and the hold bound, and the chunk table in ``docs/TASKS.md`` carries the bench's
wait counts, so both are read as well.

The measured counts are written to ``reports/test_report.json``, which is what
``tools/draw_figures.py`` reads. The prose is the claim, this file is the check, and the report is
the single source the figures and the check both use.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import mcp.types

from task2_mcp_gateway import jsonrpc
from task2_mcp_gateway.__main__ import DOWNSTREAM_PORT, GATEWAY_PORT
from task3_stream_guard.__main__ import PORT as GUARD_PORT
from task3_stream_guard.patterns import MAX_MATCH_LENGTH
from task3_stream_guard.redactor import MAX_BUFFERED_CHARS
from task4_model_router.providers import ProviderRateLimited
from task4_model_router.rate_limiter import DEFAULT_LIMIT_TOKENS
from task4_model_router.router import CHARS_PER_TOKEN, DEFAULT_TIMEOUT_MS

ROOT: Final = Path(__file__).resolve().parent.parent
README_PATH: Final = ROOT / "README.md"
REFEREE_PATH: Final = ROOT / "docs" / "REFEREE.md"
TASKS_PATH: Final = ROOT / "docs" / "TASKS.md"
REPORT_PATH: Final = ROOT / "reports" / "test_report.json"
BENCH_PATH: Final = ROOT / "reports" / "bench_report.json"
LICENSE_PATH: Final = ROOT / "LICENSE"

#: The badge wall's two colours, the slate blue on the headline badge and the warm grey on the rest.
#: The same slate blue and grey tools/draw_figures.py draws with.
BADGE_ACCENT: Final = "2F5D8A"
BADGE_GREY: Final = "6B6B66"


def _pytest(*arguments: str) -> str:
    """Run pytest with the project's own addopts cleared, and return what it printed."""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout + completed.stderr


def collect_suite() -> tuple[int, int]:
    """Return (test cases, test functions) by asking pytest to collect them.

    Cases and functions are different numbers because parametrize expands one function into
    several cases, and quoting only the larger one would let a tuple added to an existing
    decorator move the count without testing a single new behaviour.
    """
    output = _pytest("--collect-only", "-q")
    node_ids = [line for line in output.splitlines() if "::" in line]
    if not node_ids:
        raise SystemExit(f"pytest collected nothing; refusing to publish a test count of zero.\n{output}")
    return len(node_ids), len({line.split("[", 1)[0] for line in node_ids})


def run_suite() -> dict[str, int]:
    """Return the outcome counts from a real run, which is the only place a skip is visible.

    Collection cannot see a skip, and pytest exits zero with skipped tests in it, so a count built
    from collection alone can say green over a suite that quietly stopped running part of itself.
    This reads the summary line the run prints instead.
    """
    output = _pytest("-q")
    counts = {
        name: int(found.group(1)) if (found := re.search(rf"(\d+) {name}", output)) else 0
        for name in ("passed", "skipped", "xfailed", "xpassed", "failed", "error")
    }
    if not counts["passed"]:
        raise SystemExit(f"pytest reported no passing tests; refusing to publish a green count.\n{output}")
    return counts


def declared_python_version() -> str:
    """The interpreter the project pins, read from .python-version."""
    return (ROOT / ".python-version").read_text().strip()


def bench_report() -> dict[str, Any]:
    """The bench's own record of the last run."""
    if not BENCH_PATH.exists():
        raise SystemExit("reports/bench_report.json is missing. Run `make bench` before checking claims.")
    data: dict[str, Any] = json.loads(BENCH_PATH.read_text())
    return data


def stated_ms(value: float) -> str:
    """Milliseconds the way the page states them.

    Duplicated from tools/draw_figures.py on purpose. The figure draws this string from the report
    and this check reads it back off the prose, so the two agree only when both came from the same
    report. A reading inside the instrument's own noise is "under 1 ms" rather than a rounded zero.
    """
    return "under 1 ms" if abs(value) < 1 else f"{value:.0f} ms"


#: Small counts are spelled out in the prose, so a check for "ten paired trials" needs the word.
_WORDS: Final = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
)


def spelled(count: int) -> str:
    """A count the way the prose writes it: a word up to twenty, digits past that."""
    return _WORDS[count] if 0 <= count < len(_WORDS) else str(count)


def fast_timeout_ms() -> int:
    """The shortened timeout every timing test runs at, read out of the test file by name.

    It is the one number the README quotes that lives in tests/ rather than src/, and importing
    the test module here would pull pytest in for one integer, so it is read as text instead.
    """
    text = (ROOT / "tests" / "test_task4_router.py").read_text()
    found = re.search(r"^FAST_TIMEOUT_MS\s*=\s*(\d+)", text, re.MULTILINE)
    if found is None:
        raise SystemExit("tests/test_task4_router.py no longer declares FAST_TIMEOUT_MS; update this check with it.")
    return int(found.group(1))


def limiter_race_threads() -> int:
    """How many threads the limiter is raced with, read out of the test file by name.

    The README quotes the count as a claim about what the suite proves, so it is pinned to the
    test the same way the shortened timeout is, rather than typed twice.
    """
    text = (ROOT / "tests" / "test_task4_rate_limiter.py").read_text()
    found = re.search(r"^\s*thread_count\s*=\s*(\d+)", text, re.MULTILINE)
    if found is None:
        raise SystemExit("tests/test_task4_rate_limiter.py no longer declares thread_count; update this check with it.")
    return int(found.group(1))


def processes_raced() -> int:
    """How many test files race the limiter across processes, which is the badge's second number.

    The thread race is a claim about one process, and the badge says so beside it. This counts
    the test files that spawn workers with the standard library's process tools, so the day such
    a test lands the badge has to move with it.
    """
    markers = ("multiprocessing", "ProcessPoolExecutor")
    return sum(1 for path in (ROOT / "tests").glob("test_*.py") if any(m in path.read_text() for m in markers))


def license_name() -> str:
    """The licence, read off the first line of the LICENSE file the badge points a reader at."""
    first = LICENSE_PATH.read_text().splitlines()[0].strip()
    if first.startswith("MIT"):
        return "MIT"
    raise SystemExit(f"LICENSE opens with {first!r}; teach this check the badge text for it.")


def badge_url(label: str, message: str, colour: str) -> str:
    """One shields.io static badge, in the exact form the README embeds it.

    Spaces are underscores and the separator between a number and the number that makes it look
    worse is a middle dot, percent encoded so the URL survives every renderer.
    """
    dot = "%C2%B7"
    return (
        f"https://img.shields.io/badge/{label}-{message.replace(' ', '_').replace(chr(183), dot)}-{colour}"
        f"?style=flat-square"
    )


def expected_badges(passed: int, bench: dict[str, Any]) -> list[tuple[str, str]]:
    """Every badge under the title, as (image URL, source) pairs.

    Each badge pairs a headline number with the number that makes it look worse, and both halves
    come from the same place the prose gets them, so a badge that flatters on its own cannot be
    typed in.
    """
    worst = bench["worst_first_token"]
    best_ms = min(float(row["added_ms"]) for row in bench["first_token"])
    return [
        (badge_url("tests", f"{passed} passed · no coverage measured", BADGE_ACCENT), "the passing case count"),
        (
            badge_url(
                "held_at_most",
                f"{MAX_BUFFERED_CHARS} chars · {bench['straddling_worst_case_held_chars']} seen",
                BADGE_GREY,
            ),
            "MAX_BUFFERED_CHARS and straddling_worst_case_held_chars in reports/bench_report.json",
        ),
        (
            badge_url(
                "first_token",
                f"{stated_ms(best_ms)} on prose · {stated_ms(float(worst['added_ms']))} worst",
                BADGE_GREY,
            ),
            "the best and worst first token rows in reports/bench_report.json",
        ),
        (
            badge_url("timeout", f"{DEFAULT_TIMEOUT_MS} ms · raced at {fast_timeout_ms()} ms", BADGE_GREY),
            "DEFAULT_TIMEOUT_MS in src/task4_model_router/router.py and FAST_TIMEOUT_MS in the router tests",
        ),
        (
            badge_url("limiter", f"{limiter_race_threads()} threads · {processes_raced()} processes", BADGE_GREY),
            "thread_count in tests/test_task4_rate_limiter.py and a scan of tests/ for process races",
        ),
        (badge_url("license", license_name(), BADGE_GREY), "the first line of LICENSE"),
    ]


def first_token_rows(bench: dict[str, Any]) -> list[str]:
    """The rows the README's first token record table has to carry, one per bench opening.

    Chunks held, the median the guardrail adds, and the range across the ten pairs, all from the
    report the figure beside the table is drawn from, so the table and the figure cannot disagree.
    """
    rows = []
    for row in bench["first_token"]:
        label = str(row["label"])
        added = stated_ms(float(row["added_ms"]))
        added = f"{added[:1].upper()}{added[1:]}"
        spread = f"{float(row['min_ms']):.0f} to {float(row['max_ms']):.0f} ms"
        rows.append(f"| {label[:1].upper()}{label[1:]} | {row['waits']} | {added} | {spread} |")
    return rows


def summary_line(passed: int, skipped: int, functions: int, bench: dict[str, Any]) -> str:
    """The one line this check prints when it is happy, which the README quotes verbatim.

    Pinning the whole line rather than the passed count alone is what keeps the skip count honest.
    A skip added as one more parametrize case moves neither the passed count nor the function count,
    so those two patterns would stay green while the page kept saying 0 skipped.
    """
    worst_ms = float(bench["worst_first_token"]["added_ms"])
    return (
        f"claims ok, {passed} passed and {skipped} skipped from {functions} functions, "
        f"{MAX_BUFFERED_CHARS} chars held at most, worst first token {worst_ms:.0f} ms, "
        f"Python {declared_python_version()}"
    )


def provider_rate_limit_status() -> str:
    """The status the provider layer calls a rate limit, read back off the exception itself.

    Derived from behaviour rather than from a constant, because there is no constant. A change
    to what the provider layer treats as a rate limit changes this message, and the README's
    failover sentence then fails instead of quietly describing the old semantics.
    """
    message = str(ProviderRateLimited("primary"))
    found = re.search(r"\b(\d{3})\b", message)
    if found is None:
        raise SystemExit("ProviderRateLimited no longer names a status code; update this check with it.")
    return found.group(1)


#: The first line inside the README's generated mermaid fence, the same string tools/draw_figures.py writes.
MERMAID_SENTINEL: Final = "%% drawn by tools/draw_figures.py, edit the generator"
GENERATED_FENCE: Final = re.compile(r"^```mermaid\n" + re.escape(MERMAID_SENTINEL) + r"\n.*?^```\n", re.S | re.M)
BADGE_LINE: Final = re.compile(r"^(?:!\[[^\]]*\]\(https://img\.shields\.io/[^)]*\) ?)+\n", re.M)
#: Every HTML image tag with all of its attributes, which is how the badges and the hero are embedded.
HTML_IMAGE: Final = re.compile(r"<img\b[^>]*>", re.I)


def prose(readme: str) -> str:
    """The README with the generated diagram, the badges and the embedded figures cut out.

    All three are rebuilt from the sources on every run, so a fresh number in any of them would
    satisfy a regex while the sentence that quotes the old number stayed wrong. A badge carries its
    numbers twice, in its URL and in its alt text, and the hero's alt text carries every code and
    constant the figure draws, so an HTML image tag is cut whole, attributes included. The prose
    checks only get to see what a person typed.
    """
    if GENERATED_FENCE.search(readme) is None:
        raise SystemExit("README.md has no generated mermaid fence to cut out; run make figures first.")
    return HTML_IMAGE.sub("", BADGE_LINE.sub("", GENERATED_FENCE.sub("", readme)))


def readme_claims(passed: int, functions: int, bench: dict[str, Any]) -> list[tuple[str, str]]:
    """Every number the README prose has to carry, as a regex built from the source it quotes.

    Returns (pattern, source) pairs, so a failure names where the right value lives and not only
    the text that went missing. The patterns match the number and its unit, not the sentence around
    them, so the prose can be reworded without touching this file as long as the figure stays.
    """
    worst = bench["worst_first_token"]
    best_ms = min(float(row["added_ms"]) for row in bench["first_token"])
    best = stated_ms(best_ms)
    best_pattern = rf"\b{re.escape(best)}\b" if best.startswith("under") else rf"(?<!under )\b{re.escape(best)}\b"
    return [
        (rf"\b{passed} tests\b", "the passing case count from this run"),
        (rf"\b{functions} functions\b", "the test function count from this run"),
        (rf"\b{MAX_BUFFERED_CHARS} characters\b", "MAX_BUFFERED_CHARS in src/task3_stream_guard/redactor.py"),
        (rf"\b{MAX_MATCH_LENGTH} character\b", "MAX_MATCH_LENGTH in src/task3_stream_guard/patterns.py"),
        (rf"\b{float(worst['added_ms']):.0f} ms\b", "the worst first token row in reports/bench_report.json"),
        (best_pattern, "the best first token row in reports/bench_report.json"),
        (rf"\b{int(worst['waits'])} chunks\b", "the waits column of that worst row"),
        (rf"\b{int(bench['chunk_size_chars'])} character chunks\b", "chunk_size_chars in reports/bench_report.json"),
        (
            rf"\bevery {float(bench['upstream_delay_ms']):.0f} ms\b",
            "upstream_delay_ms in reports/bench_report.json, the cadence the first token numbers are relative to",
        ),
        (rf"\b{DEFAULT_TIMEOUT_MS} ms\b", "DEFAULT_TIMEOUT_MS in src/task4_model_router/router.py"),
        (rf"\b{fast_timeout_ms()} ms\b", "FAST_TIMEOUT_MS in tests/test_task4_router.py"),
        (rf"\b{spelled(CHARS_PER_TOKEN)} characters a token\b", "CHARS_PER_TOKEN in src/task4_model_router/router.py"),
        (rf"\b{DEFAULT_LIMIT_TOKENS:,} tokens\b", "DEFAULT_LIMIT_TOKENS in src/task4_model_router/rate_limiter.py"),
        (rf"\b(?i:{spelled(limiter_race_threads())}) threads\b", "thread_count in tests/test_task4_rate_limiter.py"),
        (rf"\b{provider_rate_limit_status()}\b", "the status ProviderRateLimited names, which is the failover signal"),
        (rf"\bon {GATEWAY_PORT}\b", "GATEWAY_PORT in src/task2_mcp_gateway/__main__.py"),
        (rf"\bon {DOWNSTREAM_PORT}\b", "DOWNSTREAM_PORT in src/task2_mcp_gateway/__main__.py"),
        (rf"\bon {GUARD_PORT}\b", "PORT in src/task3_stream_guard/__main__.py"),
        (
            rf"\b{spelled(int(bench['trials_per_shape']))} paired trials\b",
            "trials_per_shape in reports/bench_report.json",
        ),
        (rf"(?<![\d-]){mcp.types.INVALID_PARAMS}(?!\d)", "INVALID_PARAMS in the mcp SDK, which task 1 raises"),
        (
            rf"(?<![\d-]){jsonrpc.UNAUTHORIZED_TOOL_CALL}(?!\d)",
            "UNAUTHORIZED_TOOL_CALL in src/task2_mcp_gateway/jsonrpc.py",
        ),
        (rf"\bPython {re.escape(declared_python_version())}\b", ".python-version"),
    ]


def referee_headings(passed: int) -> list[tuple[str, str]]:
    """The two card headings in docs/REFEREE.md that carry a number this check owns.

    The timing cards quote the runs they were audited against and are left alone, since a
    measurement is allowed to move between runs and the card says so. A count and a constant are not.
    """
    return [
        (rf"^### {passed} tests pass\b", "the passing case count from this run"),
        (
            rf"^### {MAX_BUFFERED_CHARS} characters held at most\b",
            "MAX_BUFFERED_CHARS in src/task3_stream_guard/redactor.py",
        ),
    ]


def chunk_table_rows(bench: dict[str, Any]) -> list[str]:
    """The rows docs/TASKS.md has to carry for the chunks held table.

    That table is the one grid on the page typed by hand rather than drawn, so it is pinned here
    against the same report the figures read. The counts are deterministic, unlike the timings
    beside them, which is why the doc quotes these and points at the report for the rest.
    """
    rows = []
    for row in bench["first_token"]:
        label = str(row["label"])
        rows.append(f"| {label[:1].upper()}{label[1:]} | {row['waits']} |")
    return rows


def main() -> int:
    cases, functions = collect_suite()
    outcomes = run_suite()
    passed = outcomes["passed"]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "source": "uv run pytest -o addopts= -q, counts from --collect-only -q",
                "cases": cases,
                "functions": functions,
                **outcomes,
            },
            indent=2,
        )
        + "\n"
    )

    bench = bench_report()
    failures = []
    if outcomes["failed"] or outcomes["error"]:
        failures.append(f"the suite is not green, {outcomes['failed']} failed and {outcomes['error']} errored")
    if passed + outcomes["skipped"] + outcomes["xfailed"] + outcomes["xpassed"] != cases:
        failures.append(f"pytest collected {cases} cases but the run accounts for a different number")

    readme = README_PATH.read_text()
    typed = prose(readme)
    for pattern, source in readme_claims(passed, functions, bench):
        if re.search(pattern, typed) is None:
            failures.append(f"README.md no longer carries a match for {pattern!r}, from {source}")
    for url, source in expected_badges(passed, bench):
        if url not in readme:
            failures.append(f"README.md no longer embeds the badge {url}, from {source}")
    processes = processes_raced()
    if processes:
        if "no two processes" in readme:
            failures.append(
                f"README.md still says no two processes race the limiter, but {processes} test file(s) "
                "now do; the limiter badge would repeat it, so update the "
                "Limitations claim to the new count"
            )
        elif f"{processes} process" not in readme:
            failures.append(
                f"{processes} test file(s) now race the limiter across processes, but README.md does not "
                "name that count anywhere; the limiter badge would repeat it, so "
                "add the claim"
            )
    elif "no two processes" not in readme:
        failures.append(
            "README.md no longer says no two processes race the limiter, though processes_raced() is "
            "still zero; the limiter badge that used to catch a drift here is gone, so restore the claim "
            "or teach this check its new wording"
        )
    for row in first_token_rows(bench):
        if row not in readme:
            failures.append(f'README.md is missing the first token record row "{row}"')
    referee = REFEREE_PATH.read_text()
    for pattern, source in referee_headings(passed):
        if re.search(pattern, referee, re.MULTILINE) is None:
            failures.append(f"docs/REFEREE.md has no heading matching {pattern!r}, from {source}")
    tasks = TASKS_PATH.read_text()
    for row in chunk_table_rows(bench):
        if row not in tasks:
            failures.append(f'docs/TASKS.md is missing the chunks held row "{row}"')

    if outcomes["xfailed"] or outcomes["xpassed"]:
        failures.append(
            f"the suite carries {outcomes['xfailed']} expected failures and {outcomes['xpassed']} unexpected passes, "
            "and the page mentions neither"
        )
    line = summary_line(passed, outcomes["skipped"], functions, bench)
    if line not in readme:
        failures.append(f"README.md no longer quotes this run's summary line verbatim: {line}")

    for failure in failures:
        print(failure)
    if failures:
        return 1
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
