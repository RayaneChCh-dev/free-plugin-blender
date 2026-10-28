"""The agent loop for API-key providers: model → tool calls → results → model… No bpy.

The model sees the same tools as Claude through the Free Plugin MCP server
(`mcpserver/tools.py`). Tool results go back as `tool` messages; images (a
screenshot) follow in a user message, since tool messages only carry text.
"""

from __future__ import annotations

import json

MAX_STEPS = 30


def _summary(name, arguments):
    if name == "run_python":
        lines = [line.strip() for line in str(arguments.get("code", "")).splitlines()]
        first = next((line for line in lines if line and not line.startswith(("#", "import ", "from "))), "")
        return f"{name}: {first[:90]}"
    detail = arguments.get("name") or arguments.get("kind") or arguments.get("object") or arguments.get("query")
    return f"{name}: {detail}" if detail else name


def run_turn(history, text, *, complete, call_tool, on_event, should_stop=lambda: False, max_steps=MAX_STEPS):
    """Run one user turn. `history` (OpenAI-format messages) is extended in place.

    complete(history) → (assistant message, usage); call_tool(name, arguments) → (content blocks, is_error);
    on_event(role, text) shows progress ("assistant", "tool", "error", "info", "usage").
    """
    history.append({"role": "user", "content": text})
    for _step in range(max_steps):
        if should_stop():
            on_event("info", "Stopped.")
            return
        message, usage = complete(history)
        history.append(message)
        on_event("usage", usage)
        if message.get("content"):
            on_event("assistant", message["content"])
        calls = message.get("tool_calls") or []
        if not calls:
            return
        images = []
        for call in calls:
            function = call.get("function") or {}
            name = function.get("name", "")
            try:
                arguments = json.loads(function.get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
            except ValueError as error:
                blocks, failed = [{"type": "text", "text": f"Bad JSON arguments: {error}"}], True
            else:
                on_event("tool", _summary(name, arguments))
                blocks, failed = call_tool(name, arguments)
            texts = [b["text"] for b in blocks if b.get("type") == "text"]
            images += [b for b in blocks if b.get("type") == "image"]
            if failed:
                on_event("tool", f"failed: {' '.join(texts)[:200]}")
            history.append({"role": "tool", "tool_call_id": call.get("id", ""),
                            "content": "\n".join(texts) or ("image below" if images else "ok")})
        # Every tool call got its answer above (the API requires it); a stop is honoured next step.
        if images:
            history.append({"role": "user", "content": [{"type": "text", "text": "Image returned by the tool:"}] + [
                {"type": "image_url", "image_url": {"url": f"data:{b['mimeType']};base64,{b['data']}"}}
                for b in images]})
    on_event("error", f"Stopped after {max_steps} steps without a final answer")


def strip_images(history):
    """A copy without image data, to save in the .blend file."""
    light = []
    for message in history:
        content = message.get("content")
        if isinstance(content, list):
            content = [part if part.get("type") != "image_url" else {"type": "text", "text": "[image]"}
                       for part in content]
            message = {**message, "content": content}
        light.append(message)
    return light
