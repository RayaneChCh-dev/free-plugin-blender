"""The Free Plugin MCP server over real HTTP: lifecycle, every tool, chat config per mode. Fakes only."""

import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402
from fakes import fake_fal, fake_polyhaven, last_call  # noqa: E402

STATE = Path(tempfile.mkdtemp(prefix="fakeclaude-"))
os.environ["FAKE_CLAUDE_STATE"] = str(STATE)


def post(server, message, token):
    request = urllib.request.Request(server.url, data=json.dumps(message).encode(), method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, None


def test():
    harness.enable()
    mcp, tasks, chat = harness.module(".mcpserver"), harness.module(".tasks"), harness.module(".chat")
    fal, net = harness.module(".providers.fal"), harness.module(".net")
    polyhaven = harness.module(".providers.polyhaven")
    png, glb = harness.fixture_files()
    fal.request_json, fal.time.sleep, polyhaven.request_json = fake_fal, lambda _s: None, fake_polyhaven
    net.download = harness.module(".operators").net.download = harness.fake_download(png, glb)
    os.environ["FAL_KEY"] = "test-key"
    prefs = bpy.context.preferences.addons[harness.MODULE].preferences

    harness.check("mode OWN by default", prefs.mcp_mode == "OWN" and mcp.wanted())
    prefs.mcp_mode = "EXTERNAL"
    harness.check("off in mode mcp-for-blender", not mcp.wanted() and mcp.state.server is None)
    prefs.mcp_mode = "OWN"
    server = mcp.state.server
    harness.check("starts in mode OWN, on its own port", server is not None and server.port > 0, mcp.state.error)
    token = mcp.token()
    harness.check("token made and kept", len(token) >= 24 and mcp.token() == token)

    ids = iter(range(1, 1000))

    def call(method, params=None, *, with_token=True, limit=60):
        box = {}
        message = {"jsonrpc": "2.0", "id": next(ids), "method": method, "params": params or {}}
        worker = threading.Thread(target=lambda: box.update(r=post(server, message, token if with_token else "")))
        worker.start()
        end = time.time() + limit
        while worker.is_alive() and time.time() < end:
            mcp.pump()
            tasks._pump()
            time.sleep(0.02)
        return box.get("r", (None, None))

    def tool(tool_name, /, **arguments):
        status, body = call("tools/call", {"name": tool_name, "arguments": arguments})
        result = body["result"]
        text = "\n".join(b.get("text", "") for b in result["content"] if b["type"] == "text")
        return result["isError"], text

    harness.check("token required", call("ping", with_token=False)[0] == 401)
    status, body = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "test", "version": "0"}})
    info = body["result"]
    harness.check("initialize", status == 200 and info["serverInfo"]["name"] == "free-plugin-blender"
                  and "scene_summary" in info["instructions"], info)
    names = [t["name"] for t in call("tools/list")[1]["result"]["tools"]]
    harness.check("tools listed", {"scene_summary", "add_object", "edit_object", "set_material", "screenshot",
                                   "generate", "assets", "run_python", "object_info"} <= set(names), names)
    listing = json.dumps(call("tools/list")[1]["result"]["tools"])
    harness.check("tool listing stays small", len(listing) < 6000, len(listing))

    error, text = tool("scene_summary")
    harness.check("scene summary", not error and "Cube · mesh · at (0, 0, 0) · size (2, 2, 2)" in text, text)
    error, text = tool("add_object", kind="sphere", name="Ball", location=[1, 2, 0.5], size=1, color=[1, 0, 0])
    ball = bpy.data.objects.get("Ball")
    harness.check("add_object", not error and ball is not None and tuple(ball.location) == (1, 2, 0.5), text)
    color = tuple(ball.active_material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value)
    harness.check("colour material", color[:3] == (1, 0, 0), color)
    error, text = tool("edit_object", name="Ball", location=[0, 0, 3], rotation_deg=[0, 0, 90], rename="Sun Ball")
    moved = bpy.data.objects["Sun Ball"].location.z == 3
    harness.check("edit_object", not error and moved and "rot (0, 0, 90)°" in text, text)
    error, text = tool("set_material", object="Cube", metallic=1.0, roughness=0.2, color=[0.1, 0.2, 0.9])
    harness.check("set_material", not error and "Cube" in text, text)
    error, text = tool("object_info", name="Cube")
    data = json.loads(text)
    harness.check("object_info", data["materials"][0]["color"] == [0.1, 0.2, 0.9] and data["vertices"] == 8, data)
    error, text = tool("object_info", name="Nope")
    harness.check("unknown object is a tool error", error and "No object named" in text)
    error, text = tool("edit_object", name="Sun Ball", delete=True)
    harness.check("delete", not error and "Sun Ball" not in bpy.data.objects)
    error, text = tool("run_python", code="print(len(bpy.data.objects))\nresult = C.scene.name")
    harness.check("run_python", not error and "result = 'Scene'" in text, text)
    error, text = tool("run_python", code="1/0")
    harness.check("python error returned", error and "ZeroDivisionError" in text, text)
    error, text = tool("screenshot")
    harness.check("no screenshot without a window", error and "without a window" in text, text)
    error, text = tool("add_object", kind="dragon")
    harness.check("bad kind", error and "kind must be" in text)

    error, text = tool("plugin_status")
    status_data = json.loads(text)
    harness.check("plugin_status", status_data["fal_key"] and "trellis" in status_data["models"]["mesh"], status_data)
    error, text = tool("generate", kind="image", prompt="a red tagine")
    harness.check("generate waits for the result", not error and json.loads(text)["state"] == "done", text)
    harness.check("generation reached fal.ai", last_call()[1].get("prompt") == "a red tagine", last_call())
    error, text = tool("generate", kind="material", prompt="zellige", object="Nope")
    harness.check("generate on a missing object", error and "No object named" in text, text)
    error, text = tool("assets", action="search", kind="hdris", query="sunset")
    harness.check("Poly Haven search", not error and json.loads(text) == [{"id": "sunset_a", "name": "Sunset A"}], text)
    error, text = tool("find_presets", query="walk")
    harness.check("find presets", not error and all("walk" in (p["name"] + p["sub"]).lower() for p in json.loads(text)))
    error, text = tool("task_status")
    harness.check("task_status", not error and "a red tagine" in text, text)
    harness.check("calls counted", mcp.state.calls >= 15, mcp.state.calls)

    # run_script: many tool calls in one, only the printed text comes back.
    before = len(bpy.data.objects)
    error, text = tool("run_script", code="""
for i in range(10):
    kiln.add_object(kind='cube', name=f'Grid{i}', location=[i * 1.5, 0, 0], size=1)
hits = kiln.assets(action='search', kind='hdris', query='sunset')
try:
    kiln.edit_object(name='Nope', delete=True)
except KilnError as e:
    print('caught:', e)
finally:
    print('hdri', hits[0]['id'])
result = len(kiln.scene_summary().splitlines())
""")
    harness.check("run_script adds through the tools", not error and len(bpy.data.objects) == before + 10
                  and bpy.data.objects["Grid9"].location.x == 13.5, text)
    harness.check("run_script returns only what it printed", "caught: No object named 'Nope'" in text
                  and "hdri sunset_a" in text and "result = " in text and "[13 tool call(s)" in text
                  and "Grid3" not in text, text)
    error, text = tool("run_script", code="kiln.object_info(name='Nope')")
    harness.check("run_script error: traceback returned", error and "KilnError" in text, text)

    # Chat config per mode (through the fake claude).
    fake = harness.FIXTURES / "fakeclaude" / "claude"
    prefs.claude_path = str(fake)
    scene = bpy.context.scene
    for mode, expected in (("OWN", ["free_plugin"]), ("BOTH", ["blender", "free_plugin"]), ("EXTERNAL", ["blender"])):
        prefs.mcp_mode = mode
        harness.check(f"{mode}: send starts", chat.send("bonjour", scene) is None)
        end = time.time() + 15
        while chat.state.busy and time.time() < end:
            time.sleep(0.05)
        argv = json.loads((STATE / "last_call.json").read_text())["argv"]
        servers = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
        allowed = argv[argv.index("--allowedTools") + 1]
        prompt = argv[argv.index("--append-system-prompt") + 1]
        harness.check(f"{mode}: servers", sorted(servers) == expected, sorted(servers))
        harness.check(f"{mode}: allowed tools", allowed == ",".join(f"mcp__{n}" for n in expected), allowed)
        if "free_plugin" in servers:
            own = servers["free_plugin"]
            harness.check(f"{mode}: HTTP entry with the token", own["type"] == "http" and own["url"] == server.url
                          and own["headers"]["Authorization"] == f"Bearer {token}", own)
        harness.check(f"{mode}: instance check only with mcp-for-blender",
                      (chat.INSTANCE in prompt) == ("blender" in servers))
    harness.check("OWN prompt is shorter", len(chat.system_prompt({"free_plugin": {}}))
                  < len(chat.system_prompt({"blender": {}})) / 2)
    harness.check("server stops when no longer used", mcp.state.server is None)

    prefs.own_mcp_terminal = True
    harness.check("kept on for the terminal", mcp.state.server is not None
                  and "claude mcp add --transport http" in mcp.terminal_command())
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    prefs.own_mcp_port = blocker.getsockname()[1]
    harness.check("taken port reported", mcp.state.server is None and "is taken" in mcp.state.error, mcp.state.error)
    blocker.close()
    prefs.own_mcp_port, prefs.own_mcp_terminal = 0, False

    # Preferences draw in every mode (a stand-in layout records the labels).
    class Layout:
        def __init__(self, labels):
            self.labels = labels

        def __getattr__(self, name):
            return lambda *a, **k: Layout(self.labels) if name in ("box", "row", "column") else self._leaf(k)

        def _leaf(self, keywords):
            if "text" in keywords:
                self.labels.append(keywords["text"])
            return type("Leaf", (), {})()

    for mode in ("EXTERNAL", "BOTH", "OWN"):
        prefs.mcp_mode, labels = mode, []
        type(prefs).draw(_Proxy(prefs, Layout(labels)), bpy.context)
        own = any("Free Plugin MCP: on" in t for t in labels)
        harness.check(f"{mode}: preferences draw", own == (mode != "EXTERNAL"), labels[-6:])
    prefs.mcp_mode = "EXTERNAL"


class _Proxy:
    """The preferences with a stand-in layout (AddonPreferences.layout is read-only)."""

    def __init__(self, prefs, layout):
        object.__setattr__(self, "_prefs", prefs)
        object.__setattr__(self, "layout", layout)

    def __getattr__(self, name):
        return getattr(self._prefs, name)


harness.run(test)
