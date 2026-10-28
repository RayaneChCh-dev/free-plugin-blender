import json
import urllib.error
import urllib.request

import pytest
from fpb.mcpserver import httpserver, protocol
from fpb.mcpserver.protocol import Image, Tool, ToolError


def _fail(**_):
    raise ToolError("no such object")


TOOLS = [
    Tool("echo", "Echo", {"text": {"type": "string"}}, ["text"], run=lambda text: text),
    Tool("info", "JSON", run=lambda: {"a": 1}),
    Tool("shot", "Image", run=lambda: ("caption", Image("AAAA"))),
    Tool("fail", "Fails", run=_fail),
]


def dispatcher():
    return protocol.Dispatcher(TOOLS, lambda tool, args: tool.run(**args), name="t", version="1",
                               instructions="be brief")


def rpc(method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if request_id is not None:
        message["id"] = request_id
    return message


def test_initialize_negotiates_the_version():
    d = dispatcher()
    result = d.handle(rpc("initialize", {"protocolVersion": "2025-03-26"}))["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"] == {"name": "t", "version": "1"} and result["instructions"] == "be brief"
    assert d.handle(rpc("initialize", {"protocolVersion": "1999-01-01"}))["result"]["protocolVersion"] == \
        protocol.VERSIONS[0]


def test_tools_list_and_calls():
    d = dispatcher()
    listing = d.handle(rpc("tools/list"))["result"]["tools"]
    assert [t["name"] for t in listing] == ["echo", "info", "shot", "fail"]
    assert listing[0]["inputSchema"] == {"type": "object", "properties": {"text": {"type": "string"}},
                                         "required": ["text"]}
    call = d.handle(rpc("tools/call", {"name": "echo", "arguments": {"text": "hi"}}))["result"]
    assert call == {"content": [{"type": "text", "text": "hi"}], "isError": False}
    assert json.loads(d.handle(rpc("tools/call", {"name": "info"}))["result"]["content"][0]["text"]) == {"a": 1}
    blocks = d.handle(rpc("tools/call", {"name": "shot"}))["result"]["content"]
    assert blocks == [{"type": "text", "text": "caption"}, {"type": "image", "data": "AAAA", "mimeType": "image/png"}]


def test_errors():
    d = dispatcher()
    failed = d.handle(rpc("tools/call", {"name": "fail"}))["result"]
    assert failed["isError"] and failed["content"][0]["text"] == "no such object"
    bad_args = d.handle(rpc("tools/call", {"name": "echo", "arguments": {"nope": 1}}))["result"]
    assert bad_args["isError"] and "Bad arguments" in bad_args["content"][0]["text"]
    assert d.handle(rpc("tools/call", {"name": "missing"}))["error"]["code"] == protocol.INVALID_PARAMS
    assert d.handle(rpc("resources/list"))["error"]["code"] == protocol.METHOD_NOT_FOUND
    assert d.handle({"id": 3})["error"]["code"] == protocol.INVALID_REQUEST


def test_notifications_and_batches():
    d = dispatcher()
    assert d.handle(rpc("notifications/initialized", request_id=None)) is None
    assert d.handle({"jsonrpc": "2.0", "id": 9, "result": {}}) is None
    batch = d.handle([rpc("ping", request_id=1), rpc("notifications/initialized", request_id=None)])
    assert batch == [{"jsonrpc": "2.0", "id": 1, "result": {}}]


@pytest.fixture
def server():
    s = httpserver.Server(dispatcher().handle, "secret").start()
    yield s
    s.stop()


def post(server, body, headers=None, path="/mcp", method="POST"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", data=data if method == "POST" else None,
                                     method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else None


AUTH = {"Authorization": "Bearer secret"}


def test_http_round_trip(server):
    status, body = post(server, rpc("tools/call", {"name": "echo", "arguments": {"text": "salut"}}), AUTH)
    assert status == 200 and body["result"]["content"][0]["text"] == "salut"
    assert post(server, rpc("notifications/initialized", request_id=None), AUTH) == (202, None)
    assert server.url == f"http://127.0.0.1:{server.port}/mcp"


def test_http_refusals(server):
    assert post(server, rpc("ping"))[0] == 401
    assert post(server, rpc("ping"), {"Authorization": "Bearer wrong"})[0] == 401
    assert post(server, rpc("ping"), {**AUTH, "Origin": "https://evil.example"})[0] == 403
    assert post(server, rpc("ping"), {**AUTH, "Origin": "http://localhost:3000"})[0] == 200
    assert post(server, rpc("ping"), AUTH, path="/other")[0] == 404
    assert post(server, None, AUTH, method="GET")[0] == 405
    status, body = post(server, b"{not json", AUTH)
    assert status == 400 and body["error"]["code"] == protocol.PARSE_ERROR
