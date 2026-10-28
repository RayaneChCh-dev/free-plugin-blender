"""Scene tab "+": capture the viewport (without the bar), the chip shows, the image goes to Claude (fake)."""

import json
import os
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from sim import check, click, key, module, rect, run, type_text, until  # noqa: E402

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fakeclaude"
STATE = Path(tempfile.mkdtemp(prefix="fakeclaude-"))
(STATE / "signed_in").write_text("1")
os.environ["FAKE_CLAUDE_STATE"] = str(STATE)
REPORT = sys.argv[-2]

prefs = bpy.context.preferences.addons[module().__name__].preferences
prefs.claude_path, prefs.mcp_mode, prefs.mcp_port = str(FAKE / "claude"), "EXTERNAL", 9877
account, chat, bar = module(".account"), module(".chat"), module(".overlay")


def ids():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return [r[0] for r in bar.state.rects.get(region.as_pointer(), [])]


def capture():
    bpy.ops.freeplugin.overlay_chat_attach(source="VIEWPORT")
    check("bar hidden while capturing", bar.state.hidden)


def last_call():
    return json.loads((STATE / "last_call.json").read_text())


run([
    lambda: account.refresh(force=True),
    until(lambda: account.account.logged_in is True),
    lambda: click(rect("pill")),
    lambda: check("Scene tab has a + button", "attach" in ids(), ids()),
    capture,
    until(lambda: bool(bar.state.chat_images)),
    lambda: None,
    lambda: check("bar back after the capture", not bar.state.hidden and "card" in ids()),
    lambda: check("capture saved, chip shown", os.path.isfile(bar.state.chat_images[0][1])
                  and "chat_image:0" in ids(), (bar.state.chat_images, ids())),
    lambda: click(rect("text")),
    lambda: type_text("what do you see"),
    lambda: key("RET"),
    until(lambda: not chat.state.busy and (STATE / "last_call.json").exists()),
    lambda: check("sent as JSON with the image", "--input-format" in last_call()["argv"]
                  and [b["type"] for b in json.loads(last_call()["stdin"])["message"]["content"]]
                  == ["text", "image"]),
    lambda: check("chip cleared after sending", bar.state.chat_images == [] and "chat_image:0" not in ids()),
], REPORT)
