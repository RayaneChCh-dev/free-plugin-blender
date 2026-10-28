"""Chat with Claude Code from Blender, on the user's own Claude subscription.

Each message runs `claude -p` (Claude Code in headless mode) on a worker thread.
Claude acts on this Blender through a Blender MCP server (default:
`uvx mcp-for-blender`, which talks to the blender_mcp add-on on port 9876) and
can call the `bpy.ops.freeplugin.*` operators from there. Built-in tools are
disabled (`--tools ""`) and only that MCP server is loaded and allowed, so the
chat can drive Blender and nothing else directly.

The conversation (messages + Claude session id) is saved in the .blend file,
on the scene, as `scene["free_plugin_chat"]`.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import threading
import uuid
from pathlib import Path

import bpy

from . import catalog, prefs

MCP_SERVER = "blender"
_MAX_MESSAGES = 200
# Identifies this Blender: the MCP server reaches whichever Blender owns the port,
# so Claude checks this value before touching anything.
INSTANCE = uuid.uuid4().hex[:12]


class _State:
    def __init__(self):
        self.messages: list[dict] = []  # {"role": user|assistant|tool|error|info, "text": str}
        self.session_id = ""
        self.busy = False
        self.status = ""
        self.process: subprocess.Popen | None = None
        self.dirty = False
        self.mcp_listening = False
        self.scene_name = ""


state = _State()


def _add(role, text):
    text = (text or "").strip()
    if not text:
        return
    if role == "assistant" and state.messages and state.messages[-1]["role"] == "assistant":
        state.messages[-1]["text"] += "\n\n" + text
    else:
        state.messages.append({"role": role, "text": text})
    del state.messages[:-_MAX_MESSAGES]
    state.dirty = True


# --------------------------------------------------------------------------- setup

def _search_path() -> str:
    extra = [Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin", Path("/usr/local/bin"),
             Path("/opt/homebrew/bin"), Path.home() / ".claude" / "local"]
    return os.pathsep.join([os.environ.get("PATH", ""), *map(str, extra)])


def subprocess_env() -> dict:
    return {**os.environ, "PATH": _search_path()}


def claude_executable() -> str | None:
    configured = prefs.get().claude_path.strip()
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("claude", path=_search_path())


def _mcp_config() -> str:
    settings = prefs.get()
    command, *args = shlex.split(settings.mcp_command) or ["uvx", "mcp-for-blender"]
    port = str(settings.mcp_port)
    # mcp-for-blender reads BLENDER_PORT, Blender Lab's MCP reads BLENDER_MCP_PORT.
    env = {"BLENDER_PORT": port, "BLENDER_MCP_PORT": port}
    return json.dumps({"mcpServers": {MCP_SERVER: {"command": command, "args": args, "env": env}}})


def _workspace() -> Path:
    path = prefs.user_dir() / "chat"
    path.mkdir(exist_ok=True)
    return path


def system_prompt() -> str:
    def keys(slot):
        return ", ".join(f"{e['key']} ({e.get('cost') or 'see fal.ai'})" for e in catalog.models(slot))

    return f"""You are an assistant inside the user's open Blender session. You act on the scene only
through the `{MCP_SERVER}` MCP tools (run Python with bpy, inspect the scene, take screenshots).

Several Blender windows can be open and the MCP tools reach whichever one owns the MCP port. At the
start of every turn, before changing anything, run
`bpy.context.window_manager.get("free_plugin_instance")` and check it equals "{INSTANCE}". If it
does not, change nothing and tell the user the MCP is connected to another Blender window (close the
other one or give each its own MCP port).

The "Free Plugin Blender" add-on is installed. From Python you can call its operators:
- bpy.ops.freeplugin.generate_image(prompt=..., model=<key or fal id>, options='<json>')
- bpy.ops.freeplugin.generate_texture(prompt=...)  # seamless material on the ACTIVE mesh
- bpy.ops.freeplugin.generate_3d(prompt=..., model=...)  # imported at the 3D cursor
- bpy.ops.freeplugin.generate_video(prompt=..., model=...)  # added to the Video Sequencer
- bpy.ops.freeplugin.rig()  # rigs the ACTIVE humanoid (Meshy on fal.ai, ~$0.20)
- Poly Haven (free, CC0): set bpy.context.scene.free_plugin.ph_kind ("hdris"|"textures"|"models") and
  .ph_query, call bpy.ops.freeplugin.polyhaven_search(), read .ph_results[i].asset_id, then
  bpy.ops.freeplugin.polyhaven_apply(asset_id=..., kind=...) (HDRI → world, texture → active mesh,
  model → imported at the 3D cursor)
- bpy.ops.freeplugin.local_remesh() / local_lods()  # free
These operators return at once and finish in the background. Poll
json.loads(bpy.context.window_manager.get("free_plugin_tasks", "[]")) until the task's "state" is
"done" or "error"; "result" holds the new object names or file path. Wait a few seconds between polls.

Catalog keys with indicative prices:
- image: {keys("image")}
- video: {keys("video")}
- mesh: {keys("mesh")}

Generations are billed to the user's fal.ai account. Prefer free options first (modelling with bpy,
Poly Haven), then the cheapest suitable model (trellis for 3D, seedream45 for images). Say what a
generation will cost before or when you start it. Never start a video, or anything above $0.50, unless
the user explicitly asked for it. Blender units are metres, Z is up.

Answer in the user's language, briefly: say what you did, not how."""


# --------------------------------------------------------------------------- running

def send(text: str, scene, note: str = "") -> str | None:
    """Start a turn. Returns an error message, or None when the turn started.

    `note` is context for Claude (e.g. the selection) that is sent but not shown.
    """
    text = text.strip()
    if not text:
        return "Empty message"
    if state.busy:
        return "Claude is still answering"
    executable = claude_executable()
    if executable is None:
        return "Claude Code is not installed: see Scene tab › Claude account"
    from . import account

    if account.account.logged_in is False:
        return "Connect your Claude subscription first (Scene tab › Claude account)"

    state.scene_name = scene.name
    _add("user", text)
    state.busy, state.status = True, "Claude is thinking…"
    command = [
        executable, "-p", "--output-format", "stream-json", "--verbose",
        "--tools", "", "--strict-mcp-config", "--mcp-config", _mcp_config(),
        "--allowedTools", f"mcp__{MCP_SERVER}", "--permission-mode", "dontAsk",
        "--append-system-prompt", system_prompt(),
    ]
    if state.session_id:
        command += ["--resume", state.session_id]
    model = prefs.get().chat_model
    if model != "DEFAULT":
        command += ["--model", model.lower()]
    prompt = f"{text}\n\n{note}" if note else text
    threading.Thread(target=_run, args=(command, prompt), name="free-plugin:chat", daemon=True).start()
    return None


def _run(command, text):
    env = subprocess_env()
    try:
        process = subprocess.Popen(
            command, cwd=_workspace(), env=env, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as error:
        _add("error", f"Could not start Claude Code: {error}")
        state.busy, state.status = False, ""
        return
    state.process = process
    process.stdin.write(text)
    process.stdin.close()
    stderr_lines: list[str] = []
    threading.Thread(target=lambda: stderr_lines.extend(process.stderr), daemon=True).start()
    got_result = False
    for line in process.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        got_result |= _handle(event)
    process.wait()
    if not got_result and process.returncode not in (0, None):
        if process.returncode < 0:
            _add("info", "Stopped.")
        else:
            _add("error", "Claude Code failed: " + "".join(stderr_lines[-8:]).strip()[-600:])
    state.process, state.busy, state.status = None, False, ""
    state.dirty = True


def _summarize_tool(name, payload):
    short = name.split("__")[-1]
    code = payload.get("code") if isinstance(payload, dict) else None
    if code:
        lines = [line.strip() for line in code.splitlines()]
        first = next((line for line in lines if line and not line.startswith(("#", "import ", "from "))), "")
        return f"{short}: {first[:90]}"
    return short


def _handle(event) -> bool:
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        state.session_id = event.get("session_id", state.session_id)
        servers = {s.get("name"): s.get("status") for s in event.get("mcp_servers", [])}
        if servers.get(MCP_SERVER) not in (None, "connected"):
            _add("error", f"Blender MCP server is {servers.get(MCP_SERVER)}: check the MCP command in the preferences")
    elif kind == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text":
                _add("assistant", block.get("text", ""))
            elif block.get("type") == "tool_use":
                summary = _summarize_tool(block.get("name", ""), block.get("input"))
                _add("tool", summary)
                state.status = f"Running {summary.split(':')[0]}…"
    elif kind == "user":
        for block in event.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                content = block.get("content")
                text = content if isinstance(content, str) else json.dumps(content)[:300]
                _add("tool", f"failed: {text[:200]}")
            state.status = "Claude is thinking…"
    elif kind == "result":
        state.session_id = event.get("session_id", state.session_id)
        if event.get("is_error") or event.get("subtype") != "success":
            _add("error", str(event.get("result") or event.get("subtype"))[:600])
        denials = event.get("permission_denials") or []
        if denials:
            names = sorted({d.get("tool_name", "?") for d in denials})
            _add("info", "Not allowed in the chat: " + ", ".join(names))
        return True
    return False


def stop():
    if state.process is not None and state.process.poll() is None:
        state.process.terminate()


def reset():
    stop()
    state.messages.clear()
    state.session_id = ""
    state.dirty = True


# --------------------------------------------------------------------------- Blender side

def _mcp_port_open(port) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.05):
            return True
    except OSError:
        return False


def _load(scene):
    raw = scene.get("free_plugin_chat")
    data = json.loads(raw) if isinstance(raw, str) else {}
    state.messages = data.get("messages", [])
    state.session_id = data.get("session_id", "")
    state.scene_name = scene.name


def _tick():
    """Main thread: save the conversation into the scene, refresh MCP status, redraw."""
    wm = bpy.context.window_manager
    if wm is not None and wm.get("free_plugin_instance") != INSTANCE:
        wm["free_plugin_instance"] = INSTANCE
    if state.dirty:
        scene = bpy.data.scenes.get(state.scene_name) or bpy.context.scene
        if scene is not None:
            scene["free_plugin_chat"] = json.dumps({"session_id": state.session_id, "messages": state.messages})
        state.dirty = False
        for window in wm.windows if wm else ():
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    try:
        state.mcp_listening = _mcp_port_open(prefs.get().mcp_port)
    except KeyError:  # add-on being disabled
        return None
    from . import account

    account.refresh()
    return 0.3 if state.busy else 2.0


@bpy.app.handlers.persistent
def _on_load(_dummy):
    stop()
    scene = bpy.context.scene
    if scene is not None:
        _load(scene)


def write_transcript() -> str:
    lines = []
    for message in state.messages:
        prefix = {"user": "You", "assistant": "Claude", "tool": "  tool", "error": "  error", "info": "  info"}
        lines.append(f"{prefix.get(message['role'], message['role'])}: {message['text']}\n")
    text = bpy.data.texts.get("Free Plugin Chat") or bpy.data.texts.new("Free Plugin Chat")
    text.from_string("\n".join(lines))
    return text.name


def _initial_load():
    if bpy.context.scene is not None:
        _load(bpy.context.scene)


def register():
    # bpy.context is restricted while add-ons register: read the scene a moment later.
    bpy.app.timers.register(_initial_load, first_interval=0.2)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_tick, first_interval=1.0, persistent=True)


def unregister():
    stop()
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
