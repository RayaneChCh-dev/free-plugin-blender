import base64
import json

import pytest
from fpb import attach

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
                       "AAAABJRU5ErkJggg==")


def test_claude_stdin_is_one_user_message_with_text_then_image(tmp_path):
    image = tmp_path / "riad.png"
    image.write_bytes(PNG)
    line = attach.claude_stdin("Build this", [image])
    assert line.endswith("\n") and line.count("\n") == 1
    event = json.loads(line)
    assert event["type"] == "user" and event["message"]["role"] == "user"
    text, picture = event["message"]["content"]
    assert text == {"type": "text", "text": "Build this"}
    assert picture["type"] == "image" and picture["source"]["media_type"] == "image/png"
    assert base64.b64decode(picture["source"]["data"]) == PNG


def test_openai_content_uses_data_uris(tmp_path):
    image = tmp_path / "dunes.jpg"
    image.write_bytes(b"\xff\xd8jpeg")
    text, picture = attach.openai_content("Build this", [image])
    assert text == {"type": "text", "text": "Build this"}
    assert picture["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_shown_names_the_files_and_refuses_non_images(tmp_path):
    assert attach.shown("Hi", []) == "Hi"
    assert attach.shown("Hi", [tmp_path / "a.png"]) == "Hi\n\nAttached: a.png"
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    with pytest.raises(ValueError):
        attach.encode(clip)
