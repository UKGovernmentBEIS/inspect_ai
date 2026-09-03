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
    [
        "s7",
        "sample-7",
        "42",
        "a.b_c-d",
        "X",
        "0",
        "task_001.v2",
        # Any single path component was a usable dir name before, so it
        # keeps its name: spaces, punctuation, non-ASCII, leading `.`/`-`.
        "with space",
        "HumanEval:0",
        "a+b (1)",
        "ünïcödé",
        "日本語",
        ".hidden",
        "-flag",
        "--rf",
        "..x",
        "a" * 200,
        "日" * 66,  # 198 UTF-8 bytes
    ],
)
def test_sample_dir_segment_passes_through_single_component_ids(
    sample_id: str,
) -> None:
    """Existing checkpoint dirs keep their names, so they stay resumable."""
    assert sample_dir_segment(sample_id) == sample_id


@pytest.mark.parametrize("sample_id", ["a" * 201, "日" * 67])
def test_sample_dir_segment_hashes_over_long_ids(sample_id: str) -> None:
    """Past 200 UTF-8 bytes an id is hashed so ``mkdir`` never hits NAME_MAX."""
    segment = sample_dir_segment(sample_id)
    assert segment.endswith(f"~{_hashed(sample_id)}")
    assert len(f"{segment}__{10**6}".encode()) < 255


@pytest.mark.parametrize("sample_id", [0, 1, 42, 10**12, -1])
def test_sample_dir_segment_passes_through_int_ids(sample_id: int) -> None:
    assert sample_dir_segment(sample_id) == str(sample_id)


def _hashed(sample_id: str) -> str:
    return hashlib.sha256(sample_id.encode()).hexdigest()[:12]


@pytest.mark.parametrize(
    "sample_id",
    [
        "../../x",
        "a/b",
        "/abs",
        ".",
        "..",
        "-flag/x",
        "--rf /",
        "",
        "a\x00b",
        "a\\b",
        "a~b",
        "~",
    ],
)
def test_sample_dir_segment_rewrites_non_component_ids_to_one_safe_segment(
    sample_id: str,
) -> None:
    segment = sample_dir_segment(sample_id)
    assert segment != sample_id
    assert segment.endswith(f"~{_hashed(sample_id)}")
    # Exactly one path component, never a traversal.
    assert "/" not in segment and "\\" not in segment and "\x00" not in segment
    assert segment not in (".", "..")
    # Bounded: 64-char safe prefix + "~" + 12 hex.
    assert len(segment) <= 64 + 1 + 12
    # The readable prefix is filename-safe ASCII and starts alphanumeric.
    prefix = segment[: -(1 + 12)]
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", prefix)


def test_sample_dir_segment_is_deterministic_and_collision_resistant() -> None:
    assert sample_dir_segment("a/b") == sample_dir_segment("a/b")
    # Both sanitize to the same safe prefix; the hash suffix keeps them apart.
    assert sample_dir_segment("a/b") != sample_dir_segment("a\\b")
    assert sample_dir_segment("a/b") != sample_dir_segment("a~b")


def test_sample_dir_segment_hashed_form_never_collides_with_a_passthrough_id() -> None:
    """``~`` is reserved from the passthrough set, so the namespaces are disjoint."""
    hashed = sample_dir_segment("a/b")
    assert "~" in hashed
    # An id that literally equals the hashed form is itself rewritten (and
    # to something else), so two distinct ids cannot share a dir.
    assert sample_dir_segment(hashed) != hashed
    assert sample_dir_segment(hashed) != sample_dir_segment("a/b")


def test_sample_dir_segment_traversal_id_readable_prefix() -> None:
    segment = sample_dir_segment("../../escape")
    assert segment == f"escape~{_hashed('../../escape')}"


def test_sample_dir_segment_prefix_drops_sanitizer_debris() -> None:
    assert sample_dir_segment("--rf /") == f"rf~{_hashed('--rf /')}"
    # Nothing usable left after sanitizing: a fixed stand-in keeps the
    # segment readable.
    assert sample_dir_segment("---/") == f"id~{_hashed('---/')}"


def test_sample_dir_segment_huge_id_is_bounded() -> None:
    huge = "/" + "y" * 10_240
    segment = sample_dir_segment(huge)
    assert len(segment) == 64 + 1 + 12
    assert segment == "y" * 64 + "~" + _hashed(huge)
