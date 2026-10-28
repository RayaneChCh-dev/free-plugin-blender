"""Viewport prompt bar and Claude sign-in with real (simulated) clicks and keys."""

import os
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from sim import check, click, key, module, rect, run, type_text, until  # noqa: E402

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fakeclaude"
os.environ["FAKE_CLAUDE_STATE"] = tempfile.mkdtemp(prefix="fakeclaude-")
REPORT, IMAGE = sys.argv[-2], sys.argv[-1]

prefs = bpy.context.preferences.addons[module().__name__].preferences
prefs.claude_path, prefs.fal_key = str(FAKE / "claude"), ""
account, chat, bar = module(".account"), module(".chat"), module(".overlay")


def props():
    return bpy.context.scene.free_plugin


def chip():
    return bar._info(bpy.context, bar.state.mode)[0]


def pick_file():
    window, area = next((w, a) for w in bpy.context.window_manager.windows for a in w.screen.areas
                        if a.type == "FILE_BROWSER")
    params = area.spaces.active.params
    params.directory, params.filename = str(Path(IMAGE).parent).encode(), Path(IMAGE).name
    key("RET", window=window)


def send_code():
    props().auth_code = "GOOD"
    bpy.ops.freeplugin.claude_send_code()


run([
    lambda: account.refresh(force=True),
    until(lambda: account.account.logged_in is not None),
    lambda: click(rect("pill")),
    lambda: check("pill opens the card", bar.state.expanded and bar.state.focused),
    lambda: check("chip asks to connect", chip() == "Connect Claude", chip()),
    lambda: type_text("bonjour"),
    lambda: key("RET"),
    lambda: check("send refused while signed out", "Connect your Claude" in bar.state.notice[0], bar.state.notice),
    lambda: click(rect("info")),
    until(lambda: bool(account.account.login_url)),
    lambda: check("chip starts the sign-in", "claude.ai/oauth" in account.account.login_url),
    send_code,
    until(lambda: account.account.logged_in is True and not account.account.login_running),
    lambda: check("signed in", account.account.logged_in is True, account.label()),
    lambda: click(rect("text")),
    lambda: key("RET"),
    until(lambda: not chat.state.busy and len(chat.state.messages) > 1),
    lambda: check("Enter sends, answer shown", [m["role"] for m in chat.state.messages][:2] == ["user", "assistant"]),
    lambda: check("field cleared", bar.state.field.text == ""),
    lambda: click(rect("new")),
    lambda: check("new chat clears", chat.state.messages == []),
    lambda: click(rect("model")),
    lambda: key("H"),
    lambda: check("model menu (scene) → Haiku 5.5", prefs.chat_model == "claude-haiku-5-5", prefs.chat_model),
    lambda: check("effort chip shows the default", bar._model_label(bpy.context, "scene") == "Haiku 5.5"),
    lambda: click(rect("effort")),
    lambda: key("H"),
    lambda: check("effort menu → High", prefs.chat_effort == "high", prefs.chat_effort),
    lambda: click(rect("tab:image")),
    lambda: check("Image tab", bar.state.mode == "image"),
    lambda: click(rect("attach")),
    lambda: key("C"),
    lambda: check("+ → Camera view", props().image_reference == "CAMERA", props().image_reference),
    lambda: click(rect("attach_clear")),
    lambda: check("× clears the reference", props().image_reference == "NONE"),
    lambda: click(rect("attach")),
    lambda: key("I"),
    until(lambda: len(bpy.context.window_manager.windows) > 1, 4),
    lambda: check("+ → Image file… opens the browser", len(bpy.context.window_manager.windows) > 1),
    pick_file,
    until(lambda: props().image_reference == "FILE", 4),
    lambda: check("picked file is the reference", props().image_reference_path.endswith(Path(IMAGE).name)),
    lambda: click(rect("model")),
    lambda: key("N"),
    lambda: check("model menu (image) → Nano Banana", props().image_model.model == "nano_banana"),
    lambda: check("chip asks for the fal key", chip() == "Add fal.ai key", chip()),
    lambda: click(rect("text")),
    lambda: type_text("a riad"),
    lambda: click(rect("generate")),
    lambda: check("no key: notice, nothing started",
                  "fal.ai key" in bar.state.notice[0] and not module(".tasks").TASKS, bar.state.notice),
    lambda: click(rect("tab:material")),
    lambda: check("material targets the active mesh", bar._attachment(bpy.context, "material") == "On: Cube"),
    *[lambda: key("BACK_SPACE") for _ in range(10)],
    lambda: check("Backspace erases the field", bar.state.field.text == "", repr(bar.state.field.text)),
    lambda: key("ESC"),
    lambda: check("Esc on an empty field closes", not bar.state.expanded and not bar.state.focused),
], REPORT)
