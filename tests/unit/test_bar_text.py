from fpb.overlay import richtext, thread


def measure(text, style):
    return len(text) * (11 if style == "bold" else 10)


def texts(line):
    return "".join(t for t, _s in line.runs)


def test_inline_marks():
    assert richtext.runs("un sol de **20 m** et `bpy.ops`.") == [
        ("un sol de ", "plain"), ("20 m", "bold"), (" et ", "plain"), ("bpy.ops", "code"), (".", "plain")]
    assert richtext.runs("2 * 3 = 6 et **pas fermé") == [("2 * 3 = 6 et **pas fermé", "plain")]
    assert richtext.plain("## Titre **gras**") == "Titre gras"


def test_wrap_keeps_styles_and_width():
    lines = richtext.layout("une fontaine en **zellige vert** au centre de la place", 200, measure)
    assert all(sum(measure(t, s) for t, s in line.runs) <= 200 for line in lines)
    assert " ".join(texts(line) for line in lines) == "une fontaine en zellige vert au centre de la place"
    assert ("vert ", "bold") in [run for line in lines for run in line.runs] or \
        ("vert", "bold") in [run for line in lines for run in line.runs]


def test_lists_headings_paragraphs():
    lines = richtext.layout("# Plan\n\n- sol\n- fontaine en zellige vert très long\n\nFin.", 160, measure)
    assert lines[0].runs == [("Plan", "bold")]
    assert lines[1].bullet == "•" and lines[1].indent == 14.0 and lines[1].gap_before
    wrapped = [line for line in lines if not line.bullet and line.indent == 14.0]
    assert wrapped, "a long list item continues under its text"
    assert lines[-1].gap_before and texts(lines[-1]) == "Fin."
    numbered = richtext.layout("1. un\n2) deux", 300, measure)
    assert [line.bullet for line in numbered] == ["1.", "2)"]


def test_long_word_is_cut():
    lines = richtext.layout("x" * 50, 100, measure)
    assert len(lines) == 5 and all(measure(texts(line), "plain") <= 100 for line in lines)
    assert richtext.layout("", 100, measure)[0].runs == []


def test_thread_groups_tools_and_places_avatars():
    messages = [{"role": "user", "text": "fais une place"},
                {"role": "assistant", "text": "Je regarde."},
                {"role": "tool", "text": "execute_blender_code: bpy.ops.mesh.primitive_plane_add()"},
                {"role": "tool", "text": "mcp__blender__execute_blender_code: x = 1"},
                {"role": "tool", "text": "failed: boom"},
                {"role": "tool", "text": "polyhaven_search: sunset"},
                {"role": "assistant", "text": "C'est fait."},
                {"role": "info", "text": "Stopped."},
                {"role": "user", "text": "merci"},
                {"role": "tool", "text": "scene_summary"}]
    found = thread.items(messages)
    assert [i.kind for i in found] == ["user", "assistant", "tools", "assistant", "info", "user", "tools"]
    assert [i.avatar for i in found] == [False, True, False, False, False, False, True]
    tools = found[2]
    assert tools.failed == 1 and len(tools.tools) == 4 and tools.key == 2
    assert thread.summary(tools) == ("3 actions, 1 failed", "execute_blender_code ×2 · polyhaven_search")
    assert thread.summary(found[-1]) == ("1 action", "scene_summary")
