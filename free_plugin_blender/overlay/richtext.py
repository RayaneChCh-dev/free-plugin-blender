"""A little Markdown for the chat: **bold**, `code`, bullet lists, headings, and wrapping. No bpy.

Claude's answers use these few marks; anything else stays as written. `layout()`
wraps the styled runs into lines with a `measure(text, style)` callback, so the
drawing code only has to paint them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_HEADING = re.compile(r"^#{1,4}\s+")


@dataclass
class Line:
    runs: list = field(default_factory=list)  # [(text, style)]; style: "plain" | "bold" | "code"
    indent: float = 0.0
    bullet: str = ""  # drawn in the indent of a list item's first line
    gap_before: bool = False  # a blank line, or a new paragraph, before this one


def runs(text, base="plain"):
    """[(text, style)] for one line of Markdown."""
    found, position = [], 0
    for match in _INLINE.finditer(text):
        if match.start() > position:
            found.append((text[position:match.start()], base))
        bold, code = match.groups()
        found.append((bold, "bold") if bold is not None else (code, "code"))
        position = match.end()
    if position < len(text):
        found.append((text[position:], base))
    return [(t, s) for t, s in found if t]


def _tokens(styled):
    """Words with their trailing spaces, each keeping its style."""
    for text, style in styled:
        for word in re.findall(r"\S+\s*|\s+", text):
            yield word, style


def _split_long(word, style, width, measure):
    """A word wider than the line, cut where it fits."""
    pieces, current = [], ""
    for char in word:
        if current and measure(current + char, style) > width:
            pieces.append(current)
            current = ""
        current += char
    return pieces + ([current] if current else [])


def layout(text, width, measure, indent=14.0):
    """Wrap Markdown text into Lines no wider than `width`."""
    lines: list[Line] = []
    pending_gap = False
    for raw in text.splitlines() or [""]:
        if not raw.strip():
            pending_gap = bool(lines)
            continue
        bullet, base, body = "", "plain", raw
        match = _BULLET.match(raw)
        if match:
            marker = match.group(0).strip()
            bullet, body = ("•" if marker in "-*•" else marker), raw[match.end():]
        elif _HEADING.match(raw):
            base, body = "bold", _HEADING.sub("", raw)
        left = indent if bullet else 0.0
        available = max(10.0, width - left)
        line = Line(indent=left, bullet=bullet, gap_before=pending_gap)
        pending_gap, used = False, 0.0
        for word, style in _tokens(runs(body.rstrip(), base)):
            size = measure(word.rstrip(), style)
            if used and used + size > available:
                lines.append(line)
                line, used = Line(indent=left), 0.0
                word = word.lstrip()
                if not word:
                    continue
                size = measure(word.rstrip(), style)
            if size > available:
                for piece in _split_long(word, style, available, measure):
                    if used:
                        lines.append(line)
                        line, used = Line(indent=left), 0.0
                    line.runs.append((piece, style))
                    used = measure(piece, style)
                continue
            line.runs.append((word, style))
            used += measure(word, style)
        lines.append(line)
    if not lines:
        lines.append(Line())
    for line in lines:  # no trailing space at the end of a line
        if line.runs:
            text_, style = line.runs[-1]
            line.runs[-1] = (text_.rstrip(), style)
    return lines


def plain(text):
    """The text without its marks (for measuring, copying, or a one-line preview)."""
    return "".join(t for t, _s in runs(_HEADING.sub("", text)))
