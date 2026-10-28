import time

import pytest
from fpb.mcpserver import script
from fpb.mcpserver.protocol import Image, ToolError


class Tools:
    """A fake `call`: records the calls, like the MCP package's call_tool."""

    def __init__(self):
        self.calls, self.objects = [], []

    def __call__(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "add_object":
            self.objects.append(arguments.get("name", f"obj{len(self.objects)}"))
            return f"added {self.objects[-1]}"
        if name == "scene_summary":
            return {"objects": list(self.objects)}
        if name == "screenshot":
            return "camera 64x36", Image("AAAA")
        if name == "task_status":
            return [{"id": "t1", "state": "done" if len(self.calls) > 3 else "running"}]
        raise ToolError(f"No object named {arguments.get('name')!r}")


def test_many_calls_in_one_run_only_prints_return():
    tools = Tools()
    text = script.run("for i in range(25):\n    kiln.add_object(kind='CUBE', name=f'c{i}')\n"
                      "print(len(kiln.scene_summary()['objects']))", tools)
    assert len(tools.calls) == 26 and tools.calls[0] == ("add_object", {"kind": "CUBE", "name": "c0"})
    assert text.splitlines()[0] == "25" and "added" not in text and "[26 tool call(s)" in text


def test_polling_loop_and_result():
    tools = Tools()
    text = script.run("import time\nwhile kiln.task_status(id='t1')[0]['state'] == 'running':\n"
                      "    time.sleep(0.01)\nresult = 'ready'", tools)
    assert "result = 'ready'" in text and len(tools.calls) == 4


def test_tool_error_is_catchable_and_finally_runs():
    tools = Tools()
    text = script.run("try:\n    kiln.edit_object(name='Nope')\nexcept KilnError as e:\n    print('caught', e)\n"
                      "finally:\n    print('cleanup')", tools)
    assert "caught No object named 'Nope'" in text and "cleanup" in text


def test_uncaught_error_returns_output_and_traceback():
    with pytest.raises(script.ScriptError) as error:
        script.run("print('before')\nkiln.edit_object(name='Nope')", Tools())
    assert "before" in str(error.value) and "KilnError" in str(error.value)


def test_screenshots_come_back_as_images():
    value = script.run("print(kiln.screenshot(source='camera'))", Tools())
    assert isinstance(value, tuple) and value[0].startswith("camera 64x36") and isinstance(value[1], Image)


def test_nested_run_script_refused():
    text = script.run("try:\n    kiln.run_script(code='1')\nexcept KilnError as e:\n    print(e)", Tools())
    assert "cannot be called from a script" in text


def test_timeout_kills_the_script():
    started = time.time()
    with pytest.raises(script.ScriptError, match="timeout"):
        script.run("while True:\n    pass", Tools(), timeout=1)
    assert time.time() - started < 5


def test_isolated_child_and_folder_removed(tmp_path):
    text = script.run("import os, sys\nprint(sys.flags.isolated, os.path.basename(os.getcwd()).startswith('kiln-'))",
                      Tools())
    assert text.startswith("1 True")
