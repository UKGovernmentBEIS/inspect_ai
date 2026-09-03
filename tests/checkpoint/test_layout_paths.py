"""Tests for the path-containment helpers in ``_layout/_paths.py``."""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

import pytest

from inspect_ai.util._checkpoint._layout._paths import (
    contained_component,
    contained_relative,
    sample_dir_segment,
)

# --- contained_relative -----------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "config",
        "keys/abc",
        "data/ab/cdef",
        "ckpt-00001.tar.zst",
        "a.b/c-d_e",
        "..foo/bar..",  # dots inside a component are fine
    ],
)
def test_contained_relative_accepts_plain_relative_paths(rel: str) -> None:
    assert contained_relative(rel) == PurePosixPath(rel)
    assert contained_relative(rel).as_posix() == rel


@pytest.mark.parametrize(
    "rel, match",
    [
        ("", "empty"),
        ("/etc/passwd", "absolute"),
        ("//etc/passwd", "absolute"),
        ("../x", r"'\.\.' is not allowed"),
        ("a/../x", r"'\.\.' is not allowed"),
        ("a/..", r"'\.\.' is not allowed"),
        ("./x", r"'\.' is not allowed"),
        ("a/./x", r"'\.' is not allowed"),
        ("a//b", "empty"),
        ("a/", "empty"),
        ("a\\..\\b", "separator"),
        ("a/b\x00c", "NUL"),
    ],
)
def test_contained_relative_rejects_escapes(rel: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        contained_relative(rel)


def test_contained_relative_error_names_the_path() -> None:
    with pytest.raises(ValueError, match=re.escape("'restic/host/../x'")):
        contained_relative("restic/host/../x")


# --- contained_component ----------------------------------------------------


@pytest.mark.parametrize("name", ["default", "web-1", "a.b", "..x", "x.."])
def test_contained_component_accepts_single_segment(name: str) -> None:
    assert contained_component(name) == name


@pytest.mark.parametrize(
    "name", ["", ".", "..", "a/b", "/a", "a\\b", "a\x00", "../etc"]
)
def test_contained_component_rejects_non_segments(name: str) -> None:
    with pytest.raises(ValueError):
        contained_component(name)


# --- sample_dir_segment -----------------------------------------------------


@pytest.mark.parametrize(
    "sample_id",
    ["s7", "sample-7", "42", "a.b_c-d", "X", "0", "task_001.v2", "a" * 300],
)
def test_sample_dir_segment_passes_through_safe_string_ids(sample_id: str) -> None:
    """Existing checkpoint dirs keep their names, so they stay resumable."""
    assert sample_dir_segment(sample_id) == sample_id


@pytest.mark.parametrize("sample_id", [0, 1, 42, 10**12])
def test_sample_dir_segment_passes_through_non_negative_int_ids(
    sample_id: int,
) -> None:
    assert sample_dir_segment(sample_id) == str(sample_id)


def _hashed(sample_id: str) -> str:
    return hashlib.sha256(sample_id.encode()).hexdigest()[:12]


def test_sample_dir_segment_negative_int_id_is_hashed_like_its_string() -> None:
    """A negative int is dash-leading, so it follows the same rule as the string ``"-1"``."""
    assert sample_dir_segment(-1) == f"1-{_hashed('-1')}"
    assert sample_dir_segment(-1) == sample_dir_segment("-1")


@pytest.mark.parametrize(
    "sample_id",
    [
        "../../x",
        "a/b",
        "/abs",
        ".",
        "..",
        ".hidden",
        "-flag",
        "-flag/x",
        "--rf /",
        "---",
        "",
        "with space",
        "ünïcödé",
        "日本語",
        "a\x00b",
        "a\\b",
    ],
)
def test_sample_dir_segment_rewrites_unsafe_ids_to_one_safe_segment(
    sample_id: str,
) -> None:
    segment = sample_dir_segment(sample_id)
    assert segment != sample_id
    assert segment.endswith(f"-{_hashed(sample_id)}")
    # Exactly one path component, never a traversal, never hidden/flag-like.
    assert "/" not in segment and "\\" not in segment and "\x00" not in segment
    assert segment not in (".", "..")
    # Same leading-alphanumeric rule as the passthrough set: never hidden,
    # never flag-like.
    assert re.match(r"[A-Za-z0-9]", segment)
    # Bounded: 64-char safe prefix + "-" + 12 hex.
    assert len(segment) <= 64 + 1 + 12
    # The safe prefix is filename-safe ASCII.
    prefix = segment[: -(1 + 12)]
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", prefix)


def test_sample_dir_segment_is_deterministic_and_collision_resistant() -> None:
    assert sample_dir_segment("a/b") == sample_dir_segment("a/b")
    # Both sanitize to the same safe prefix; the hash suffix keeps them apart.
    assert sample_dir_segment("a/b") != sample_dir_segment("a\\b")
    assert sample_dir_segment("a/b") != sample_dir_segment("a b")


def test_sample_dir_segment_traversal_id_readable_prefix() -> None:
    segment = sample_dir_segment("../../escape")
    assert segment == f"escape-{_hashed('../../escape')}"


def test_sample_dir_segment_flag_like_id_drops_leading_dashes() -> None:
    assert sample_dir_segment("--rf /") == f"rf-{_hashed('--rf /')}"
    # Nothing usable left after sanitizing: a fixed stand-in keeps the
    # segment alphanumeric-leading.
    assert sample_dir_segment("---") == f"id-{_hashed('---')}"


def test_sample_dir_segment_huge_id_is_bounded() -> None:
    huge = "/" + "y" * 10_240
    segment = sample_dir_segment(huge)
    assert len(segment) == 64 + 1 + 12
    assert segment == "y" * 64 + "-" + _hashed(huge)
