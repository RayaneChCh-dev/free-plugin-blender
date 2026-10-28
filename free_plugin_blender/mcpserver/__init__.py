"""The Free Plugin MCP server: compact Blender tools for Claude, served by this Blender.

It listens on 127.0.0.1 (a port per Blender, automatic by default) and needs a token,
so it only ever reaches this window, unlike a shared add-on port. Requests arrive on
HTTP threads; tools that touch bpy are queued to the main thread (`on_main`) and run
by a `bpy.app.timers` pump, the same way as the generation tasks.

It runs when the chat uses it (preference "Claude's Blender tools") or when the user
keeps it on for Claude Code in a terminal (`terminal_command()`).
"""

from __future__ import annotations

import queue
import re
import secrets
import threading
from pathlib import Path

import bpy

from .. import prefs
from . import httpserver, protocol, tools

SERVER_NAME = "free_plugin"
_queue: queue.SimpleQueue = queue.SimpleQueue()


class _State:
    server: httpserver.Server | None = None
    error = ""
    calls = 0


state = _State()


def on_main(function, timeout=90):
    """Run function() on Blender's main thread and return its value (or raise its error)."""
    if threading.current_thread() is threading.main_thread():
        return function()
    box, done = {}, threading.Event()
    _queue.put((function, box, done))
    if not done.wait(timeout):
        raise protocol.ToolError("Blender did not answer in time (busy, or a modal dialog is open)")
    if "error" in box:
        raise box["error"]
    return box["value"]


tools.on_main = on_main


def pump():
    """Main thread: run the queued tool calls."""
    while True:
        try:
            function, box, done = _queue.get_nowait()
        except queue.Empty:
            break
        try:
            box["value"] = function()
        except Exception as error:  # noqa: BLE001 - handed back to the HTTP thread
            box["error"] = error
        done.set()
    return 0.05 if state.server is not None else None


def _call(tool, arguments):
    state.calls += 1
    return on_main(lambda: tool.run(**arguments)) if tool.main_thread else tool.run(**arguments)


def _version():
    manifest = Path(__file__).resolve().parents[1].joinpath("blender_manifest.toml").read_text()
    match = re.search(r'^version = "(.+)"', manifest, re.M)
    return match[1] if match else "0"


def token() -> str:
    settings = prefs.get()
    if not settings.own_mcp_token:
        settings.own_mcp_token = secrets.token_urlsafe(24)
    return settings.own_mcp_token


def wanted() -> bool:
    settings = prefs.get()
    return settings.mcp_mode != "EXTERNAL" or settings.own_mcp_terminal


def start():
    if state.server is not None:
        return state.server
    port = prefs.get().own_mcp_port
    dispatcher = protocol.Dispatcher(tools.build(), _call, name="free-plugin-blender", version=_version(),
                                     instructions=tools.INSTRUCTIONS)
    try:
        state.server = httpserver.Server(dispatcher.handle, token(), port=port).start()
    except OSError as error:
        state.error = f"Port {port} is taken: choose another, or 0 for automatic" if port else str(error)
        return None
    state.error = ""
    if not bpy.app.timers.is_registered(pump):
        bpy.app.timers.register(pump, first_interval=0.05, persistent=True)
    return state.server


def stop():
    if state.server is not None:
        state.server.stop()
        state.server = None
    if bpy.app.timers.is_registered(pump):
        bpy.app.timers.unregister(pump)


def sync(*_args):
    """Start or stop the server to match the preferences (also restarts it on a port change)."""
    try:
        want = wanted()
    except KeyError:  # add-on being disabled
        return None
    port = prefs.get().own_mcp_port
    if state.server is not None and (not want or (port and port != state.server.port)):
        stop()
    if want:
        start()
    return None


def url() -> str:
    return state.server.url if state.server else ""


def client_config() -> dict:
    """Entry for `--mcp-config` (Claude Code's HTTP transport)."""
    return {"type": "http", "url": url(), "headers": {"Authorization": f"Bearer {token()}"}}


def terminal_command() -> str:
    return (f"claude mcp add --transport http free-plugin-blender {url()} "
            f'--header "Authorization: Bearer {token()}"')


def register():
    bpy.app.timers.register(sync, first_interval=0.5)  # bpy.context is restricted during register()


def unregister():
    if bpy.app.timers.is_registered(sync):
        bpy.app.timers.unregister(sync)
    stop()
