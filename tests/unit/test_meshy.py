"""The chosen settings become Meshy create payloads the API accepts."""

import importlib

import pytest

meshy = importlib.import_module("fpb.providers.meshy")


@pytest.fixture
def created(monkeypatch):
    payloads = []

    def create(endpoint, payload, key):
        payloads.append(payload)
        return f"task{len(payloads)}"

    monkeypatch.setattr(meshy, "create", create)
    monkeypatch.setattr(meshy, "wait", lambda endpoint, task_id, key, progress=None: {"id": task_id})
    return payloads


def test_auto_sends_no_geometry():
    assert meshy.geometry({}) == {}


def test_topology_and_polycount_need_a_remesh():
    assert meshy.geometry({"topology": "quad"}) == {"should_remesh": True, "topology": "quad"}
    assert meshy.geometry({"model_type": "standard", "target_polycount": 5000}) == {
        "model_type": "standard", "should_remesh": True, "target_polycount": 5000}


def test_smart_topology_sets_its_model_and_drops_what_it_refuses():
    assert meshy.geometry({"model_type": "smart-topology", "topology": "quad", "target_polycount": 100_000}) == {
        "model_type": "smart-topology", "ai_model": "meshy-t2.5", "target_polycount": 30_000}


def test_text_preview_stops_before_refine(created):
    result = meshy.text_to_3d("chair", "key", options={"mode": "preview"})
    assert [p["mode"] for p in created] == ["preview"]
    assert result == {"id": "task1"}


def test_text_defaults_to_textured_pbr(created):
    meshy.text_to_3d("chair", "key")
    assert [p["mode"] for p in created] == ["preview", "refine"]
    assert created[1]["preview_task_id"] == "task1" and created[1]["enable_pbr"] is True


def test_text_pbr_off(created):
    meshy.text_to_3d("chair", "key", options={"enable_pbr": False})
    assert created[1]["enable_pbr"] is False


def test_image_preview_never_sends_pbr(created):
    meshy.image_to_3d("data:x", "key", options={"mode": "preview", "enable_pbr": True, "topology": "quad"})
    assert created == [{"image_url": "data:x", "should_texture": False, "target_formats": ["glb"],
                        "should_remesh": True, "topology": "quad"}]


def test_image_full(created):
    meshy.image_to_3d("data:x", "key", options={"mode": "full", "model_type": "smart-topology"})
    assert created[0]["should_texture"] is True and created[0]["enable_pbr"] is True
    assert created[0]["ai_model"] == "meshy-t2.5"
