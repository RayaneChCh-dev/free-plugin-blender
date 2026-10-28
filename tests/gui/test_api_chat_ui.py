"""Scene builder with an API key: provider chips, live model menu, sidebar, with real clicks. Fake API."""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from sim import check, click, key, module, rect, run, until, view  # noqa: E402

REPORT = sys.argv[-2]
bar, panels, oc = module(".overlay"), module(".panels"), module(".providers.openai_compat")
api_models = module(".api_models")
prefs = bpy.context.preferences.addons[module().__name__].preferences
drawn = []


def fake_openai(method, url, headers=None, body=None, timeout=60):
    return {"data": [{"id": "gpt-5.1"}, {"id": "gpt-5"}, {"id": "gpt-5-mini"}]}


oc.request_json = fake_openai


def ids():
    return [r[0] for r in bar.state.rects.get(view()[2].as_pointer(), [])]


def chip():
    return bar._info(bpy.context, "scene")[0]


def watch_sidebar():
    original = panels._draw_chat

    def draw(layout, context):
        original(layout, context)
        drawn.append(prefs.chat_provider)
    panels._draw_chat = draw
    bpy.context.scene.free_plugin.sidebar_tab = "SCENE"
    view()[1].spaces.active.show_region_ui = True
    view()[1].tag_redraw()


run([
    lambda: setattr(prefs, "chat_provider", "OPENAI"),
    lambda: click(rect("pill")),
    lambda: check("chip asks for the OpenAI key", chip() == "Add OpenAI key", chip()),
    lambda: setattr(prefs, "openai_key", "sk-fake"),
    until(lambda: bool(api_models.models())),
    lambda: check("model list loaded", api_models.models()[:2] == ["gpt-5.1", "gpt-5"], api_models.models()),
    lambda: check("chip shows the provider", chip() == "OpenAI API", chip()),
    lambda: check("model chip shows the newest", bar._model_label(bpy.context, "scene") == "gpt-5.1"),
    lambda: click(rect("model")),
    lambda: key("DOWN_ARROW"),
    lambda: key("DOWN_ARROW"),
    lambda: key("RET"),
    lambda: check("model picked in the menu", prefs.openai_model in ("gpt-5", "gpt-5-mini"), prefs.openai_model),
    lambda: check("effort chip still there", "effort" in ids()),
    lambda: key("ESC"),
    watch_sidebar,
    lambda: None,
    lambda: None,
    lambda: check("sidebar chat draws with OpenAI", "OPENAI" in drawn, drawn[-3:]),
    lambda: setattr(prefs, "chat_provider", "CLAUDE"),
], REPORT)
