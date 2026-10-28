"""Simple generation controls (ratio, resolution, quality, mode…) mapped onto each model's own fields.

Every model names things differently: a 16:9 picture is `aspect_ratio: "16:9"` on Nano
Banana, `image_size: "landscape_16_9"` on FLUX and a `{width, height}` object on Seedream.
A control here offers the choices the current model can take, read from its schema,
and `resolve()` turns the user's choices into that model's options. "auto" always
means: send nothing, keep the model's default. No bpy.
"""

from __future__ import annotations

import math

AUTO = "auto"

_IMAGE_SIZE_OF_RATIO = {
    "1:1": "square_hd", "16:9": "landscape_16_9", "9:16": "portrait_16_9",
    "4:3": "landscape_4_3", "3:4": "portrait_4_3",
}
_LONG_SIDE = {"1K": 1024, "2K": 2048, "4K": 4096}
# Polygon targets for Low / Medium / High detail, per field name.
_DETAIL = {
    "target_polycount": (5_000, 30_000, 100_000),
    "face_limit": (5_000, 30_000, 100_000),
    "face_count": (40_000, 300_000, 1_000_000),
    "decimation_target": (20_000, 100_000, 500_000),
}


class Control:
    def __init__(self, key, label, choices=(), description=""):
        self.key, self.label, self.description = key, label, description
        self.static_choices = list(choices)  # (value, label)

    def choices(self, fields, entry):
        """Supported (value, label) pairs for this model, without "auto"; empty = not supported."""
        return [(value, label) for value, label in self.static_choices if _apply(self.key, value, fields, entry)]


class _DynamicControl(Control):
    """Choices are the model's own enum values (durations, video resolutions)."""

    def __init__(self, key, label, field, unit="", description=""):
        super().__init__(key, label, description=description)
        self.field, self.unit = field, unit

    def choices(self, fields, entry):
        options = fields.get(self.field, {}).get("options") or []
        return [(str(v), f"{str(v).rstrip('s')} {self.unit}".strip() if self.unit else str(v))
                for v in options if str(v) != AUTO]


CONTROLS = {
    "image": [
        Control("aspect", "Ratio", [(r, r) for r in ("1:1", "16:9", "9:16", "4:3", "3:4", "21:9")],
                "Shape of the picture"),
        Control("resolution", "Resolution", [("1K", "1K"), ("2K", "2K"), ("4K", "4K")],
                "Size of the picture (longest side about 1024, 2048 or 4096 px)"),
        Control("quality", "Quality", [("low", "Low"), ("medium", "Medium"), ("high", "High")],
                "Higher is slower and sometimes costs more"),
        Control("format", "Format", [("png", "PNG"), ("jpeg", "JPEG"), ("webp", "WebP")], "File format"),
    ],
    "mesh": [
        Control("mode", "Mode", [("preview", "Preview"), ("full", "Full")],
                "Preview: shape only, no texture (faster, cheaper when the model charges less). Full: textured"),
        Control("model_type", "Type", [("standard", "Standard"), ("lowpoly", "Low-poly"),
                                       ("smart-topology", "Smart topology")], "Kind of mesh"),
        Control("topology", "Topology", [("triangle", "Triangles"), ("quad", "Quads")],
                "Quads are easier to edit and subdivide"),
        Control("detail", "Detail", [("low", "Low"), ("medium", "Medium"), ("high", "High")],
                "Polygon count: Low for games, High for close-ups"),
        Control("pbr", "PBR", [("on", "On"), ("off", "Off")], "Metallic, roughness and normal maps"),
        Control("texture", "Texture", [("standard", "Standard"), ("hd", "HD")], "Texture resolution"),
    ],
    "video": [
        _DynamicControl("duration", "Duration", "duration", "s", "Length of the clip"),
        Control("aspect", "Ratio", [(r, r) for r in ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9")],
                "Shape of the video"),
        _DynamicControl("resolution", "Resolution", "resolution", description="Video resolution"),
        Control("audio", "Audio", [("on", "On"), ("off", "Off")], "Generate sound with the video"),
    ],
}


def controls(slot):
    return CONTROLS.get(slot, [])


def fields_of(schema):
    return {f["name"]: f for f in (schema or {}).get("fields", [])}


def _option(fields, name, value):
    """{name: value} when the field exists and accepts value (enum option, or any bool)."""
    field = fields.get(name)
    if field is None:
        return None
    if field["kind"] == "ENUM":
        match = next((o for o in field.get("options", []) if str(o).lower() == str(value).lower()), None)
        return None if match is None else {name: match}
    if field["kind"] == "BOOL" and isinstance(value, bool):
        return {name: value}
    return None


def _clamp(field, value):
    low, high = field.get("minimum", -math.inf), field.get("maximum", math.inf)
    return int(min(max(value, low), high))


def _size_for(ratio, resolution):
    """{width, height} with about resolution² pixels in the given ratio, multiples of 64, ≤ 4096."""
    width_part, height_part = (int(x) for x in ratio.split(":"))
    pixels = _LONG_SIDE[resolution] ** 2
    width = math.sqrt(pixels * width_part / height_part)
    height = pixels / width
    scale = min(1.0, 4096 / max(width, height))
    return {"width": int(width * scale) // 64 * 64, "height": int(height * scale) // 64 * 64}


def _apply(key, value, fields, entry, choices=None):
    """Options for one control choice on this model, or None when the model cannot take it."""
    if key == "aspect":
        return _option(fields, "aspect_ratio", value) or (
            _option(fields, "image_size", _IMAGE_SIZE_OF_RATIO[value]) if value in _IMAGE_SIZE_OF_RATIO else None)
    if key == "resolution" and value in _LONG_SIDE:
        direct = _option(fields, "resolution", value)
        if direct:
            return direct
        if entry.get("size_object") and "image_size" in fields and value in entry.get("resolutions", _LONG_SIDE):
            ratio = (choices or {}).get("aspect", AUTO)
            return {"image_size": _size_for(ratio if ratio != AUTO else "1:1", value)}
        return None
    if key == "resolution":  # video: the model's own values
        return _option(fields, "resolution", value)
    if key == "quality":
        direct = _option(fields, "quality", value)
        if direct:
            return direct
        steps = fields.get("num_inference_steps")
        if steps and "default" in steps:
            factor = {"low": 0.5, "medium": 1.0, "high": 1.75}[value]
            return {"num_inference_steps": _clamp(steps, round(steps["default"] * factor))}
        return None
    if key == "format":
        return _option(fields, "output_format", value)
    if key == "mode":
        full = value == "full"
        return (_option(fields, "mode", value) or _option(fields, "generate_type", "Normal" if full else "Geometry")
                or _option(fields, "should_texture", full) or _option(fields, "texture", full))
    if key == "model_type":
        return _option(fields, "model_type", value)
    if key == "topology":
        return _option(fields, "topology", value) or _option(fields, "quad", value == "quad")
    if key == "detail":
        for name, targets in _DETAIL.items():
            if name in fields:
                return {name: _clamp(fields[name], targets[("low", "medium", "high").index(value)])}
        return None
    if key == "pbr":
        return _option(fields, "enable_pbr", value == "on") or _option(fields, "pbr", value == "on")
    if key == "texture":
        size = fields.get("texture_size")
        if size and size.get("options"):
            options = size["options"]
            return {"texture_size": size.get("default", options[0]) if value == "standard" else options[-1]}
        return _option(fields, "texture_quality", "standard" if value == "standard" else "detailed")
    if key in ("duration",):
        return _option(fields, "duration", value)
    if key == "audio":
        return _option(fields, "generate_audio", value == "on")
    return None


def resolve(slot, choices: dict, schema, entry) -> dict:
    """Model options for the user's choices; unsupported or "auto" choices send nothing."""
    fields, options = fields_of(schema), {}
    for control in controls(slot):
        value = choices.get(control.key, AUTO)
        if value == AUTO:
            continue
        mapped = _apply(control.key, value, fields, entry or {}, choices)
        if mapped:
            options.update(mapped)
    return options
