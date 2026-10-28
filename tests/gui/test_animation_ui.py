"""Animation mode of the viewport bar and the sidebar's Animation tab, with real clicks."""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(1, str(Path(__file__).resolve().parents[1] / "blender"))
import rigs  # noqa: E402
from sim import check, click, key, module, rect, run, type_text, view  # noqa: E402

REPORT = sys.argv[-2]
bar, panels, tasks = module(".overlay"), module(".panels"), module(".tasks")
prefs = bpy.context.preferences.addons[module().__name__].preferences
prefs.fal_key = ""
drawn = []


def props():
    return bpy.context.scene.free_plugin


def chip():
    return bar._info(bpy.context, bar.state.mode)[0]


def attachment():
    return bar._attachment(bpy.context, "animation")


def watch_sidebar():
    original = panels._draw_animation

    def draw(layout, context):
        original(layout, context)
        drawn.append(context.active_object.name if context.active_object else None)
    panels._draw_animation = draw
    props().sidebar_tab = "ANIM"
    _window, area, _region = view()
    area.spaces.active.show_region_ui = True
    area.tag_redraw()


def make_rig():
    window, area, region = view()
    with bpy.context.temp_override(window=window, area=area, region=region):
        rig = rigs.meshy("HeroRig", location=(0, 0, 0))
    bpy.context.view_layer.objects.active = rig
    view()[1].tag_redraw()


run([
    lambda: click(rect("pill")),
    lambda: click(rect("tab:animation")),
    lambda: check("Animation tab", bar.state.mode == "animation", bar.state.mode),
    lambda: check("no rig: mannequin announced", attachment() == "No rig: a mannequin is created", attachment()),
    lambda: check("chip asks for the fal key", chip() == "Add fal.ai key", chip()),
    lambda: check("model chip", bar._model_label(bpy.context, "animation") == "Hunyuan Motion"),
    lambda: click(rect("duration")),
    lambda: key("L"),
    lambda: check("duration menu → Long (8 s)", props().motion_duration == 8.0, props().motion_duration),
    lambda: click(rect("text")),
    lambda: type_text("a jump"),
    lambda: click(rect("generate")),
    lambda: check("no key: notice, nothing started", "fal.ai key" in bar.state.notice[0] and not tasks.TASKS,
                  bar.state.notice),
    lambda: check("text kept", bar.state.field.text == "a jump", bar.state.field.text),
    lambda: setattr(prefs, "fal_key", "not-a-real-key"),
    lambda: None,
    lambda: check("price shown once the key is set", chip() == "Price: ≈ $0.08", chip()),
    lambda: setattr(prefs, "fal_key", ""),
    make_rig,
    lambda: None,
    lambda: check("rig chip names the rig", attachment() == "On: HeroRig", attachment()),
    lambda: check("rig chip drawn, not closable", "attach_clear" in [r[0] for r in bar.state.rects.get(
        view()[2].as_pointer(), [])]),
    lambda: click(rect("attach_clear")),
    lambda: check("clicking the rig chip keeps it", attachment() == "On: HeroRig"),
    lambda: key("ESC"),
    watch_sidebar,
    lambda: None,
    lambda: None,
    lambda: check("sidebar Animation tab draws", "HeroRig" in drawn, drawn[-3:]),
    lambda: check("preset list filled", len(props().anim_results) > 600, len(props().anim_results)),
], REPORT)
