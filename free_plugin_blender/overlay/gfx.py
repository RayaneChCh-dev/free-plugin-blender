"""Drawing primitives for the viewport overlay: rounded boxes, icons and text (gpu + blf)."""

from __future__ import annotations

import math

import blf
import gpu
from gpu_extras.batch import batch_for_shader

FONT = 0  # Blender's UI font


def hexa(value, alpha=1.0):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (alpha,)


# Palette (our own, deliberately neutral).
BG = hexa("#1c1d21", 0.97)
BG_RAISED = hexa("#26282d", 1.0)
BG_HOVER = hexa("#30333a", 1.0)
BORDER = hexa("#3a3d45", 1.0)
TEXT = hexa("#e8e9ec")
TEXT_DIM = hexa("#9a9ca3")
TEXT_FAINT = hexa("#6c6f77")
ACCENT = hexa("#6e8bff")
ACCENT_HOVER = hexa("#8aa0ff")
ACCENT_TEXT = hexa("#0d1020")
USER_BUBBLE = hexa("#2e3550")
DANGER = hexa("#ff6b6b")
OK = hexa("#5fd38a")

_shader = None


def _uniform():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    return _shader


def _fill(vertices, indices, color):
    shader = _uniform()
    batch = batch_for_shader(shader, "TRIS", {"pos": vertices}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def begin():
    gpu.state.blend_set("ALPHA")


def end():
    gpu.state.blend_set("NONE")


def rounded(x, y, w, h, radius, color, segments=6):
    radius = max(0.0, min(radius, w / 2, h / 2))
    if radius < 0.5:
        _fill([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], [(0, 1, 2), (0, 2, 3)], color)
        return
    corners = ((x + w - radius, y + h - radius, 0), (x + radius, y + h - radius, 90),
               (x + radius, y + radius, 180), (x + w - radius, y + radius, 270))
    outline = []
    for cx, cy, start in corners:
        for step in range(segments + 1):
            angle = math.radians(start + 90 * step / segments)
            outline.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    center = (x + w / 2, y + h / 2)
    vertices = [center, *outline]
    count = len(outline)
    indices = [(0, 1 + i, 1 + (i + 1) % count) for i in range(count)]
    _fill(vertices, indices, color)


def bordered(x, y, w, h, radius, fill, border=BORDER, width=1.0):
    rounded(x - width, y - width, w + 2 * width, h + 2 * width, radius + width, border)
    rounded(x, y, w, h, radius, fill)


def circle(cx, cy, radius, color, segments=24):
    vertices = [(cx, cy)] + [(cx + radius * math.cos(2 * math.pi * i / segments),
                              cy + radius * math.sin(2 * math.pi * i / segments)) for i in range(segments)]
    _fill(vertices, [(0, 1 + i, 1 + (i + 1) % segments) for i in range(segments)], color)


def ring(cx, cy, radius, thickness, color, segments=24, start=0.0, sweep=360.0):
    vertices, indices = [], []
    for i in range(segments + 1):
        angle = math.radians(start + sweep * i / segments)
        cos, sin = math.cos(angle), math.sin(angle)
        vertices += [(cx + radius * cos, cy + radius * sin),
                     (cx + (radius - thickness) * cos, cy + (radius - thickness) * sin)]
    for i in range(segments):
        a = 2 * i
        indices += [(a, a + 1, a + 2), (a + 1, a + 3, a + 2)]
    _fill(vertices, indices, color)


def triangle(points, color):
    _fill(list(points), [(0, 1, 2)], color)


def line(x1, y1, x2, y2, thickness, color):
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length * thickness / 2, dx / length * thickness / 2
    _fill([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)],
          [(0, 1, 2), (0, 2, 3)], color)


# --------------------------------------------------------------------------- icons

def icon_plus(cx, cy, size, color, thickness=1.6):
    line(cx - size / 2, cy, cx + size / 2, cy, thickness, color)
    line(cx, cy - size / 2, cx, cy + size / 2, thickness, color)


def icon_close(cx, cy, size, color, thickness=1.4):
    half = size / 2
    line(cx - half, cy - half, cx + half, cy + half, thickness, color)
    line(cx - half, cy + half, cx + half, cy - half, thickness, color)


def icon_send(cx, cy, size, color):
    """An upward arrow."""
    half = size / 2
    triangle([(cx, cy + half), (cx - half * 0.8, cy), (cx + half * 0.8, cy)], color)
    line(cx, cy + half * 0.2, cx, cy - half, size * 0.22, color)


def icon_stop(cx, cy, size, color):
    rounded(cx - size / 2, cy - size / 2, size, size, size * 0.18, color)


def icon_history(cx, cy, size, color, thickness=1.4):
    ring(cx, cy, size / 2, thickness, color)
    line(cx, cy, cx, cy + size * 0.3, thickness, color)
    line(cx, cy, cx + size * 0.22, cy - size * 0.1, thickness, color)


def icon_chevron(cx, cy, size, color, thickness=1.4):
    half = size / 2
    line(cx - half, cy + half * 0.4, cx, cy - half * 0.4, thickness, color)
    line(cx, cy - half * 0.4, cx + half, cy + half * 0.4, thickness, color)


def icon_spinner(cx, cy, size, color, phase):
    ring(cx, cy, size / 2, max(1.5, size * 0.14), color, segments=18, start=-phase * 360, sweep=270)


# --------------------------------------------------------------------------- text

def text_size(size):
    blf.size(FONT, size)


def measure(text, size=None):
    if size is not None:
        blf.size(FONT, size)
    return blf.dimensions(FONT, text)[0]


def text(x, y, value, size, color):
    blf.size(FONT, size)
    blf.color(FONT, *color)
    blf.position(FONT, x, y, 0)
    blf.draw(FONT, value)


def text_centered(cx, cy, value, size, color):
    blf.size(FONT, size)
    width = blf.dimensions(FONT, value)[0]
    text(cx - width / 2, cy - size * 0.36, value, size, color)


def ellipsize(value, width, size):
    blf.size(FONT, size)
    if blf.dimensions(FONT, value)[0] <= width:
        return value
    while value and blf.dimensions(FONT, value + "…")[0] > width:
        value = value[:-1]
    return value + "…"
