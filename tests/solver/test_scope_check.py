import math

import anyio
import pytest

from inspect_ai.model import ModelName
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.scorer import CORRECT, INCORRECT
from inspect_ai.scorer._metric import value_to_float
from inspect_ai.scorer._target import Target
from inspect_ai.solver import Generate, TaskState, scope_check
from inspect_ai.solver._scope_check import (
    _diff,
    _glob_to_regex,
    _has_delta,
    _matches,
    _sample_allowed,
    _subtract,
)

# ---- matcher (globstar) --------------------------------------------------


@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        # mid-segment ** is a plain star, not a globstar (fail-open guard)
        ("output**", "outputs/secret/pwned", False),
        ("output**", "outputX", True),
        ("a**/b", "axx/deep/b", False),
        ("a**/b", "axx/b", True),
        # segment globstar spans zero or more dirs
        ("a/**/b", "a/b", True),
        ("a/**/b", "a/x/y/b", True),
        # leading **/ works for absolute and relative keys
        ("**/*.pyc", "/app/pkg/__pycache__/m.pyc", True),
        ("**/*.pyc", "x.pyc", True),
        # trailing /** covers the directory node itself
        ("**/__pycache__/**", "__pycache__", True),
        ("**/__pycache__/**", "a/b/__pycache__/m.pyc", True),
        ("out/**", "out", True),
        ("out/**", "out/result.txt", True),
        ("bare", "bare", True),
        ("bare", "bare/child", False),
        ("**", "anything/at/all", True),
        # anchoring: a trailing newline must not slip past the end
        ("out.txt", "out.txt\n", False),
        # DOTALL: a globstar spans newlines inside a legal filename
        ("logs/**", "logs/a\nb", True),
        # backslash is a literal, legal POSIX filename char
        ("report*", "report\\Q1.txt", True),
        # consecutive-star oddities collapse to a within-segment star
        ("a/****/b", "a/x/b", True),
        ("a/****/b", "a/x/y/b", False),
    ],
)
def test_glob_to_regex(pattern, path, expected):
    assert bool(_glob_to_regex(pattern).match(path)) is expected


def test_matches_any():
    compiled = [_glob_to_regex(p) for p in ("src/**", "*.md")]
    assert _matches("src/pkg/mod.py", compiled)
    assert _matches("README.md", compiled)
    assert not _matches("secret.key", compiled)


# ---- diff / subtract -----------------------------------------------------


def _f(sha: str):
    return {"type": "file", "mode": 420, "sha256": sha, "target": None}


def test_diff_added_modified_deleted():
    before = {"a": _f("1"), "b": _f("2"), "c": _f("3")}
    after = {"a": _f("1"), "b": _f("X"), "d": _f("4")}
    assert _diff(before, after) == {
        "added": ["d"],
        "modified": ["b"],
        "deleted": ["c"],
    }


def test_diff_error_flip_is_modified():
    before = {"a": _f("1")}
    after = {"a": {"type": "error", "reason": "PermissionError"}}
    assert _diff(before, after)["modified"] == ["a"]


def test_subtract_allowed():
    delta = {"added": ["src/new.py", "evil.sh"], "modified": [], "deleted": ["docs/x"]}
    off = _subtract(delta, [_glob_to_regex("src/**"), _glob_to_regex("docs/**")])
    assert off == {"added": ["evil.sh"], "modified": [], "deleted": []}


def test_has_delta():
    assert not _has_delta({"added": [], "modified": [], "deleted": []})
    assert _has_delta({"added": [], "modified": ["x"], "deleted": []})


# ---- sample-metadata footprint ------------------------------------------


def test_sample_allowed_extends():
    assert _sample_allowed({}) == []
    assert _sample_allowed({"scope_check": {"allowed": ["a", "b"]}}) == ["a", "b"]


def test_sample_allowed_malformed():
    with pytest.raises(ValueError):
        _sample_allowed({"scope_check": ["not", "an", "object"]})
    with pytest.raises(ValueError):
        _sample_allowed({"scope_check": {"allowed": [1, 2]}})


# ---- solver behaviour (sandbox monkeypatched) ---------------------------


def _make_state(metadata=None) -> TaskState:
    return TaskState(
        model=ModelName("openai/gpt-4o-mini"),
        sample_id="s1",
        epoch=0,
        input="hello",
        messages=[ChatMessageUser(content="hi")],
        target=Target(""),
        metadata=metadata or {},
    )


async def _generate(state: TaskState, **kwargs) -> TaskState:  # Generate stub
    return state


def _passthru():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve


def _raises(exc: Exception):
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        raise exc

    return solve


def _patch_manifests(monkeypatch, sequence):
    """Patch _collect_manifest to return (or raise) each item in turn."""
    import inspect_ai.solver._scope_check as fc

    seq = list(sequence)

    async def fake(roots):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(fc, "_collect_manifest", fake)


def _run(solver, state):
    return anyio.run(solver, state, _generate)


def test_observational_records_unscored_delta(monkeypatch):
    base = {"a.txt": _f("1")}
    final = {"a.txt": _f("1"), "junk.log": _f("9")}
    _patch_manifests(monkeypatch, [base, final])
    state = _run(scope_check(_passthru()), _make_state())
    score = state.scores["scope_check"]
    assert math.isnan(value_to_float()(score.value))  # unscored sentinel
    assert score.metadata["off_footprint"]["added"] == ["junk.log"]


def test_gate_flags_off_footprint(monkeypatch):
    base = {"a.txt": _f("1")}
    final = {"a.txt": _f("1"), "junk.log": _f("9")}
    _patch_manifests(monkeypatch, [base, final])
    state = _run(scope_check(_passthru(), gate=True), _make_state())
    assert state.scores["scope_check"].value == INCORRECT


def test_gate_passes_when_clean(monkeypatch):
    base = {"a.txt": _f("1")}
    final = {"a.txt": _f("1"), "out/result.txt": _f("2")}
    _patch_manifests(monkeypatch, [base, final])
    state = _run(scope_check(_passthru(), allowed=["out/**"], gate=True), _make_state())
    assert state.scores["scope_check"].value == CORRECT


def test_sample_metadata_extends_allowed(monkeypatch):
    base = {"a.txt": _f("1")}
    final = {"a.txt": _f("1"), "ref/answer.py": _f("2")}
    _patch_manifests(monkeypatch, [base, final])
    state = _make_state({"scope_check": {"allowed": ["ref/**"]}})
    state = _run(scope_check(_passthru(), gate=True), state)
    assert state.scores["scope_check"].value == CORRECT


def test_default_ignores_pyc(monkeypatch):
    base = {"a.txt": _f("1")}
    final = {"a.txt": _f("1"), "pkg/__pycache__/m.pyc": _f("2")}
    _patch_manifests(monkeypatch, [base, final])
    state = _run(scope_check(_passthru(), gate=True), _make_state())
    assert state.scores["scope_check"].value == CORRECT


def test_gate_fails_closed_on_report_error(monkeypatch):
    # baseline ok, final snapshot fails while the wrapped solver succeeded
    _patch_manifests(
        monkeypatch, [{"a.txt": _f("1")}, RuntimeError("boom"), RuntimeError("boom")]
    )
    state = _run(scope_check(_passthru(), gate=True), _make_state())
    score = state.scores["scope_check"]
    assert score.value == INCORRECT
    assert "failed closed" in (score.explanation or "")


def test_observational_report_error_is_unscored(monkeypatch):
    _patch_manifests(
        monkeypatch, [{"a.txt": _f("1")}, RuntimeError("boom"), RuntimeError("boom")]
    )
    state = _run(scope_check(_passthru()), _make_state())
    assert "scope_check_error" in state.scores["scope_check"].metadata


def test_wrapped_exception_reraised(monkeypatch):
    base = {"a.txt": _f("1")}
    final = {"a.txt": _f("1"), "junk": _f("2")}
    _patch_manifests(monkeypatch, [base, final])
    with pytest.raises(ValueError, match="inner"):
        _run(scope_check(_raises(ValueError("inner"))), _make_state())
