"""A fal.ai model's input schema, reduced to the fields a panel can show.

fal publishes an OpenAPI document per endpoint:
    https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>
`extract()` turns it into plain JSON (bundled under data/schemas/, cached for
custom models) so the UI is built from what the model actually accepts.
"""

from __future__ import annotations

import re
import urllib.parse

from ..net import ApiError, request_json

OPENAPI_URL = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id={}"

# Handled by the plugin itself, never shown as options.
_HIDDEN = {"sync_mode", "enable_safety_checker", "num_images", "max_images", "prompt"}
_IMAGE_ROLE_PREFERENCE = ("image_urls", "image_url", "start_image_url", "input_image_url")


def safe_name(endpoint_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "_", endpoint_id) + ".json"


def fetch(endpoint_id: str) -> dict:
    url = OPENAPI_URL.format(urllib.parse.quote(endpoint_id, safe="/"))
    try:
        return extract(endpoint_id, request_json("GET", url, timeout=30))
    except ApiError as error:
        if "HTTP 404" in str(error):
            raise ApiError(f"Unknown fal.ai model {endpoint_id!r}") from None
        raise


def _input_schema(openapi: dict) -> dict:
    schemas = openapi["components"]["schemas"]
    post = next(item["post"] for item in openapi["paths"].values() if "post" in item)
    ref = post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    return schemas[ref.rsplit("/", 1)[-1]]


def _flatten(spec: dict) -> dict:
    """Collapse `anyOf: [X, null]` and `anyOf: [object, enum]` to the usable branch."""
    branches = [b for b in spec.get("anyOf", []) if b.get("type") != "null"]
    if not branches:
        return spec
    chosen = next((b for b in branches if "enum" in b), None) or branches[0]
    merged = {k: v for k, v in spec.items() if k != "anyOf"}
    merged.update(chosen)
    return merged


def _field(name: str, raw: dict) -> dict | None:
    spec = _flatten(raw)
    if "$ref" in spec or spec.get("type") in {"array", "object"} or name.endswith(("_url", "_urls")):
        return None
    if "enum" in spec:
        kind = "ENUM"
    else:
        kind = {"boolean": "BOOL", "integer": "INT", "number": "FLOAT", "string": "STRING"}.get(spec.get("type"))
    if kind is None:
        return None
    field = {
        "name": name,
        "title": raw.get("title") or name.replace("_", " ").title(),
        "kind": kind,
        "description": (raw.get("description") or spec.get("description") or "")[:300],
    }
    if kind == "ENUM":
        field["options"] = list(spec["enum"])
    for key in ("minimum", "maximum"):
        if key in spec:
            field[key] = spec[key]
    default = raw.get("default", spec.get("default"))
    representable = kind != "ENUM" or default in field["options"]
    if default is not None and representable and not isinstance(default, (dict, list)):
        field["default"] = default
    return field


def extract(endpoint_id: str, openapi: dict) -> dict:
    schema = _input_schema(openapi)
    properties = schema.get("properties", {})
    order = schema.get("x-fal-order-properties") or list(properties)
    image_fields = [n for n in order if n.endswith(("image_url", "image_urls"))]
    required = schema.get("required") or []
    image_field = next((n for n in _IMAGE_ROLE_PREFERENCE if n in properties), None)
    if image_field is None:
        image_field = next((n for n in image_fields if n in required), image_fields[0] if image_fields else None)
    fields = [f for n in order if n in properties and n not in _HIDDEN and (f := _field(n, properties[n]))]
    return {
        "id": endpoint_id,
        "prompt_field": "prompt" if "prompt" in properties else None,
        "image_field": image_field,
        "image_list": bool(image_field) and _flatten(properties[image_field]).get("type") == "array",
        "fields": fields,
    }
