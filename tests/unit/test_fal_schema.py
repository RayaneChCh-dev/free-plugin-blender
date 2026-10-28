import json

from conftest import FIXTURES
from fpb.providers import fal_schema


def load(name):
    return json.loads((FIXTURES / "openapi" / f"{name}.json").read_text())


def fields(schema):
    return {f["name"]: f for f in schema["fields"]}


def test_seedream_text_to_image_roles_and_options():
    schema = fal_schema.extract("x", load("fal-ai_bytedance_seedream_v4.5_text-to-image"))
    assert schema["prompt_field"] == "prompt"
    assert schema["image_field"] is None
    by_name = fields(schema)
    # anyOf[object, enum] collapses to the enum; the object default is not representable.
    assert by_name["image_size"]["kind"] == "ENUM"
    assert "square_hd" in by_name["image_size"]["options"]
    assert "default" not in by_name["image_size"]
    # nullable integer without default
    assert by_name["seed"]["kind"] == "INT" and "default" not in by_name["seed"]
    # plugin-handled fields are hidden
    assert not {"prompt", "sync_mode", "enable_safety_checker", "num_images"} & set(by_name)


def test_seedream_edit_takes_an_image_list():
    schema = fal_schema.extract("x", load("fal-ai_bytedance_seedream_v4.5_edit"))
    assert schema["image_field"] == "image_urls"
    assert schema["image_list"] is True


def test_kling_image_field_and_enum_default():
    schema = fal_schema.extract("x", load("fal-ai_kling-video_v3_pro_image-to-video"))
    assert schema["image_field"] == "start_image_url"
    assert schema["image_list"] is False
    by_name = fields(schema)
    assert by_name["duration"]["default"] == "5"
    assert "end_image_url" not in by_name  # extra file inputs are not options
    assert by_name["cfg_scale"]["kind"] == "FLOAT" and by_name["cfg_scale"]["maximum"] == 1


def test_hunyuan_input_image_field_and_int_range():
    schema = fal_schema.extract("x", load("fal-ai_hunyuan-3d_v3.1_pro_image-to-3d"))
    assert schema["image_field"] == "input_image_url"
    face = fields(schema)["face_count"]
    assert face["kind"] == "INT" and face["minimum"] == 40000 and face["default"] == 500000


def test_order_follows_fal_order_property():
    schema = fal_schema.extract("x", load("tripo3d_h3.1_text-to-3d"))
    names = [f["name"] for f in schema["fields"]]
    assert names.index("texture") < names.index("pbr") < names.index("texture_quality")


def test_safe_name_is_a_plain_filename():
    assert fal_schema.safe_name("fal-ai/kling-video/v3/pro") == "fal-ai_kling-video_v3_pro.json"
