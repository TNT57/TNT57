"""Second card: top languages (left) and contribution streaks + last 52 weeks (right).

Used by build_card.py. Reads the "languages" and "contrib" parts of profile/stats.json.
"""

from datetime import date
from xml.sax.saxutils import escape

CHAR_W = 9.6
FONT = "Consolas, Menlo, 'DejaVu Sans Mono', 'Liberation Mono', 'Courier New', monospace"


def _date_range(start: str | None, end: str | None, this_year: int) -> str:
    if not start:
        return "no streak yet"
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    left = f"{a:%b} {a.day}"
    right = f"{b:%b} {b.day}"
    text = left if a == b else f"{left} – {right}"
    return text if a.year == b.year == this_year else f"{text}, {b.year}"


def _header(x: float, y: float, title: str, chars: int) -> str:
    rule = "─" * (chars - len(title) - 3)
    return (f'<text x="{x}" y="{y}"><tspan class="cc">─ </tspan><tspan class="text">{escape(title)}</tspan>'
            f'<tspan class="cc"> {rule}</tspan></text>')


def render_activity(theme: dict, stats: dict, width: int) -> str:
    pad, gap = 30, 40
    col_w = (width - 2 * pad - gap) / 2
    col_chars = int(col_w / CHAR_W)
    left_x, right_x = pad, pad + col_w + gap
    height = 240
    langs = stats.get("languages") or []
    c = stats.get("contrib") or {}

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}px" height="{height}px" font-family="{FONT}" '
        f'font-size="16px">',
        "<style>",
        f".text {{fill: {theme['text']};}} .key {{fill: {theme['key']};}} .value {{fill: {theme['value']};}}",
        f".cc {{fill: {theme['cc']};}} .add {{fill: {theme['add']};}} text {{white-space: pre;}}",
        "</style>",
        f'<rect width="{width}px" height="{height}px" fill="{theme["bg"]}" rx="15" stroke="{theme["border"]}" '
        f'stroke-width="1"/>',
        _header(left_x, 42, "Top Languages", col_chars),
        _header(right_x, 42, "Contributions", col_chars),
    ]

    # ── Left: stacked bar + legend ──────────────────────────────────────────
    bar_y, bar_h = 66, 14
    out.append(f'<clipPath id="bar"><rect x="{left_x}" y="{bar_y}" width="{col_w:.1f}" height="{bar_h}" '
               f'rx="{bar_h / 2}"/></clipPath>')
    out.append('<g clip-path="url(#bar)">')
    if not langs:
        out.append(f'<rect x="{left_x}" y="{bar_y}" width="{col_w:.1f}" height="{bar_h}" class="cc"/>')
    x = left_x
    for i, lang in enumerate(langs):
        w = col_w * lang["pct"] / 100
        out.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{w + 0.5:.1f}" height="{bar_h}" fill="{lang["color"]}"/>')
        if i:  # thin gap so similar colours (e.g. two blues) stay apart
            out.append(f'<rect x="{x - 1:.1f}" y="{bar_y}" width="2" height="{bar_h}" fill="{theme["bg"]}"/>')
        x += w
    out.append("</g>")

    item_w = col_w / 2
    item_chars = int((item_w - 30) / CHAR_W)
    for i, lang in enumerate(langs[:6]):
        cx = left_x + (i % 2) * item_w
        cy = 128 + (i // 2) * 36
        pct = f"{lang['pct']:.1f}%"
        dots = "." * max(item_chars - len(lang["name"]) - len(pct) - 2, 1)
        out.append(f'<circle cx="{cx + 6}" cy="{cy - 5}" r="6" fill="{lang["color"]}"/>')
        out.append(f'<text x="{cx + 20}" y="{cy}"><tspan class="key">{escape(lang["name"])}</tspan>'
                   f'<tspan class="cc"> {dots} </tspan><tspan class="value">{pct}</tspan></text>')
    if not langs:
        out.append(f'<text x="{left_x}" y="120" class="cc">waiting for the first GitHub Action run…</text>')

    # ── Right: three numbers + weekly bars ──────────────────────────────────
    this_year = date.fromisoformat(c["current_end"] or c["longest_end"] or "2000-01-01").year if c else 0
    since = date.fromisoformat(c["since"]) if c.get("since") else None
    blocks = [
        (c.get("total", "?"), "Total Contributions", f"since {since:%b %Y}" if since else ""),
        (c.get("current_streak", "?"), "Current Streak",
         _date_range(c.get("current_start"), c.get("current_end"), this_year) if c else ""),
        (c.get("longest_streak", "?"), "Longest Streak",
         _date_range(c.get("longest_start"), c.get("longest_end"), this_year) if c else ""),
    ]
    block_w = col_w / 3
    for i, (num, label, sub) in enumerate(blocks):
        cx = right_x + block_w * i + block_w / 2
        num_text = f"{num:,}" if isinstance(num, int) else str(num)
        unit = " days" if i and isinstance(num, int) and num != 1 else (" day" if i else "")
        cls = "add" if i == 1 else "value"
        out.append(f'<text x="{cx:.1f}" y="{92}" text-anchor="middle" font-size="30px" font-weight="bold" '
                   f'class="{cls}">{num_text}<tspan font-size="14px" font-weight="normal" class="cc">{unit}</tspan>'
                   f'</text>')
        out.append(f'<text x="{cx:.1f}" y="116" text-anchor="middle" font-size="14px" class="key">{label}</text>')
        out.append(f'<text x="{cx:.1f}" y="135" text-anchor="middle" font-size="12px" class="cc">'
                   f'{escape(sub)}</text>')

    weeks = c.get("weeks") or []
    if weeks:
        top, bottom = 158, 205
        n = len(weeks)
        bar_gap = 3
        bw = (col_w - bar_gap * (n - 1)) / n
        peak = max(weeks) or 1
        for i, count in enumerate(weeks):
            h = max((bottom - top) * count / peak, 2)
            cls = "add" if count else "cc"
            opacity = 0.35 + 0.65 * count / peak if count else 0.5
            out.append(f'<rect x="{right_x + i * (bw + bar_gap):.1f}" y="{bottom - h:.1f}" width="{bw:.1f}" '
                       f'height="{h:.1f}" rx="1.5" class="{cls}" opacity="{opacity:.2f}"/>')
        out.append(f'<text x="{right_x}" y="224" font-size="12px" class="cc">52 weeks ago</text>')
        out.append(f'<text x="{right_x + col_w:.1f}" y="224" font-size="12px" text-anchor="end" class="cc">'
                   f'this week</text>')

    out += ["</svg>", ""]
    return "\n".join(out)
