"""Markdown syntax stripping so a phrase spanning a marker matches like in the browser."""

import re

_FENCED = re.compile(r"^ {0,3}(`{3,}|~{3,})[^\n]*\n([\s\S]*?)(?:^ {0,3}\1 *$|\Z)", re.M)
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
# indented code cannot interrupt a paragraph: only at the start or after a blank line
_INDENTED = re.compile(r"(?:\A|(?<=\n\n))((?: {4}|\t)[^\n]*(?:\n(?: {4}|\t)[^\n]*)*)")
_PRIVATE_USE = range(0xE000, 0xF900)

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),  # [text](url)
    (re.compile(r"^ {0,3}#{1,6} ", re.M), ""),  # headings
    (re.compile(r"^ {0,3}> ", re.M), ""),  # block quotes
    (re.compile(r"^ *(?:[-*+]|\d+\.) (?:\[[ xX]\] )?", re.M), ""),  # list / task items
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"), r"\1"),  # strong
    (
        re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)"),
        r"\1",
    ),  # strong, not intraword
    (re.compile(r"\*(?=\S)(.+?)(?<=\S)\*"), r"\1"),  # emphasis
    (
        re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)"),
        r"\1",
    ),  # emphasis, not intraword
    (re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"), r"\1"),  # strikethrough
]


def strip_markdown_for_count(text: str) -> str:
    """Remove common markdown markers; code content (fenced, indented or inline) is kept verbatim.

    Only syntax goes, never words, so every substring of the result also occurs
    in the rendered text.
    """
    # code bodies are parked behind a placeholder built from a private-use
    # code point the text does not contain (a text holding all 6400 is left as is)
    sentinel = next((chr(c) for c in _PRIVATE_USE if chr(c) not in text), None)
    if sentinel is None:
        return text
    verbatim: list[str] = []

    def park(body: str) -> str:
        verbatim.append(body)
        return f"{sentinel}{len(verbatim) - 1}{sentinel}"

    text = _FENCED.sub(lambda m: park(m.group(2)), text)
    text = _INDENTED.sub(lambda m: park(m.group(1)), text)
    text = _CODE_SPAN.sub(lambda m: park(m.group(2)), text)
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    placeholder = re.compile(f"{sentinel}(\\d+){sentinel}")
    return placeholder.sub(lambda m: verbatim[int(m.group(1))], text)
