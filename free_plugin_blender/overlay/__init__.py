"""The prompt bar in the 3D viewport.

At rest it is a pill at the bottom of every 3D view. Clicking it opens a card:
mode tabs above it (Scene builder, 3D, Image, Material, Video, Animation, Assets), a header
(new chat, title, price or account status), the conversation or search results,
the selected objects as @mentions, the text field, a model menu and the
Generate button.

It is drawn with gpu/blf from a POST_PIXEL draw handler. A single modal
operator per window routes events: clicks on the bar and typing while it has
focus are consumed, everything else passes through to Blender. Hit rectangles
are published per region by the draw pass and read by the modal.
"""

from __future__ import annotations

import os
import time
import traceback

import bpy

from .. import (
    account,
    animation,
    api_models,
    catalog,
    chat,
    claude_models,
    mcpserver,
    prefs,
    presets,
    tasks,
    ui_controls,
)
from . import gfx
from .field import Field, wrap

MODES = (
    ("scene", "Scene builder"),
    ("mesh", "3D Model"),
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
        self.notice = ("", 0.0)
        self.session = 0
        self.errors = 0
        self.max_scroll = 0.0


state = _State()


def _notify(text):
    state.notice = (text, time.time())


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
    return [o.name for o in objects if o.name not in state.excluded][:4]


def _model_label(context, mode):
    props = context.scene.free_plugin
    if mode == "scene":
        if prefs.get().chat_provider != "CLAUDE":
            return api_models.current() or "Choose a model"
        return claude_models.model_label(prefs.get().chat_model)
    if mode == "assets":
        return dict(ASSET_KINDS)[props.ph_kind]
    if mode == "animation":
        return "Hunyuan Motion"
    entry = getattr(props, f"{SLOT_OF_MODE[mode]}_model").entry()
    return entry["label"] if entry else "Choose a model"


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
        return "Poly Haven · free", gfx.TEXT_DIM, None
    if _needs_fal(context, mode) and not prefs.fal_key():
        return "Add fal.ai key", gfx.DANGER, "prefs"
    if mode == "animation":
        return f"Price: {presets.MOTION_COST}", gfx.TEXT_DIM, None
    entry = getattr(context.scene.free_plugin, f"{SLOT_OF_MODE[mode]}_model").entry() or {}
    cost = entry.get("cost")
    return (f"Price: {cost}" if cost else "Price: see fal.ai"), gfx.TEXT_DIM, None


def _attachment(context, mode):
    props = context.scene.free_plugin
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


def _title(mode):
    notice, at = state.notice
    if notice and time.time() - at < 6:
        return notice, gfx.TEXT
    status = _status()
    if status:
        return status, gfx.TEXT_DIM
    if mode == "scene":
        first = next((m["text"] for m in chat.state.messages if m["role"] == "user"), "")
        return (first.splitlines()[0] if first else "New chat"), gfx.TEXT
    return dict(MODES)[mode], gfx.TEXT


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
    if region is None or region.width < 320 * s or region.height < 200 * s:
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


def _draw_pill(context, region, s, rects):
    width, height = min(380 * s, region.width - 40 * s), 40 * s
    x, y = (region.width - width) / 2, 22 * s
    hovered = state.hover in ("pill", "pill_send")
    gfx.bordered(x, y, width, height, height / 2, gfx.BG_HOVER if hovered else gfx.BG)
    size = 13 * s
    text = state.field.text.splitlines()[0] if state.field.text else PLACEHOLDERS[state.mode]
    color = gfx.TEXT if state.field.text else gfx.TEXT_DIM
    gfx.text(x + 18 * s, y + height / 2 - size * 0.36, gfx.ellipsize(text, width - 70 * s, size), size, color)
    radius = 14 * s
    cx, cy = x + width - radius - 6 * s, y + height / 2
    busy = chat.state.busy and state.mode == "scene"
    gfx.circle(cx, cy, radius, gfx.ACCENT_HOVER if state.hover == "pill_send" else gfx.ACCENT)
    if busy:
        gfx.icon_spinner(cx, cy, 14 * s, gfx.ACCENT_TEXT, time.time() % 1.0)
    else:
        gfx.icon_send(cx, cy, 12 * s, gfx.ACCENT_TEXT)
    rects.append(("pill", x, y, width, height))
    rects.append(("pill_send", cx - radius, cy - radius, 2 * radius, 2 * radius))


def _chip(rects, chip_id, x, y, label, size, s, *, closable=False, chevron=False, icon_color=None, fill=None):
    """A small rounded label; returns its width."""
    pad = 8 * s
    text_width = gfx.measure(label, size)
    width = pad + text_width + (16 * s if closable or chevron else 0) + pad
    height = 22 * s
    hovered = state.hover == chip_id
    gfx.rounded(x, y, width, height, 6 * s, fill or (gfx.BG_HOVER if hovered else gfx.BG_RAISED))
    gfx.text(x + pad, y + height / 2 - size * 0.36, label, size, icon_color or gfx.TEXT)
    if closable:
        gfx.icon_close(x + width - pad - 4 * s, y + height / 2, 6 * s, gfx.TEXT_DIM)
    if chevron:
        gfx.icon_chevron(x + width - pad - 4 * s, y + height / 2, 7 * s, gfx.TEXT_DIM)
    rects.append((chip_id, x, y, width, height))
    return width


def _thread_blocks(width, s):
    """Conversation as drawable blocks: (role, lines, height). Oldest first."""
    size, small = 12.5 * s, 11 * s
    blocks = []
    for message in chat.state.messages:
        role, text = message["role"], message["text"]
        if role == "tool":
            gfx.text_size(small)
            line = gfx.ellipsize("⚙ " + text.splitlines()[0], width, small)
            blocks.append((role, [line], 18 * s))
            continue
        limit = width * (0.78 if role == "user" else 1.0) - (20 * s if role == "user" else 0)
        gfx.text_size(size)
        lines = [text[a:b].rstrip() for a, b in wrap(text, limit, lambda t: gfx.measure(t))]
        line_height = 17 * s
        extra = 14 * s if role == "user" else 6 * s
        blocks.append((role, lines, len(lines) * line_height + extra))
    return blocks


def _draw_thread(rects, x, y, width, height, s, blocks):
    """Draw the newest messages that fit in (x, y, width, height), honouring the scroll."""
    size, small, line_height = 12.5 * s, 11 * s, 17 * s
    total = sum(h + 6 * s for _, _, h in blocks)
    state.max_scroll = max(0.0, total - height)
    state.scroll = min(state.scroll, state.max_scroll)
    cursor = y - state.scroll  # bottom of the newest block
    for role, lines, block_height in reversed(blocks):
        top = cursor + block_height
        if cursor > y + height:
            break
        if role == "user":
            text_width = max(gfx.measure(line, size) for line in lines) if lines else 0
            bubble_width = text_width + 20 * s
            bx = x + width - bubble_width
            visible_bottom, visible_top = max(cursor, y), min(top, y + height)
            if visible_top > visible_bottom:
                gfx.rounded(bx, visible_bottom, bubble_width, visible_top - visible_bottom, 10 * s, gfx.USER_BUBBLE)
            for index, line in enumerate(lines):
                baseline = top - 7 * s - (index + 1) * line_height + 4 * s
                if y <= baseline <= y + height - size:
                    gfx.text(bx + 10 * s, baseline, line, size, gfx.TEXT)
        elif role == "tool":
            if y <= cursor + 4 * s <= y + height - small:
                gfx.text(x, cursor + 4 * s, lines[0], small, gfx.TEXT_FAINT)
        else:
            color = {"error": gfx.DANGER, "info": gfx.TEXT_DIM}.get(role, gfx.TEXT)
            for index, line in enumerate(lines):
                baseline = top - (index + 1) * line_height + 3 * s
                if y <= baseline <= y + height - size:
                    gfx.text(x, baseline, line, size, color)
        cursor = top + 6 * s
    rects.append(("thread", x, y, width, height))


def _draw_assets(context, rects, x, y, width, height, s):
    props = context.scene.free_plugin
    size, row = 12.5 * s, 26 * s
    results = list(props.ph_results)
    if not results:
        gfx.text(x, y + height / 2 - 4 * s, "Search, then click a result: HDRI → world, "
                 "texture → active mesh, model → 3D cursor.", 11 * s, gfx.TEXT_DIM)
        return
    columns = 2
    column_width = (width - 8 * s) / columns
    for index, item in enumerate(results[: columns * int(height // row)]):
        column, line = index % columns, index // columns
        rx = x + column * (column_width + 8 * s)
        ry = y + height - (line + 1) * row
        item_id = f"asset:{item.asset_id}"
        gfx.rounded(rx, ry + 2 * s, column_width, row - 4 * s, 6 * s,
                    gfx.BG_HOVER if state.hover == item_id else gfx.BG_RAISED)
        gfx.text(rx + 10 * s, ry + row / 2 - size * 0.36, gfx.ellipsize(item.name, column_width - 20 * s, size),
                 size, gfx.TEXT)
        rects.append((item_id, rx, ry + 2 * s, column_width, row - 4 * s))


def props_entry_is_provider(context):
    return bool((context.scene.free_plugin.mesh_model.entry() or {}).get("provider"))


def _draw_card(context, region, s, rects):
    mode = state.mode
    pad, gap = 14 * s, 8 * s
    width = min(700 * s, region.width - 32 * s)
    x, y0 = (region.width - width) / 2, 16 * s
    generate_width = 118 * s
    size, line_height = 13.5 * s, 19 * s

    # Text field geometry.
    text_x = x + pad
    text_width = width - 2 * pad - generate_width - gap
    gfx.text_size(size)
    field = state.field
    lines = wrap(field.text, text_width, lambda t: gfx.measure(t)) if field.text else [(0, 0)]
    shown_lines = max(2, min(6, len(lines)))
    mentions = _mentions(context) if mode == "scene" else []
    attachment = _attachment(context, mode)
    chips_height = 28 * s if (mentions or attachment) else 0
    bottom_row = 30 * s
    input_height = chips_height + shown_lines * line_height + gap + bottom_row
    header_height = 38 * s
    middle_height, blocks = 0, None
    if mode == "assets":
        count = len(context.scene.free_plugin.ph_results)
        middle_height = min(-(-count // 2) * 26 * s, 182 * s) if count else 30 * s
    elif mode == "scene" and state.show_thread and chat.state.messages:
        blocks = _thread_blocks(width - 2 * pad, s)
        content = sum(h + 6 * s for _, _, h in blocks)
        middle_height = min(content, 260 * s, region.height * 0.45)
    card_height = pad + input_height + (middle_height + gap if middle_height else 0) + header_height

    gfx.bordered(x, y0, width, card_height, 14 * s, gfx.BG)
    rects.append(("card", x, y0, width, card_height))

    # Tabs above the card.
    tab_size = 12 * s
    modes = _modes()
    tab_widths = [gfx.measure(label, tab_size) + 22 * s for _, label in modes]
    tabs_width = sum(tab_widths) + 8 * s
    tx, ty, tab_height = x + (width - tabs_width) / 2, y0 + card_height + 8 * s, 30 * s
    gfx.bordered(tx, ty, tabs_width, tab_height, tab_height / 2, gfx.BG)
    cursor = tx + 4 * s
    for (key, label), tab_width in zip(modes, tab_widths):
        tab_id = f"tab:{key}"
        if key == mode or state.hover == tab_id:
            gfx.rounded(cursor, ty + 4 * s, tab_width, tab_height - 8 * s, (tab_height - 8 * s) / 2,
                        gfx.BG_RAISED if key == mode else gfx.BG_HOVER)
        gfx.text_centered(cursor + tab_width / 2, ty + tab_height / 2, label, tab_size,
                          gfx.TEXT if key == mode else gfx.TEXT_DIM)
        rects.append((tab_id, cursor, ty + 4 * s, tab_width, tab_height - 8 * s))
        cursor += tab_width

    # Header: new chat, title, info chip.
    hy = y0 + card_height - header_height
    icon_box = 26 * s
    ix = x + pad - 4 * s
    for icon_id, painter in (("new", gfx.icon_plus),):
        if mode != "scene":
            break
        bx, by = ix, hy + (header_height - icon_box) / 2
        gfx.rounded(bx, by, icon_box, icon_box, 7 * s,
                    gfx.BG_HOVER if state.hover == icon_id else gfx.BG_RAISED)
        painter(bx + icon_box / 2, by + icon_box / 2, 11 * s, gfx.TEXT_DIM)
        rects.append((icon_id, bx, by, icon_box, icon_box))
        ix += icon_box + 6 * s
    info_text, info_color, _action = _info(context, mode)
    info_size = 11.5 * s
    info_width = gfx.measure(info_text, info_size) + 18 * s
    info_x = x + width - pad - info_width
    gfx.rounded(info_x, hy + (header_height - 24 * s) / 2, info_width, 24 * s, 7 * s, gfx.BG_RAISED)
    gfx.text(info_x + 9 * s, hy + header_height / 2 - info_size * 0.36, info_text, info_size, info_color)
    rects.append(("info", info_x, hy + (header_height - 24 * s) / 2, info_width, 24 * s))
    title, title_color = _title(mode)
    title_space = info_x - ix - 2 * gap
    title = gfx.ellipsize(title, title_space, 12.5 * s)
    gfx.text_centered(ix + gap + title_space / 2, hy + header_height / 2, title, 12.5 * s, title_color)

    # Middle: conversation or asset results.
    if middle_height:
        my = y0 + pad + input_height + gap
        if mode == "assets":
            _draw_assets(context, rects, x + pad, my, width - 2 * pad, middle_height, s)
        else:
            _draw_thread(rects, x + pad, my, width - 2 * pad, middle_height, s, blocks)

    # Input: chips, text, bottom row.
    top = y0 + pad + input_height
    chip_y = top - 24 * s
    cx = text_x
    chip_size = 11.5 * s
    if attachment:
        warning = attachment == "Select a mesh first"
        cx += _chip(rects, "attach_clear", cx, chip_y, ("⚠ " if warning else "◧ ") + attachment, chip_size, s,
                    closable=mode not in ("material", "animation"), icon_color=gfx.DANGER if warning else None) + 6 * s
    for name in mentions:
        cx += _chip(rects, f"mention:{name}", cx, chip_y, "@" + name, chip_size, s, closable=True,
                    icon_color=gfx.ACCENT_HOVER) + 6 * s
    text_top = top - chips_height
    first_line = max(0, len(lines) - shown_lines)
    caret_line = next((i for i, (a, b) in enumerate(lines) if a <= field.caret <= b), len(lines) - 1)
    if caret_line < first_line:
        first_line = caret_line
    if not field.text:
        gfx.text(text_x, text_top - line_height + 4 * s, PLACEHOLDERS[mode], size, gfx.TEXT_FAINT)
    for row, (a, b) in enumerate(lines[first_line:first_line + shown_lines]):
        baseline = text_top - (row + 1) * line_height + 4 * s
        gfx.text(text_x, baseline, field.text[a:b], size, gfx.TEXT)
    if state.focused and int(time.time() * 2) % 2 == 0:
        a, _b = lines[caret_line]
        row = caret_line - first_line
        caret_x = text_x + gfx.measure(field.text[a:field.caret], size)
        baseline = text_top - (row + 1) * line_height + 4 * s
        gfx.line(caret_x + 1, baseline - 3 * s, caret_x + 1, baseline + size * 0.95, 1.5 * s, gfx.ACCENT_HOVER)
    rects.append(("text", text_x, text_top - shown_lines * line_height, text_width, shown_lines * line_height))

    by = y0 + pad
    bx = text_x
    if mode in ("image", "mesh", "video"):
        box = 26 * s
        gfx.rounded(bx, by + 2 * s, box, box, 7 * s, gfx.BG_HOVER if state.hover == "attach" else gfx.BG_RAISED)
        gfx.icon_plus(bx + box / 2, by + 2 * s + box / 2, 11 * s, gfx.TEXT_DIM)
        rects.append(("attach", bx, by + 2 * s, box, box))
        bx += box + 6 * s
    bx += _chip(rects, "model", bx, by + 4 * s, _model_label(context, mode), 12 * s, s, chevron=True) + 6 * s
    if mode == "scene":
        effort = "Effort: " + claude_models.effort_label(prefs.get().chat_effort)
        _chip(rects, "effort", bx, by + 4 * s, effort, 12 * s, s, chevron=True)
    elif mode == "animation":
        _chip(rects, "duration", bx, by + 4 * s, _duration_label(context), 12 * s, s, chevron=True)
    elif mode in ui_controls.BAR_CONTROLS and not (mode == "mesh" and props_entry_is_provider(context)):
        slot = SLOT_OF_MODE[mode]
        room = text_x + text_width
        for key in ui_controls.BAR_CONTROLS[mode]:
            control, supported, _value, label = ui_controls.control_state(context.scene, slot, key)
            if not supported:
                continue
            text = label or control.label
            chip_width = gfx.measure(text, 12 * s) + 32 * s
            if bx + chip_width > room:
                break
            bx += _chip(rects, f"control:{slot}:{key}", bx, by + 4 * s, text, 12 * s, s, chevron=True,
                        icon_color=gfx.TEXT if label else gfx.TEXT_DIM) + 6 * s

    # Generate / Send / Stop.
    gx = x + width - pad - generate_width
    gy, gh = y0 + pad, input_height
    busy = mode == "scene" and chat.state.busy
    empty = not field.text.strip()
    if busy:
        fill = gfx.BG_HOVER if state.hover == "generate" else gfx.BG_RAISED
    elif empty:
        fill = gfx.BG_RAISED
    else:
        fill = gfx.ACCENT_HOVER if state.hover == "generate" else gfx.ACCENT
    gfx.rounded(gx, gy, generate_width, gh, 10 * s, fill)
    label = {"scene": "SEND", "assets": "SEARCH"}.get(mode, "GENERATE")
    if busy:
        gfx.icon_spinner(gx + generate_width / 2, gy + gh / 2 + 10 * s, 16 * s, gfx.ACCENT, time.time() % 1.0)
        gfx.text_centered(gx + generate_width / 2, gy + gh / 2 - 14 * s, "STOP", 11.5 * s, gfx.TEXT)
    else:
        gfx.text_centered(gx + generate_width / 2, gy + gh / 2, label, 12 * s,
                          gfx.TEXT_FAINT if empty else gfx.ACCENT_TEXT)
    rects.append(("generate", gx, gy, generate_width, gh))


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
        error = chat.send(text, context.scene, note)
        if error:
            _notify(error)
            return
        state.field.set("")
        state.show_thread, state.scroll = True, 0.0
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
        state.field.set("")
        state.scroll = 0.0
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
    elif hit.startswith("mention:"):
        state.excluded.add(hit[8:])
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
            prefs.get().openai_model = self.value
        elif self.target == "duration":
            props.motion_duration = float(self.value)
        elif self.target == "kind":
            props.ph_kind = self.value
            props.ph_results.clear()
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
        if state.mode == "image":
            props.image_reference_path = self.filepath
        else:
            props.mesh_image_path = self.filepath
        _set_source(props, state.mode, "FILE")
        _redraw()
        return {"FINISHED"}


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


class FREEPLUGIN_MT_overlay_attach(bpy.types.Menu):
    bl_idname = "FREEPLUGIN_MT_overlay_attach"
    bl_label = "Start from"

    def draw(self, context):
        layout = self.layout
        op = layout.operator("freeplugin.overlay_set", text="Text only", icon="FONT_DATA")
        op.target, op.value = "source", "NONE"
        op = layout.operator("freeplugin.overlay_set", text="Camera view", icon="CAMERA_DATA")
        op.target, op.value = "source", "CAMERA"
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
    FREEPLUGIN_MT_overlay_model,
    FREEPLUGIN_MT_overlay_effort,
    FREEPLUGIN_MT_overlay_duration,
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
