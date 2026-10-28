import os

from fpb import library


def make(root, relative, mtime):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.utime(path, (mtime, mtime))
    return path


def test_scan_kinds_order_and_skipped_folders(tmp_path):
    make(tmp_path, "models/20261028-101500-a-clay-tagine-pot.glb", 300)
    make(tmp_path, "rigs/knight/rigged.glb", 250)
    make(tmp_path, "animations/20261028-110000-a-joyful-jump.fbx", 200)
    make(tmp_path, "images/20261028-090000-riad-courtyard.png", 400)
    make(tmp_path, "textures/20261028-091000-green-zellige.png", 100)
    make(tmp_path, "videos/20261028-120000-slow-dolly-in.mp4", 500)
    make(tmp_path, "captures/camera.png", 600)       # not a generation
    make(tmp_path, "polyhaven/barrel/barrel.gltf", 600)  # Poly Haven cache
    make(tmp_path, "models/notes.txt", 600)          # not a model file

    found = library.scan([tmp_path])
    assert [e.name for e in found] == ["slow dolly in", "riad courtyard", "a clay tagine pot", "rigged",
                                       "a joyful jump", "green zellige"]
    assert [e.kind for e in found] == ["VIDEO", "IMAGE", "MESH", "MESH", "ANIMATION", "IMAGE"]
    assert found[-1].folder == "textures" and found[0].label == "Video"


def test_filter_and_query(tmp_path):
    make(tmp_path, "models/20261028-101500-a-clay-tagine-pot.glb", 3)
    make(tmp_path, "images/20261028-090000-clay-wall.png", 2)
    make(tmp_path, "images/20261028-090500-riad.png", 1)
    assert [e.name for e in library.scan([tmp_path], "IMAGE")] == ["clay wall", "riad"]
    assert [e.name for e in library.scan([tmp_path], query="CLAY")] == ["a clay tagine pot", "clay wall"]
    assert [e.name for e in library.scan([tmp_path], query="clay pot")] == ["a clay tagine pot"]
    assert library.scan([tmp_path], "VIDEO") == []


def test_several_roots_missing_root_and_no_duplicates(tmp_path):
    make(tmp_path / "new", "images/a.png", 2)
    make(tmp_path / "old", "images/b.png", 1)
    roots = [tmp_path / "new", tmp_path / "old", tmp_path / "missing", tmp_path / "new"]
    assert [e.name for e in library.scan(roots)] == ["a", "b"]


def test_cache_reuses_then_rescans(tmp_path):
    cache = library.Cache(ttl=60)
    assert cache.get([tmp_path]) == []
    make(tmp_path, "images/a.png", 1)
    assert cache.get([tmp_path]) == []  # cached
    assert len(cache.get([tmp_path], "IMAGE")) == 1  # other arguments: scanned again
    cache.clear()
    assert len(cache.get([tmp_path])) == 1
