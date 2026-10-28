import json

import pytest
from fpb import agent
from fpb.net import ApiError
from fpb.providers import openai_compat as oc


def test_chat_models_filter_and_order():
    ids = ["text-embedding-3-large", "gpt-4o-mini", "gpt-5", "gpt-5-mini", "gpt-5.1", "whisper-1", "tts-1",
           "gpt-4o-realtime-preview", "o3", "dall-e-3", "gpt-5-2025-08-07", "gpt-image-1", "babbage-002"]
    models = oc.chat_models(ids)
    assert models[0] == "gpt-5.1" and "gpt-5" in models and "o3" in models
    assert not {"text-embedding-3-large", "whisper-1", "tts-1", "dall-e-3", "gpt-image-1", "babbage-002",
                "gpt-4o-realtime-preview"} & set(models)
    assert models.index("gpt-5") < models.index("gpt-5-mini") < models.index("gpt-4o-mini")
    assert models.index("gpt-5") < models.index("gpt-5-2025-08-07")
    assert oc.default_model(models) == "gpt-5.1" and oc.default_model([]) == ""


def test_tool_specs():
    from fpb.mcpserver.protocol import Tool

    spec = oc.tool_specs([Tool("echo", "Echo", {"text": {"type": "string"}}, ["text"], run=print)])
    assert spec == [{"type": "function", "function": {"name": "echo", "description": "Echo", "parameters": {
        "type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}]


def test_complete_and_reasoning_retry(monkeypatch):
    sent = []

    def fake(method, url, headers=None, body=None, timeout=60):
        sent.append((url, headers, json.loads(json.dumps(body))))
        if "reasoning_effort" in body:
            raise ApiError("HTTP 400: Unsupported parameter: 'reasoning_effort' is not supported with this model.")
        return {"choices": [{"message": {"role": "assistant", "content": "hi", "refusal": None}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 64}}}

    monkeypatch.setattr(oc, "request_json", fake)
    message, usage = oc.complete("https://x/v1", "k", "gpt-4o", [{"role": "user", "content": "hi"}], effort="xhigh")
    assert message == {"role": "assistant", "content": "hi"}
    assert sent[0][2]["reasoning_effort"] == "high" and "reasoning_effort" not in sent[1][2]
    assert sent[0][0] == "https://x/v1/chat/completions" and sent[0][1] == {"Authorization": "Bearer k"}
    assert oc.usage_counts(usage) == (100, 64, 5)
    with pytest.raises(ApiError, match="No API key"):
        oc.complete("https://x/v1", "", "m", [])


def _call(call_id, name, arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def test_turn_with_tools_and_image():
    replies = iter([
        ({"role": "assistant", "content": "Je regarde.", "tool_calls": [
            _call("a", "scene_summary", {}), _call("b", "screenshot", {"source": "viewport"})]}, {"prompt_tokens": 1}),
        ({"role": "assistant", "content": "Fait."}, {"prompt_tokens": 2}),
    ])
    events, calls, history = [], [], []

    def call_tool(name, arguments):
        calls.append(name)
        if name == "screenshot":
            image = {"type": "image", "data": "QUJD", "mimeType": "image/png"}
            return [{"type": "text", "text": "viewport 10x10"}, image], False
        return [{"type": "text", "text": "Cube · mesh"}], False

    agent.run_turn(history, "ajoute un cube", complete=lambda h: next(replies), call_tool=call_tool,
                   on_event=lambda role, text: events.append((role, text)))
    assert calls == ["scene_summary", "screenshot"]
    assert [m["role"] for m in history] == ["user", "assistant", "tool", "tool", "user", "assistant"]
    assert history[2] == {"role": "tool", "tool_call_id": "a", "content": "Cube · mesh"}
    assert history[4]["content"][1]["image_url"]["url"] == "data:image/png;base64,QUJD"
    assert [e for e in events if e[0] != "usage"] == [("assistant", "Je regarde."), ("tool", "scene_summary"),
                                                       ("tool", "screenshot"), ("assistant", "Fait.")]
    light = agent.strip_images(history)
    assert light[4]["content"][1] == {"type": "text", "text": "[image]"} and "QUJD" in json.dumps(history)


def test_errors_bad_json_and_step_limit():
    bad = {"role": "assistant", "tool_calls": [{"id": "x", "function": {"name": "run_python", "arguments": "{oops"}}]}
    events, history = [], []
    agent.run_turn(history, "go", complete=lambda h: (dict(bad), {}), call_tool=lambda n, a: ([], False),
                   on_event=lambda role, text: events.append((role, text)), max_steps=3)
    assert history[2]["content"].startswith("Bad JSON arguments")
    assert events[-1] == ("error", "Stopped after 3 steps without a final answer")
    events.clear()
    agent.run_turn([], "go", complete=lambda h: (dict(bad), {}), call_tool=lambda n, a: ([], False),
                   on_event=lambda role, text: events.append((role, text)), should_stop=lambda: True)
    assert events == [("info", "Stopped.")]


def test_failed_tool_is_shown():
    replies = iter([({"role": "assistant", "tool_calls": [_call("a", "object_info", {"name": "Nope"})]}, {}),
                    ({"role": "assistant", "content": "Introuvable."}, {})])
    events = []
    agent.run_turn([], "info", complete=lambda h: next(replies),
                   call_tool=lambda n, a: ([{"type": "text", "text": "No object named 'Nope'"}], True),
                   on_event=lambda role, text: events.append((role, text)))
    assert ("tool", "object_info: Nope") in events and ("tool", "failed: No object named 'Nope'") in events
