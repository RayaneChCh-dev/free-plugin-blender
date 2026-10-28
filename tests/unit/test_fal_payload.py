import pytest
from fpb.net import ApiError
from fpb.providers import fal

SCHEMA = {"id": "m", "prompt_field": "prompt", "image_field": "image_urls", "image_list": True,
          "fields": [{"name": "image_size", "kind": "ENUM", "options": ["square_hd", "landscape_16_9"]}]}


def test_payload_puts_prompt_and_images_in_model_fields():
    payload = fal.build_payload(SCHEMA, {"seed": 3}, prompt="riad", image_uris=["data:a"])
    assert payload == {"seed": 3, "prompt": "riad", "image_urls": ["data:a"]}


def test_single_image_field_gets_a_string():
    schema = {**SCHEMA, "image_field": "image_url", "image_list": False}
    assert fal.build_payload(schema, {}, image_uris=["data:a"])["image_url"] == "data:a"


def test_image_on_a_text_only_model_is_an_error():
    with pytest.raises(ApiError):
        fal.build_payload({**SCHEMA, "image_field": None}, {}, image_uris=["data:a"])


def test_square_options_uses_whatever_the_model_calls_it():
    assert fal.square_options(SCHEMA, {})["image_size"] == "square_hd"
    ratio = {"fields": [{"name": "aspect_ratio", "options": ["16:9", "1:1"]}]}
    assert fal.square_options(ratio, {}) == {"aspect_ratio": "1:1"}
    assert fal.square_options({"fields": []}, {"a": 1}) == {"a": 1}


def test_result_url_prefers_glb_and_finds_nested_files():
    result = {"model_mesh": {"url": "https://x/m.fbx"}, "model_urls": {"glb": {"url": "https://x/m.glb"}}}
    assert fal.result_url(result, "mesh") == "https://x/m.glb"
    assert fal.result_url({"images": [{"url": "https://x/i.png"}]}, "image") == "https://x/i.png"
    assert fal.result_url({"video": {"url": "https://x/v", "content_type": "video/mp4"}}, "video") == "https://x/v"
    with pytest.raises(ApiError):
        fal.result_url({"seed": 1}, "image")


def test_extension_from_url():
    assert fal.extension("https://x/a.GLB?sig=1", "mesh") == "glb"
    assert fal.extension("https://x/noext", "video") == "mp4"


def test_rig_urls():
    result = {"rigged_character_glb": {"url": "r"}, "basic_animations": {"walking_glb": {"url": "w"}}}
    assert fal.rig_urls(result) == ["r", "w", None]


def test_run_without_key_fails_fast():
    with pytest.raises(ApiError, match="fal.ai key"):
        fal.run("m", {}, "")
