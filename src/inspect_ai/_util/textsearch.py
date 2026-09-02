"""Text search under a fold, reported as source substrings.

Shared by the viewer's Find (literal, browser fold) and grep-style scanning
(literal or regex, casefold, word boundaries): the pattern runs over a folded
copy of the text and every hit is mapped back to source offsets, so callers
get the exact substrings the source (and a browser's DOM) contains.
"""

import re
import unicodedata
from array import array
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

Fold = Literal["browser", "case", "none"]
"""`browser`: NFKD, marks dropped, casefold (Chrome's find-in-page); `case`: casefold; `none`: exact."""

MatchMode = Literal["literal", "regex"]

_NON_ASCII = re.compile(r"[^\x00-\x7f]+")


@dataclass(frozen=True)
class TextMatch:
    start: int
    end: int
    text: str
    """The exact source substring, so a client can match it literally."""


@lru_cache(maxsize=65536)  # a guess: comfortably above the code points a log uses
def fold_char(char: str, fold: Fold = "browser") -> str:
    """The fold of one code point; parity with Chrome's find-in-page for `browser`.

    Probed: İ/i, ß/ss, é/e (NFC and NFD), ﬁ/fi match; dotless ı stays distinct.
    """
    if fold == "none":
        return char
    if fold == "browser":
        char = "".join(
            c
            for c in unicodedata.normalize("NFKD", char)
            if not unicodedata.category(c).startswith("M")
        )
    return char.casefold()


def fold_text(text: str, fold: Fold = "browser") -> str:
    return "".join(fold_char(char, fold) for char in text)


def compile_query(
    query: str,
    *,
    mode: MatchMode = "literal",
    fold: Fold = "browser",
    word_boundary: bool = False,
) -> re.Pattern[str] | None:
    r"""The pattern to run over `FoldedText.folded`; None when `query` is empty.

    A literal query is folded like the text and matched exactly (never
    `re.IGNORECASE`, whose Unicode rules conflate dotless ı with i). A regex is
    not folded (that would rewrite `\S` to `\s`); it runs with `re.IGNORECASE`
    under a fold so uppercase literals in the pattern still hit the lowercase
    folded text, but it must spell folded forms itself (`strasse`, not
    `straße`, under `browser`). Caveat of that flag: a regex `i` also matches
    dotless `ı`, which the literal path keeps distinct. Invalid regex raises
    `re.error`.
    """
    if not query:
        return None
    if mode == "literal":
        pattern, flags = re.escape(fold_text(query, fold)), 0
    else:
        pattern, flags = query, re.IGNORECASE if fold != "none" else 0
    if word_boundary:
        pattern = rf"\b(?:{pattern})\b"
    return re.compile(pattern, flags)


class FoldedText:
    """A text under a fold with a map from folded to source offsets.

    Folding is precomputed once so a search is a plain regex scan over the
    folded text; ASCII text folds to `lower()` with identity offsets. Folding
    can change length (ß → ss, ﬁ → fi), which is why offsets are mapped rather
    than reused.
    """

    __slots__ = ("text", "folded", "fold", "_origin")

    def __init__(self, text: str, fold: Fold = "browser") -> None:
        self.text = text
        self.fold = fold
        self._origin: array[int] | None = None
        if fold == "none":
            self.folded = text
            return
        if text.isascii():
            self.folded = text.lower()
            return
        parts: list[str] = []
        origin = array("I")
        position = 0
        for run in _NON_ASCII.finditer(text):
            _fold_ascii(text[position : run.start()], position, parts, origin)
            for index in range(run.start(), run.end()):
                folded = fold_char(text[index], fold)
                parts.append(folded)
                origin.extend([index] * len(folded))
            position = run.end()
        _fold_ascii(text[position:], position, parts, origin)
        self.folded = "".join(parts)
        self._origin = origin

    def find_all(self, pattern: re.Pattern[str] | None) -> Iterator[tuple[int, int]]:
        """Source (start, end) of each non-overlapping hit, left to right.

        `finditer` semantics: an empty hit (`x*` on `y`) is skipped and a
        non-empty alternative at the same spot still counts.
        """
        if pattern is None:
            return
        folded = self.folded
        origin = self._origin
        position = 0
        while position <= len(folded):
            for hit in pattern.finditer(folded, position):
                start, end = hit.span()
                if end == start:
                    continue
                if origin is None:
                    yield start, end
                    continue
                # a hit must start and end on source code-point boundaries: `sa`
                # does not match `ßa`; retry one folded character later
                inside_start = start > 0 and origin[start - 1] == origin[start]
                inside_end = end < len(folded) and origin[end] == origin[end - 1]
                if inside_start or inside_end:
                    position = start + 1
                    break
                # marks fold to nothing; the ones ending the match belong to it
                source_end = origin[end - 1] + 1
                while source_end < len(self.text) and not fold_char(
                    self.text[source_end], self.fold
                ):
                    source_end += 1
                yield origin[start], source_end
            else:
                return


def _fold_ascii(text: str, offset: int, parts: list[str], origin: "array[int]") -> None:
    parts.append(text.lower())
    origin.extend(range(offset, offset + len(text)))


def find_matches(
    text: str,
    query: str,
    *,
    mode: MatchMode = "literal",
    fold: Fold = "browser",
    word_boundary: bool = False,
) -> list[TextMatch]:
    """Every non-overlapping match of `query` in `text`, as source offsets and substrings."""
    folded = FoldedText(text, fold)
    pattern = compile_query(query, mode=mode, fold=fold, word_boundary=word_boundary)
    return [
        TextMatch(start, end, text[start:end])
        for start, end in folded.find_all(pattern)
    ]
