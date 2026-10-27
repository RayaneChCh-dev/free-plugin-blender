"""Meshy API: text/image → 3D, retexture, rigging.

Docs: https://docs.meshy.ai/en/api — every create returns {"result": task_id},
every task is polled at GET <endpoint>/<id> until SUCCEEDED / FAILED / CANCELED.
"""

from __future__ import annotations

import time

from ..net import ApiError, request_json

BASE = "https://api.meshy.ai/openapi"
TEXT_TO_3D = "v2/text-to-3d"
IMAGE_TO_3D = "v1/image-to-3d"
RETEXTURE = "v1/retexture"
RIGGING = "v1/rigging"


def _headers(key):
    if not key:
        raise ApiError("No Meshy key: set it in Preferences > Add-ons > Free Plugin Blender, or MESHY_API_KEY")
    return {"Authorization": f"Bearer {key}"}


def create(endpoint, payload, key) -> str:
    return request_json("POST", f"{BASE}/{endpoint}", headers=_headers(key), body=payload)["result"]


def wait(endpoint, task_id, key, progress=None, timeout=1800) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = request_json("GET", f"{BASE}/{endpoint}/{task_id}", headers=_headers(key))
        status = task.get("status")
        if status == "SUCCEEDED":
            return task
        if status in {"FAILED", "CANCELED"}:
            message = (task.get("task_error") or {}).get("message") or status
            raise ApiError(f"Meshy: {message}")
        if progress:
            progress(f"Meshy {status.lower()} {task.get('progress', 0)}%")
        time.sleep(3.0)
    raise ApiError(f"Meshy: timed out after {timeout}s")


def text_to_3d(prompt, key, *, texture=True, pbr=False, progress=None) -> dict:
    preview_id = create(TEXT_TO_3D, {"mode": "preview", "prompt": prompt, "target_formats": ["glb"]}, key)
    task = wait(TEXT_TO_3D, preview_id, key, progress)
    if not texture:
        return task
    refine_id = create(
        TEXT_TO_3D,
        {"mode": "refine", "preview_task_id": preview_id, "enable_pbr": pbr, "target_formats": ["glb"]},
        key,
    )
    return wait(TEXT_TO_3D, refine_id, key, progress)


def image_to_3d(image_uri, key, *, texture=True, pbr=False, progress=None) -> dict:
    payload = {"image_url": image_uri, "should_texture": texture, "target_formats": ["glb"]}
    if texture:
        payload["enable_pbr"] = pbr
    return wait(IMAGE_TO_3D, create(IMAGE_TO_3D, payload, key), key, progress)


def retexture(key, prompt, *, input_task_id=None, model_uri=None, pbr=True, progress=None) -> dict:
    payload = {"text_style_prompt": prompt, "enable_pbr": pbr, "target_formats": ["glb"]}
    payload.update({"input_task_id": input_task_id} if input_task_id else {"model_url": model_uri})
    return wait(RETEXTURE, create(RETEXTURE, payload, key), key, progress)


def rig(key, *, input_task_id=None, model_uri=None, height_meters=1.7, progress=None) -> dict:
    payload = {"height_meters": height_meters}
    payload.update({"input_task_id": input_task_id} if input_task_id else {"model_url": model_uri})
    return wait(RIGGING, create(RIGGING, payload, key), key, progress)


def glb_url(task) -> str:
    url = (task.get("model_urls") or {}).get("glb")
    if not url:
        raise ApiError("Meshy task has no GLB output")
    return url
