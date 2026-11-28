"""Build the neofetch-style profile card (dark_mode.svg + light_mode.svg).

Inputs:  profile/config.toml (your info), profile/ascii_{dark,light}.txt (portrait),
         profile/stats.json (numbers from fetch_stats.py)
Outputs (in assets/): card_dark.svg, card_light.svg       - the neofetch card
                     activity_dark.svg, activity_light.svg - languages + streaks
"""

import calendar
import json
import sys
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from activity_card import render_activity

ROOT = Path(__file__).resolve().parent.parent

FONT_SIZE = 16
LINE_H = 20
CHAR_W = 9.6  # widest common monospace fonts are 0.6em wide
PAD = 20
GAP = 3  # empty characters between the portrait and the text

THEMES = {
    "dark": {
        "bg": "#161b22", "border": "#30363d", "text": "#c9d1d9", "key": "#ffa657",
        "value": "#a5d6ff", "cc": "#616e7f", "add": "#3fb950", "del": "#f85149",
        "art": "#c9d1d9",
    },
    "light": {
        "bg": "#f6f8fa", "border": "#d0d7de", "text": "#24292f", "key": "#953800",
        "value": "#0a3069", "cc": "#a8b3bf", "add": "#1a7f37", "del": "#cf222e",
        "art": "#24292f",
    },
}


# ── helpers ────────────────────────────────────────────────────────────────
def uptime(since: date, today: date) -> str:
    """'3 years, 2 months, 19 days' between two dates."""
    years, months, days = today.year - since.year, today.month - since.month, today.day - since.day
    if days < 0:
        months -= 1
        prev_month = today.month - 1 or 12
        prev_year = today.year if today.month > 1 else today.year - 1
        days += calendar.monthrange(prev_year, prev_month)[1]
    if months < 0:
        years -= 1
        months += 12

    def unit(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    return f"{unit(years, 'year')}, {unit(months, 'month')}, {unit(days, 'day')}"


def seg_len(segs) -> int:
    return sum(len(text) for text, _ in segs)


def dotted(key: str, value_segs, width: int, lead: bool = True):
    """'. Key: ........ value' padded with dots to exactly `width` chars."""
    head = [(". ", "cc")] if lead else []
    head += [(key, "key"), (":", "cc")]
    room = width - seg_len(head) - seg_len(value_segs) - 2
    if room < 1:
        print(f"warning: line for '{key}' is {1 - room} char(s) too long", file=sys.stderr)
        room = 1
    return head + [(" " + "." * room + " ", "cc")] + value_segs


def rule(title: str, width: int, header: bool = False):
    """'─ Title ──────' (or 'user@host ─────' for the header)."""
    if header:
        user, _, host = title.partition("@")
        segs = [(user, "text"), ("@", "cc"), (host, "text")] if host else [(title, "text")]
    else:
        segs = [("─ ", "cc"), (title, "text")]
    return segs + [(" " + "─" * (width - seg_len(segs) - 1), "cc")]


def fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def stats_lines(stats: dict, width: int):
    left_w = width // 2 + 3
    right_w = width - left_w - 3

    def two(lkey, lval, rkey, rval):
        return dotted(lkey, lval, left_w) + [(" | ", "cc")] + dotted(rkey, rval, right_w, lead=False)

    v = lambda x: [(fmt(x), "value")]  # noqa: E731
    loc = [
        (fmt(stats.get("loc_total", "?")), "value"), (" ( ", "cc"),
        (fmt(stats.get("loc_add", "?")) + "++", "add"), (", ", "cc"),
        (fmt(stats.get("loc_del", "?")) + "--", "del"), (" )", "cc"),
    ]
    # Use the long label only if it fits.
    loc_key = "Lines of Code on GitHub" if len("Lines of Code on GitHub") + seg_len(loc) + 6 <= width else "Lines of Code"
    return [
        two("Repos", [(fmt(stats.get("repos", "?")), "value"), (" {", "cc"), ("Contributed: ", "key"),
                      (fmt(stats.get("contributed", "?")), "value"), ("}", "cc")],
            "Stars", v(stats.get("stars", "?"))),
        two("Commits", v(stats.get("commits", "?")), "Followers", v(stats.get("followers", "?"))),
        dotted(loc_key, loc, width),
    ]


def build_lines(cfg: dict, stats: dict, today: date):
    width = cfg.get("width", 60)
    up = uptime(date.fromisoformat(cfg["uptime_since"]), today)
    lines = []
    for i, group in enumerate(cfg["group"]):
        if i:
            lines.append([(".", "cc")])  # blank line between groups
        if "title" in group:
            lines.append(rule(group["title"], width, header=(i == 0)))
        if group.get("stats"):
            lines += stats_lines(stats, width)
        for key, value in group.get("rows", []):
            lines.append(dotted(key, [(value.replace("{uptime}", up), "value")], width))
    return lines


# ── SVG ────────────────────────────────────────────────────────────────────
def layout(art: list[str], cfg: dict) -> tuple[float, int]:
    """(x where the text column starts, total card width) in pixels."""
    art_w = max(map(len, art)) * 0.6 * cfg["ascii"].get("font_size", FONT_SIZE)
    text_x = PAD + art_w + GAP * CHAR_W
    return text_x, round(text_x + cfg.get("width", 60) * CHAR_W + PAD)


def render_svg(theme: dict, art: list[str], lines, cfg: dict) -> str:
    art_font = cfg["ascii"].get("font_size", FONT_SIZE)
    art_line = cfg["ascii"].get("line_height", LINE_H)
    text_x, width_px = layout(art, cfg)
    art_h = len(art) * art_line
    text_h = (len(lines) + 2) * LINE_H  # +2 = blank + prompt line
    height_px = round(PAD * 2 + max(art_h, text_h))

    def top(block_h: float, line_h: float) -> float:  # vertically centre each column
        return (height_px - block_h) / 2 + line_h * 0.75

    out = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="Consolas, Menlo, \'DejaVu Sans Mono\', '
        f'\'Liberation Mono\', \'Courier New\', monospace" width="{width_px}px" height="{height_px}px" '
        f'font-size="{FONT_SIZE}px">',
        "<style>",
        f".text {{fill: {theme['text']};}} .key {{fill: {theme['key']};}} .value {{fill: {theme['value']};}}",
        f".cc {{fill: {theme['cc']};}} .add {{fill: {theme['add']};}} .del {{fill: {theme['del']};}}",
        f".art {{fill: {theme['art']};}} text, tspan {{white-space: pre;}}",
        "</style>",
        f'<rect width="{width_px}px" height="{height_px}px" fill="{theme["bg"]}" rx="15" '
        f'stroke="{theme["border"]}" stroke-width="1"/>',
        f'<text x="{PAD}" y="{top(art_h, art_line):.1f}" class="art" font-size="{art_font}px" '
        f'xml:space="preserve">',
    ]
    y0 = top(art_h, art_line)
    for i, row in enumerate(art):
        out.append(f'<tspan x="{PAD}" y="{y0 + i * art_line:.1f}">{escape(row)}</tspan>')
    out.append("</text>")

    y0 = top(text_h, LINE_H)
    out.append(f'<text x="{text_x:.1f}" y="{y0:.1f}" class="text" xml:space="preserve">')
    for i, segs in enumerate(lines):
        body = "".join(f'<tspan class="{cls}">{escape(t)}</tspan>' for t, cls in segs)
        out.append(f'<tspan x="{text_x:.1f}" y="{y0 + i * LINE_H:.1f}">{body}</tspan>')
    # Terminal prompt with a blinking cursor.
    prompt_y = y0 + (len(lines) + 1) * LINE_H
    host = cfg["group"][0].get("title", "user@github")
    out.append(
        f'<tspan x="{text_x:.1f}" y="{prompt_y:.1f}"><tspan class="add">{escape(host)}</tspan>'
        f'<tspan class="cc">:</tspan><tspan class="value">~</tspan><tspan class="cc">$ </tspan>'
        f'<tspan class="text">█<animate attributeName="opacity" values="1;1;0;0" dur="1.2s" '
        f'repeatCount="indefinite"/></tspan></tspan>'
    )
    out += ["</text>", "</svg>", ""]
    return "\n".join(out)


def main() -> None:
    cfg = tomllib.loads((ROOT / "profile" / "config.toml").read_text(encoding="utf-8"))
    stats_file = ROOT / "profile" / "stats.json"
    stats = json.loads(stats_file.read_text()) if stats_file.exists() else {}
    today = datetime.now(timezone.utc).date()

    lines = build_lines(cfg, stats, today)
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        art = (ROOT / "profile" / f"ascii_{name}.txt").read_text(encoding="utf-8").rstrip("\n").split("\n")
        (assets / f"card_{name}.svg").write_text(render_svg(theme, art, lines, cfg), encoding="utf-8")
        width = layout(art, cfg)[1]  # same width as the main card so they line up
        (assets / f"activity_{name}.svg").write_text(render_activity(theme, stats, width), encoding="utf-8")
    for segs in lines:
        print("".join(t for t, _ in segs))
    print("\nwrote assets/card_{dark,light}.svg + assets/activity_{dark,light}.svg")


if __name__ == "__main__":
    main()
