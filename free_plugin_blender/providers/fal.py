"""fal.ai queue API: one key, many models (Seedream, Kling, Veo, Flux…).

Docs: https://fal.ai/docs/documentation/model-apis/inference/queue
File inputs accept Base64 data URIs, so nothing has to be uploaded first.
"""

from __future__ import annotations

import time

from ..net import ApiError, request_json

QUEUE = "https://queue.fal.run"

# Defaults, overridable in the add-on preferences.
IMAGE_MODEL = "fal-ai/bytedance/seedream/v4.5/text-to-image"
EDIT_MODEL = "fal-ai/bytedance/seedream/v4.5/edit"
VIDEO_T2V_MODEL = "fal-ai/kling-video/v3/pro/text-to-video"
VIDEO_I2V_MODEL = "fal-ai/kling-video/v3/pro/image-to-video"


# 3D generators, all billed per request on fal.ai (prices from fal.ai, October 2026).
# A model without a "text" endpoint is fed an image generated first from the prompt.
MODELS_3D = {
    "TRELLIS": {
        "label": "TRELLIS", "cost": "≈ $0.02",
        "image": "fal-ai/trellis", "image_field": "image_url",
    },
    "TRELLIS2": {
        "label": "TRELLIS 2", "cost": "≈ $0.30",
        "image": "fal-ai/trellis-2", "image_field": "image_url",
    },
    "TRIPO": {
        "label": "Tripo H3.1", "cost": "≈ $0.30",
        "text": "tripo3d/h3.1/text-to-3d", "image": "tripo3d/h3.1/image-to-3d",
        "image_field": "image_url", "pbr_field": "pbr",
    },
    "HUNYUAN": {
        "label": "Hunyuan3D 3.1 Pro", "cost": "≈ $0.38 (+$0.15 PBR)",
        "text": "fal-ai/hunyuan-3d/v3.1/pro/text-to-3d", "image": "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d",
        "image_field": "input_image_url", "pbr_field": "enable_pbr",
    },
}
RIG_MODEL = "fal-ai/meshy/rigging"  # ≈ $0.20, returns walk/run clips too

# Turns a prompt into a clean reference picture for image-only 3D models.
OBJECT_REFERENCE_SUFFIX = (
    ", single object, centered, full view, three-quarter angle, plain white background, "
    "soft even studio lighting, no shadows, 3D asset reference"
)


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


def image_payload(prompt, image_size, reference_uris=()):
    payload = {"prompt": prompt, "image_size": image_size, "num_images": 1}
    if reference_uris:
        payload["image_urls"] = list(reference_uris)
    return payload


def video_payload(model_id, prompt, duration, aspect_ratio, audio, start_image_uri=None):
    payload = {"prompt": prompt, "duration": str(duration), "generate_audio": audio}
    if start_image_uri:
        # Kling v3 names the field `start_image_url`; most other fal video models `image_url`.
        field = "start_image_url" if "kling-video/v3" in model_id else "image_url"
        payload[field] = start_image_uri
    else:
        payload["aspect_ratio"] = aspect_ratio
    return payload


def first_image_url(result):
    images = result.get("images") or []
    if not images:
        raise ApiError(f"fal.ai returned no image: {str(result)[:300]}")
    return images[0]["url"]


def model_3d_payload(spec, *, prompt=None, image_uri=None, pbr=True):
    payload = {spec["image_field"]: image_uri} if image_uri else {"prompt": prompt}
    if "pbr_field" in spec:
        payload[spec["pbr_field"]] = pbr
    return payload


def glb_url(result):
    """The GLB link; 3D models on fal name it differently."""
    urls = result.get("model_urls") or {}
    candidates = [(result.get("model_glb") or {}).get("url"),
                  (urls.get("glb") or {}).get("url"),
                  (result.get("model_mesh") or {}).get("url")]
    for url in candidates:
        if url and url.split("?")[0].lower().endswith(".glb"):
            return url
    for url in candidates:
        if url:
            return url
    raise ApiError(f"fal.ai returned no 3D model: {str(result)[:300]}")


def rig_urls(result):
    """[rigged character, walking, running] GLB links (the clips may be missing)."""
    rigged = (result.get("rigged_character_glb") or {}).get("url")
    if not rigged:
        raise ApiError(f"fal.ai returned no rigged model: {str(result)[:300]}")
    clips = result.get("basic_animations") or {}
    return [rigged] + [(clips.get(name) or {}).get("url") for name in ("walking_glb", "running_glb")]


def video_url(result):
    video = result.get("video") or {}
    if not video.get("url"):
        raise ApiError(f"fal.ai returned no video: {str(result)[:300]}")
    return video["url"]
