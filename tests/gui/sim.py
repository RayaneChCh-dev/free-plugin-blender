"""Drive Blender's real event loop (`blender --enable-event-simulate`) for UI tests.

Events go through Window.event_simulate, so menus, modal operators and the file
browser behave as with a real mouse and keyboard. Needs a display.

Keep each step to a handful of events: a burst of ~20 simulated events in one
tick can stall Blender's event loop (in C, nothing to do with the add-on). Use
one step per key for repeated keys.
"""

import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

import addon_utils
import bpy

MODULE = "bl_ext.user_default.free_plugin_blender"
addon_utils.enable(MODULE, default_set=True)
# Generated files go to a throwaway folder, never the user's ~/Kiln.
bpy.context.preferences.addons[MODULE].preferences.output_dir = tempfile.mkdtemp(prefix="kiln-out-")
RESULTS, ERRORS = [], []


def module(name=""):
    return sys.modules[MODULE + name]


def view():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    return window, area, next(r for r in area.regions if r.type == "WINDOW")


def rect(hit_id):
    """Window coordinates of the centre of a bar element, from the last draw."""
    _window, _area, region = view()
    for rid, x, y, width, height in module(".overlay").state.rects.get(region.as_pointer(), []):
        if rid == hit_id:
            return region.x + x + width / 2, region.y + y + height / 2
    raise LookupError(f"{hit_id} is not on screen")


def click(position, window=None):
    window = window or bpy.context.window_manager.windows[0]
    x, y = map(int, position)
    window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    window.event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
    window.event_simulate(type="LEFTMOUSE", value="RELEASE", x=x, y=y)


def key(name, unicode=None, window=None):
    window = window or bpy.context.window_manager.windows[0]
    x, y = window.width // 2, window.height // 2
    press = dict(type=name, value="PRESS", x=x, y=y)
    if unicode:
        press["unicode"] = unicode
    window.event_simulate(**press)
    window.event_simulate(type=name, value="RELEASE", x=x, y=y)


def type_text(text):
    for char in text:
        key("SPACE" if char == " " else char.upper() if char.isalpha() else "ZERO", unicode=char)


def check(name, condition, detail=""):
    RESULTS.append(("PASS" if condition else "FAIL", name, "" if condition else str(detail)[:160]))
    print(RESULTS[-1][0], name, flush=True)


def until(condition, limit=8.0):
    """A step that waits (re-runs) until condition() is true or the limit passes."""
    box = {}

    def step():
        box.setdefault("start", time.time())
        return None if condition() or time.time() - box["start"] > limit else 0.2
    return step


def run(steps, report):
    """Run the steps on a timer (one per tick, a step returning a number waits that long)."""
    steps = list(steps)

    def tick():
        if not steps:
            for error in ERRORS:
                RESULTS.append(("FAIL", "exception", error))
            Path(report).write_text(json.dumps(RESULTS, indent=1))
            bpy.ops.wm.quit_blender()
            return None
        try:
            wait = steps[0]()
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            ERRORS.append(repr(error))
            wait = None
        if wait is None:
            steps.pop(0)
        return 0.6 if wait is None else wait

    bpy.app.timers.register(tick, first_interval=3.0)
