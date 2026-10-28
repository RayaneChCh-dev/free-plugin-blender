"""@mentions: × hides the object until it is deselected; selecting it again brings the chip back."""

import os
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from sim import check, click, module, rect, run  # noqa: E402

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fakeclaude"
os.environ["FAKE_CLAUDE_STATE"] = tempfile.mkdtemp(prefix="fakeclaude-")
REPORT = sys.argv[-2]

prefs = bpy.context.preferences.addons[module().__name__].preferences
prefs.claude_path = str(FAKE / "claude")
bar = module(".overlay")


def ids():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return [r[0] for r in bar.state.rects.get(region.as_pointer(), [])]


def select(name, value=True):
    obj = bpy.data.objects[name]
    obj.select_set(value)
    if value:
        bpy.context.view_layer.objects.active = obj


run([
    lambda: select("Cube"),
    lambda: click(rect("pill")),
    lambda: check("selected object shown as a mention", "mention:Cube" in ids(), ids()),
    lambda: click(rect("mention:Cube")),
    lambda: None,
    lambda: check("× hides it", "mention:Cube" not in ids(), ids()),
    lambda: select("Cube", False),
    lambda: None,
    lambda: select("Cube"),
    lambda: None,
    lambda: check("selected again: the mention is back", "mention:Cube" in ids(), ids()),
], REPORT)
