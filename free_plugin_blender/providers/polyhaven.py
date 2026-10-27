"""Poly Haven: free CC0 HDRIs, PBR textures and 3D models, no key needed.

API: https://api.polyhaven.com — /assets?t=<type> lists everything,
/files/<id> gives download URLs per map, resolution and format.
"""

from __future__ import annotations

from ..net import ApiError, request_json

API = "https://api.polyhaven.com"
_assets_cache: dict[str, dict] = {}

# Poly Haven map name → role in a Principled BSDF material.
TEXTURE_MAPS = {
    "Diffuse": "base_color",
    "Rough": "roughness",
    "nor_gl": "normal",
    "Displacement": "displacement",
}


def search(kind, query="", limit=40):
    """kind is "hdris", "textures" or "models". Returns [(id, name)] sorted by popularity."""
    if kind not in _assets_cache:
        _assets_cache[kind] = request_json("GET", f"{API}/assets?t={kind}")
    words = [w for w in query.lower().split() if w]
    hits = []
    for asset_id, info in _assets_cache[kind].items():
        haystack = " ".join([asset_id, info.get("name", ""), *info.get("tags", []), *info.get("categories", [])]).lower()
        if all(w in haystack for w in words):
            hits.append((info.get("download_count", 0), asset_id, info.get("name", asset_id)))
    hits.sort(reverse=True)
    return [(asset_id, name) for _count, asset_id, name in hits[:limit]]


def _pick(by_res, resolution, formats):
    res = resolution if resolution in by_res else sorted(by_res, key=lambda r: int(r[:-1]))[0]
    for fmt in formats:
        if fmt in by_res[res]:
            return by_res[res][fmt]["url"]
    return None


def hdri_url(asset_id, resolution="2k"):
    files = request_json("GET", f"{API}/files/{asset_id}")
    url = _pick(files.get("hdri", {}), resolution, ("hdr", "exr"))
    if not url:
        raise ApiError(f"No HDRI file for {asset_id}")
    return url


def model_files(asset_id, resolution="1k"):
    """(gltf url, {relative path: url}) — the .gltf needs its .bin and textures beside it."""
    files = request_json("GET", f"{API}/files/{asset_id}")
    by_res = files.get("gltf", {})
    if not by_res:
        raise ApiError(f"No glTF file for {asset_id}")
    res = resolution if resolution in by_res else sorted(by_res, key=lambda r: int(r[:-1]))[0]
    entry = by_res[res]["gltf"]
    return entry["url"], {path: info["url"] for path, info in entry.get("include", {}).items()}


def texture_urls(asset_id, resolution="2k"):
    files = request_json("GET", f"{API}/files/{asset_id}")
    maps = {}
    for name, role in TEXTURE_MAPS.items():
        if name in files:
            url = _pick(files[name], resolution, ("jpg", "png"))
            if url:
                maps[role] = url
    if "base_color" not in maps:
        raise ApiError(f"No diffuse map for {asset_id}")
    return maps
