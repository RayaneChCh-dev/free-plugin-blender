from fpb import presets


def test_library_is_complete():
    found = presets.all_presets()
    assert len(found) > 600
    assert {p["category"] for p in found} == {key for key, _ in presets.CATEGORIES[1:]}
    assert all({"id", "name", "category", "sub", "in_place"} <= p.keys() for p in found)
    assert len({p["id"] for p in found}) == len(found)


def test_search_words_category_in_place():
    walks = presets.search("walk")
    assert walks and all("walk" in f"{p['name']} {p['sub']} {p['category']}".lower() for p in walks)
    dances = presets.search(category="Dancing")
    assert dances and {p["category"] for p in dances} == {"Dancing"}
    still = presets.search(in_place_only=True)
    assert still and all(p["in_place"] for p in still)
    assert presets.search("zzz no such move") == []


def test_every_word_must_match():
    sample = [{"id": 1, "name": "Fast Run", "category": "WalkAndRun", "sub": "Running", "in_place": False},
              {"id": 2, "name": "Slow Walk", "category": "WalkAndRun", "sub": "Walking", "in_place": True}]
    assert [p["id"] for p in presets.search("run fast", presets=sample)] == [1]
    assert [p["id"] for p in presets.search("walkandrun", presets=sample)] == [1, 2]
    assert [p["id"] for p in presets.search("", "WalkAndRun", True, presets=sample)] == [2]


def test_get():
    first = presets.all_presets()[0]
    assert presets.get(first["id"]) == first
    assert presets.get(-1) is None
