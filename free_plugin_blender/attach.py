"""Images sent along with a chat message, in each provider's format. No bpy.

Claude Code takes them on stdin with `--input-format stream-json` (one JSON line per
user message, Anthropic content blocks); the API-key providers take OpenAI-style
`image_url` parts with a data URI.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def encode(path) -> tuple[str, str]:
    """(media type, base64 data) of an image file."""
    path = Path(path)
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(f"Not an image Claude can read: {path.name}")
    return media_type, base64.b64encode(path.read_bytes()).decode("ascii")


def claude_stdin(text, images) -> str:
    """The stdin line for `claude -p --input-format stream-json`: the text, then the images."""
    content = [{"type": "text", "text": text}]
    for path in images:
        media_type, data = encode(path)
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def openai_content(text, images) -> list:
    """An OpenAI-format user content list: the text, then each image as a data URI."""
    content = [{"type": "text", "text": text}]
    for path in images:
        media_type, data = encode(path)
        content.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}})
    return content


def shown(text, images) -> str:
    """What the conversation shows for the message: the text and the attached file names."""
    names = ", ".join(Path(p).name for p in images)
    return f"{text}\n\nAttached: {names}" if names else text
