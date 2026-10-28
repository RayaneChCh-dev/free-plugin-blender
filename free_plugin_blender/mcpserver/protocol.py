"""MCP over JSON-RPC: initialize, tools/list, tools/call, ping. No bpy.

Spec: https://modelcontextprotocol.io/specification (tools, lifecycle). The server is
stateless: every request carries everything it needs, so no session id is issued.
"""

from __future__ import annotations

import json
import traceback

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")  # newest first
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


class ToolError(Exception):
    """A tool failed in a way the model should read (returned with isError, not as a protocol error)."""


class Image:
    def __init__(self, data_base64: str, mime="image/png"):
        self.data, self.mime = data_base64, mime


class Tool:
    def __init__(self, name, description, properties=None, required=(), *, run, main_thread=True):
        self.name, self.description, self.run, self.main_thread = name, description, run, main_thread
        self.schema = {"type": "object", "properties": properties or {}}
        if required:
            self.schema["required"] = list(required)

    def listing(self):
        return {"name": self.name, "description": self.description, "inputSchema": self.schema}


def content(value) -> list[dict]:
    """A tool's return value as MCP content blocks: text, JSON as text, images."""
    if isinstance(value, tuple):
        return [block for part in value for block in content(part)]
    if isinstance(value, Image):
        return [{"type": "image", "data": value.data, "mimeType": value.mime}]
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    return [{"type": "text", "text": json.dumps(value, ensure_ascii=False, separators=(",", ":"))}]


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


class Dispatcher:
    """Turns JSON-RPC messages into responses. `call(tool, arguments)` runs a tool (it may hop threads)."""

    def __init__(self, tools, call, *, name="free-plugin", version="0", instructions=""):
        self.tools = {tool.name: tool for tool in tools}
        self.call, self.name, self.version, self.instructions = call, name, version, instructions

    def handle(self, message):
        """A response (dict or list for a batch), or None when nothing is to be sent back."""
        if isinstance(message, list):
            responses = [r for r in (self.handle(m) for m in message) if r is not None]
            return responses or None
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
            if isinstance(message, dict) and "method" not in message and ("result" in message or "error" in message):
                return None  # a response to something we never ask: ignore
            return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "Invalid request")
        request_id, method = message.get("id"), message["method"]
        params = message.get("params") or {}
        if request_id is None:  # notification (initialized, cancelled…): nothing to answer
            return None
        if method == "initialize":
            asked = params.get("protocolVersion")
            result = {"protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": self.name, "version": self.version}}
            if self.instructions:
                result["instructions"] = self.instructions
            return _result(request_id, result)
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/list":
            return _result(request_id, {"tools": [tool.listing() for tool in self.tools.values()]})
        if method == "tools/call":
            tool = self.tools.get(params.get("name"))
            if tool is None:
                return _error(request_id, INVALID_PARAMS, f"Unknown tool: {params.get('name')}")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _error(request_id, INVALID_PARAMS, "arguments must be an object")
            try:
                return _result(request_id, {"content": content(self.call(tool, arguments)), "isError": False})
            except ToolError as error:
                return _result(request_id, {"content": content(str(error)), "isError": True})
            except TypeError as error:  # unexpected or missing argument
                return _result(request_id, {"content": content(f"Bad arguments: {error}"), "isError": True})
            except Exception as error:  # noqa: BLE001 - reported to the model, logged for us
                traceback.print_exc()
                return _result(request_id, {"content": content(f"{type(error).__name__}: {error}"), "isError": True})
        return _error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
