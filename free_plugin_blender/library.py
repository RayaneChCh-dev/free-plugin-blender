"""Your generations, read back from the output folder for the Assets tab. No bpy.

Each generator saves into a sub-folder of the output folder (`images/`, `models/`…);
`scan()` lists what is there, newest first, and `KINDS` says which filter each
folder belongs to. Captures, exports and the Poly Haven download cache are not
generations and are left out.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

FILTERS = (("ALL", "All"), ("MESH", "3D"), ("ANIMATION", "Animation"), ("IMAGE", "Images"), ("VIDEO", "Video"))

# Sub-folder → (kind, what clicking it does). Kinds are the filter keys above.
KINDS = {
    "models": "MESH",
    "rigs": "MESH",
    "animations": "ANIMATION",
    "images": "IMAGE",
    "textures": "IMAGE",
    "videos": "VIDEO",
}
EXTENSIONS = {
    "MESH": {".glb", ".gltf", ".fbx", ".obj", ".usdz", ".usd"},
    "ANIMATION": {".glb", ".gltf", ".fbx"},
    "IMAGE": {".png", ".jpg", ".jpeg", ".webp"},
    "VIDEO": {".mp4", ".mov", ".webm"},
}
_STAMP = re.compile(r"^\d{8}-\d{6}-")


@dataclass(frozen=True)
class Entry:
    path: Path
    kind: str  # a FILTERS key other than ALL
    folder: str  # the sub-folder it came from: "textures" means a material image
    mtime: float

    @property
    def name(self) -> str:
        """"20261028-101500-a-clay-tagine-pot.glb" → "a clay tagine pot"."""
        stem = _STAMP.sub("", self.path.stem)
        return stem.replace("-", " ").replace("_", " ").strip() or self.path.stem

    @property
    def label(self) -> str:
        return dict(FILTERS)[self.kind]


def scan(roots, kind="ALL", query="") -> list[Entry]:
    """Generations under each root (newest first), of one kind, whose name contains `query`."""
    found, seen = [], set()
    words = query.lower().split()
    for root in roots:
        for folder, folder_kind in KINDS.items():
            if kind != "ALL" and folder_kind != kind:
                continue
            directory = Path(root) / folder
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                if path.suffix.lower() not in EXTENSIONS[folder_kind] or not path.is_file():
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                entry = Entry(path, folder_kind, folder, path.stat().st_mtime)
                if all(word in entry.name.lower() for word in words):
                    found.append(entry)
    found.sort(key=lambda e: e.mtime, reverse=True)
    return found


class Cache:
    """`scan()` at most every `ttl` seconds for the same arguments: the bar redraws often."""

    def __init__(self, ttl=2.0):
        self.ttl, self._key, self._at, self._value = ttl, None, 0.0, []

    def get(self, roots, kind="ALL", query=""):
        key = (tuple(str(r) for r in roots), kind, query)
        now = time.monotonic()
        if key != self._key or now - self._at > self.ttl:
            self._key, self._at, self._value = key, now, scan(roots, kind, query)
        return self._value

    def clear(self):
        self._key = None


CACHE = Cache()
