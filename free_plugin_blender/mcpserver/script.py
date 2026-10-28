"""`run_script`: a Python script that calls the Free Plugin tools itself, in one model turn. No bpy.

Every model call re-sends the whole context, so a task done in 30 tool calls costs 30 times that
context (docs/BENCHMARK.md). Here the model writes one script; its intermediate results stay in
variables, waiting is a `while` loop, cleanup is a `finally`, and only what the script prints (plus
the last screenshots it took) goes back to the model.

The script runs in a child Python (`python -I`, empty working folder, killed at the timeout). It
reaches Blender only through `kiln.<tool>(**arguments)`: each call is one JSON line on the child's
stdout, answered by one line on its stdin, and runs through the same `call` as an MCP request. It is
isolation from crashes and hangs, not a security sandbox: the tools include run_python.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

MAX_TIMEOUT = 900
MAX_OUTPUT = 6000
MAX_IMAGES = 2

# Runs in the child. The RPC channel is the real stdout; print() goes to a buffer sent at the end.
CHILD = r'''
import io, json, sys, traceback

_rpc_out, _rpc_in = sys.stdout, sys.stdin
_printed = io.StringIO()
sys.stdout = _printed


class KilnError(Exception):
    """A Free Plugin tool failed: the message says why."""


class _Kiln:
    KilnError = KilnError

    def call(self, tool, /, **arguments):  # positional only: tools take a `name` argument
        _rpc_out.write(json.dumps({"call": tool, "args": arguments}) + "\n")
        _rpc_out.flush()
        reply = json.loads(_rpc_in.readline() or '{"error": "Blender closed the script"}')
        if "error" in reply:
            raise KilnError(reply["error"])
        return reply["value"]

    def __getattr__(self, tool):
        if tool.startswith("_"):
            raise AttributeError(tool)
        return lambda **arguments: self.call(tool, **arguments)


namespace = {"kiln": _Kiln(), "KilnError": KilnError, "result": None, "__name__": "__kiln__"}
with open(sys.argv[1], encoding="utf-8") as handle:
    code = handle.read()
try:
    exec(compile(code, "<script>", "exec"), namespace)
    end = {"done": _printed.getvalue()}
    if namespace.get("result") is not None:
        end["result"] = repr(namespace["result"])
except BaseException:
    lines = traceback.format_exc().splitlines()
    end = {"failed": _printed.getvalue(), "traceback": "\n".join(lines[-8:])}
_rpc_out.write(json.dumps(end) + "\n")
_rpc_out.flush()
'''


class ScriptError(Exception):
    """The script failed or timed out: the message has its output and the traceback."""


def _plain(value, images):
    """A tool's return value for the child: JSON values as they are, images kept for the final answer."""
    if isinstance(value, tuple):
        parts = [_plain(part, images) for part in value]
        texts = [p for p in parts if p is not None]
        return texts[0] if len(texts) == 1 else texts
    if hasattr(value, "data") and hasattr(value, "mime"):  # protocol.Image
        images.append(value)
        return None
    return value


def _clip(text, limit=MAX_OUTPUT):
    return text if len(text) <= limit else "…" + text[-limit:]


def run(code: str, call, timeout=300, python=None, forbidden=("run_script",)):
    """Run `code`; `call(name, arguments)` runs one tool and returns its value or raises.

    Returns the printed text, or (text, *images) when the script took screenshots.
    """
    timeout = max(1, min(int(timeout or 300), MAX_TIMEOUT))
    folder = tempfile.mkdtemp(prefix="kiln-script-")
    path = os.path.join(folder, "script.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(code)
    child_path = os.path.join(folder, "_kiln_child.py")
    with open(child_path, "w", encoding="utf-8") as handle:
        handle.write(CHILD)
    process = subprocess.Popen([python or sys.executable, "-I", child_path, path], cwd=folder,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8")
    timer = threading.Timer(timeout, process.kill)
    timer.start()
    images, calls, started = [], 0, time.time()
    try:
        for line in process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if "call" not in message:
                return _finish(message, images, calls, started)
            name, arguments = message["call"], message.get("args") or {}
            calls += 1
            try:
                if name in forbidden:
                    raise ScriptError(f"{name} cannot be called from a script")
                reply = {"value": _plain(call(name, arguments), images)}
            except Exception as error:  # noqa: BLE001 - handed to the script as KilnError
                reply = {"error": str(error) or type(error).__name__}
            try:
                process.stdin.write(json.dumps(reply, default=str) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                break
        stderr = process.stderr.read()[-1500:]
        if time.time() - started >= timeout - 0.5:
            raise ScriptError(f"Stopped after {timeout} s (timeout). {calls} tool call(s) done.")
        raise ScriptError(f"The script process ended unexpectedly. {stderr}".strip())
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        for name in ("script.py", "_kiln_child.py"):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass
        try:
            os.rmdir(folder)
        except OSError:
            pass  # the script left files behind: keep them


def _finish(message, images, calls, started):
    seconds = time.time() - started
    footer = f"[{calls} tool call(s), {seconds:.1f} s]"
    if "failed" in message:
        printed = message.get("failed", "")
        raise ScriptError(_clip(f"{printed}\n{message.get('traceback', '')}".strip()) + f"\n{footer}")
    text = message.get("done", "")
    if "result" in message:
        text += ("\n" if text else "") + f"result = {message['result']}"
    text = _clip(text.strip() or "ok") + f"\n{footer}"
    return (text, *images[-MAX_IMAGES:]) if images else text


DESCRIPTION = ("Run a Python script that calls these tools as kiln.<tool>(**args) (e.g. kiln.add_object(kind='CUBE'), "
               "kiln.generate(...), kiln.run_python(code=...)): many steps in one call. Results are Python values; "
               "a failed tool raises KilnError. Only print() output, `result` and the last screenshots come back. "
               "No bpy in the script itself.")
