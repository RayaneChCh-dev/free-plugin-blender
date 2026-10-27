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


def video_url(result):
    video = result.get("video") or {}
    if not video.get("url"):
        raise ApiError(f"fal.ai returned no video: {str(result)[:300]}")
    return video["url"]
