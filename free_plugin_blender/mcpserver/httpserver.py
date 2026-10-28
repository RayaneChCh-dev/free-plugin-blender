"""MCP "Streamable HTTP" transport on 127.0.0.1, JSON responses only. No bpy.

POST /mcp with a JSON-RPC message → 200 with the JSON response, or 202 for a
notification. GET (server-sent events) is not offered: 405, which the spec allows.
Every request needs `Authorization: Bearer <token>`; a browser Origin other than
localhost is refused, so a web page cannot reach Blender through DNS rebinding.
"""

from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .protocol import PARSE_ERROR

PATH = "/mcp"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_BODY = 20 * 1024 * 1024


class Server:
    def __init__(self, handle, token, port=0, host="127.0.0.1"):
        self.handle, self.token = handle, token
        self._httpd = ThreadingHTTPServer((host, port), _handler_for(self))
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="free-plugin:mcp", daemon=True)

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}{PATH}"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()


def _handler_for(server):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):  # quiet: Blender's console is the user's
            pass

        def _send(self, status, body=None, headers=()):
            data = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, value)
            if body is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self):
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).hostname not in _LOCAL_HOSTS:
                self._send(403, {"error": "origin not allowed"})
                return False
            if urlsplit(self.path).path != PATH:
                self._send(404, {"error": "not found"})
                return False
            given = self.headers.get("Authorization", "")
            if not hmac.compare_digest(given.encode(), f"Bearer {server.token}".encode()):
                self._send(401, {"error": "missing or wrong token"}, [("WWW-Authenticate", "Bearer")])
                return False
            return True

        def do_POST(self):  # noqa: N802 - http.server naming
            if not self._allowed():
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._send(413, {"error": "too large"})
                return
            try:
                message = json.loads(self.rfile.read(length) or b"null")
            except ValueError:
                error = {"code": PARSE_ERROR, "message": "Parse error"}
                self._send(400, {"jsonrpc": "2.0", "id": None, "error": error})
                return
            response = server.handle(message)
            if response is None:
                self._send(202)
            else:
                self._send(200, response)

        def do_GET(self):  # noqa: N802
            if self._allowed():
                self._send(405, {"error": "use POST"}, [("Allow", "POST")])

        def do_DELETE(self):  # noqa: N802
            if self._allowed():
                self._send(405, {"error": "no sessions"}, [("Allow", "POST")])

    return Handler
