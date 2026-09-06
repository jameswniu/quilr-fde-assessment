"""Draw the README figures as SVG. ``--check`` fails when a committed figure has drifted.

    uv run python tools/draw_figures.py --write
    uv run python tools/draw_figures.py --check

Nothing in a figure is typed by hand. Every number is either read from a report under
``reports/`` at draw time or imported from the constant in ``src/`` that defines it, so a
figure cannot say something the code and the measurements do not. Figures are deterministic
text, which makes drift a diff: ``--check`` redraws and compares against what is committed.

Two guards run at draw time. No font may sit under 22 units on a 1200 unit viewBox, which is
what keeps the page readable at 75% browser zoom in GitHub's roughly 890px column. And every
line drawn inside a card is width estimated against that card, so a string that would cross a
border fails the build instead of shipping. An overflow is fixed by shortening the string,
never by dropping a font under the floor.

The palette is the monochrome house one: one ink, a few greys, white paper, a silver rim, and
a single banknote green spent in three places. It is deliberately not the client's palette,
because borrowing a company's brand colours reads as a claim of affiliation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from task2_mcp_gateway import jsonrpc  # noqa: E402
from task2_mcp_gateway.__main__ import DOWNSTREAM_PORT, GATEWAY_PORT  # noqa: E402
from task3_stream_guard.__main__ import PORT as GUARD_PORT  # noqa: E402
from task3_stream_guard.patterns import MAX_MATCH_LENGTH  # noqa: E402
from task3_stream_guard.redactor import MAX_BUFFERED_CHARS  # noqa: E402
from task4_model_router.rate_limiter import DEFAULT_LIMIT_TOKENS  # noqa: E402
from task4_model_router.router import DEFAULT_TIMEOUT_MS  # noqa: E402

ASSETS: Final = ROOT / "assets"

INK: Final = "#111111"
BLACK: Final = "#0a0a0a"
CHIP: Final = "#1c1c20"
GRAY700: Final = "#3f3f46"
GRAY600: Final = "#52525b"
GRAY400: Final = "#a1a1aa"
GRAY200: Final = "#e4e4e7"
GRAY50: Final = "#fafafa"
PAPER: Final = "#ffffff"
SILVER_HI: Final = "#f5f5f5"
SILVER: Final = "#d4d4d8"
SILVER_LO: Final = "#a1a1aa"
GREEN: Final = "#1b5e3f"
FONT: Final = "Helvetica Neue,Helvetica,Arial,sans-serif"
MONO: Final = "SFMono-Regular,Menlo,Consolas,Liberation Mono,monospace"

FONT_FLOOR: Final = 22.0
WIDTH: Final = 1200
MARGIN: Final = 48
#: Every card in the system map is this tall: a title, two detail lines and a mono footnote.
CARD_HEIGHT: Final = 168


def report(name: str) -> dict[str, Any]:
    """Read a report, and refuse to draw from one that is missing or empty.

    A generator that quietly substitutes zeros for a missing measurement publishes numbers it
    invented, which is worse than one that stops, so this raises rather than defaults.
    """
    path = ROOT / "reports" / name
    if not path.exists():
        raise SystemExit(f"reports/{name} is missing. Run `make bench` and `make claims` before drawing figures.")
    data: dict[str, Any] = json.loads(path.read_text())
    if not data:
        raise SystemExit(f"reports/{name} is empty; refusing to draw figures from it.")
    return data


def esc(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fit(value: object, size: float, box_w: float, inner_pad: float = 22, bold: bool = False) -> None:
    """Fail the build if a line would not fit inside its card.

    The estimate is 0.58 em per character for regular text and 0.62 for bold, which
    over-estimates Helvetica a little so a passing string keeps some margin. The budget is the
    box width less the inner padding on both sides.
    """
    estimate = len(str(value)) * size * (0.62 if bold else 0.58)
    room = box_w - 2 * inner_pad
    if estimate > room:
        raise SystemExit(f'"{value}" is too wide for its card: estimated {estimate:.0f} units, {room:.0f} available')


def fit_mono(value: object, size: float, avail: float) -> None:
    """The same guard for monospace, at 0.62 em per character."""
    estimate = len(str(value)) * size * 0.62
    if estimate > avail:
        raise SystemExit(f'"{value}" is too wide for its figure: estimated {estimate:.0f} units, {avail:.0f} available')


def rim_defs() -> str:
    """The silver rim. One vertical gradient per file, referenced by every card border in it."""
    return (
        '<defs><linearGradient id="rim" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{SILVER_HI}"/>'
        f'<stop offset="0.5" stop-color="{SILVER}"/>'
        f'<stop offset="1" stop-color="{SILVER_LO}"/>'
        "</linearGradient></defs>"
    )


def num(value: float) -> str:
    """A coordinate, written as a whole number unless it genuinely has a fraction."""
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"


def rect(
    x: float,
    y: float,
    w: float,
    h: float,
    fill: str = "none",
    *,
    rx: float = 0,
    stroke: str | None = None,
    stroke_width: float = 1.5,
) -> str:
    """One rectangle. Every box in every figure goes through here, so the attributes stay uniform."""
    attributes = f'x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}"'
    if rx:
        attributes += f' rx="{num(rx)}"'
    attributes += f' fill="{fill}"'
    if stroke is not None:
        attributes += f' stroke="{stroke}" stroke-width="{stroke_width}"'
    return f"<rect {attributes}/>"


def card(x: float, y: float, w: float, h: float) -> str:
    """A white card with the silver rim. Square corners, and the rim carries the finish."""
    return rect(x, y, w, h, PAPER, stroke="url(#rim)", stroke_width=1.75)


def text(x: float, y: float, value: object, size: float, fill: str, weight: str = "400", anchor: str = "start") -> str:
    return (
        f'<text x="{x:.0f}" y="{y:.0f}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}">{esc(value)}</text>'
    )


def mono(
    x: float, y: float, value: object, size: float, fill: str, anchor: str = "start", spacing: float | None = None
) -> str:
    letter_spacing = f' letter-spacing="{spacing}"' if spacing else ""
    return (
        f'<text x="{x:.0f}" y="{y:.0f}" font-family="{MONO}" font-size="{size}" '
        f'fill="{fill}" text-anchor="{anchor}"{letter_spacing}>{esc(value)}</text>'
    )


def stated_ms(value: float) -> str:
    """Milliseconds as a figure is allowed to state them.

    A reading inside the instrument's own noise is written as "under 1 ms" rather than as a
    rounded zero, which would otherwise print as a signed zero and read as a measurement.
    """
    return "under 1 ms" if abs(value) < 1 else f"{value:.0f} ms"


def open_svg(height: float, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height:.0f}" '
        f'role="img" aria-label="{esc(label)}">'
    )


def hero() -> str:
    """The band at the top of the README, and the only place three headline numbers appear.

    Each tile carries its own qualifier rather than the number alone. A green suite has its
    missing coverage figure beside it, the worst first token cost has the best beside it, and
    the derived ceiling has the closest thing to a witness for it. A flattering number on its
    own is the defect this shape exists to prevent, and the skip count is drawn from a real run
    rather than written here, because a collected count cannot see a skipped test.
    """
    bench = report("bench_report.json")
    tests = report("test_report.json")
    worst = bench["worst_first_token"]
    best = min(bench["first_token"], key=lambda row: float(row["added_ms"]))

    height = 420.0
    banner = (
        "Four tasks from the Quilr FDE brief, an MCP server, a security gateway, "
        "a streaming PII guardrail and a model router"
    )
    parts = [open_svg(height, banner)]
    parts.append(rect(0, 0, WIDTH, height, BLACK))

    kicker = "FOUR TASKS / ONE SUITE / NO NETWORK"
    fit_mono(kicker, 22, WIDTH - 2 * MARGIN)
    parts.append(mono(MARGIN, 46, kicker, 22, SILVER, spacing=3))

    title = "Four tasks from the FDE brief"
    fit(title, 44, WIDTH - 2 * MARGIN, bold=True)
    parts.append(text(MARGIN, 98, title, 44, PAPER, "700"))
    parts.append(rect(0, 126, 64, 4, PAPER))

    subtitle = "MCP server, security gateway, streaming PII guardrail, model router."
    fit(subtitle, 24, WIDTH - 2 * MARGIN)
    parts.append(text(MARGIN, 166, subtitle, 24, SILVER_LO))

    tiles = [
        (
            f"{tests['passed']} tests, {tests['skipped']} skip{'' if tests['skipped'] == 1 else 's'}",
            "no coverage measured",
        ),
        (f"{float(worst['added_ms']):.0f} ms worst case", f"{stated_ms(float(best['added_ms']))} on safe prose"),
        (f"{MAX_BUFFERED_CHARS} char ceiling", f"derived bound, {bench['straddling_worst_case_held_chars']} seen"),
    ]
    x = float(MARGIN)
    for tile_title, tile_sub in tiles:
        tile_w = 355.0
        fit(tile_title, 26, tile_w, bold=True)
        fit(tile_sub, 22, tile_w)
        parts.append(rect(x, 196, tile_w, 96, CHIP, rx=12, stroke=GRAY600))
        parts.append(rect(x, 196, 6, 96, PAPER, rx=3))
        parts.append(text(x + 22, 234, tile_title, 26, PAPER, "600"))
        parts.append(text(x + 22, 268, tile_sub, 22, SILVER_LO))
        x += tile_w + 15

    x = float(MARGIN)
    for stage in ("mcp server", "gateway", "stream guard", "router"):
        stage_w = round(len(stage) * 13.2) + 40
        fit(stage, 22, stage_w, inner_pad=20)
        highlighted = stage == "stream guard"
        if highlighted:
            parts.append(rect(x, 316, stage_w, 40, GREEN, rx=2))
        else:
            parts.append(rect(x, 316, stage_w, 40, rx=2, stroke=GRAY400))
        parts.append(mono(x + stage_w / 2, 343, stage, 22, PAPER, "middle"))
        x += stage_w + 14

    foot = "make bench writes the report, make figures redraws this band"
    fit_mono(foot, 22, WIDTH - 2 * MARGIN)
    parts.append(mono(MARGIN, 396, foot, 22, SILVER))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _map_card(x: float, y: float, w: float, title: str, details: list[str], footnote: str) -> list[str]:
    """One bordered card in the system map: a bold title, two detail lines, a mono footnote."""
    fit(title, 26, w, bold=True)
    parts = [card(x, y, w, CARD_HEIGHT), text(x + 22, y + 44, title, 26, INK, "700")]
    for index, line in enumerate(details):
        fit(line, 22, w)
        parts.append(text(x + 22, y + 82 + index * 34, line, 22, INK))
    fit_mono(footnote, 22, w - 44)
    parts.append(mono(x + 22, y + 150, footnote, 22, GRAY700))
    return parts


def system_map() -> str:
    """What each task owns, and the one place two of them are not wired to each other.

    The honest line is section 02: task 1 speaks stdio and the gateway proxies HTTP, so the
    thing behind the gateway in this repo is the mock downstream, not task 1. A map that drew
    an arrow between them would be the first thing a reviewer caught.
    """
    tests = report("test_report.json")
    full_w = float(WIDTH - 2 * MARGIN)
    half_w = (full_w - 44) / 2
    right_x = MARGIN + half_w + 44

    sections: list[tuple[str, str, list[tuple[float, float, str, list[str], str]]]] = [
        (
            "01  MCP SERVER",
            "two tools, one source of truth for the schema",
            [
                (
                    float(MARGIN),
                    full_w,
                    "task1_mcp_server, two tools over stdio",
                    [
                        "get_customer_record and trigger_refund, strict, unknown fields rejected",
                        "stdout carries JSON-RPC only, sys.stdout is rebound to stderr",
                    ],
                    f"bad arguments -> {jsonrpc.INVALID_PARAMS}, an unknown customer -> an isError result",
                )
            ],
        ),
        (
            "02  GATEWAY",
            "task 1 speaks stdio, so the downstream here is the mock",
            [
                (
                    float(MARGIN),
                    half_w,
                    f"gateway, port {GATEWAY_PORT}",
                    ["bearer token to admin or viewer", "admin_ tools need the admin role"],
                    f"a viewer gets {jsonrpc.UNAUTHORIZED_TOOL_CALL}, no forward",
                ),
                (
                    right_x,
                    half_w,
                    f"mock downstream, port {DOWNSTREAM_PORT}",
                    ["tools/list and tools/call", "records every request it sees"],
                    "so a test can prove no forward",
                ),
            ],
        ),
        (
            "03  STREAM GUARD",
            "the only task with a bench",
            [
                (
                    float(MARGIN),
                    full_w,
                    f"task3_stream_guard, POST /v1/generate on {GUARD_PORT}",
                    [
                        "emails, US SSNs and Luhn cards become [REDACTED] as the response streams",
                        "only text that can no longer change is emitted, so a split value is caught",
                    ],
                    f"bounded patterns, {MAX_MATCH_LENGTH} char longest match, {MAX_BUFFERED_CHARS} char ceiling",
                )
            ],
        ),
        (
            "04  MODEL ROUTER",
            "admission first, then failover",
            [
                (
                    float(MARGIN),
                    half_w,
                    "limiter, sqlite on disk",
                    [f"{DEFAULT_LIMIT_TOKENS:,} tokens a minute per key", "rows keyed by a digest, not the key"],
                    "admission in BEGIN IMMEDIATE",
                ),
                (
                    right_x,
                    half_w,
                    "router, then failover",
                    [f"429 or {DEFAULT_TIMEOUT_MS} ms, try the secondary", "one error shape, one request id"],
                    "a failed call refunds its charge",
                ),
            ],
        ),
    ]

    body: list[str] = []
    cursor = 196.0
    for label, note, cards in sections:
        fit_mono(label, 22, 310 - MARGIN)
        fit_mono(note, 22, WIDTH - MARGIN - 310)
        body.append(mono(MARGIN, cursor + 8, label, 22, INK, spacing=2))
        body.append(mono(310, cursor + 8, note, 22, GRAY700))
        for x, w, title, details, footnote in cards:
            body.extend(_map_card(x, cursor + 26, w, title, details, footnote))
        cursor += 26 + CARD_HEIGHT + 44

    height = cursor - 44 + 62
    label_text = "System map of what each of the four tasks owns, and where two of them are not wired together"
    out = [open_svg(height, label_text)]
    out.append(rect(0, 0, WIDTH, height, GRAY50))
    out.append(rect(0, 0, 8, height, GREEN))
    out.append(rim_defs())
    out.append(mono(MARGIN, 56, "SYSTEM MAP", 22, GRAY700, spacing=4))
    title = "How the four tasks meet"
    fit(title, 44, 698, inner_pad=0, bold=True)
    out.append(text(MARGIN, 108, title, 44, INK, "700"))
    subtitle = "What each one owns, and the one place two of them are not wired together."
    fit(subtitle, 24, WIDTH - 2 * MARGIN)
    out.append(text(MARGIN, 156, subtitle, 24, GRAY700))
    out.append(card(746, 40, 430, 96))
    for index, line in enumerate([f"4 tasks / {tests['passed']} tests green", "no network / no API key"]):
        fit_mono(line, 22, 430 - 44)
        out.append(mono(768, 80 + index * 36, line, 22, INK))
    out.extend(body)
    foot = "every number here is read from src/ at draw time, make figures-check compares"
    fit_mono(foot, 22, WIDTH - 2 * MARGIN)
    out.append(mono(MARGIN, height - 30, foot, 22, GRAY700))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def first_token_panel() -> str:
    """Time to first token by leading content shape, drawn from what make bench measured.

    Bars are the measured cost and the label carries the chunk count behind it, because the
    chunk count is the part that survives a change of machine: the milliseconds are that count
    times whatever cadence the upstream happens to send at.
    """
    bench = report("bench_report.json")
    rows = [
        (f"{row['label']}", float(row["added_ms"]), f"{stated_ms(float(row['added_ms']))}, {row['waits']} held")
        for row in bench["first_token"]
    ]

    row_h = 54.0
    card_pad = 28.0
    card_y = 122.0
    card_h = card_pad + row_h * len(rows) + 10
    height = card_y + card_h + 78
    label_w = 470.0
    value_w = 250.0
    plot_x = MARGIN + label_w
    plot_w = (WIDTH - 2 * MARGIN) - label_w - value_w
    largest = max(value for _, value, _ in rows) or 1.0

    parts = [open_svg(height, "Time to first token that the guardrail adds, by what the response opens with")]
    parts.append(rect(0, 0, WIDTH, height, GRAY50))
    parts.append(rim_defs())
    title = "What the guardrail costs at the first token"
    fit(title, 30, WIDTH - 2 * MARGIN, bold=True)
    parts.append(text(MARGIN, 58, title, 30, INK, "700"))
    subtitle = (
        f"median of {bench['trials_per_shape']} paired trials per opening, upstream sends "
        f"{bench['chunk_size_chars']} char chunks every {float(bench['upstream_delay_ms']):.0f} ms"
    )
    fit(subtitle, 22, WIDTH - 2 * MARGIN)
    parts.append(text(MARGIN, 94, subtitle, 22, GRAY700))
    parts.append(card(MARGIN, card_y, WIDTH - 2 * MARGIN, card_h))

    y = card_y + card_pad + 14
    for label, value, shown in rows:
        fit(label, 22, label_w, inner_pad=16)
        fit(shown, 22, value_w, inner_pad=8)
        parts.append(text(plot_x - 18, y + 8, label, 22, INK, anchor="end"))
        bar_w = max(3.0, plot_w * value / largest)
        parts.append(rect(plot_x, y - 10, bar_w, 24, GRAY600, stroke=INK, stroke_width=1))
        parts.append(text(plot_x + bar_w + 14, y + 8, shown, 22, INK))
        y += row_h

    parts.append(rect(MARGIN, card_y + card_h - 1, WIDTH - 2 * MARGIN, 1, GRAY200))
    foot = "reports/bench_report.json, written by make bench, redrawn by make figures"
    fit_mono(foot, 22, WIDTH - 2 * MARGIN)
    parts.append(mono(MARGIN, height - 34, foot, 22, GRAY700))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


FIGURES: Final[dict[str, Any]] = {
    "hero.svg": hero,
    "system-map.svg": system_map,
    "first-token.svg": first_token_panel,
}


def fonts_under_floor(svg: str) -> list[str]:
    """Every font size in the document that sits below the 75% zoom legibility floor."""
    return [part.split('"')[0] for part in svg.split('font-size="')[1:] if float(part.split('"')[0]) < FONT_FLOOR]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="redraw and compare against what is committed")
    parser.add_argument("--write", action="store_true", help="redraw and write the figures")
    args = parser.parse_args()
    if not args.check and not args.write:
        parser.error("pass --write or --check")

    ASSETS.mkdir(exist_ok=True)
    failed = False
    for name, draw in FIGURES.items():
        svg = draw()
        under = fonts_under_floor(svg)
        if under:
            print(f"{name}: fonts under the {FONT_FLOOR:.0f} unit floor: {under}")
            failed = True
        path = ASSETS / name
        if args.check:
            if not path.exists() or path.read_text() != svg:
                print(f"{name}: the committed figure no longer matches its generator")
                failed = True
            else:
                print(f"{name}: ok")
        else:
            path.write_text(svg)
            print(f"wrote assets/{name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
