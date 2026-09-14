"""Conformance tests for inspect_ai._view.scope.

Drives the corpus in ``scope_conformance/cases.json`` (also shipped as
``inspect_ai/_view/scope_conformance.json`` so other consumers can load it
from the installed package).
"""

from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest

import inspect_ai._view
from inspect_ai._view.common import normalize_uri
from inspect_ai._view.scope import (
    Location,
    PathScope,
    ScopeRoot,
    _local_path_from_file_uri,
    canonical_location,
    resolve_child,
    scope_from_claims,
)

CORPUS_PATH = Path(__file__).parent / "scope_conformance" / "cases.json"
PACKAGED_CORPUS_PATH = Path(inspect_ai._view.__file__).parent / "scope_conformance.json"

CORPUS: dict[str, Any] = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))

_PLATFORM = "windows" if os.name == "nt" else "posix"


def _platform_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in cases if c.get("platform") in (None, _PLATFORM)]


def _ids(cases: list[dict[str, Any]]) -> list[str]:
    return [c["id"] for c in cases]


@pytest.fixture
def fixture_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Materialize the corpus fixture layout and chdir into it.

    Returns the resolved root, which is what ``{tmp}`` substitutes to (the
    temp dir itself may sit behind a symlink, e.g. ``/var`` on macOS).
    """
    layout = CORPUS["fixture"]
    for d in layout["dirs"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    for f in layout["files"]:
        (tmp_path / f).write_text("x", encoding="utf-8")
    for link, target in layout["symlinks"].items():
        try:
            (tmp_path / link).symlink_to(tmp_path / target)
        except OSError:
            pytest.skip("symlinks are not supported here")
    root = tmp_path.resolve()
    monkeypatch.chdir(root)
    return root


def _substitute(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        tmp = root.as_posix() if os.name != "nt" else str(root)
        return value.replace("{tmp_uri}", f"file://{root.as_posix()}").replace(
            "{tmp}", tmp
        )
    if isinstance(value, list):
        return [_substitute(v, root) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, root) for k, v in value.items()}
    return value


def _decode(location: str, decode: str | None) -> str:
    if decode == "path":
        return normalize_uri(location)
    if decode == "query":
        return urllib.parse.unquote(location)
    assert decode is None, decode
    return location


_CASES = _platform_cases(CORPUS["cases"])


@pytest.mark.parametrize("case", _CASES, ids=_ids(_CASES))
def test_scope_conformance_case(case: dict[str, Any], fixture_root: Path) -> None:
    case = _substitute(case, fixture_root)
    scope = scope_from_claims({"inspect_view_scope": case["scope"]}).path_scope
    permission = case["permission"]
    if case["location"] is None:
        resolved = scope.default_location(permission)
    else:
        resolved = scope.resolve(
            _decode(case["location"], case.get("decode")), permission
        )

    expect = case["expect"]
    if expect == "denied":
        assert resolved is None, f"{case['id']}: expected denial, got {resolved}"
    else:
        assert resolved is not None, f"{case['id']}: expected a resolution"
        assert resolved.io_path == expect["resolved"]
        assert resolved.permission == permission
        assert resolved.root in scope.roots


_CLAIMS = CORPUS["claims"]


@pytest.mark.parametrize("case", _CLAIMS, ids=_ids(_CLAIMS))
def test_scope_from_claims_conformance(case: dict[str, Any], tmp_path: Path) -> None:
    case = _substitute(case, tmp_path.resolve())
    if case["expect"] == "valid":
        scope_from_claims(case["claim"])
    else:
        with pytest.raises(ValueError):
            scope_from_claims(case["claim"])


_CHILDREN = CORPUS["children"]


@pytest.mark.parametrize("case", _CHILDREN, ids=_ids(_CHILDREN))
def test_resolve_child_conformance(case: dict[str, Any]) -> None:
    if case["expect"] == "rejected":
        with pytest.raises(ValueError):
            resolve_child(case["base"], case["child"])
    else:
        assert resolve_child(case["base"], case["child"]) == case["expect"]["joined"]


def test_packaged_corpus_matches_test_corpus() -> None:
    """The shipped copy must not drift from the tests' copy."""
    assert PACKAGED_CORPUS_PATH.read_bytes() == CORPUS_PATH.read_bytes()


def test_corpus_ids_are_unique() -> None:
    for section in ("cases", "claims", "children"):
        ids = _ids(CORPUS[section])
        assert len(ids) == len(set(ids)), section


def test_unknown_permission_never_grants(fixture_root: Path) -> None:
    root = ScopeRoot.parse(str(fixture_root / "logs"), "dir", ["read", "admin"])
    assert root.permissions == frozenset({"read"})
    scope = PathScope((root,))
    assert scope.resolve(str(fixture_root / "logs" / "run.eval"), "write") is None


def test_location_identity_compares_canonical_forms(fixture_root: Path) -> None:
    direct = canonical_location(str(fixture_root / "logs" / "run.eval"))
    via_alias = canonical_location(str(fixture_root / "alias" / "run.eval"))
    via_uri = canonical_location(f"file://{fixture_root.as_posix()}/logs//run.eval")
    other = canonical_location(str(fixture_root / "outside" / "secret.eval"))
    assert direct is not None and via_alias is not None and via_uri is not None
    assert other is not None
    assert isinstance(direct, Location)
    assert direct.same_object(via_alias)
    assert direct.same_object(via_uri)
    assert not direct.same_object(other)
    assert direct == via_alias == via_uri


def test_canonical_location_unparseable() -> None:
    assert canonical_location("") is None
    assert canonical_location("s3:///no-authority/x") is None
    assert canonical_location("s3://bucket/a#b") is None


def test_windows_file_uri_parsing_is_literal() -> None:
    """The Windows branches of the file: URI parser, exercised on any platform."""
    assert _local_path_from_file_uri("file:///C:/w/logs/run.eval", windows=True) == (
        "C:/w/logs/run.eval"
    )
    assert _local_path_from_file_uri("file://C:/w/logs/run.eval", windows=True) == (
        "C:/w/logs/run.eval"
    )
    assert _local_path_from_file_uri(
        "file://server/share/logs/run.eval", windows=True
    ) == str(PureWindowsPath("//server/share/logs/run.eval"))
    assert _local_path_from_file_uri("file://server/", windows=True) is None
    assert (
        _local_path_from_file_uri("file://server/share/logs/run.eval", windows=False)
        is None
    )
    assert _local_path_from_file_uri("file://C:/w/logs/run.eval", windows=False) is None
    # no percent-decoding, ? and # are name characters
    assert _local_path_from_file_uri("file:///w/a%20b?c#d", windows=False) == (
        "/w/a%20b?c#d"
    )
    assert _local_path_from_file_uri("file:///w/a\\b", windows=False) is None
    assert _local_path_from_file_uri("file://localhost/w/x", windows=False) == "/w/x"
    assert _local_path_from_file_uri("file://LOCALHOST/w/x", windows=False) == "/w/x"
    assert _local_path_from_file_uri("file://user@localhost/w/x", windows=False) is None
