"""OpenAI-compatible Chat Completions with tools: OpenAI first, the same format serves others. No bpy.

Docs: https://platform.openai.com/docs/api-reference/chat — `POST {base}/chat/completions`
with `tools`, and `GET {base}/models` for the live model list.
"""

from __future__ import annotations

import re

from ..net import ApiError, request_json

PROVIDERS = {
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
               "keys_url": "https://platform.openai.com/api-keys"},
}

# Models a chat cannot use: embeddings, speech, images, moderation, legacy completions…
_NOT_CHAT = re.compile(r"(embed|tts|whisper|transcri|audio|realtime|image|dall-e|moderation|search|"
                       r"davinci|babbage|instruct|computer-use|sora)", re.I)
_CHAT = re.compile(r"^(gpt-|o\d|chatgpt-)", re.I)

# Our effort levels → reasoning_effort. Models that do not reason refuse it (retried without).
EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


def _headers(key):
    if not key:
        raise ApiError("No API key: set it in Preferences > Add-ons > Free Plugin Blender")
    return {"Authorization": f"Bearer {key}"}


def chat_models(ids, provider="openai"):
    """The ids a chat can use, newest-looking first."""
    keep = [i for i in ids if not _NOT_CHAT.search(i) and (provider != "openai" or _CHAT.match(i))]
    return sorted(set(keep), key=_rank)


def _rank(model_id):
    """Sort key: higher versions first, full models before mini/nano, undated before dated."""
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", model_id.split("-20")[0])[:2]] or [0.0]
    small = any(word in model_id for word in ("mini", "nano", "lite"))
    dated = bool(re.search(r"-\d{4}-\d{2}-\d{2}$", model_id))
    return (-numbers[0], -(numbers[1] if len(numbers) > 1 else 0), small, dated, model_id)


def default_model(models):
    return models[0] if models else ""


def list_models(base_url, key, provider="openai"):
    data = request_json("GET", f"{base_url}/models", headers=_headers(key), timeout=30)
    return chat_models([m.get("id", "") for m in data.get("data", [])], provider)


def tool_specs(tools):
    """Our MCP tools (`mcpserver.protocol.Tool`) as function tools."""
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}}
            for t in tools]


def complete(base_url, key, model, messages, tools=(), effort="medium", timeout=300):
    """One assistant message: (message dict, usage dict)."""
    body = {"model": model, "messages": messages}
    if tools:
        body["tools"] = list(tools)
    if effort in EFFORT:
        body["reasoning_effort"] = EFFORT[effort]
    url = f"{base_url}/chat/completions"
    try:
        data = request_json("POST", url, headers=_headers(key), body=body, timeout=timeout)
    except ApiError as error:
        if "reasoning_effort" not in body or "reasoning" not in str(error).lower():
            raise
        body.pop("reasoning_effort")  # a model that does not reason
        data = request_json("POST", url, headers=_headers(key), body=body, timeout=timeout)
    choices = data.get("choices") or []
    if not choices:
        raise ApiError(f"No answer from {model}: {str(data)[:300]}")
    message = choices[0].get("message") or {}
    message = {k: v for k, v in message.items() if k in ("role", "content", "tool_calls") and v is not None}
    message.setdefault("role", "assistant")
    return message, data.get("usage") or {}


def usage_counts(usage):
    """(tokens sent, of which cached, tokens out) from a Chat Completions usage object."""
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    return usage.get("prompt_tokens", 0) or 0, cached, usage.get("completion_tokens", 0) or 0
