import pytest

from inspect_ai._util.lineage import (
    LineageMatch,
    PrefixLineages,
    eq_prefix_len,
    needs_strict_eq,
    strict_eq,
)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ([{"x": "a"}, {"x": "b"}], [{"x": "a"}, {"x": "c"}], 1),
        (["a", "b", "c"], ["a", "b"], 2),
        (["a"], ["a", "b"], 1),
        ([], ["a"], 0),
        ([{"n": 1}], [{"n": 1.0}], 0),
        ([{"x": "y"}, {"n": True}], [{"x": "y"}, {"n": 1}], 1),
        ([{"n": 1}, {"x": "y"}], [{"n": 1}, {"x": "z"}], 1),
        ([{"n": 1}, {"x": "y"}, {"n": 2}], [{"n": 1}, {"x": "y"}, {"n": 2.0}], 2),
        ([str(i) for i in range(100)] + ["x"], [str(i) for i in range(101)], 100),
        (["a", "b", "c", "d", "e"], ["z", "b", "c", "d", "e"], 0),
    ],
)
def test_eq_prefix_len_is_the_strict_prefix(
    a: list[object], b: list[object], expected: int
) -> None:
    assert eq_prefix_len(a, b, [needs_strict_eq(v) for v in b]) == expected
    assert expected == next(
        (i for i, (x, y) in enumerate(zip(a, b)) if not strict_eq(x, y)),
        min(len(a), len(b)),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("s", False),
        (None, False),
        ({"a": ["b", {"c": None}]}, False),
        ({"a": 1}, True),
        ([True], True),
        ({1: "a"}, True),
        (("a",), True),
    ],
)
def test_needs_strict_eq(value: object, expected: bool) -> None:
    assert needs_strict_eq(value) is expected


def _record(lineages: PrefixLineages[str], msgs: list[object]) -> LineageMatch[str]:
    match = lineages.match("k", msgs)
    entries = match.entries + [
        f"e{len(match.entries) + i}" for i in range(len(msgs) - match.length)
    ]
    lineages.record("k", match, list(msgs), [needs_strict_eq(m) for m in msgs], entries)
    return match


def test_prefix_lineages_extend_replaces_and_fork_appends() -> None:
    lineages: PrefixLineages[str] = PrefixLineages(slots=8, max_idle=32)
    _record(lineages, ["a", "b"])
    assert _record(lineages, ["a", "b", "c"]).length == 2
    assert len(lineages) == 1
    assert _record(lineages, ["a", "x"]).length == 1
    assert sorted(len(lin.snapshots) for lin in lineages.lineages) == [2, 3]
    assert lineages.match("k", ["a", "b", "c", "d"]).length == 3
    assert lineages.match("other", ["a", "b"]).length == 0


def test_prefix_lineages_retain_callers_objects() -> None:
    lineages: PrefixLineages[str] = PrefixLineages(slots=8, max_idle=32)
    msg = {"role": "user", "content": "a"}
    _record(lineages, [msg])
    assert lineages.lineages[0].snapshots[0] is msg


def test_prefix_lineages_cap_and_idle_drop() -> None:
    lineages: PrefixLineages[str] = PrefixLineages(slots=3, max_idle=4)
    for i in range(5):
        _record(lineages, [f"lineage-{i}"])
    assert len(lineages) == 3
    for _ in range(6):
        _record(lineages, ["live"])
    assert [lin.snapshots for lin in lineages.lineages] == [["live"]]
