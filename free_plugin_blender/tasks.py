"""Background jobs: network on a worker thread, scene changes on the main thread.

`run()` starts the worker; whatever `on_done` does to the scene is queued and
executed by a `bpy.app.timers` pump, because bpy is not thread-safe.

The task list is mirrored as JSON into `window_manager["free_plugin_tasks"]`
so an MCP client (Claude Code) can poll the outcome of an operator it called:

    import json, bpy
    json.loads(bpy.context.window_manager.get("free_plugin_tasks", "[]"))
"""

from __future__ import annotations

import json
import queue
import threading
import time
import traceback

import bpy

_main_thread_queue: queue.SimpleQueue = queue.SimpleQueue()
TASKS: list["Task"] = []
_MAX_TASKS = 20


class Task:
    def __init__(self, label):
        self.id = f"{int(time.time() * 1000):x}"
        self.label = label
        self.state = "running"
        self.detail = "starting…"
        self.result = None
        self.started = time.time()

    def set(self, detail):
        self.detail = detail

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "state": self.state,
            "detail": self.detail,
            "result": self.result,
            "seconds": round(time.time() - self.started),
        }


def run(label, work, on_done=None) -> Task:
    """Run `work(task)` off the main thread, then `on_done(task, value)` on it."""
    task = Task(label)
    TASKS.insert(0, task)
    del TASKS[_MAX_TASKS:]

    def target():
        try:
            value = work(task)
        except Exception as error:  # noqa: BLE001 - surfaced in the UI
            traceback.print_exc()
            task.state, task.detail = "error", str(error)
            return
        _main_thread_queue.put((task, on_done, value))

    threading.Thread(target=target, name=f"free-plugin:{label}", daemon=True).start()
    return task


def _finish(task, on_done, value):
    try:
        result = on_done(task, value) if on_done else value
    except Exception as error:  # noqa: BLE001
        traceback.print_exc()
        task.state, task.detail = "error", f"Import failed: {error}"
        return
    task.state = "done"
    task.result = result if isinstance(result, (str, int, float, list, dict)) else str(result)
    task.detail = "done"


def _pump():
    while True:
        try:
            item = _main_thread_queue.get_nowait()
        except queue.Empty:
            break
        _finish(*item)
    wm = bpy.context.window_manager
    if wm is not None:
        wm["free_plugin_tasks"] = json.dumps([t.as_dict() for t in TASKS])
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type in {"VIEW_3D", "SEQUENCE_EDITOR", "IMAGE_EDITOR"}:
                    area.tag_redraw()
    return 0.5 if any(t.state == "running" for t in TASKS) else 1.0


def register():
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=0.5, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
