"""Chat with an API key (OpenAI-compatible) running the agent loop on the built-in tools. Fake API."""

import json
import os
import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402

requests = []
script = []  # the assistant messages the fake API answers with, in order


def fake_openai(method, url, headers=None, body=None, timeout=60):
    requests.append((method, url, headers, json.loads(json.dumps(body)) if body else None))
    if url.endswith("/models"):
        return {"data": [{"id": i} for i in ("gpt-4o-mini", "gpt-5.1", "text-embedding-3-small", "gpt-5")]}
    if body.get("messages", [{}])[-1].get("content") == "slow":
        time.sleep(2)
    message = script.pop(0) if script else {"role": "assistant", "content": "Rien d'autre."}
    return {"choices": [{"message": message}],
            "usage": {"prompt_tokens": 2000, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 1500}}}


def call(call_id, tool_name, /, **arguments):
    return {"id": call_id, "type": "function", "function": {"name": tool_name, "arguments": json.dumps(arguments)}}


def wait_chat(chat, mcp, tasks, limit=20):
    end = time.time() + limit
    while chat.state.busy and time.time() < end:
        mcp.pump()
        tasks._pump()
        time.sleep(0.02)
    tasks._pump()
    chat._tick()


def test():
    harness.enable()
    chat, mcp, tasks = harness.module(".chat"), harness.module(".mcpserver"), harness.module(".tasks")
    api_models, oc = harness.module(".api_models"), harness.module(".providers.openai_compat")
    oc.request_json = fake_openai
    prefs = bpy.context.preferences.addons[harness.MODULE].preferences
    scene = bpy.context.scene

    harness.check("Claude by default", prefs.chat_provider == "CLAUDE")
    prefs.chat_provider = "OPENAI"
    harness.check("no key: refused with a hint", "OpenAI key" in (chat.send("bonjour", scene) or ""))

    prefs.openai_key = "sk-test"  # triggers the model list
    harness.wait()
    harness.check("live model list, chat models only", api_models.models() == ["gpt-5.1", "gpt-5", "gpt-4o-mini"],
                  api_models.models())
    harness.check("newest model by default", api_models.current() == "gpt-5.1")
    harness.check("model list cached on disk", "gpt-5.1" in (harness.module(".prefs").user_dir()
                                                             / "api_models.json").read_text())
    prefs.openai_model = "gpt-5"
    harness.check("chosen model kept", api_models.current() == "gpt-5")

    # A turn with tool calls: the agent adds a red sphere through the built-in tools.
    script[:] = [
        {"role": "assistant", "content": "Je regarde la scène.", "tool_calls": [call("c1", "scene_summary")]},
        {"role": "assistant", "content": None, "tool_calls": [
            call("c2", "add_object", kind="sphere", name="AgentBall", location=[0, 0, 1], color=[1, 0, 0]),
            call("c3", "object_info", name="Nope")]},
        {"role": "assistant", "content": "Sphère rouge ajoutée."},
    ]
    requests.clear()
    harness.check("send starts", chat.send("ajoute une sphère rouge", scene, "[Blender selection: Cube]") is None)
    wait_chat(chat, mcp, tasks)
    harness.check("tool really ran in Blender", "AgentBall" in bpy.data.objects)
    roles = [m["role"] for m in chat.state.messages]
    harness.check("conversation shown", roles == ["user", "assistant", "tool", "tool", "tool", "tool", "assistant"],
                  roles)
    harness.check("failed tool shown", any(m["text"].startswith("failed: No object named")
                                           for m in chat.state.messages))
    posts = [r for r in requests if r[0] == "POST"]
    first = posts[0][3]
    harness.check("three calls to the API", len(posts) == 3, len(posts))
    harness.check("model, effort, key", first["model"] == "gpt-5" and first["reasoning_effort"] == "medium"
                  and posts[0][2]["Authorization"] == "Bearer sk-test")
    harness.check("system prompt and tools sent", first["messages"][0]["role"] == "system"
                  and "scene_summary" in first["messages"][0]["content"]
                  and {t["function"]["name"] for t in first["tools"]} >= {"scene_summary", "add_object", "run_python"})
    harness.check("selection note sent", "[Blender selection: Cube]" in first["messages"][1]["content"])
    last = posts[-1][3]["messages"]
    tool_messages = [m for m in last if m["role"] == "tool"]
    harness.check("tool results returned to the model", [m["tool_call_id"] for m in tool_messages] == ["c1", "c2", "c3"]
                  and "Cube" in tool_messages[0]["content"] and "AgentBall" in tool_messages[1]["content"])
    harness.check("tokens of the whole turn", chat.state.usage == "Last answer: 6.0k tokens in (4.5k cached) · 150 out",
                  chat.state.usage)
    saved = json.loads(scene["free_plugin_chat"])
    harness.check("history saved in the scene", len(saved["api_history"]) == 7 and saved["messages"][-1]["text"]
                  == "Sphère rouge ajoutée.", len(saved["api_history"]))

    # Next turn carries the history.
    chat.send("merci", scene)
    wait_chat(chat, mcp, tasks)
    harness.check("history sent on the next turn", len([r for r in requests if r[0] == "POST"][-1][3]["messages"]) == 9)

    # Stop: the loop ends before its next step.
    script[:] = [{"role": "assistant", "content": None, "tool_calls": [call("s1", "scene_summary")]}] * 5
    chat.send("slow", scene)
    time.sleep(0.3)
    harness.check("busy while answering", chat.state.busy and chat.send("x", scene) == "Still answering")
    chat.stop()
    wait_chat(chat, mcp, tasks)
    harness.check("stopped", not chat.state.busy and chat.state.messages[-1]["text"] == "Stopped.",
                  chat.state.messages[-1])
    harness.check("pump released", mcp.state.clients == 0)

    # API errors are shown, not raised.
    def failing(method, url, headers=None, body=None, timeout=60):
        raise oc.ApiError("HTTP 401 on https://api.openai.com/v1/chat/completions: invalid key")
    oc.request_json = failing
    chat.send("encore", scene)
    wait_chat(chat, mcp, tasks)
    harness.check("API error shown", chat.state.messages[-1]["role"] == "error"
                  and "invalid key" in chat.state.messages[-1]["text"])

    chat.reset()
    chat._tick()
    harness.check("reset clears the history", json.loads(scene["free_plugin_chat"])["api_history"] == [])
    os.environ.pop("OPENAI_API_KEY", None)
    prefs.chat_provider = "CLAUDE"


harness.run(test)
