from fpb.overlay.field import Field, wrap


def measure(text):
    return len(text) * 10


def test_typing_and_word_deletion():
    field = Field()
    field.insert("hello world")
    field.backspace(word=True)
    assert field.text == "hello " and field.caret == 6
    field.insert("there")
    field.left(word=True)
    assert field.caret == 6


def test_home_end_work_per_line():
    field = Field("first\nsecond")
    field.home()
    assert field.text[field.caret:] == "second"
    field.end()
    assert field.caret == len(field.text)


def test_delete_and_unicode():
    field = Field("café ☕")
    field.backspace()
    assert field.text == "café "
    field.set("abc")
    field.left()
    field.delete()
    assert field.text == "ab"


def test_backspace_past_the_start_is_harmless():
    field = Field("ab")
    for _ in range(5):
        field.backspace()
    assert field.text == "" and field.caret == 0


def test_paste_normalises_newlines():
    field = Field()
    field.insert("a\r\nb\rc")
    assert field.text == "a\nb\nc"


def test_wrap_covers_the_text_and_respects_width():
    text = "the quick brown fox jumps over the lazy dog"
    lines = wrap(text, 100, measure)
    assert "".join(text[a:b] for a, b in lines) == text
    assert all(measure(text[a:b].rstrip()) <= 100 for a, b in lines)


def test_wrap_cuts_long_words_and_keeps_empty_lines():
    assert len(wrap("x" * 25, 100, measure)) == 3
    assert wrap("one\n\ntwo", 1000, measure) == [(0, 3), (4, 4), (5, 8)]
    assert wrap("", 100, measure) == [(0, 0)]
