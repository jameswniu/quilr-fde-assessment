"""Draw the README figures as SVG. ``--check`` fails when a committed figure has drifted.

    uv run python tools/draw_figures.py --write
    uv run python tools/draw_figures.py --check

Nothing in a figure is typed by hand. Every number is either read from a report under
``reports/`` at draw time or imported from the constant in ``src/`` that defines it, so a
figure cannot say something the code and the measurements do not. Figures are deterministic
text, which makes drift a diff: ``--check`` redraws and compares against what is committed.

Three guards run at draw time. No font may sit under 22 units on a 1200 unit viewBox, which is
what keeps the page readable at 75% browser zoom in GitHub's roughly 890px column. Every line
drawn inside a card is width estimated against that card, so a string that would cross a border
fails the build instead of shipping. And every text colour is checked against the surface it
sits on at the WCAG 4.5 ratio, so a pair that reads fine on a bright monitor and not on a dim
one cannot ship either. An overflow is fixed by shortening the string, never by dropping a font
under the floor, and a contrast failure by darkening the ink, never by enlarging the text.

The figure sits on a pale paper with dark ink, thin grey strokes and one slate blue for the
bars, so it reads like the rest of the page and not like a poster, and the mermaid diagram uses
mermaid's own neutral theme for the same reason. The diagram is generated here too and spliced
between the README's mermaid fences, so --check catches a hand edit to it the same way it
catches one to the SVG.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from task2_mcp_gateway import jsonrpc  # noqa: E402
from task3_stream_guard.redactor import MAX_BUFFERED_CHARS  # noqa: E402
from task4_model_router.errors import GatewayErrorCode  # noqa: E402
from task4_model_router.providers import ProviderRateLimited  # noqa: E402
from task4_model_router.rate_limiter import DEFAULT_WINDOW_SECONDS  # noqa: E402
from task4_model_router.router import DEFAULT_TIMEOUT_MS  # noqa: E402

ASSETS: Final = ROOT / "assets"

#: Pale paper, the surface behind the figure.
PAPER: Final = "#FAFAF8"
#: The card fill on paper.
PANEL: Final = "#FFFFFF"
#: Near black, every heading and label.
INK: Final = "#1F1F1F"
#: Secondary text.
DIM: Final = "#6B6B66"
#: Card and rule strokes.
LINE: Final = "#D0CFCA"
#: A slate blue, the bars and nothing else.
ACCENT: Final = "#2F5D8A"
FONT: Final = "Helvetica Neue,Helvetica,Arial,sans-serif"
MONO: Final = "SFMono-Regular,Menlo,Consolas,Liberation Mono,monospace"

FONT_FLOOR: Final = 22.0
WIDTH: Final = 1200
MARGIN: Final = 48
#: The WCAG ratio for ordinary text, which every text and surface pair below has to clear.
CONTRAST_FLOOR: Final = 4.5

#: Every text colour with every surface it is drawn on. Checked once per run, before drawing.
TEXT_ON_SURFACE: Final[tuple[tuple[str, str], ...]] = (
    (INK, PAPER),
    (INK, PANEL),
    (DIM, PAPER),
    (DIM, PANEL),
    (ACCENT, PAPER),
)


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


def fit_mono(value: object, size: float, avail: float, spacing: float = 0) -> None:
    """The same guard for monospace, at 0.62 em per character plus any letter spacing."""
    estimate = len(str(value)) * (size * 0.62 + spacing)
    if estimate > avail:
        raise SystemExit(f'"{value}" is too wide for its figure: estimated {estimate:.0f} units, {avail:.0f} available')


def _luminance(colour: str) -> float:
    """Relative luminance as WCAG 2 defines it, from a #rrggbb string."""
    channels = [int(colour.lstrip("#")[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground: str, background: str) -> float:
    """The WCAG contrast ratio between two colours, 1 for identical and 21 for black on white."""
    brighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (brighter + 0.05) / (darker + 0.05)


def check_contrast() -> list[str]:
    """Every text and surface pair under the 4.5 floor, named with its ratio."""
    return [
        f"{text} on {surface} is {contrast(text, surface):.2f}, under {CONTRAST_FLOOR}"
        for text, surface in TEXT_ON_SURFACE
        if contrast(text, surface) < CONTRAST_FLOOR
    ]


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


def text(x: float, y: float, value: object, size: float, fill: str, weight: str = "400", anchor: str = "start") -> str:
    return (
        f'<text x="{x:.0f}" y="{y:.0f}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}">{esc(value)}</text>'
    )


def mono(
    x: float,
    y: float,
    value: object,
    size: float,
    fill: str,
    anchor: str = "start",
    spacing: float | None = None,
    weight: str = "400",
) -> str:
    letter_spacing = f' letter-spacing="{spacing}"' if spacing else ""
    return (
        f'<text x="{x:.0f}" y="{y:.0f}" font-family="{MONO}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}"{letter_spacing}>{esc(value)}</text>'
    )


def stated_ms(value: float) -> str:
    """Milliseconds as a figure is allowed to state them.

    A reading inside the instrument's own noise is written as "under 1 ms" rather than as a
    rounded zero, which would otherwise print as a signed zero and read as a measurement.
    """
    return "under 1 ms" if abs(value) < 1 else f"{value:.0f} ms"


def rate_limit_status() -> str:
    """The status the provider layer calls a rate limit, read off the exception itself."""
    found = re.search(r"\b(\d{3})\b", str(ProviderRateLimited("primary")))
    if found is None:
        raise SystemExit("ProviderRateLimited no longer names a status code; update the hero with it.")
    return found.group(1)


def open_svg(height: float, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height:.0f}" '
        f'role="img" aria-label="{esc(label)}">'
    )


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
    parts.append(rect(0, 0, WIDTH, height, PAPER))
    title = "What the guardrail costs at the first token"
    fit(title, 30, WIDTH - 2 * MARGIN, inner_pad=0, bold=True)
    parts.append(text(MARGIN, 58, title, 30, INK, "700"))
    subtitle = (
        f"median of {bench['trials_per_shape']} paired trials per opening, upstream sends "
        f"{bench['chunk_size_chars']} char chunks every {float(bench['upstream_delay_ms']):.0f} ms"
    )
    fit(subtitle, 22, WIDTH - 2 * MARGIN, inner_pad=0)
    parts.append(text(MARGIN, 94, subtitle, 22, DIM))
    parts.append(rect(MARGIN, card_y, WIDTH - 2 * MARGIN, card_h, PANEL, rx=10, stroke=LINE))

    y = card_y + card_pad + 14
    for label, value, shown in rows:
        fit(label, 22, label_w, inner_pad=16)
        fit(shown, 22, value_w, inner_pad=8)
        parts.append(text(plot_x - 18, y + 8, label, 22, INK, anchor="end"))
        bar_w = max(3.0, plot_w * value / largest)
        parts.append(rect(plot_x, y - 10, bar_w, 24, ACCENT, rx=2))
        parts.append(text(plot_x + bar_w + 14, y + 8, shown, 22, INK))
        y += row_h

    foot = "reports/bench_report.json, written by make bench, redrawn by make figures"
    fit_mono(foot, 22, WIDTH - 2 * MARGIN)
    parts.append(mono(MARGIN, height - 34, foot, 22, DIM))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


README: Final = ROOT / "README.md"
#: The first line inside the generated fence, which is how the splicer tells it from a hand written one.
MERMAID_SENTINEL: Final = "%% drawn by tools/draw_figures.py, edit the generator"


def mermaid_flow() -> str:
    """The four gates as four lanes, with the codes and limits read from ``src/``.

    Two lanes per row and each lane two ranks wide, so the grid stays inside GitHub's column at
    its natural size, which is the only way the text keeps its size, since GitHub scales a wider
    diagram down and the labels with it. Four lanes side by side ran to twice the column, four
    stacked ran to twice the height. The invisible links only fix which lane sits under which,
    since mermaid otherwise places unconnected subgraphs in whatever order it likes. The diagram
    keeps GitHub's own font, since a mono family is measured with sans metrics here and the
    labels overflow their boxes. No edge joins the first two lanes, because task 1 speaks stdio
    and the gateway proxies HTTP, so nothing in this repo puts task 1 behind task 2. GitHub draws
    its pan and zoom control over the bottom right corner of every mermaid diagram, so an empty
    spacer node under the bottom row keeps the last lane out from under it.
    """
    init = (
        '%%{init: {"theme": "neutral", "themeVariables": {"fontSize": "16px"}, '
        '"flowchart": {"curve": "linear", "nodeSpacing": 14, "rankSpacing": 22, "padding": 6, '
        '"diagramPadding": 8, "subGraphTitleMargin": {"top": 6, "bottom": 14}}}}%%'
    )
    lines = [
        "```mermaid",
        MERMAID_SENTINEL,
        init,
        "flowchart TB",
        '  subgraph S2["02 role gate, task 2"]',
        "    direction LR",
        f'    B2["admin_ tool<br/>as viewer?"] -- yes --> B3["{jsonrpc.UNAUTHORIZED_TOOL_CALL}<br/>not forwarded"]',
        '    B2 -- no --> B4["forwarded to<br/>the downstream"]',
        "  end",
        '  subgraph S1["01 schema gate, task 1"]',
        "    direction LR",
        f'    A2["arguments fit<br/>the schema?"] -- no --> A3["{jsonrpc.INVALID_PARAMS}<br/>Invalid params"]',
        '    A2 -- yes --> A4["handler runs"]',
        "  end",
        '  subgraph S4["04 budget gate, task 4"]',
        "    direction LR",
        f'    D2["budget in the<br/>last {DEFAULT_WINDOW_SECONDS:.0f} s?"] -- no --> '
        f'D3["{GatewayErrorCode.RATE_LIMITED}<br/>retry_after_seconds"]',
        f'    D2 -- yes --> D4["primary first,<br/>secondary on a {rate_limit_status()}<br/>'
        f'or after {DEFAULT_TIMEOUT_MS} ms"]',
        "  end",
        '  subgraph S3["03 hold gate, task 3"]',
        "    direction LR",
        f'    C2["could this text<br/>still change?"] -- yes --> C3["held, {MAX_BUFFERED_CHARS} chars<br/>at most"]',
        '    C2 -- no --> C4["emitted, PII<br/>as [REDACTED]"]',
        "  end",
        "  S1 ~~~ S3",
        "  S2 ~~~ S4",
        '  Z["<br/><br/>"]',
        "  S3 ~~~ Z",
        "  S4 ~~~ Z",
        f"  classDef stop fill:{PANEL},stroke:{ACCENT},stroke-width:2px,color:{INK}",
        f"  classDef hold fill:{PANEL},stroke:{DIM},stroke-width:2px,color:{INK}",
        "  class A3,B3,D3 stop",
        "  class C3 hold",
        "  classDef spacer fill:none,stroke:none,color:transparent",
        "  class Z spacer",
        "```",
    ]
    return "\n".join(lines) + "\n"


def spliced_readme(block: str) -> str:
    """The README with the generated block in place of the mermaid fence that opens with the sentinel.

    Only a fence whose first line is the sentinel is touched, so a diagram someone writes by hand is
    never overwritten, and a README with no such fence stops both ``--write`` and ``--check`` rather
    than letting either pick a fence to replace.
    """
    lines = README.read_text().split("\n")
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if line == "```mermaid" and i + 1 < len(lines) and lines[i + 1] == MERMAID_SENTINEL
        ),
        None,
    )
    if start is None:
        raise SystemExit(
            f"README.md has no mermaid fence opening with {MERMAID_SENTINEL!r}; add one where the diagram goes."
        )
    end = next((i for i in range(start + 1, len(lines)) if lines[i] == "```"), None)
    if end is None:
        raise SystemExit("README.md's generated mermaid fence never closes.")
    return "\n".join(lines[:start] + block.rstrip("\n").split("\n") + lines[end + 1 :])


FIGURES: Final[dict[str, Any]] = {"first-token.svg": first_token_panel}


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

    failed = False
    for failure in check_contrast():
        print(f"palette: {failure}")
        failed = True
    if failed:
        return 1

    ASSETS.mkdir(exist_ok=True)
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

    wanted = spliced_readme(mermaid_flow())
    if args.check:
        if README.read_text() != wanted:
            print("README.md: the mermaid block no longer matches its generator")
            failed = True
        else:
            print("README.md mermaid: ok")
    elif README.read_text() != wanted:
        README.write_text(wanted)
        print("wrote the mermaid block into README.md")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
