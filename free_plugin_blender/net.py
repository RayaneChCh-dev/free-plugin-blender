"""Small stdlib HTTP helpers, so the extension ships without any wheel."""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "free-plugin-blender/0.1"


class ApiError(RuntimeError):
    pass


def request_json(method, url, *, headers=None, body=None, timeout=60):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:500]
        raise ApiError(f"HTTP {error.code} on {url.split('?')[0]}: {detail}") from None
    except urllib.error.URLError as error:
        raise ApiError(f"Network error on {url.split('?')[0]}: {error.reason}") from None
    return json.loads(raw) if raw else {}


def download(url, dest: Path, timeout=300) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if url.startswith("data:"):
        dest.write_bytes(base64.b64decode(url.split(",", 1)[1]))
        return dest
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, dest.open("wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
    except urllib.error.URLError as error:
        dest.unlink(missing_ok=True)
        raise ApiError(f"Download failed: {error}") from None
    return dest


def data_uri(path: Path, mime: str | None = None) -> str:
    mime = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
