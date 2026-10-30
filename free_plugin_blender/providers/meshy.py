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
SMART_TOPOLOGY = "smart-topology"
SMART_MODEL = "meshy-t2.5"  # Smart Topology refuses the default ai_model.
SMART_MAX_POLYCOUNT = 30_000


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


def geometry(options) -> dict:
    """Mesh fields for the chosen settings, within what Meshy accepts together.

    Smart Topology builds the mesh at the target directly and is triangles only (quad is a
    400); on Standard, topology and polycount only apply to a remesh, so they ask for one.
    """
    topology, polycount = options.get("topology"), options.get("target_polycount")
    if options.get("model_type") == SMART_TOPOLOGY:
        payload = {"model_type": SMART_TOPOLOGY, "ai_model": SMART_MODEL}
        if polycount:
            payload["target_polycount"] = min(polycount, SMART_MAX_POLYCOUNT)
        return payload
    payload = {"model_type": options["model_type"]} if "model_type" in options else {}
    if topology or polycount:
        payload["should_remesh"] = True
    if topology:
        payload["topology"] = topology
    if polycount:
        payload["target_polycount"] = polycount
    return payload


def text_to_3d(prompt, key, *, options=None, progress=None) -> dict:
    """options: from controls.resolve. Mode "preview" stops at the untextured mesh."""
    options = options or {}
    preview = {"mode": "preview", "prompt": prompt, "target_formats": ["glb"], **geometry(options)}
    preview_id = create(TEXT_TO_3D, preview, key)
    task = wait(TEXT_TO_3D, preview_id, key, progress)
    if options.get("mode") == "preview":
        return task
    refine_id = create(
        TEXT_TO_3D,
        {"mode": "refine", "preview_task_id": preview_id, "enable_pbr": options.get("enable_pbr", True),
         "target_formats": ["glb"]},
        key,
    )
    return wait(TEXT_TO_3D, refine_id, key, progress)


def image_to_3d(image_uri, key, *, options=None, progress=None) -> dict:
    options = options or {}
    texture = options.get("mode") != "preview"
    payload = {"image_url": image_uri, "should_texture": texture, "target_formats": ["glb"], **geometry(options)}
    if texture:
        payload["enable_pbr"] = options.get("enable_pbr", True)
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
