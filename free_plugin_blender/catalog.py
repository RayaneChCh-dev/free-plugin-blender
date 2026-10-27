"""The model catalog: bundled data/models.json + the user's own models.json.

No bpy here. `configure()` is given the user folder once at register time;
everything else is a lookup.
"""

from __future__ import annotations

import json
from pathlib import Path

from .providers import fal_schema

SLOTS = ("image", "video", "mesh")
CUSTOM = "CUSTOM"

_DATA = Path(__file__).with_name("data")
_user_dir: Path | None = None
_models: dict[str, list[dict]] = {}
_schemas: dict[str, dict] = {}

USER_TEMPLATE = {
    "_comment": "Your own models. Same format as the bundled catalog; a matching key replaces a bundled entry.",
    "image": [],
    "video": [],
    "mesh": [],
}


def configure(user_dir: Path):
    global _user_dir
    _user_dir = user_dir
    reload()


def user_catalog_path() -> Path:
    path = _user_dir / "models.json"
    if not path.exists():
        path.write_text(json.dumps(USER_TEMPLATE, indent=2))
    return path


def reload():
    _models.clear()
    _schemas.clear()
    bundled = json.loads((_DATA / "models.json").read_text())
    user = {}
    if _user_dir is not None and (_user_dir / "models.json").exists():
        try:
            user = json.loads((_user_dir / "models.json").read_text())
        except ValueError as error:
            print(f"free-plugin-blender: ignoring invalid models.json: {error}")
    for slot in SLOTS:
        entries = {e["key"]: e for e in bundled.get(slot, [])}
        for entry in user.get(slot, []):
            if "key" in entry and ("text" in entry or "image" in entry or entry.get("provider")):
                entries[entry["key"]] = entry
        _models[slot] = list(entries.values())


def models(slot) -> list[dict]:
    return _models.get(slot, [])


def get(slot, key) -> dict | None:
    return next((e for e in models(slot) if e["key"] == key), None)


def custom_entry(endpoint_id: str) -> dict:
    """A one-off entry for any fal id; text or image role comes from its schema."""
    return {"key": CUSTOM, "label": endpoint_id, "cost": "", "text": endpoint_id, "image": endpoint_id}


def endpoint(entry: dict, with_image: bool) -> str | None:
    """The endpoint to call. Image-only models also serve text, through a reference image."""
    if entry.get("provider"):
        return None
    if with_image:
        return entry.get("image")
    return entry.get("text") or entry.get("image")


def cached_schema(endpoint_id: str) -> dict | None:
    if endpoint_id in _schemas:
        return _schemas[endpoint_id]
    for folder in (_DATA / "schemas", (_user_dir / "schemas") if _user_dir else None):
        if folder is not None and (folder / fal_schema.safe_name(endpoint_id)).exists():
            schema = json.loads((folder / fal_schema.safe_name(endpoint_id)).read_text())
            _schemas[endpoint_id] = schema
            return schema
    return None


def fetch_schema(endpoint_id: str) -> dict:
    """Network: run off the main thread. Stores the result in the user cache."""
    schema = fal_schema.fetch(endpoint_id)
    if _user_dir is not None:
        folder = _user_dir / "schemas"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / fal_schema.safe_name(endpoint_id)).write_text(json.dumps(schema, indent=1))
    _schemas[endpoint_id] = schema
    return schema


def clear_schema_cache():
    _schemas.clear()
    if _user_dir is not None:
        for path in (_user_dir / "schemas").glob("*.json") if (_user_dir / "schemas").exists() else ():
            path.unlink()
