"""Chat and Claude account against tests/fixtures/fakeclaude (no real Claude, no network)."""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402

FAKE = harness.FIXTURES / "fakeclaude"
STATE = Path(tempfile.mkdtemp(prefix="fakeclaude-"))
os.environ["FAKE_CLAUDE_STATE"] = str(STATE)


def wait_chat(chat, limit=20):
    end = time.time() + limit
    while chat.state.busy and time.time() < end:
        time.sleep(0.05)
    chat._tick()


def wait_account(account, condition, limit=15):
    end = time.time() + limit
    while not condition() and time.time() < end:
        time.sleep(0.05)


def last_call():
    return json.loads((STATE / "last_call.json").read_text())


def test():
    harness.enable()
    chat, account = harness.module(".chat"), harness.module(".account")
    prefs = bpy.context.preferences.addons[harness.MODULE].preferences
    harness.check("defaults: Opus 5.5, medium effort", prefs.chat_model == "claude-opus-5-5"
                  and prefs.chat_effort == "medium", (prefs.chat_model, prefs.chat_effort))
    prefs.claude_path, prefs.chat_model, prefs.mcp_port = str(FAKE / "claude"), "claude-haiku-5-5", 9877
    prefs.mcp_mode = "EXTERNAL"  # the checks below are about the mcp-for-blender command line
    scene = bpy.context.scene

    # Account: signed out → sign-in with a code → signed in.
    account.refresh(force=True)
    wait_account(account.account, lambda: account.account.logged_in is not None)
    harness.check("signed-out status", account.account.logged_in is False, account.label())
    harness.check("send refused while signed out", "Connect your Claude" in (chat.send("hi", scene) or ""))
    harness.check("login starts", account.login() is None)
    wait_account(account.account, lambda: bool(account.account.login_url))
    harness.check("sign-in URL captured", "claude.ai/oauth" in account.account.login_url, account.account.login_url)
    account.send_code("GOOD")
    wait_account(account.account, lambda: account.account.logged_in is True and not account.account.login_running)
    harness.check("signed in after the code", account.account.logged_in and account.account.plan == "Max",
                  account.label())

    # A turn: what is sent, what is shown, what is saved.
    harness.check("send starts", chat.send("ajoute un cube", scene, "[Blender selection: Cube]") is None)
    wait_chat(chat)
    roles = [m["role"] for m in chat.state.messages]
    harness.check("conversation shown", roles == ["user", "assistant", "tool", "tool", "assistant", "info"], roles)
    harness.check("tool summary skips imports", chat.state.messages[2]["text"].endswith("primitive_cube_add()"))
    call = last_call()
    argv = call["argv"]
    harness.check("selection note sent, not shown", "[Blender selection: Cube]" in call["stdin"]
                  and "Blender selection" not in chat.state.messages[0]["text"])
    harness.check("built-in tools off", argv[argv.index("--tools") + 1] == "")
    harness.check("only the Blender MCP allowed", argv[argv.index("--allowedTools") + 1] == "mcp__blender"
                  and "--strict-mcp-config" in argv)
    harness.check("exact model id passed", argv[argv.index("--model") + 1] == "claude-haiku-5-5")
    harness.check("effort passed (default medium)", argv[argv.index("--effort") + 1] == "medium")
    mcp = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]["blender"]
    harness.check("MCP port passed to the server", mcp["env"]["BLENDER_PORT"] == "9877")
    prompt = argv[argv.index("--append-system-prompt") + 1]
    harness.check("system prompt has the catalog and instance id",
                  "trellis ($0.02)" in prompt and chat.INSTANCE in prompt)
    harness.check("instance id published", bpy.context.window_manager.get("free_plugin_instance") == chat.INSTANCE)
    harness.check("saved in the scene", len(json.loads(scene["free_plugin_chat"])["messages"]) == 6)
    harness.check("token usage shown", chat.state.usage == "Last answer: 9.3k tokens in (9.0k cached) · 450 out",
                  chat.state.usage)

    prefs.chat_model, prefs.chat_effort = "DEFAULT", "xhigh"
    chat.send("encore", scene)
    wait_chat(chat)
    argv = last_call()["argv"]
    harness.check("next turn resumes the session", argv[argv.index("--resume") + 1] == chat.state.session_id)
    harness.check("Claude Code default: no --model", "--model" not in argv)
    harness.check("effort change applies", argv[argv.index("--effort") + 1] == "xhigh")

    # Stop a running turn; a second message is refused meanwhile.
    chat.send("slow please", scene)
    time.sleep(0.5)
    harness.check("busy while answering", chat.state.busy)
    harness.check("second message refused", chat.send("x", scene) == "Claude is still answering")
    chat.stop()
    wait_chat(chat)
    harness.check("stopped", not chat.state.busy and chat.state.messages[-1]["text"] == "Stopped.")

    name = chat.write_transcript()
    harness.check("transcript written", "Claude: C'est fait." in bpy.data.texts[name].as_string())
    chat.reset()
    chat._tick()
    harness.check("reset clears", chat.state.messages == [] and json.loads(scene["free_plugin_chat"])["messages"] == [])

    harness.check("logout", account.logout() is None)
    wait_account(account.account, lambda: account.account.logged_in is False)
    harness.check("signed out", account.account.logged_in is False)


harness.run(test)
