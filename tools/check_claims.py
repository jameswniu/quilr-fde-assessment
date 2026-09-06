"""Fail the build when a number on the README no longer matches what the repo measures.

    uv run python tools/check_claims.py

Three numbers sit on the landing page as badges: how many test cases are green, the hard
ceiling on held text, and the Python version. The refusal map beside the system map carries
six more, hand written into mermaid where figures-check cannot reach them. A number nothing rechecks is a number that
drifts, so this reruns the suite, rereads the two constants from source, and exits nonzero
when any of them disagrees. The suite is run rather than only collected, because collection
cannot see a skip and the page claims a skip count. It also checks the generated hero carries the same figures, since
a committed SVG is another place a stale number can hide.

The measured counts are written to ``reports/test_report.json``, which is what
``tools/draw_figures.py`` reads. Nothing here is typed by hand twice: the badge is the claim,
this file is the check, and the report is the single source both the figure and the check use.
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
from task3_stream_guard.redactor import MAX_BUFFERED_CHARS
from task4_model_router.errors import STATUS_CODES, GatewayErrorCode
from task4_model_router.providers import ProviderRateLimited
from task4_model_router.rate_limiter import DEFAULT_WINDOW_SECONDS
from task4_model_router.router import DEFAULT_TIMEOUT_MS

ROOT: Final = Path(__file__).resolve().parent.parent
REPORT_PATH: Final = ROOT / "reports" / "test_report.json"
BENCH_PATH: Final = ROOT / "reports" / "bench_report.json"

#: The badges the README carries, and the pattern that reads each one back out of it.
BADGE_PATTERNS: Final[dict[str, str]] = {
    "tests": r"img\.shields\.io/badge/tests-(\d+)_green",
    "ceiling": r"img\.shields\.io/badge/held_text-(\d+)_char_ceiling",
    "python": r"img\.shields\.io/badge/python-([\d.]+)-",
}


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
    decorator move the badge without testing a single new behaviour.
    """
    output = _pytest("--collect-only", "-q")
    node_ids = [line for line in output.splitlines() if "::" in line]
    if not node_ids:
        raise SystemExit(f"pytest collected nothing; refusing to publish a test count of zero.\n{output}")
    return len(node_ids), len({line.split("[", 1)[0] for line in node_ids})


def run_suite() -> dict[str, int]:
    """Return the outcome counts from a real run, which is the only place a skip is visible.

    Collection cannot see a skip, and pytest exits zero with skipped tests in it, so a badge
    built from a collected count alone can say green over a suite that quietly stopped running
    part of itself. This reads the summary line the run prints instead.
    """
    output = _pytest("-q")
    counts = {
        name: int(found.group(1)) if (found := re.search(rf"(\d+) {name}", output)) else 0
        for name in ("passed", "skipped", "xfailed", "xpassed", "failed", "error")
    }
    if not counts["passed"]:
        raise SystemExit(f"pytest reported no passing tests; refusing to publish a green badge.\n{output}")
    return counts


def skip_tile(passed: int, skipped: int) -> str:
    """The hero's first tile, built the same way the figure builds it.

    Duplicated deliberately. The figure draws this string from the report and this check reads it
    back off the committed SVG, so the two agree only when the figure was redrawn after the run.
    """
    return f"{passed} tests, {skipped} skip{'' if skipped == 1 else 's'}"


def declared_python_version() -> str:
    """The interpreter the project pins, read from .python-version."""
    return (ROOT / ".python-version").read_text().strip()


def badge_claims() -> dict[str, str]:
    """What the README currently asserts, pulled straight out of its badge URLs."""
    text = (ROOT / "README.md").read_text()
    claims = {}
    for name, pattern in BADGE_PATTERNS.items():
        found = re.search(pattern, text)
        if found is None:
            raise SystemExit(f"README.md carries no {name} badge matching {pattern}; update this check with the wall.")
        claims[name] = found.group(1)
    return claims


def hero_alt() -> str:
    """The hero's alt text, which is the sentence of numbers a reader gets before any image loads."""
    text = (ROOT / "README.md").read_text()
    found = re.search(r'<img src="assets/hero\.svg" alt="([^"]*)"', text)
    if found is None:
        raise SystemExit("README.md carries no hero image with alt text; update this check with the page.")
    return found.group(1)


def chunk_table_rows() -> list[str]:
    """The rows docs/TASKS.md has to carry for the chunks held table.

    That table is the one grid on the page typed by hand rather than drawn, so it is pinned here
    against the same report the figures read. The counts are deterministic, unlike the timings
    beside them, which is why the doc quotes these and points at the report for the rest.
    """
    bench = bench_report()
    rows = []
    for row in bench["first_token"]:
        label = str(row["label"])
        rows.append(f"| {label[:1].upper()}{label[1:]} | {row['waits']} |")
    return rows


def bench_report() -> dict[str, Any]:
    """The bench's own record of the last run."""
    if not BENCH_PATH.exists():
        raise SystemExit("reports/bench_report.json is missing. Run `make bench` before checking claims.")
    data: dict[str, Any] = json.loads(BENCH_PATH.read_text())
    return data


def refusal_map_rows() -> list[str]:
    """Node labels the README's refusal map has to carry, built from the constants themselves.

    That map is hand written mermaid rather than a generated SVG, so figures-check never sees
    it. Without this it would be the one picture on the page whose error codes and timeouts
    could go stale in silence.
    """
    return [
        # Task 2 refuses the call, so the code comes from the gateway's own module.
        f"Refused, {jsonrpc.UNAUTHORIZED_TOOL_CALL}, downstream never called",
        # Task 1 refuses on the schema, and it raises with the SDK's constant, not the gateway's.
        f"Refused, {mcp.types.INVALID_PARAMS}",
        f"Room left in the {int(DEFAULT_WINDOW_SECONDS)} second window",
        # The limiter's refusal is what a caller sees, so this is the caller-facing status.
        f"Refused, {STATUS_CODES[GatewayErrorCode.RATE_LIMITED]} with retry_after_seconds",
        # This edge is the provider answering 429, a different boundary, read off its own error.
        f"{provider_rate_limit_status()} or timeout",
        f"Primary answers inside {DEFAULT_TIMEOUT_MS} ms",
        f"Held, not refused, {MAX_BUFFERED_CHARS} chars at most",
    ]


def provider_rate_limit_status() -> str:
    """The status the provider layer calls a rate limit, read back off the exception itself.

    Derived from behaviour rather than from a constant, because there is no constant. A change
    to what the provider layer treats as a rate limit changes this message, and the refusal map
    then fails instead of quietly describing the old semantics.
    """
    message = str(ProviderRateLimited("primary"))
    found = re.search(r"\b(\d{3})\b", message)
    if found is None:
        raise SystemExit("ProviderRateLimited no longer names a status code; update this check with it.")
    return found.group(1)


def measured_witness() -> int:
    """How much held text the bench actually witnessed, which the page quotes beside the ceiling.

    The ceiling itself is derived from the pattern lengths. The witness is measured, so it moves
    if the fixture or the chunk size changes, and quoting a stale one beside a derived bound
    would make the gap between them look smaller than it is.
    """
    return int(bench_report()["straddling_worst_case_held_chars"])


def hero_text() -> str:
    """The generated hero, which repeats two of the same numbers in a place nobody rereads."""
    path = ROOT / "assets" / "hero.svg"
    if not path.exists():
        raise SystemExit("assets/hero.svg is missing. Run `make figures` before checking claims.")
    return path.read_text()


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

    claims = badge_claims()
    hero = hero_text()
    failures = []
    if outcomes["failed"] or outcomes["error"]:
        failures.append(f"the suite is not green, {outcomes['failed']} failed and {outcomes['error']} errored")
    if passed + outcomes["skipped"] + outcomes["xfailed"] + outcomes["xpassed"] != cases:
        failures.append(f"pytest collected {cases} cases but the run accounts for a different number")
    if claims["tests"] != str(passed):
        failures.append(f"tests badge says {claims['tests']}, the run passes {passed}")
    if claims["ceiling"] != str(MAX_BUFFERED_CHARS):
        failures.append(f"held text badge says {claims['ceiling']}, redactor.py says {MAX_BUFFERED_CHARS}")
    if claims["python"] != declared_python_version():
        failures.append(f"python badge says {claims['python']}, .python-version says {declared_python_version()}")
    if skip_tile(passed, outcomes["skipped"]) not in hero:
        failures.append(f'assets/hero.svg does not say "{skip_tile(passed, outcomes["skipped"])}"; run `make figures`')
    if f"{MAX_BUFFERED_CHARS} char" not in hero:
        failures.append(f"assets/hero.svg does not say {MAX_BUFFERED_CHARS} char; run `make figures`")
    alt = hero_alt()
    if f"{passed} tests" not in alt:
        failures.append(f"the hero alt text in README.md does not say {passed} tests")
    if f"{MAX_BUFFERED_CHARS} char" not in alt:
        failures.append(f"the hero alt text in README.md does not say {MAX_BUFFERED_CHARS} char")
    seen = measured_witness()
    if str(seen) not in alt:
        failures.append(f"the hero alt text in README.md does not say {seen}, the held text the bench witnessed")
    readme = (ROOT / "README.md").read_text()
    for node in refusal_map_rows():
        if node not in readme:
            failures.append(f'the refusal map in README.md is missing "{node}"')
    tasks = (ROOT / "docs" / "TASKS.md").read_text()
    for row in chunk_table_rows():
        if row not in tasks:
            failures.append(f'docs/TASKS.md is missing the chunks held row "{row}"')

    for failure in failures:
        print(failure)
    if failures:
        return 1
    print(
        f"claims ok, {passed} passed and {outcomes['skipped']} skipped from {functions} functions, "
        f"{MAX_BUFFERED_CHARS} char ceiling, Python {claims['python']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
