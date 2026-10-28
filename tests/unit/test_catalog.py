import json

from fpb import catalog


def test_bundled_catalog_is_consistent(tmp_path):
    catalog.configure(tmp_path)
    for slot in catalog.SLOTS:
        assert catalog.models(slot), slot
        for entry in catalog.models(slot):
            assert entry["key"] and entry["label"]
            assert entry.get("provider") or entry.get("text") or entry.get("image"), entry
            for endpoint in filter(None, (entry.get("text"), entry.get("image"))):
                assert catalog.cached_schema(endpoint) is not None, f"no bundled schema for {endpoint}"


def test_user_catalog_adds_and_overrides(tmp_path):
    (tmp_path / "models.json").write_text(json.dumps({
        "image": [{"key": "mine", "label": "Mine", "text": "fal-ai/flux/dev"},
                  {"key": "seedream45", "label": "Overridden", "text": "fal-ai/x"},
                  {"label": "no key, ignored", "text": "fal-ai/y"}],
    }))
    catalog.configure(tmp_path)
    keys = [e["key"] for e in catalog.models("image")]
    assert "mine" in keys and keys.count("seedream45") == 1
    assert catalog.get("image", "seedream45")["label"] == "Overridden"


def test_invalid_user_catalog_is_ignored(tmp_path):
    (tmp_path / "models.json").write_text("{not json")
    catalog.configure(tmp_path)
    assert catalog.get("image", "seedream45") is not None


def test_endpoint_choice(tmp_path):
    catalog.configure(tmp_path)
    trellis = catalog.get("mesh", "trellis")
    assert catalog.endpoint(trellis, with_image=False) == trellis["image"]  # text goes through an image
    seedream = catalog.get("image", "seedream45")
    assert catalog.endpoint(seedream, with_image=True).endswith("/edit")
    assert catalog.endpoint(catalog.get("mesh", "meshy"), with_image=False) is None
    custom = catalog.custom_entry("fal-ai/flux/dev")
    assert catalog.endpoint(custom, True) == catalog.endpoint(custom, False) == "fal-ai/flux/dev"


def test_user_template_is_created(tmp_path):
    catalog.configure(tmp_path)
    data = json.loads(catalog.user_catalog_path().read_text())
    assert set(catalog.SLOTS) <= set(data)
