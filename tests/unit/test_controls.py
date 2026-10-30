import json
from pathlib import Path

import pytest
from fpb import controls

SCHEMAS = Path(__file__).resolve().parents[2] / "free_plugin_blender" / "data" / "schemas"
CATALOG = json.loads((SCHEMAS.parent / "models.json").read_text())


def schema(name):
    return json.loads((SCHEMAS / f"{name}.json").read_text())


def entry(slot, key):
    return next(e for e in CATALOG[slot] if e["key"] == key)


def choices_of(slot, key, schema_name, model_entry=None):
    control = next(c for c in controls.controls(slot) if c.key == key)
    return [v for v, _ in control.choices(controls.fields_of(schema(schema_name)), model_entry or {})]


# --- image --------------------------------------------------------------------------------

def test_ratio_maps_to_each_models_own_field():
    nano = controls.resolve("image", {"aspect": "16:9"}, schema("fal-ai_nano-banana"), {})
    flux = controls.resolve("image", {"aspect": "16:9"}, schema("fal-ai_flux-2"), {})
    assert nano == {"aspect_ratio": "16:9"}
    assert flux == {"image_size": "landscape_16_9"}
    assert "21:9" not in choices_of("image", "aspect", "fal-ai_flux-2")  # FLUX has no 21:9 preset
    assert "21:9" in choices_of("image", "aspect", "fal-ai_nano-banana")


def test_resolution_direct_or_as_a_size_object():
    pro = controls.resolve("image", {"resolution": "4K"}, schema("fal-ai_nano-banana-pro"), {})
    assert pro == {"resolution": "4K"}
    seedream = entry("image", "seedream45")
    options = controls.resolve("image", {"aspect": "16:9", "resolution": "4K"},
                               schema("fal-ai_bytedance_seedream_v4.5_text-to-image"), seedream)
    size = options["image_size"]
    assert size["width"] > size["height"] and max(size.values()) <= 4096
    assert size["width"] % 64 == 0 and size["height"] % 64 == 0
    assert abs(size["width"] / size["height"] - 16 / 9) < 0.05
    # Seedream refuses 1K pictures: not offered
    assert choices_of("image", "resolution", "fal-ai_bytedance_seedream_v4.5_text-to-image", seedream) == ["2K", "4K"]
    assert choices_of("image", "resolution", "fal-ai_flux-2") == []  # not supported → greyed out


def test_quality_through_steps_and_format():
    flux = schema("fal-ai_flux-2")
    assert controls.resolve("image", {"quality": "high"}, flux, {}) == {"num_inference_steps": 49}
    assert controls.resolve("image", {"quality": "low"}, flux, {}) == {"num_inference_steps": 14}
    assert controls.resolve("image", {"format": "webp"}, flux, {}) == {"output_format": "webp"}
    assert choices_of("image", "quality", "fal-ai_nano-banana") == []


def test_auto_sends_nothing():
    assert controls.resolve("image", {"aspect": "auto", "quality": "auto"}, schema("fal-ai_flux-2"), {}) == {}


# --- 3D -----------------------------------------------------------------------------------

def test_meshy7_takes_every_3d_control():
    options = controls.resolve("mesh", {"mode": "preview", "model_type": "lowpoly", "topology": "quad",
                                        "detail": "high", "pbr": "on"}, schema("fal-ai_meshy_v7_text-to-3d"), {})
    assert options == {"mode": "preview", "model_type": "lowpoly", "topology": "quad",
                       "target_polycount": 100_000, "enable_pbr": True}


def test_3d_controls_on_other_models():
    hunyuan = controls.resolve("mesh", {"mode": "preview", "detail": "low", "pbr": "on"},
                               schema("fal-ai_hunyuan-3d_v3.1_pro_text-to-3d"), {})
    assert hunyuan == {"generate_type": "Geometry", "face_count": 40_000, "enable_pbr": True}
    tripo = controls.resolve("mesh", {"mode": "full", "topology": "quad", "texture": "hd"},
                             schema("tripo3d_h3.1_text-to-3d"), {})
    assert tripo == {"texture": True, "quad": True, "texture_quality": "detailed"}
    trellis2 = controls.resolve("mesh", {"texture": "hd", "detail": "medium"}, schema("fal-ai_trellis-2"), {})
    assert trellis2 == {"texture_size": 4096, "decimation_target": 100_000}
    assert choices_of("mesh", "model_type", "fal-ai_trellis") == []
    assert choices_of("mesh", "mode", "fal-ai_trellis") == []


def test_detail_is_clamped_to_the_model_range():
    fields = {"face_count": {"name": "face_count", "kind": "INT", "minimum": 50_000, "maximum": 200_000}}
    assert controls._apply("detail", "low", fields, {}) == {"face_count": 50_000}
    assert controls._apply("detail", "high", fields, {}) == {"face_count": 200_000}


# --- video --------------------------------------------------------------------------------

def test_video_durations_and_resolutions_come_from_the_model():
    assert choices_of("video", "duration", "fal-ai_veo3.1_fast") == ["4s", "6s", "8s"]
    assert choices_of("video", "duration", "fal-ai_kling-video_v2.5-turbo_pro_text-to-video") == ["5", "10"]
    assert choices_of("video", "resolution", "fal-ai_minimax_hailuo-02_standard_image-to-video") == ["512P", "768P"]
    veo = controls.resolve("video", {"duration": "6s", "resolution": "1080p", "audio": "off", "aspect": "9:16"},
                           schema("fal-ai_veo3.1_fast"), {})
    assert veo == {"duration": "6s", "resolution": "1080p", "generate_audio": False, "aspect_ratio": "9:16"}


def test_a_value_the_new_model_lacks_is_dropped():
    # 15 s is fine on Kling 3, not on Kling 2.5 Turbo: nothing is sent instead of an invalid value
    assert controls.resolve("video", {"duration": "15"},
                            schema("fal-ai_kling-video_v2.5-turbo_pro_text-to-video"), {}) == {}


@pytest.mark.parametrize("path", sorted(SCHEMAS.glob("*.json")), ids=lambda p: p.stem)
def test_every_bundled_model_resolves_without_error(path):
    data = json.loads(path.read_text())
    for slot in controls.CONTROLS:
        for control in controls.controls(slot):
            for value, _label in control.choices(controls.fields_of(data), {"size_object": True}):
                controls.resolve(slot, {control.key: value}, data, {"size_object": True})


def test_meshy_own_key_settings_come_from_its_catalog_fields():
    meshy = entry("mesh", "meshy")
    options = controls.resolve("mesh", {"mode": "preview", "model_type": "smart-topology", "topology": "quad",
                                        "detail": "low", "pbr": "off"}, meshy, meshy)
    assert options == {"mode": "preview", "model_type": "smart-topology", "topology": "quad",
                       "target_polycount": 5_000, "enable_pbr": False}
    assert controls.resolve("mesh", {"model_type": "lowpoly"}, meshy, meshy) == {}
