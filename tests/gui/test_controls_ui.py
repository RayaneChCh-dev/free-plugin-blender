"""Setting chips in the viewport bar: shown per model, menu opens, choice applies."""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from sim import check, click, key, module, rect, run  # noqa: E402

REPORT = sys.argv[-2]
bar = module(".overlay")


def props():
    return bpy.context.scene.free_plugin


def chips():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return [r[0] for r in bar.state.rects.get(region.as_pointer(), []) if r[0].startswith("control:")]


def layout_ok():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    boxes = {r[0]: r[1:] for r in bar.state.rects.get(region.as_pointer(), [])}
    text_x, _ty, text_w, _th = boxes["text"]
    card_x, _cy, card_w, _ch = boxes["card"]
    generate_x, generate_y, _gw, _gh = boxes["generate"]
    chip_ends = [x + w for rid, (x, _y, w, _h) in boxes.items() if rid.startswith("control:") or rid == "model"]
    # The button closes the bottom row: chips stop before it, the text stays inside the card.
    return (all(end <= generate_x for end in chip_ends) and text_x + text_w <= card_x + card_w
            and generate_y < boxes["text"][1])


def set_model(slot, key_):
    getattr(props(), f"{slot}_model").model = key_


run([
    lambda: set_model("image", "nano_banana_pro"),
    lambda: click(rect("pill")),
    lambda: click(rect("tab:image")),
    lambda: check("Nano Banana Pro: ratio, resolution, format chips (no quality)",
                  chips() == ["control:image:aspect", "control:image:resolution", "control:image:format"], chips()),
    lambda: check("chips stop before Generate, text inside the card", layout_ok()),
    lambda: click(rect("control:image:aspect")),
    lambda: key("DOWN_ARROW"),
    lambda: key("DOWN_ARROW"),
    lambda: key("DOWN_ARROW"),
    lambda: key("RET"),
    lambda: check("ratio chosen from the menu", props().choices.image_aspect not in ("", "auto"),
                  props().choices.image_aspect),
    lambda: set_model("image", "flux2"),
    lambda: None,
    lambda: check("FLUX.2: quality appears, resolution goes", "control:image:quality" in chips()
                  and "control:image:resolution" not in chips(), chips()),
    lambda: click(rect("tab:mesh")),
    lambda: set_model("mesh", "meshy7"),
    lambda: None,
    lambda: check("layout still right with four 3D chips", layout_ok()),
    lambda: check("Meshy 7: mode, type, topology, detail chips", chips() == [
        "control:mesh:mode", "control:mesh:model_type", "control:mesh:topology", "control:mesh:detail"], chips()),
    lambda: set_model("mesh", "trellis"),
    lambda: None,
    lambda: check("TRELLIS: only what it takes", "control:mesh:model_type" not in chips(), chips()),
], REPORT)
