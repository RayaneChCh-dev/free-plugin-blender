"""One editable string and its caret. Pure Python, so it is testable without Blender."""

from __future__ import annotations

import re

_WORD = re.compile(r"\w+|[^\w\s]+|\s+")


class Field:
    def __init__(self, text=""):
        self.text = text
        self.caret = len(text)

    def set(self, text):
        self.text, self.caret = text, len(text)

    def insert(self, chars):
        chars = chars.replace("\r\n", "\n").replace("\r", "\n")
        self.text = self.text[:self.caret] + chars + self.text[self.caret:]
        self.caret += len(chars)

    def _word_left(self):
        position = self.caret
        while position > 0 and self.text[position - 1].isspace():
            position -= 1
        while position > 0 and not self.text[position - 1].isspace():
            position -= 1
        return position

    def _word_right(self):
        position, size = self.caret, len(self.text)
        while position < size and self.text[position].isspace():
            position += 1
        while position < size and not self.text[position].isspace():
            position += 1
        return position

    def backspace(self, word=False):
        start = self._word_left() if word else max(0, self.caret - 1)
        self.text = self.text[:start] + self.text[self.caret:]
        self.caret = start

    def delete(self, word=False):
        end = self._word_right() if word else min(len(self.text), self.caret + 1)
        self.text = self.text[:self.caret] + self.text[end:]

    def left(self, word=False):
        self.caret = self._word_left() if word else max(0, self.caret - 1)

    def right(self, word=False):
        self.caret = self._word_right() if word else min(len(self.text), self.caret + 1)

    def home(self):
        self.caret = self.text.rfind("\n", 0, self.caret) + 1

    def end(self):
        newline = self.text.find("\n", self.caret)
        self.caret = len(self.text) if newline < 0 else newline


def wrap(text, width, measure):
    """Lines of `text` no wider than `width`, as (start, end) offsets so a caret can be placed.

    `measure(s)` returns the drawn width of s. Breaks at spaces; a word longer
    than the line is cut wherever it overflows.
    """
    lines = []
    start = 0
    for paragraph in text.split("\n"):
        end_of_paragraph = start + len(paragraph)
        line_start = start
        position = start
        last_break = None
        while position < end_of_paragraph:
            if text[position] == " ":
                last_break = position + 1
            if measure(text[line_start:position + 1]) > width and position > line_start:
                cut = last_break if last_break and last_break > line_start else position
                lines.append((line_start, cut))
                line_start, last_break = cut, None
                position = cut
                continue
            position += 1
        lines.append((line_start, end_of_paragraph))
        start = end_of_paragraph + 1
    return lines
