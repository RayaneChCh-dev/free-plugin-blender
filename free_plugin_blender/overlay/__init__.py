"""The prompt bar in the 3D viewport.

At rest it is a pill at the bottom of every 3D view. Clicking it opens a card
(design: the "Barre du viewport" mock): a header with the mode tabs, the account
status, new chat and collapse; the conversation (tool calls folded into one line
per answer) or search results; a banner when something must be set up first; the
composer with the selected objects as @mentions, the text, the model and setting
chips, and the send or Generate button with its price.

It is drawn with gpu/blf from a POST_PIXEL draw handler. A single modal
operator per window routes events: clicks on the bar and typing while it has
focus are consumed, everything else passes through to Blender. Hit rectangles
are published per region by the draw pass and read by the modal.
"""

from __future__ import annotations

import os
import re
import time
import traceback
from pathlib import Path

import bpy
import gpu

from .. import (
    account,
    animation,
    api_models,
    catalog,
    chat,
    claude_models,
    library,
    mcpserver,
    prefs,
    presets,
    tasks,
    ui_controls,
)
from . import gfx, richtext, thread
from .field import Field, wrap

MODES = (
    ("scene", "Scene"),
    ("mesh", "3D"),
    ("image", "Image"),
    ("material", "Material"),
    ("video", "Video"),
    ("animation", "Animation"),
    ("assets", "Assets"),
)
PLACEHOLDERS = {
    "scene": "Describe the scene you imagine…",
    "mesh": "Describe a 3D object…",
    "image": "Describe an image…",
    "material": "Describe a material for the active object…",
    "video": "Describe the shot…",
    "animation": "Describe a motion: a joyful jump, a slow walk…",
    "assets": "Search free Poly Haven assets…",
}
SLOT_OF_MODE = {"mesh": "mesh", "image": "image", "material": "image", "video": "video"}
ASSET_KINDS = (("hdris", "HDRI"), ("textures", "Textures"), ("models", "Models"))
SOURCES = (("POLYHAVEN", "Poly Haven"), ("MINE", "My generations"))


def _mine(context):
    """Assets tab showing your own generations rather than Poly Haven."""
    return context.scene.free_plugin.assets_source == "MINE"


def _library(context):
    """Your generations matching the tab's filter and what is typed in the field."""
    props = context.scene.free_plugin
    return library.CACHE.get(prefs.library_roots(), props.lib_filter, state.field.text.strip())


def _placeholder(context, mode):
    if mode == "assets" and _mine(context):
        return "Search your generations…"
    return PLACEHOLDERS[mode]
_PASS_THROUGH_TYPES = {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE", "TIMER", "TIMER_REPORT", "TIMERREGION",
                       "WINDOW_DEACTIVATE", "NONE", "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE",
                       "MOUSESMARTZOOM"}


class _State:
    def __init__(self):
        self.expanded = False
        self.focused = False
        self.mode = "scene"
        self.field = Field()
        self.rects: dict[int, list] = {}
        self.hover = None
        self.pressed = None
        self.scroll = 0.0
        self.show_thread = True
        self.excluded: set[str] = set()
        self.library: list = []  # the generations last drawn in Assets › My generations, for clicks
        self.picked = ""  # the image last clicked in My generations: its actions show under the list
        self.chat_images: list[tuple[str, str]] = []  # (label, path) sent to Claude with the next message
        self.hidden = False  # True while a viewport capture is taken, so the bar is not in it
        self.notice = ("", 0.0)
        self.session = 0
        self.errors = 0
        self.max_scroll = 0.0
        self.open_groups: set[int] = set()  # tool groups expanded in the conversation (first message index)


state = _State()


def _notify(text):
    state.notice = (text, time.time())


def show(mode, notice=""):
    """Open the bar on a tab (e.g. after an action elsewhere), with a notice above the field."""
    state.expanded, state.mode = True, mode
    if mode == "scene":
        state.show_thread, state.scroll = True, 0.0
    if notice:
        _notify(notice)
    _redraw()


# The actions under a generated image: (operator action, button label).
RESULT_ACTIONS = (("MATERIAL", "Use as material"), ("MESH", "Make 3D"), ("SCENE", "Build a scene"))


def _result(context, mode):
    """The generated image whose actions show above the field, or None."""
    if mode == "image":
        latest = next((t for t in tasks.TASKS if t.label.startswith("Image:")), None)
        if latest is None or latest.state != "done" or not isinstance(latest.result, str):
            return None
        path = latest.result
    elif mode == "assets" and _mine(context) and state.picked:
        path = state.picked
    else:
        return None
    return path if os.path.isfile(path) else None


def _draw_result(rects, x, y, row_w, s, path):
    """"✓ name" on the left, the action buttons on the right."""
    height, size = 34 * s, 12 * s
    gfx.outlined(x, y, row_w, height, 10 * s, gfx.SURFACE_BORDER, gfx.SURFACE)
    right = x + row_w - 6 * s
    for action, label in reversed(RESULT_ACTIONS):
        button_w = gfx.measure(label, size) + 20 * s
        right -= button_w
        hit = f"act:{action}"
        fill = gfx.ACCENT if action == "SCENE" else gfx.BG_HOVER
        if state.hover == hit:
            fill = hexa_bright(fill)
        gfx.rounded(right, y + 5 * s, button_w, height - 10 * s, 7 * s, fill)
        gfx.text_centered(right + button_w / 2, y + height / 2, label, size,
                          gfx.ACCENT_TEXT if action == "SCENE" else gfx.TEXT)
        rects.append((hit, right, y + 5 * s, button_w, height - 10 * s))
        right -= 6 * s
    gfx.icon_check(x + 16 * s, y + height / 2, 11 * s, gfx.OK)
    name = library.Entry(Path(path), "IMAGE", "images", 0).name
    gfx.text(x + 30 * s, y + height / 2 - 12.5 * s * 0.36, gfx.ellipsize(name, right - x - 40 * s, 12.5 * s),
             12.5 * s, gfx.TEXT_BODY)
    return height


def _modes():
    show_video = prefs.get().show_video
    return [(key, label) for key, label in MODES if key != "video" or show_video]


def _redraw():
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# --------------------------------------------------------------------------- data the bar shows

def _mentions(context):
    objects = list(context.selected_objects)
    active = context.active_object
    if active is not None and active in objects:
        objects.remove(active)
        objects.insert(0, active)
    state.excluded &= {o.name for o in objects}  # × lasts until deselected: selecting it again brings it back
    return [o.name for o in objects if o.name not in state.excluded][:4]


def _model_label(context, mode):
    props = context.scene.free_plugin
    if mode == "scene":
        if prefs.get().chat_provider != "CLAUDE":
            return api_models.current() or "Choose a model"
        return claude_models.model_label(prefs.get().chat_model)
    if mode == "assets":
        return dict(library.FILTERS)[props.lib_filter] if _mine(context) else dict(ASSET_KINDS)[props.ph_kind]
    if mode == "animation":
        return "Hunyuan Motion"
    entry = getattr(props, f"{SLOT_OF_MODE[mode]}_model").entry()
    return entry.get("bar_label", entry["label"]) if entry else "Choose a model"


def _needs_fal(context, mode):
    if mode == "animation":
        return True
    return mode in SLOT_OF_MODE and not (mode == "mesh" and context.scene.free_plugin.mesh_model.model == "meshy")


def _info(context, mode):
    """(text, color, action) for the chip in the card header; action runs on click."""
    if mode == "scene" and prefs.get().chat_provider != "CLAUDE":
        label = api_models.preset()["label"]
        if not prefs.api_key():
            return f"Add {label} key", gfx.DANGER, "prefs"
        return f"{label} API", gfx.TEXT_DIM, None
    if mode == "scene":
        if chat.claude_executable() is None:
            return "Install Claude Code", gfx.DANGER, "install"
        if account.account.login_running:
            return "Signing in… (browser)", gfx.TEXT_DIM, None
        if account.account.logged_in is False:
            return "Connect Claude", gfx.DANGER, "connect"
        mode = prefs.get().mcp_mode
        if mode != "OWN" and not chat.state.mcp_listening:
            return "MCP add-on off", gfx.DANGER, "prefs"
        if mode != "EXTERNAL" and mcpserver.state.error:
            return "MCP port taken", gfx.DANGER, "prefs"
        plan = f"Claude {account.account.plan}" if account.account.plan else "Claude"
        return plan, gfx.TEXT_DIM, None
    if mode == "assets":
        if _mine(context):
            count = len(_library(context))
            return f"{count} file{'s' if count != 1 else ''} · {_short_path(prefs.output_root())}", gfx.TEXT_DIM, None
        return "Poly Haven · free", gfx.TEXT_DIM, None
    if _needs_fal(context, mode) and not prefs.fal_key():
        return "Add fal.ai key", gfx.DANGER, "prefs"
    if mode == "animation":
        return f"Price: {presets.MOTION_COST}", gfx.TEXT_DIM, None
    entry = getattr(context.scene.free_plugin, f"{SLOT_OF_MODE[mode]}_model").entry() or {}
    cost = entry.get("cost")
    return (f"Price: {cost}" if cost else "Price: see fal.ai"), gfx.TEXT_DIM, None


def _short_path(path):
    return str(path).replace(os.path.expanduser("~"), "~", 1)


RENDER_LABEL = "Rendered scene"


def _attachment(context, mode):
    props = context.scene.free_plugin
    source = {"image": props.image_reference, "mesh": props.mesh_source, "video": props.video_source}.get(mode)
    if source == "RENDER":
        return RENDER_LABEL
    if mode == "image":
        if props.image_reference == "CAMERA":
            return "Camera view"
        if props.image_reference == "FILE":
            return os.path.basename(props.image_reference_path) or "Image file"
    if mode == "mesh":
        if props.mesh_source == "CAMERA":
            return "Camera view"
        if props.mesh_source == "FILE":
            return os.path.basename(props.mesh_image_path) or "Image file"
    if mode == "video" and props.video_source == "CAMERA":
        return "Camera view"
    if mode == "material":
        active = context.active_object
        return f"On: {active.name}" if active is not None and active.type == "MESH" else "Select a mesh first"
    if mode == "animation":
        rig = animation.character(context.active_object)[1]
        return f"On: {rig.name}" if rig is not None else "No rig: a mannequin is created"
    return None


def _duration_label(context):
    return f"Duration: {context.scene.free_plugin.motion_duration:g} s"


def _status():
    running = next((t for t in tasks.TASKS if t.state == "running"), None)
    if running is not None:
        return f"{running.label} — {running.detail}"
    recent = next((t for t in tasks.TASKS if time.time() - t.started < 30), None)
    if recent is not None and recent.state == "error":
        return f"{recent.label} — error: {recent.detail}"
    return ""


def _live(mode):
    """(text, kind) for the line above the field: a notice, Claude's step, a running generation."""
    notice, at = state.notice
    if notice and time.time() - at < 6:
        return notice, "notice"
    if mode == "scene" and chat.state.busy:
        return None  # shown at the end of the conversation instead
    running = next((t for t in tasks.TASKS if t.state == "running"), None)
    if running is not None:
        return f"{running.label} — {running.detail}", "busy"
    recent = next((t for t in tasks.TASKS if time.time() - t.started < 30), None)
    if recent is not None and recent.state == "error":
        return f"{recent.label} — {recent.detail}", "error"
    return None


# What to tell the user when the header chip needs an action: (sentence, button).
_FIXES = {
    "Install Claude Code": ("Claude Code is not installed: the chat runs through it.", "Install"),
    "Connect Claude": ("Connect your Claude subscription to chat.", "Connect"),
    "MCP add-on off": ("The Blender MCP add-on is off: Claude can't reach this scene.", "Fix it"),
    "MCP port taken": ("The Free Plugin MCP port is taken by another program.", "Fix it"),
    "Add fal.ai key": ("Generating needs a fal.ai key (pay per use).", "Add key"),
}


def _banner(context, mode):
    """(sentence, button) when something must be set up first, else None."""
    text, _color, action = _info(context, mode)
    if action is None:
        return None
    if text in _FIXES:
        return _FIXES[text]
    if text.startswith("Add ") and text.endswith(" key"):
        return f"Chatting with {text[4:-4]} needs its API key.", "Add key"
    return text, "Fix it"


def _usage_short():
    match = re.search(r"([\d.]+k?) tokens in .*· ([\d.]+k?) out", chat.state.usage or "")
    return f"{match[1]} in · {match[2]} out" if match else ""


def _price(context, mode):
    if mode == "animation":
        return presets.MOTION_COST
    if mode in SLOT_OF_MODE:
        entry = getattr(context.scene.free_plugin, f"{SLOT_OF_MODE[mode]}_model").entry() or {}
        return entry.get("cost") or "price: see fal.ai"
    return ""


# --------------------------------------------------------------------------- drawing

def _draw_callback():
    if state.errors > 20:
        return
    try:
        _draw(bpy.context)
    except Exception:  # noqa: BLE001 - a draw handler must never take Blender down
        state.errors += 1
        traceback.print_exc()
        if state.errors > 20:
            print("free-plugin-blender: viewport bar disabled after repeated errors")


def _draw(context):
    region = context.region
    s = context.preferences.system.ui_scale
    if region is None or region.width < 320 * s or region.height < 200 * s or state.hidden:
        return
    rects: list = []
    gfx.begin()
    try:
        if state.expanded:
            _draw_card(context, region, s, rects)
        else:
            _draw_pill(context, region, s, rects)
    finally:
        gfx.end()
    state.rects[region.as_pointer()] = rects


def _span(context, region, s):
    """(left, width) of the region the toolbar and the sidebar leave free (they overlap it by default)."""
    left = right = 0.0
    area = context.area
    if area is not None and context.preferences.system.use_region_overlap:
        for other in area.regions:
            if other.width > 1 and other.height > 1 and other.type == "TOOLS":
                left = max(left, float(other.width))
            elif other.width > 1 and other.height > 1 and other.type == "UI":
                right = max(right, float(other.width))
    if region.width - left - right < 360 * s:  # too tight: use the whole view
        return 0.0, float(region.width)
    return left, region.width - left - right


def _draw_pill(context, region, s, rects):
    left, span = _span(context, region, s)
    pill_w, height = min(460 * s, span - 40 * s), 42 * s
    x, y = left + (span - pill_w) / 2, 18 * s
    hovered = state.hover in ("pill", "pill_send")
    gfx.bordered(x, y, pill_w, height, height / 2, gfx.BG_HOVER if hovered else gfx.BG)
    gfx.icon_spark(x + 22 * s, y + height / 2, 12 * s, gfx.CLAUDE_ICON)
    size = 13.5 * s
    draft = state.field.text.splitlines()[0] if state.field.text else ""
    label = dict(MODES)[state.mode]
    label_w = gfx.measure(label, 11.5 * s)
    radius = 14 * s
    cx, cy = x + pill_w - radius - 7 * s, y + height / 2
    room = cx - radius - 12 * s - label_w - 10 * s - (x + 40 * s)
    shown = gfx.ellipsize(draft or _placeholder(bpy.context, state.mode), room, size)
    gfx.text(x + 40 * s, cy - size * 0.36, shown, size, gfx.TEXT if draft else gfx.TEXT_FAINT)
    gfx.text(cx - radius - 12 * s - label_w, cy - 11.5 * s * 0.36, label, 11.5 * s, gfx.TEXT_FAINT)
    busy = chat.state.busy and state.mode == "scene"
    ready = bool(draft.strip())
    gfx.circle(cx, cy, radius, (gfx.ACCENT_HOVER if state.hover == "pill_send" else gfx.ACCENT) if ready
               else gfx.TAB_ACTIVE)
    if busy:
        gfx.icon_spinner(cx, cy, 14 * s, gfx.ACCENT_LIGHT, time.time() % 1.0)
    else:
        gfx.icon_send(cx, cy, 12 * s, gfx.ACCENT_TEXT if ready else gfx.TEXT_DIM)
    rects.append(("pill", x, y, pill_w, height))
    rects.append(("pill_send", cx - radius, cy - radius, 2 * radius, 2 * radius))


def _chip(rects, chip_id, x, y, label, size, s, *, closable=False, chevron=False, icon_color=None, fill=None,
          style="outline", icon=None):
    """A small rounded label; returns its width. style: outline (menus), mention, attach, warn."""
    pad = 8 * s
    icon_w = 18 * s if icon else 0
    text_width = gfx.measure(label, size)
    chip_w = pad + icon_w + text_width + (16 * s if closable or chevron else 0) + pad
    height = 26 * s
    hovered = state.hover == chip_id
    if style == "outline":
        gfx.outlined(x, y, chip_w, height, 7 * s, gfx.BG_HOVER if hovered else gfx.SURFACE_BORDER,
                     fill or (gfx.BG_HOVER if hovered else gfx.SURFACE))
        color = icon_color or gfx.TEXT
    else:
        backgrounds = {"mention": gfx.MENTION_BG, "attach": gfx.BG_RAISED, "warn": gfx.WARN_BG}
        gfx.rounded(x, y, chip_w, height, 6 * s, gfx.BG_HOVER if hovered else (fill or backgrounds[style]))
        color = icon_color or {"mention": gfx.MENTION_TEXT, "warn": gfx.WARN}.get(style, gfx.TEXT)
    if icon:
        icon(x + pad + 6 * s, y + height / 2, 12 * s, color)
    gfx.text(x + pad + icon_w, y + height / 2 - size * 0.36, label, size, color)
    if closable:
        gfx.icon_close(x + chip_w - pad - 4 * s, y + height / 2, 6 * s, gfx.TEXT_DIM)
    if chevron:
        gfx.icon_chevron(x + chip_w - pad - 4 * s, y + height / 2, 7 * s, gfx.TEXT_DIM)
    rects.append((chip_id, x, y, chip_w, height))
    return chip_w


# Text metrics of the conversation, in unscaled pixels.
_SIZE, _LINE, _GAP, _INDENT, _PAD = 13.5, 20.0, 12.0, 32.0, 18.0


def _measurer(s):
    size = _SIZE * s
    return lambda text, style: gfx.measure_style(text, size, style)


def _thread_layout(content_w, s):
    """[(item, lines, height)] for the conversation, oldest first."""
    found = []
    measure = _measurer(s)
    column = content_w - _INDENT * s
    for item in thread.items(chat.state.messages):
        if item.kind == "user":
            lines = richtext.layout(richtext.plain(item.text), content_w * 0.78 - 26 * s, measure)
            height = len(lines) * _LINE * s + 18 * s
        elif item.kind == "tools":
            lines = []
            height = 28 * s + (len(item.tools) * 18 * s + 6 * s if item.key in state.open_groups else 0)
        else:
            lines = richtext.layout(item.text, column, measure, indent=14 * s)
            height = len(lines) * _LINE * s + sum(6 * s for line in lines if line.gap_before)
        found.append((item, lines, height))
    return found


def _clip(x, y, w, h):
    """Clip drawing to (x, y, w, h) in region pixels; returns the previous box for `_unclip`.

    The scissor box is in window pixels, so it is offset by the region's viewport, and
    the scissor test must be switched on: a box alone clips nothing.
    """
    previous = gpu.state.scissor_get()
    ox, oy = gpu.state.viewport_get()[:2]
    gpu.state.scissor_set(int(ox + x), int(oy + y), max(0, int(w)), max(0, int(h)))
    gpu.state.scissor_test_set(True)
    return previous


def _unclip(previous):
    gpu.state.scissor_set(*previous)
    gpu.state.scissor_test_set(False)


def _draw_thread(rects, x, y, content_w, height, s, layout):
    """The newest items that fit in (x, y, content_w, height), honouring the scroll."""
    size, line_h, gap = _SIZE * s, _LINE * s, _GAP * s
    live = (chat.state.status or "Claude is thinking…") if chat.state.busy else ""
    total = sum(h for _i, _l, h in layout) + gap * max(0, len(layout) - 1) + (30 * s if live else 0)
    state.max_scroll = max(0.0, total - height)
    state.scroll = min(state.scroll, state.max_scroll)
    rects.append(("thread", x, y, content_w, height))  # before its items, so they get the clicks
    previous = _clip(x - 4 * s, y, content_w + 8 * s, height)
    first_rect = len(rects)
    try:
        cursor = y - state.scroll  # bottom of the newest item
        if live:
            gfx.icon_spinner(x + _INDENT * s + 7 * s, cursor + 10 * s, 13 * s, gfx.ACCENT_LIGHT, time.time() % 1.0)
            gfx.text(x + _INDENT * s + 22 * s, cursor + 10 * s - 12.5 * s * 0.36,
                     gfx.ellipsize(live, content_w - _INDENT * s - 30 * s, 12.5 * s), 12.5 * s, gfx.TEXT_DIM)
            cursor += 30 * s
        for index, (item, lines, item_h) in enumerate(reversed(layout)):
            if cursor > y + height:
                break
            top = cursor + item_h
            if top >= y:
                _draw_item(rects, item, lines, x, cursor, top, content_w, s, size, line_h,
                           working=chat.state.busy and index == 0 and item.kind == "tools")
            cursor = top + gap
    finally:
        _unclip(previous)
    # Items scrolled partly out of view only take clicks where they are visible.
    kept = []
    for hit_id, hx, hy, hw, hh in rects[first_rect:]:
        low, high = max(hy, y), min(hy + hh, y + height)
        if high > low:
            kept.append((hit_id, hx, low, hw, high - low))
    rects[first_rect:] = kept


def _draw_item(rects, item, lines, x, bottom, top, content_w, s, size, line_h, *, working):
    column_x = x + _INDENT * s
    if item.avatar:
        gfx.circle(x + 11 * s, top - 11 * s, 11 * s, gfx.CLAUDE_BG)
        gfx.icon_spark(x + 11 * s, top - 11 * s, 10 * s, gfx.CLAUDE_ICON)
    if item.kind == "user":
        text_w = max((sum(gfx.measure_style(t, size, st) for t, st in line.runs) for line in lines), default=0)
        bubble_w = text_w + 26 * s
        bx = x + content_w - bubble_w
        gfx.rounded(bx, bottom, bubble_w, top - bottom, 12 * s, gfx.USER_BUBBLE)
        for row, line in enumerate(lines):
            gfx.rich_line(bx + 13 * s, top - 9 * s - (row + 1) * line_h + 5 * s, line, size, gfx.USER_TEXT)
        return
    if item.kind == "tools":
        head, detail = thread.summary(item)
        opened = item.key in state.open_groups
        hover = state.hover == f"tools:{item.key}"
        box_h = top - bottom
        head_w = gfx.measure(head, 12 * s)
        detail = gfx.ellipsize(detail, content_w - _INDENT * s - head_w - 80 * s, 12 * s)
        box_w = min(content_w - _INDENT * s, 50 * s + head_w + gfx.measure(detail, 12 * s) + 30 * s)
        gfx.outlined(column_x, bottom, box_w, box_h, 8 * s, gfx.TOOL_BORDER, gfx.BG_HOVER if hover else gfx.TOOL_BG)
        row_y = top - 14 * s
        chevron = gfx.icon_chevron if opened else gfx.icon_chevron_right
        chevron(column_x + 14 * s, row_y, 8 * s, gfx.TEXT_DIM)
        gfx.text(column_x + 26 * s, row_y - 12 * s * 0.36, head, 12 * s, gfx.TEXT_BODY)
        gfx.text(column_x + 34 * s + head_w, row_y - 12 * s * 0.36, detail, 12 * s, gfx.TEXT_FAINT)
        mark_x = column_x + box_w - 14 * s
        if working:
            gfx.icon_spinner(mark_x, row_y, 11 * s, gfx.ACCENT_LIGHT, time.time() % 1.0)
        elif item.failed:
            gfx.icon_close(mark_x, row_y, 7 * s, gfx.DANGER, thickness=1.7)
        else:
            gfx.icon_check(mark_x, row_y, 11 * s, gfx.OK)
        if opened:
            for row, line in enumerate(item.tools):
                color = gfx.DANGER if line.startswith("failed:") else gfx.TEXT_FAINT
                gfx.text(column_x + 26 * s, top - 28 * s - (row + 1) * 18 * s + 5 * s,
                         gfx.ellipsize(line, box_w - 40 * s, 11.5 * s), 11.5 * s, color)
        rects.append((f"tools:{item.key}", column_x, bottom, box_w, box_h))
        return
    color = {"error": gfx.DANGER, "info": gfx.TEXT_DIM}.get(item.kind, gfx.TEXT_BODY)
    baseline = top
    for line in lines:
        if line.gap_before:
            baseline -= 6 * s
        baseline -= line_h
        gfx.rich_line(column_x, baseline + 5 * s, line, size, color)


def _draw_assets(context, rects, x, y, content_w, height, s):
    if _mine(context):
        _draw_library(context, rects, x, y, content_w, height, s)
        return
    props = context.scene.free_plugin
    size, row = 12.5 * s, 30 * s
    results = list(props.ph_results)
    if not results:
        gfx.text(x, y + height / 2 - 4 * s, "Search, then click a result: HDRI → world, "
                 "texture → active mesh, model → 3D cursor.", 12 * s, gfx.TEXT_DIM)
        return
    columns = 2
    column_w = (content_w - 8 * s) / columns
    for index, item in enumerate(results[: columns * int(height // row)]):
        column, line = index % columns, index // columns
        rx = x + column * (column_w + 8 * s)
        ry = y + height - (line + 1) * row
        item_id = f"asset:{item.asset_id}"
        gfx.outlined(rx, ry + 2 * s, column_w, row - 4 * s, 7 * s, gfx.SURFACE_BORDER,
                     gfx.BG_HOVER if state.hover == item_id else gfx.SURFACE)
        gfx.text(rx + 10 * s, ry + row / 2 - size * 0.36, gfx.ellipsize(item.name, column_w - 20 * s, size),
                 size, gfx.TEXT)
        rects.append((item_id, rx, ry + 2 * s, column_w, row - 4 * s))


def _draw_library(context, rects, x, y, content_w, height, s):
    """Your generations in two columns, newest first: name, and its kind on the right."""
    size, row = 12.5 * s, 30 * s
    entries = _library(context)
    state.library = entries
    if not entries:
        hint = ("Nothing matches: try another word or filter" if state.field.text.strip()
                or context.scene.free_plugin.lib_filter != "ALL" else
                f"What you generate lands in {_short_path(prefs.output_root())} and shows up here.")
        gfx.text(x, y + height / 2 - 4 * s, hint, 12 * s, gfx.TEXT_DIM)
        return
    columns = 2
    column_w = (content_w - 8 * s) / columns
    for index, entry in enumerate(entries[: columns * int(height // row)]):
        column, line = index % columns, index // columns
        rx = x + column * (column_w + 8 * s)
        ry = y + height - (line + 1) * row
        item_id = f"lib:{index}"
        gfx.outlined(rx, ry + 2 * s, column_w, row - 4 * s, 7 * s, gfx.SURFACE_BORDER,
                     gfx.BG_HOVER if state.hover == item_id else gfx.SURFACE)
        tag = entry.label
        tag_w = gfx.measure(tag, 11 * s)
        gfx.text(rx + 10 * s, ry + row / 2 - size * 0.36,
                 gfx.ellipsize(entry.name, column_w - tag_w - 30 * s, size), size, gfx.TEXT)
        gfx.text(rx + column_w - 10 * s - tag_w, ry + row / 2 - 11 * s * 0.36, tag, 11 * s, gfx.TEXT_FAINT)
        rects.append((item_id, rx, ry + 2 * s, column_w, row - 4 * s))


def _icon_button(rects, hit_id, x, y, size, painter, s):
    if state.hover == hit_id:
        gfx.rounded(x, y, size, size, 7 * s, gfx.BG_HOVER)
    painter(x + size / 2, y + size / 2, 11 * s, gfx.TEXT_DIM)
    rects.append((hit_id, x, y, size, size))


def _draw_header(context, mode, x, y, card_w, s, rects, banner):
    """Tabs, status, new chat and collapse; returns its height."""
    height = 46 * s
    gfx.line(x + 1, y, x + card_w - 1, y, 1.0, gfx.DIVIDER)
    button = 30 * s
    bx = x + card_w - 10 * s - button
    by = y + (height - button) / 2
    _icon_button(rects, "collapse", bx, by, button, gfx.icon_chevron, s)
    right = bx - 4 * s
    if mode == "scene":
        right -= button
        _icon_button(rects, "new", right, by, button, gfx.icon_plus, s)
        right -= 8 * s
    status = ""
    if banner is None and mode in ("scene", "assets"):
        status = _info(context, mode)[0]
    if status:
        status_w = gfx.measure(status, 12 * s)
        gfx.text(right - status_w, y + height / 2 - 12 * s * 0.36, status, 12 * s, gfx.TEXT_DIM)
        if mode == "scene":
            gfx.circle(right - status_w - 10 * s, y + height / 2, 3.5 * s, gfx.OK)
            status_w += 16 * s
        right -= status_w + 12 * s
    modes = _modes()
    for tab_size, pad in ((12.5 * s, 11 * s), (11.5 * s, 7 * s), (10.5 * s, 5 * s)):
        widths = [gfx.measure(label, tab_size) + 2 * pad for _key, label in modes]
        if x + 12 * s + sum(widths) + 6 * s + 2 * s * len(widths) <= right:
            break
    rail_h = 32 * s
    rail_x, rail_y = x + 12 * s, y + (height - rail_h) / 2
    rail_w = sum(widths) + 2 * s * (len(widths) - 1) + 6 * s
    gfx.rounded(rail_x, rail_y, rail_w, rail_h, 9 * s, gfx.SURFACE)
    cursor = rail_x + 3 * s
    for (key, label), tab_w in zip(modes, widths):
        tab_id = f"tab:{key}"
        if key == mode or state.hover == tab_id:
            gfx.rounded(cursor, rail_y + 3 * s, tab_w, rail_h - 6 * s, 7 * s,
                        gfx.TAB_ACTIVE if key == mode else gfx.BG_RAISED)
        gfx.text_centered(cursor + tab_w / 2, rail_y + rail_h / 2, label, tab_size,
                          gfx.TEXT_STRONG if key == mode else gfx.TEXT_DIM)
        rects.append((tab_id, cursor, rail_y + 3 * s, tab_w, rail_h - 6 * s))
        cursor += tab_w + 2 * s
    return height


def _draw_banner(rects, x, y, banner_w, s, banner):
    sentence, button = banner
    height = 38 * s
    gfx.outlined(x, y, banner_w, height, 10 * s, gfx.WARN_BORDER, gfx.WARN_BG)
    gfx.icon_warning(x + 20 * s, y + height / 2, 13 * s, gfx.WARN)
    button_w = gfx.measure(button, 12 * s) + 22 * s
    bx = x + banner_w - 8 * s - button_w
    gfx.rounded(bx, y + 6 * s, button_w, height - 12 * s, 7 * s,
                hexa_bright(gfx.WARN) if state.hover == "info" else gfx.WARN)
    gfx.text_centered(bx + button_w / 2, y + height / 2, button, 12 * s, gfx.DARK_TEXT)
    gfx.text(x + 36 * s, y + height / 2 - 12.5 * s * 0.36,
             gfx.ellipsize(sentence, bx - x - 48 * s, 12.5 * s), 12.5 * s, gfx.WARN_TEXT)
    rects.append(("info", bx, y + 6 * s, button_w, height - 12 * s))
    return height


def hexa_bright(color, amount=0.12):
    return tuple(min(1.0, c + amount) for c in color[:3]) + (color[3],)


def _draw_live(x, y, live_w, s, live):
    text, kind = live
    size = 12.5 * s
    cy = y + 10 * s
    if kind == "busy":
        gfx.icon_spinner(x + 7 * s, cy, 13 * s, gfx.ACCENT_LIGHT, time.time() % 1.0)
    else:
        gfx.circle(x + 7 * s, cy, 3.5 * s, gfx.DANGER if kind == "error" else gfx.ACCENT_LIGHT)
    color = {"error": gfx.DANGER, "notice": gfx.TEXT}.get(kind, gfx.TEXT_DIM)
    gfx.text(x + 20 * s, cy - size * 0.36, gfx.ellipsize(text, live_w - 24 * s, size), size, color)
    return 20 * s


def _draw_card(context, region, s, rects):
    mode = state.mode
    left, span = _span(context, region, s)
    card_w = min(720 * s, span - 32 * s)
    x, y0 = left + (span - card_w) / 2, 16 * s
    margin, pad = 12 * s, 12 * s
    size, line_h = 14 * s, 21 * s

    # Composer geometry, bottom-up: bottom row, text, chips.
    box_x, box_w = x + margin, card_w - 2 * margin
    text_x, text_w = box_x + pad, box_w - 2 * pad
    gfx.text_size(size)
    field = state.field
    lines = wrap(field.text, text_w, lambda t: gfx.measure(t)) if field.text else [(0, 0)]
    shown_lines = max(2, min(6, len(lines)))
    mentions = _mentions(context) if mode == "scene" else []
    attachment = _attachment(context, mode)
    chat_images = state.chat_images if mode == "scene" else []
    chips_h = 34 * s if (mentions or attachment or chat_images) else 0
    bottom_h = 30 * s
    box_h = 10 * s + chips_h + shown_lines * line_h + 8 * s + bottom_h + 8 * s

    banner = _banner(context, mode)
    live = _live(mode)
    result = _result(context, mode)
    layout, middle_h = None, 0
    if mode == "assets":
        count = len(_library(context)) if _mine(context) else len(context.scene.free_plugin.ph_results)
        middle_h = min(-(-count // 2) * 30 * s, 182 * s) if count else 30 * s
    elif mode == "scene" and state.show_thread and (chat.state.messages or chat.state.busy):
        layout = _thread_layout(card_w - 2 * _PAD * s, s)
        content = sum(h for _i, _l, h in layout) + _GAP * s * max(0, len(layout) - 1)
        content += 30 * s if chat.state.busy else 0
        middle_h = min(content, 300 * s, region.height * 0.45)

    header_h = 46 * s
    cursor = y0 + margin + box_h + 10 * s
    live_y = cursor
    if live:
        cursor += 20 * s + 8 * s
    result_y = cursor
    if result:
        cursor += 34 * s + 10 * s
    banner_y = cursor
    if banner:
        cursor += 38 * s + 10 * s
    middle_y = cursor
    if middle_h:
        cursor += middle_h + 14 * s
    card_h = cursor - y0 + header_h

    gfx.bordered(x, y0, card_w, card_h, 14 * s, gfx.BG)
    rects.append(("card", x, y0, card_w, card_h))
    _draw_header(context, mode, x, y0 + card_h - header_h, card_w, s, rects, banner)

    if middle_h:
        if mode == "assets":
            _draw_assets(context, rects, x + _PAD * s, middle_y, card_w - 2 * _PAD * s, middle_h, s)
        else:
            _draw_thread(rects, x + _PAD * s, middle_y, card_w - 2 * _PAD * s, middle_h, s, layout)
    if banner:
        _draw_banner(rects, box_x, banner_y, box_w, s, banner)
    if live:
        _draw_live(box_x + 4 * s, live_y, box_w - 8 * s, s, live)
    if result:
        _draw_result(rects, box_x, result_y, box_w, s, result)

    # Composer box.
    box_y = y0 + margin
    gfx.outlined(box_x, box_y, box_w, box_h, 12 * s, gfx.FOCUS_BORDER if state.focused else gfx.SURFACE_BORDER,
                 gfx.SURFACE)
    top = box_y + box_h - 10 * s
    chip_y = top - 26 * s
    cx = text_x
    chip_size = 12 * s
    if attachment:
        warning = attachment == "Select a mesh first"
        icon = (gfx.icon_camera if attachment in ("Camera view", RENDER_LABEL)
                else gfx.icon_warning if warning else None)
        cx += _chip(rects, "attach_clear", cx, chip_y, attachment, chip_size, s,
                    closable=mode not in ("material", "animation"), style="warn" if warning else "attach",
                    icon=icon) + 6 * s
    for name in mentions:
        cx += _chip(rects, f"mention:{name}", cx, chip_y, "@" + name, chip_size, s, closable=True,
                    style="mention") + 6 * s
    for index, (label, _path) in enumerate(chat_images):
        cx += _chip(rects, f"chat_image:{index}", cx, chip_y, label, chip_size, s, closable=True,
                    style="attach", icon=gfx.icon_camera) + 6 * s
    text_top = top - chips_h
    first_line = max(0, len(lines) - shown_lines)
    caret_line = next((i for i, (a, b) in enumerate(lines) if a <= field.caret <= b), len(lines) - 1)
    if caret_line < first_line:
        first_line = caret_line
    placeholder = "Claude is working…" if mode == "scene" and chat.state.busy else _placeholder(context, mode)
    if not field.text:
        gfx.text(text_x, text_top - line_h + 5 * s, placeholder, size, gfx.TEXT_FAINT)
    for row, (a, b) in enumerate(lines[first_line:first_line + shown_lines]):
        baseline = text_top - (row + 1) * line_h + 5 * s
        gfx.text(text_x, baseline, field.text[a:b], size, gfx.TEXT)
    if state.focused and int(time.time() * 2) % 2 == 0:
        a, _b = lines[caret_line]
        row = caret_line - first_line
        caret_x = text_x + gfx.measure(field.text[a:field.caret], size)
        baseline = text_top - (row + 1) * line_h + 5 * s
        gfx.line(caret_x + 1, baseline - 4 * s, caret_x + 1, baseline + size * 0.95, 1.5 * s, gfx.ACCENT_LIGHT)
    rects.append(("text", text_x, text_top - shown_lines * line_h, text_w, shown_lines * line_h))

    # Bottom row: the send / generate button on the right, its label, then the chips from the left.
    by = box_y + 8 * s
    busy = mode == "scene" and chat.state.busy
    empty = not field.text.strip() and not (mode == "assets" and _mine(context))
    if mode == "scene":
        radius = 16 * s
        gx, gy, gw, gh = box_x + box_w - pad - 2 * radius, by - 1 * s, 2 * radius, 2 * radius
        if busy:
            gfx.circle(gx + radius, gy + radius, radius, gfx.BG_HOVER if state.hover != "generate" else gfx.TAB_ACTIVE)
            gfx.ring(gx + radius, gy + radius, radius, 1.0 * s, hexa_bright(gfx.BG_HOVER, 0.08))
            gfx.icon_stop(gx + radius, gy + radius, 10 * s, gfx.TEXT)
        else:
            fill = gfx.TAB_ACTIVE if empty else (gfx.ACCENT_HOVER if state.hover == "generate" else gfx.ACCENT)
            gfx.circle(gx + radius, gy + radius, radius, fill)
            gfx.icon_send(gx + radius, gy + radius, 13 * s, gfx.TEXT_DIM if empty else gfx.ACCENT_TEXT)
        label = _usage_short()
    else:
        word = ("Refresh" if _mine(context) else "Search") if mode == "assets" else "Generate"
        gw, gh = gfx.measure(word, 12.5 * s) + 26 * s, 30 * s
        gx, gy = box_x + box_w - pad - gw, by
        fill = gfx.TAB_ACTIVE if empty else (gfx.ACCENT_HOVER if state.hover == "generate" else gfx.ACCENT)
        gfx.rounded(gx, gy, gw, gh, 8 * s, fill)
        gfx.text_centered(gx + gw / 2, gy + gh / 2, word, 12.5 * s, gfx.TEXT_FAINT if empty else gfx.ACCENT_TEXT)
        label = _price(context, mode)
    rects.append(("generate", gx, gy, gw, gh))
    room = gx - 10 * s
    if label:
        label_w = gfx.measure(label, 11.5 * s)
        gfx.text(room - label_w, by + 15 * s - 11.5 * s * 0.36, label, 11.5 * s, gfx.TEXT_FAINT)
        room -= label_w + 12 * s

    bx = text_x
    if mode in ("scene", "image", "mesh", "video"):
        box = 28 * s
        gfx.outlined(bx, by + 1 * s, box, box, 7 * s, gfx.SURFACE_BORDER,
                     gfx.BG_HOVER if state.hover == "attach" else gfx.SURFACE)
        gfx.icon_plus(bx + box / 2, by + 1 * s + box / 2, 11 * s, gfx.TEXT_DIM)
        rects.append(("attach", bx, by + 1 * s, box, box))
        bx += box + 6 * s
    if mode == "assets":
        source = dict(SOURCES)[context.scene.free_plugin.assets_source]
        bx += _chip(rects, "source", bx, by + 2 * s, source, chip_size, s, chevron=True) + 6 * s
    bx += _chip(rects, "model", bx, by + 2 * s, _model_label(context, mode), chip_size, s, chevron=True) + 6 * s
    if mode == "scene":
        effort = claude_models.effort_label(prefs.get().chat_effort)
        _chip(rects, "effort", bx, by + 2 * s, effort, chip_size, s, chevron=True)
    elif mode == "animation":
        _chip(rects, "duration", bx, by + 2 * s, _duration_label(context), chip_size, s, chevron=True)
    elif mode in ui_controls.BAR_CONTROLS:
        slot = SLOT_OF_MODE[mode]
        for key in ui_controls.BAR_CONTROLS[mode]:
            control, supported, _value, label_ = ui_controls.control_state(context.scene, slot, key)
            if not supported:
                continue
            text = label_ or control.label
            chip_w = gfx.measure(text, chip_size) + 32 * s
            if bx + chip_w > room:
                break
            bx += _chip(rects, f"control:{slot}:{key}", bx, by + 2 * s, text, chip_size, s, chevron=True,
                        icon_color=gfx.TEXT if label_ else gfx.TEXT_DIM) + 6 * s


# --------------------------------------------------------------------------- input

def _hit(context, event):
    """(region, id) under the mouse, or (region, None) / (None, None)."""
    for area in context.window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type != "WINDOW":
                continue
            lx, ly = event.mouse_x - region.x, event.mouse_y - region.y
            if not (0 <= lx < region.width and 0 <= ly < region.height):
                continue
            # Later rects are drawn on top: test them first, "card" last.
            for hit_id, x, y, w, h in reversed(state.rects.get(region.as_pointer(), [])):
                if x <= lx <= x + w and y <= ly <= y + h:
                    return region, hit_id
            return region, None
    return None, None


def _submit(context):
    props = context.scene.free_plugin
    mode = state.mode
    text = state.field.text.strip()
    if mode == "scene":
        if chat.state.busy:
            chat.stop()
            return
        if not text:
            return
        mentions = _mentions(context)
        note = f"[Blender selection: {', '.join(mentions)}; active: {mentions[0]}]" if mentions else ""
        images = [path for _label, path in state.chat_images if os.path.isfile(path)]
        error = chat.send(text, context.scene, note, images=images)
        if error:
            _notify(error)
            return
        state.field.set("")
        state.chat_images.clear()
        state.show_thread, state.scroll = True, 0.0
        return

    if mode == "assets" and _mine(context):
        library.CACHE.clear()  # the list filters as you type; this re-reads the folder
        return

    operator, prop = {
        "mesh": ("generate_3d", "mesh_prompt"),
        "image": ("generate_image", "image_prompt"),
        "material": ("generate_texture", "texture_prompt"),
        "video": ("generate_video", "video_prompt"),
        "animation": ("generate_motion", "motion_prompt"),
        "assets": ("polyhaven_search", "ph_query"),
    }[mode]
    if not text and not (mode == "mesh" and props.mesh_source != "TEXT"):
        _notify("Write a prompt first")
        return
    if _needs_fal(context, mode) and not prefs.fal_key():
        _notify("Add your fal.ai key first: click “Add fal.ai key” at the top right")
        return
    if mode == "material" and (context.active_object is None or context.active_object.type != "MESH"):
        _notify("Select a mesh first: the material is applied to it")
        return
    setattr(props, prop, text)
    try:
        result = getattr(bpy.ops.freeplugin, operator)()
    except RuntimeError as error:
        _notify("Select a mesh first" if "poll" in str(error) else str(error).splitlines()[-1][:120])
        return
    if "CANCELLED" in result:
        _notify("Could not start: see the status bar")
        return
    if mode != "assets":
        state.field.set("")
        _notify("Started — follow it in the header, results land in the scene")


def _open_menu(context, name):
    """Menus opened from inside the modal's event handling never show; open them right after it."""
    window, area = context.window, context.area
    region_type = "WINDOW"

    def show():
        target_area = area if area is not None and area.type == "VIEW_3D" else next(
            (a for a in window.screen.areas if a.type == "VIEW_3D"), None)
        if target_area is None:
            return None
        region = next(r for r in target_area.regions if r.type == region_type)
        with bpy.context.temp_override(window=window, area=target_area, region=region):
            bpy.ops.wm.call_menu(name=name)
        return None

    bpy.app.timers.register(show, first_interval=0.01)


def _click(context, hit):
    props = context.scene.free_plugin
    if hit in ("pill", "pill_send"):
        state.expanded = state.focused = True
        if hit == "pill_send" and state.field.text.strip():
            _submit(context)
    elif hit in ("card", "text", "thread"):
        state.focused = True
    elif hit.startswith("tab:"):
        state.mode, state.scroll, state.focused = hit[4:], 0.0, True
    elif hit == "new":
        chat.reset()
        state.chat_images.clear()
        state.field.set("")
        state.scroll = 0.0
        state.open_groups.clear()
    elif hit == "collapse":
        state.expanded = state.focused = False
    elif hit.startswith("tools:"):
        state.open_groups ^= {int(hit[6:])}
    elif hit == "model":
        _open_menu(context, FREEPLUGIN_MT_overlay_model.bl_idname)
    elif hit == "effort":
        _open_menu(context, FREEPLUGIN_MT_overlay_effort.bl_idname)
    elif hit == "duration":
        _open_menu(context, FREEPLUGIN_MT_overlay_duration.bl_idname)
    elif hit.startswith("control:"):
        _prefix, slot, key = hit.split(":")
        ui_controls.open_menu(slot, key)
        _open_menu(context, ui_controls.FREEPLUGIN_MT_control.bl_idname)
    elif hit == "attach":
        _open_menu(context, FREEPLUGIN_MT_overlay_attach.bl_idname)
    elif hit == "attach_clear":
        if state.mode != "material":
            _set_source(props, state.mode, "NONE")
    elif hit.startswith("chat_image:"):
        index = int(hit[11:])
        if index < len(state.chat_images):
            del state.chat_images[index]
    elif hit.startswith("mention:"):
        state.excluded.add(hit[8:])
    elif hit == "source":
        _open_menu(context, FREEPLUGIN_MT_overlay_source.bl_idname)
    elif hit.startswith("lib:"):
        index = int(hit[4:])
        if index < len(state.library):
            entry = state.library[index]
            bpy.ops.freeplugin.library_use(filepath=str(entry.path))
            _notify(f"{entry.name}: added to the scene")
            if entry.kind == "IMAGE":
                state.picked = str(entry.path)
    elif hit.startswith("act:"):
        path = _result(context, state.mode)
        if path:
            try:
                bpy.ops.freeplugin.use_generation(filepath=path, action=hit[4:])
            except RuntimeError as error:
                _notify(str(error).splitlines()[-1].replace("Error: ", "")[:120])
            else:
                if hit == "act:MATERIAL":
                    _notify("Material applied to the active mesh")
    elif hit.startswith("asset:"):
        bpy.ops.freeplugin.polyhaven_apply(asset_id=hit[6:], kind=props.ph_kind)
        _notify(f"Applying {hit[6:]}…")
    elif hit == "info":
        _text, _color, action = _info(context, state.mode)
        if action == "connect":
            error = account.login()
            _notify(error or "Finish signing in in your browser, then come back")
        elif action == "install":
            bpy.ops.freeplugin.claude_install()
            _notify("Install command copied: paste it in a terminal")
        elif action == "prefs":
            bpy.ops.preferences.addon_show(module=prefs.ADDON_ID)
    elif hit == "generate":
        _submit(context)


def _key(context, event):
    field = state.field
    word = event.ctrl or event.oskey
    kind = event.type
    if kind == "ESC":
        state.focused = False
        if not field.text:
            state.expanded = False
    elif kind in ("RET", "NUMPAD_ENTER"):
        if event.shift:
            field.insert("\n")
        else:
            _submit(context)
    elif kind == "BACK_SPACE":
        field.backspace(word)
    elif kind == "DEL":
        field.delete(word)
    elif kind == "LEFT_ARROW":
        field.left(word)
    elif kind == "RIGHT_ARROW":
        field.right(word)
    elif kind == "HOME":
        field.home()
    elif kind == "END":
        field.end()
    elif word and kind == "V":
        field.insert(context.window_manager.clipboard)
    elif word and kind == "A":
        field.caret = len(field.text)
    elif event.unicode and not word and event.unicode.isprintable():
        field.insert(event.unicode)


def _handle(context, event):
    kind, value = event.type, event.value
    region, hit = _hit(context, event)
    if kind in ("MOUSEMOVE", "INBETWEEN_MOUSEMOVE"):
        if hit != state.hover:
            state.hover = hit
            _redraw()
        return {"PASS_THROUGH"}

    if kind == "LEFTMOUSE":
        if value == "PRESS":
            if hit is not None:
                state.pressed = hit
                _click(context, hit)
                _redraw()
                return {"RUNNING_MODAL"}
            if state.focused or state.expanded:
                state.focused = False
                if not state.field.text and not chat.state.busy:
                    state.expanded = False
                _redraw()
        elif value == "RELEASE" and state.pressed is not None:
            state.pressed = None
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    if kind in ("WHEELUPMOUSE", "WHEELDOWNMOUSE") and state.expanded and hit is not None:
        if hit == "thread":
            step = 40 * context.preferences.system.ui_scale
            state.scroll = max(0.0, min(state.max_scroll, state.scroll + (step if kind == "WHEELUPMOUSE" else -step)))
            _redraw()
        return {"RUNNING_MODAL"}

    if kind in ("RIGHTMOUSE", "MIDDLEMOUSE") and hit is not None:
        return {"RUNNING_MODAL"}

    if state.focused and kind not in _PASS_THROUGH_TYPES and not kind.startswith(("NDOF", "TIMER", "EVT_")) \
            and "MOUSE" not in kind:
        if value == "PRESS":
            _key(context, event)
            _redraw()
        return {"RUNNING_MODAL"}
    return {"PASS_THROUGH"}


class FREEPLUGIN_OT_overlay(bpy.types.Operator):
    bl_idname = "freeplugin.overlay"
    bl_label = "Viewport prompt bar"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        self.session = state.session
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if self.session != state.session:
            return {"CANCELLED", "PASS_THROUGH"}
        try:
            return _handle(context, event)
        except Exception:  # noqa: BLE001 - never trap the user's input
            traceback.print_exc()
            state.errors += 1
            return {"PASS_THROUGH"}


# --------------------------------------------------------------------------- menus and small operators

def _set_source(props, mode, value):
    if mode == "image":
        props.image_reference = value if value != "TEXT" else "NONE"
    elif mode == "mesh":
        props.mesh_source = "TEXT" if value == "NONE" else value
    elif mode == "video":
        props.video_source = "TEXT" if value == "NONE" else value


class FREEPLUGIN_OT_overlay_set(bpy.types.Operator):
    bl_idname = "freeplugin.overlay_set"
    bl_label = "Choose"
    bl_options = {"INTERNAL"}

    target: bpy.props.StringProperty()
    value: bpy.props.StringProperty()

    def execute(self, context):
        props = context.scene.free_plugin
        if self.target == "chat_model":
            prefs.get().chat_model = self.value
        elif self.target == "chat_effort":
            prefs.get().chat_effort = self.value
        elif self.target == "api_model":
            api_models.choose(self.value)
        elif self.target == "duration":
            props.motion_duration = float(self.value)
        elif self.target == "kind":
            props.ph_kind = self.value
            props.ph_results.clear()
        elif self.target == "assets_source":
            props.assets_source = self.value
        elif self.target == "lib_filter":
            props.lib_filter = self.value
        elif self.target == "source":
            _set_source(props, state.mode, self.value)
        elif self.target in catalog.SLOTS:
            getattr(props, f"{self.target}_model").model = self.value
        _redraw()
        return {"FINISHED"}


class FREEPLUGIN_OT_overlay_pick_file(bpy.types.Operator):
    bl_idname = "freeplugin.overlay_pick_file"
    bl_label = "Use image"
    bl_options = {"INTERNAL"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_image: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        props = context.scene.free_plugin
        if state.mode == "scene":
            state.chat_images.append((os.path.basename(self.filepath), bpy.path.abspath(self.filepath)))
            _redraw()
            return {"FINISHED"}
        if state.mode == "image":
            props.image_reference_path = self.filepath
        else:
            props.mesh_image_path = self.filepath
        _set_source(props, state.mode, "FILE")
        _redraw()
        return {"FINISHED"}


class FREEPLUGIN_OT_overlay_chat_attach(bpy.types.Operator):
    """Scene tab "+": capture the viewport, the camera or a render, to send with the next message."""

    bl_idname = "freeplugin.overlay_chat_attach"
    bl_label = "Show Claude"
    bl_description = "Attach a picture of the scene to your next message"
    bl_options = {"INTERNAL"}

    source: bpy.props.EnumProperty(items=[("VIEWPORT", "Viewport capture", "What the 3D view shows, without this bar"),
                                          ("CAMERA", "Camera view", "A quick viewport render of the active camera"),
                                          ("RENDER", "Render scene", "A full render with the scene's engine (F12)")])

    def execute(self, context):
        from .. import scene as scene_utils

        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = prefs.output_dir("captures") / f"{stamp}-{self.source.lower()}.png"
        label = {"VIEWPORT": "Viewport", "CAMERA": "Camera view", "RENDER": RENDER_LABEL}[self.source]
        if self.source == "VIEWPORT":
            _capture_viewport(context.window, path, label)
            return {"FINISHED"}
        try:
            if self.source == "CAMERA":
                scene_utils.capture_camera(path)
            else:
                _notify("Rendering…")
                scene_utils.render_scene(path)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            _notify(str(error))
            return {"CANCELLED"}
        state.chat_images.append((label, str(path)))
        _redraw()
        return {"FINISHED"}


def _capture_viewport(window, path, label):
    """Hide the bar, let the view redraw, take the screenshot, show the bar again."""
    state.hidden = True
    _redraw()

    def shoot():
        try:
            area = next((a for a in window.screen.areas if a.type == "VIEW_3D"), None)
            if area is None:
                _notify("No 3D view to capture")
                return None
            region = next(r for r in area.regions if r.type == "WINDOW")
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.screen.screenshot_area(filepath=str(path))
            state.chat_images.append((label, str(path)))
        finally:
            state.hidden = False
            _redraw()
        return None

    bpy.app.timers.register(shoot, first_interval=0.15)


class FREEPLUGIN_OT_overlay_browse(bpy.types.Operator):
    """Menu entry for "Image file…": opens the file browser once the menu has closed."""

    bl_idname = "freeplugin.overlay_browse"
    bl_label = "Image file…"
    bl_description = "Pick an image on disk to start from"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        window = context.window

        def browse():
            area = next((a for a in window.screen.areas if a.type == "VIEW_3D"), window.screen.areas[0])
            region = next(r for r in area.regions if r.type == "WINDOW")
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.freeplugin.overlay_pick_file("INVOKE_DEFAULT")
            return None

        bpy.app.timers.register(browse, first_interval=0.05)
        return {"FINISHED"}


class FREEPLUGIN_MT_overlay_model(bpy.types.Menu):
    bl_idname = "FREEPLUGIN_MT_overlay_model"
    bl_label = "Model"

    def draw(self, context):
        layout = self.layout
        mode = state.mode
        if mode == "scene" and prefs.get().chat_provider != "CLAUDE":
            from .. import panels

            panels.draw_api_models(layout)
            return
        if mode == "scene":
            current = prefs.get().chat_model
            for key, label, _text in claude_models.MODELS:
                op = layout.operator("freeplugin.overlay_set", text=label,
                                     icon="CHECKMARK" if key == current else "BLANK1")
                op.target, op.value = "chat_model", key
            return
        if mode == "assets" and _mine(context):
            current = context.scene.free_plugin.lib_filter
            for key, label in library.FILTERS:
                op = layout.operator("freeplugin.overlay_set", text=label,
                                     icon="CHECKMARK" if key == current else "BLANK1")
                op.target, op.value = "lib_filter", key
            return
        if mode == "assets":
            for key, label in ASSET_KINDS:
                op = layout.operator("freeplugin.overlay_set", text=label)
                op.target, op.value = "kind", key
            return
        if mode == "animation":
            layout.label(text=f"Hunyuan Motion   {presets.MOTION_COST}", icon="CHECKMARK")
            layout.separator()
            layout.label(text="Presets: sidebar (N) › Free Plugin › Animation", icon="INFO")
            return
        slot = SLOT_OF_MODE[mode]
        for entry in catalog.models(slot):
            cost = f"   {entry['cost']}" if entry.get("cost") else ""
            op = layout.operator("freeplugin.overlay_set", text=entry["label"] + cost)
            op.target, op.value = slot, entry["key"]
        layout.separator()
        layout.label(text="Other fal.ai models: sidebar (N) › Free Plugin", icon="INFO")


class FREEPLUGIN_MT_overlay_effort(bpy.types.Menu):
    bl_idname = "FREEPLUGIN_MT_overlay_effort"
    bl_label = "Effort"

    def draw(self, context):
        layout = self.layout
        current = prefs.get().chat_effort
        for key, label, text in claude_models.EFFORTS:
            op = layout.operator("freeplugin.overlay_set", text=f"{label} — {text}",
                                 icon="CHECKMARK" if key == current else "BLANK1")
            op.target, op.value = "chat_effort", key


class FREEPLUGIN_MT_overlay_duration(bpy.types.Menu):
    bl_idname = "FREEPLUGIN_MT_overlay_duration"
    bl_label = "Duration"

    def draw(self, context):
        layout = self.layout
        current = context.scene.free_plugin.motion_duration
        for seconds, label in presets.MOTION_DURATIONS:
            op = layout.operator("freeplugin.overlay_set", text=f"{label} ({seconds:g} s)",
                                 icon="CHECKMARK" if abs(seconds - current) < 1e-3 else "BLANK1")
            op.target, op.value = "duration", str(seconds)


class FREEPLUGIN_MT_overlay_source(bpy.types.Menu):
    bl_idname = "FREEPLUGIN_MT_overlay_source"
    bl_label = "Assets from"

    def draw(self, context):
        current = context.scene.free_plugin.assets_source
        for key, label in SOURCES:
            op = self.layout.operator("freeplugin.overlay_set", text=label,
                                      icon="CHECKMARK" if key == current else "BLANK1")
            op.target, op.value = "assets_source", key
        self.layout.separator()
        self.layout.operator("freeplugin.open_outputs", text="Open my generations folder", icon="FILE_FOLDER")


class FREEPLUGIN_MT_overlay_attach(bpy.types.Menu):
    bl_idname = "FREEPLUGIN_MT_overlay_attach"
    bl_label = "Start from"

    def draw(self, context):
        layout = self.layout
        if state.mode == "scene":
            layout.label(text="Show Claude…")
            for source, label, icon in (("VIEWPORT", "Viewport capture", "RESTRICT_VIEW_OFF"),
                                        ("CAMERA", "Camera view", "CAMERA_DATA"),
                                        ("RENDER", "Render scene", "RENDER_STILL")):
                layout.operator("freeplugin.overlay_chat_attach", text=label, icon=icon).source = source
            layout.operator("freeplugin.overlay_browse", text="Image file…", icon="FILE_IMAGE")
            return
        op = layout.operator("freeplugin.overlay_set", text="Text only", icon="FONT_DATA")
        op.target, op.value = "source", "NONE"
        op = layout.operator("freeplugin.overlay_set", text="Camera view", icon="CAMERA_DATA")
        op.target, op.value = "source", "CAMERA"
        op = layout.operator("freeplugin.overlay_set", text="Render scene", icon="RENDER_STILL")
        op.target, op.value = "source", "RENDER"
        if state.mode != "video":
            layout.operator("freeplugin.overlay_browse", text="Image file…", icon="FILE_IMAGE")


# --------------------------------------------------------------------------- mounting

_draw_handle = None


def _start_modals():
    if not prefs.get().overlay_enabled:
        return None
    state.session += 1
    wm = bpy.context.window_manager
    for window in wm.windows:
        area = next((a for a in window.screen.areas if a.type == "VIEW_3D"), None) or window.screen.areas[0]
        try:
            with bpy.context.temp_override(window=window, area=area):
                bpy.ops.freeplugin.overlay("INVOKE_DEFAULT")
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    return None


def _animate():
    """Keep the caret blinking and the spinners turning while it matters."""
    if _draw_handle is None:
        return None
    if state.expanded and (state.focused or chat.state.busy or any(t.state == "running" for t in tasks.TASKS)):
        _redraw()
        return 0.25
    if not state.expanded and chat.state.busy:
        _redraw()
        return 0.25
    return 0.5


def mount():
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_callback, (), "WINDOW", "POST_PIXEL")
    state.errors = 0
    bpy.app.timers.register(_start_modals, first_interval=0.3)
    if not bpy.app.timers.is_registered(_animate):
        bpy.app.timers.register(_animate, first_interval=0.5, persistent=True)
    _redraw_safe()


def unmount():
    global _draw_handle
    state.session += 1  # running modals end on their next event
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, "WINDOW")
        _draw_handle = None
    if bpy.app.timers.is_registered(_animate):
        bpy.app.timers.unregister(_animate)
    state.rects.clear()
    _redraw_safe()


def _redraw_safe():
    try:
        _redraw()
    except Exception:  # noqa: BLE001 - restricted context during registration
        pass


@bpy.app.handlers.persistent
def _on_load(_dummy):
    # Loading a file drops modal handlers; the draw handler survives.
    if _draw_handle is not None:
        bpy.app.timers.register(_start_modals, first_interval=0.3)


classes = (
    FREEPLUGIN_OT_overlay,
    FREEPLUGIN_OT_overlay_set,
    FREEPLUGIN_OT_overlay_pick_file,
    FREEPLUGIN_OT_overlay_browse,
    FREEPLUGIN_OT_overlay_chat_attach,
    FREEPLUGIN_MT_overlay_model,
    FREEPLUGIN_MT_overlay_effort,
    FREEPLUGIN_MT_overlay_duration,
    FREEPLUGIN_MT_overlay_source,
    FREEPLUGIN_MT_overlay_attach,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    if not bpy.app.background:
        bpy.app.timers.register(lambda: (mount() if prefs.get().overlay_enabled else None), first_interval=0.5)


def unregister():
    unmount()
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
