"""One benchmark run inside a throwaway Blender: one task, one MCP mode, the real Claude Code.

Started by scripts/bench_mcp_modes.py:
    blender --factory-startup start.blend --python driver.py -- <mode> <task> <model> <report.json>
"""

import json
import sys
import tempfile
import time
import traceback

import addon_utils
import bpy

MODULE = "bl_ext.user_default.free_plugin_blender"
MCP_PORT = 9877  # never 9876: the user's own Blender listens there
TIMEOUT = 900

TASKS = {
    "build": "Build a small dining set: a wooden table with four chairs around it, on a floor plane, "
             "lit by a warm sun.",
    "batch": "Create a 5 by 5 grid of cubes 1.5 m apart, each with its own material, the colours going "
             "from red at one corner to blue at the opposite corner.",
    "look": "Look at the scene through the active camera and tell me in two sentences how the lighting "
            "and framing could be improved. Do not change anything.",
    "assets": "Use free Poly Haven assets: a sunset HDRI for the world, and two models, a wooden chair and a "
              "potted plant, placed 2 m apart on the ground.",
}


def scene_check(task):
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    materials = {s.material.name for o in meshes for s in o.material_slots if s.material}
    if task == "build":
        return len(meshes) >= 6, f"{len(meshes)} meshes"
    if task == "batch":
        return len(meshes) >= 25 and len(materials) >= 25, f"{len(meshes)} meshes, {len(materials)} materials"
    if task == "assets":
        world = bpy.context.scene.world
        hdri = bool(world and world.node_tree and any(n.type == "TEX_ENVIRONMENT" and n.image
                                                       for n in world.node_tree.nodes))
        return hdri and len(meshes) >= 3, f"{len(meshes)} meshes, HDRI {'set' if hdri else 'missing'}"
    return len(meshes) == 1, f"{len(meshes)} meshes (scene must be unchanged)"


mode, task, model, report_path = sys.argv[sys.argv.index("--") + 1:][:4]
addon_utils.enable(MODULE, default_set=True)
chat = sys.modules[MODULE + ".chat"]
prefs = bpy.context.preferences.addons[MODULE].preferences
prefs.output_dir = tempfile.mkdtemp(prefix="kiln-bench-")
prefs.mcp_mode, prefs.mcp_port, prefs.chat_model = mode, MCP_PORT, model

if mode != "OWN":
    addon_utils.enable("blender_mcp", default_set=True)
    scene = bpy.context.scene
    scene.blendermcp_auto_start_server = False
    scene.blendermcp_use_polyhaven = True  # we start it ourselves, on the benchmark port
    server_module = sys.modules["blender_mcp"]
    server = server_module.BlenderMCPServer(port=MCP_PORT)
    bpy.types.blendermcp_server = server
    server.start()

events, report = [], {"mode": mode, "task": task, "model": model}
original_handle = chat._handle


def handle(event):
    events.append(event)
    return original_handle(event)


chat._handle = handle


def finish():
    try:
        result = next((e for e in reversed(events) if e.get("type") == "result"), {})
        tools = [block.get("name", "") for e in events if e.get("type") == "assistant"
                 for block in e.get("message", {}).get("content", []) if block.get("type") == "tool_use"]
        done, detail = scene_check(task)
        report.update(
            usage=result.get("usage", {}), cost_usd=result.get("total_cost_usd"),
            turns=result.get("num_turns"), duration_ms=result.get("duration_ms"),
            model_usage=result.get("modelUsage", {}), tools=tools, done=done, check=detail,
            answer=str(result.get("result", ""))[:600],
            errors=[m["text"][:300] for m in chat.state.messages if m["role"] == "error"],
        )
    except Exception:
        report["crash"] = traceback.format_exc()
    with open(report_path, "w") as handle_:
        json.dump(report, handle_, indent=1)
    bpy.ops.wm.quit_blender()


def start():
    if mode != "OWN" and not bpy.types.blendermcp_server.running:
        return 0.5
    error = chat.send(TASKS[task], bpy.context.scene)
    if error:
        report["crash"] = error
        finish()
        return None
    started = time.time()

    def wait():
        if chat.state.busy and time.time() - started < TIMEOUT:
            return 1.0
        if chat.state.busy:
            chat.stop()
            report["timeout"] = True
        finish()
        return None

    bpy.app.timers.register(wait, first_interval=2.0)
    return None


bpy.app.timers.register(start, first_interval=1.0)
