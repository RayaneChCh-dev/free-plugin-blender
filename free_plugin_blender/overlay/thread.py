"""The conversation as display items: tool calls grouped, one avatar per answer. No bpy.

Claude's tool calls are noise once they are done, so consecutive ones become a
single "N actions" item that can be expanded. The Claude avatar is drawn once per
answer: on its first item after the user's message.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Item:
    kind: str  # "user" | "assistant" | "tools" | "info" | "error"
    text: str = ""
    tools: list = field(default_factory=list)  # tool lines of a "tools" item
    failed: int = 0
    avatar: bool = False  # first item of an answer
    key: int = 0  # index of the first message: stable id for expanding a group


def items(messages):
    found: list[Item] = []
    in_answer = False
    for index, message in enumerate(messages):
        role, text = message.get("role", ""), message.get("text", "")
        if role == "user":
            found.append(Item("user", text, key=index))
            in_answer = False
            continue
        if role == "tool":
            last = found[-1] if found else None
            if last is None or last.kind != "tools":
                last = Item("tools", key=index, avatar=not in_answer)
                found.append(last)
            if text.startswith("failed:"):
                last.failed += 1
                last.tools.append(text)
            else:
                last.tools.append(text)
        else:
            found.append(Item(role if role in ("assistant", "info", "error") else "info", text,
                              key=index, avatar=role == "assistant" and not in_answer))
        if role in ("assistant", "tool"):
            in_answer = True
    return found


def tool_name(line):
    """`mcp__blender__execute_blender_code: x = 1` → "execute_blender_code"."""
    return line.split(":", 1)[0].split("__")[-1].strip()


def summary(item, limit=4):
    """"3 actions", and the tools used, e.g. "execute_blender_code ×2 · polyhaven_search"."""
    calls = [t for t in item.tools if not t.startswith("failed:")]
    names: dict[str, int] = {}
    for line in calls:
        names[tool_name(line)] = names.get(tool_name(line), 0) + 1
    parts = [f"{name} ×{count}" if count > 1 else name for name, count in names.items()]
    if len(parts) > limit:
        parts = parts[:limit] + [f"+{len(parts) - limit}"]
    count = len(calls)
    head = f"{count} action" + ("s" if count != 1 else "")
    if item.failed:
        head += f", {item.failed} failed"
    return head, " · ".join(parts)
