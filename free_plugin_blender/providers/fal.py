"""fal.ai queue API: one key, many models (Seedream, Kling, Veo, TRELLIS…).

Docs: https://fal.ai/docs/documentation/model-apis/inference/queue
File inputs accept Base64 data URIs, so nothing has to be uploaded first.
Which fields a model takes comes from its schema (see `fal_schema.py`).
"""

from __future__ import annotations

import time

from ..net import ApiError, request_json

QUEUE = "https://queue.fal.run"
RIG_MODEL = "fal-ai/meshy/rigging"  # ≈ $0.20, returns walk/run clips too
MOTION_MODEL = "fal-ai/hunyuan-motion"  # ≈ $0.08, text → SMPL-H skeleton motion (FBX)

# Turns a prompt into a clean reference picture for image-only 3D models.
OBJECT_REFERENCE_SUFFIX = (
    ", single object, centered, full view, three-quarter angle, plain white background, "
    "soft even studio lighting, no shadows, 3D asset reference"
)

_EXTENSIONS = {
    "image": (".png", ".jpg", ".jpeg", ".webp"),
    "video": (".mp4", ".mov", ".webm"),
    "mesh": (".glb", ".gltf", ".fbx", ".obj", ".usdz"),
}


def run(model_id, payload, key, progress=None, timeout=1800):
    if not key:
        raise ApiError("No fal.ai key: set it in Preferences > Add-ons > Free Plugin Blender, or FAL_KEY")
    headers = {"Authorization": f"Key {key}"}
    submitted = request_json("POST", f"{QUEUE}/{model_id.strip('/')}", headers=headers, body=payload)
    status_url, response_url = submitted["status_url"], submitted["response_url"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = request_json("GET", status_url, headers=headers)
        state = status.get("status")
        if state == "COMPLETED":
            if status.get("error"):
                raise ApiError(f"fal.ai: {status['error']}")
            return request_json("GET", response_url, headers=headers, timeout=120)
        if progress:
            position = status.get("queue_position")
            progress("in queue" + (f" (#{position})" if position is not None else "")
                     if state == "IN_QUEUE" else "running on fal.ai…")
        time.sleep(2.0)
    raise ApiError(f"fal.ai: timed out after {timeout}s")


def build_payload(schema, options, *, prompt=None, image_uris=()):
    """Options the user set, plus the prompt and input images in the model's own field names."""
    schema = schema or {"prompt_field": "prompt", "image_field": "image_url", "image_list": False}
    payload = dict(options)
    if prompt and schema.get("prompt_field"):
        payload[schema["prompt_field"]] = prompt
    if image_uris:
        field = schema.get("image_field")
        if not field:
            raise ApiError(f"{schema.get('id', 'This model')} does not take an input image")
        payload[field] = list(image_uris) if schema.get("image_list") else image_uris[0]
    return payload


def square_options(schema, options):
    """Ask for a square picture whatever the model calls it (textures, 3D references)."""
    fields = {f["name"]: f for f in (schema or {}).get("fields", [])}
    for name, wanted in (("image_size", "square_hd"), ("aspect_ratio", "1:1")):
        if wanted in fields.get(name, {}).get("options", []):
            return {**options, name: wanted}
    return options


def _files(value):
    if isinstance(value, dict):
        if isinstance(value.get("url"), str):
            yield value
        for child in value.values():
            yield from _files(child)
    elif isinstance(value, list):
        for child in value:
            yield from _files(child)


def result_url(result, kind):
    """The first output file of `kind` (image / video / mesh), GLB preferred for meshes."""
    files = list(_files(result))
    def matches(f, extensions):
        name = (f.get("file_name") or f["url"].split("?")[0]).lower()
        return name.endswith(extensions) or (f.get("content_type") or "").startswith(kind)
    if kind == "mesh":
        for preferred in ((".glb",), _EXTENSIONS["mesh"]):
            hit = next((f for f in files if matches(f, preferred)), None)
            if hit:
                return hit["url"]
    else:
        hit = next((f for f in files if matches(f, _EXTENSIONS[kind])), None)
        if hit:
            return hit["url"]
    raise ApiError(f"fal.ai returned no {kind}: {str(result)[:300]}")


def extension(url, kind):
    name = url.split("?")[0].lower()
    return next((ext.lstrip(".") for ext in _EXTENSIONS[kind] if name.endswith(ext)), _EXTENSIONS[kind][0].lstrip("."))


def rig_urls(result):
    """[rigged character, walking, running] GLB links (the clips may be missing)."""
    rigged = (result.get("rigged_character_glb") or {}).get("url")
    if not rigged:
        raise ApiError(f"fal.ai returned no rigged model: {str(result)[:300]}")
    clips = result.get("basic_animations") or {}
    return [rigged] + [(clips.get(name) or {}).get("url") for name in ("walking_glb", "running_glb")]


def animation_url(result):
    """The animated character GLB of a rigging call made with `enable_animation`."""
    url = (result.get("animation_glb") or {}).get("url")
    if not url:
        raise ApiError(f"fal.ai returned no animation: {str(result)[:300]}")
    return url


def motion_url(result):
    """The FBX of a Hunyuan Motion call."""
    url = (result.get("fbx_file") or {}).get("url")
    if not url:
        raise ApiError(f"fal.ai returned no motion file: {str(result)[:300]}")
    return url
