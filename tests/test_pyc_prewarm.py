"""Meta-tests for the assertion-rewrite pyc prewarm in tests/conftest.py.

The prewarm (``test_helpers.pyc_prewarm``) leans on pytest's private rewrite
functions to write, ahead of the xdist workers, exactly the cached pyc each
worker would otherwise write itself. These tests pin the two properties the
speedup depends on: pytest accepts the prewarmed pyc as valid for the source
(else every worker silently rewrites anyway and the prewarm is dead weight),
and the code in it is what pytest's own rewrite produces.
"""

import importlib.util
import sys
import warnings
from pathlib import Path

import pytest
from _pytest.assertion.rewrite import _read_pyc, _rewrite_test, assertstate_key
from test_helpers import pyc_prewarm
from test_helpers.pyc_prewarm import (
    PrewarmResult,
    cached_pyc_path,
    prewarm_files,
    pyc_is_current,
    rewrite_candidates,
    rewrite_to_cache,
)

_TEST_SOURCE = "def test_something():\n    x = 1\n    assert x == 2, 'nope'\n"


def _write_test_module(path: Path, body: str = _TEST_SOURCE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_rewrite_candidates_match_pytest_rewrite_rules(
    tmp_path: Path, pytestconfig: pytest.Config
) -> None:
    tree = tmp_path / "suite"
    expected = {
        _write_test_module(tree / "test_a.py"),
        _write_test_module(tree / "sub" / "b_test.py"),
        _write_test_module(tree / "sub" / "conftest.py", "x = 1\n"),
    }
    helper = _write_test_module(tree / "helper.py", "x = 1\n")  # not a test module
    _write_test_module(tree / "__pycache__" / "test_stale.py")  # cache dir
    (tree / "notes.txt").write_text("not python")

    assert set(rewrite_candidates(pytestconfig, [str(tree)])) == expected

    # a file named on the command line is rewritten whatever its name, and a
    # node id resolves to its file
    assert rewrite_candidates(pytestconfig, [str(helper)]) == [helper]
    assert rewrite_candidates(pytestconfig, [f"{tree / 'test_a.py'}::test_x"]) == [
        tree / "test_a.py"
    ]
    assert rewrite_candidates(pytestconfig, [str(tree / "missing")]) == []


def test_rewrite_to_cache_writes_pyc_pytest_accepts(
    tmp_path: Path, pytestconfig: pytest.Config
) -> None:
    source = _write_test_module(tmp_path / "test_mod.py")
    state = pytestconfig.stash[assertstate_key]
    assert not pyc_is_current(source)

    assert rewrite_to_cache(source, pytestconfig, state)

    assert pyc_is_current(source)
    cached = _read_pyc(source, cached_pyc_path(source))
    assert cached is not None, "pytest rejected the prewarmed pyc"
    _, expected = _rewrite_test(source, pytestconfig)
    assert cached == expected


def test_pyc_is_current_reads_checked_hash_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pytest 9.2 writes a PEP 552 checked-hash pyc (flags 03000000 + the source
    # hash). The installed pytest here writes the old mtime/size format, so
    # force the hash branch to prove it reads that header regardless.
    monkeypatch.setattr(pyc_prewarm, "_CHECKED_HASH_PYC", True)
    source = _write_test_module(tmp_path / "test_mod.py")

    def write_header(flags: bytes, source_bytes: bytes) -> None:
        pyc = cached_pyc_path(source)
        pyc.parent.mkdir(parents=True, exist_ok=True)
        hash8 = importlib.util.source_hash(source_bytes)[:8]
        pyc.write_bytes(importlib.util.MAGIC_NUMBER + flags + hash8 + b"payload")

    # accepted when the stored hash matches the current source
    write_header(b"\x03\x00\x00\x00", source.read_bytes())
    assert pyc_is_current(source)

    # editing the source makes the stored hash stale, so it is rejected
    source.write_text(_TEST_SOURCE + "y = 1\n")
    assert not pyc_is_current(source)

    # rejected on the old-format flags even when the hash matches
    write_header(b"\x00\x00\x00\x00", source.read_bytes())
    assert not pyc_is_current(source)


def test_rewrite_to_cache_leaves_unparsable_source_to_the_worker(
    tmp_path: Path, pytestconfig: pytest.Config
) -> None:
    source = _write_test_module(tmp_path / "test_bad.py", "def broken(:\n")
    state = pytestconfig.stash[assertstate_key]

    assert not rewrite_to_cache(source, pytestconfig, state)
    assert not cached_pyc_path(source).exists()


@pytest.mark.parametrize(
    "body",
    [
        # compiler warning (SyntaxWarning on 3.12+, DeprecationWarning before)
        pytest.param('def test_x():\n    assert "\\d" == r"\\d"\n', id="escape"),
        # pytest's own rewrite-time PytestAssertRewriteWarning
        pytest.param("def test_x():\n    assert (1, 'msg')\n", id="always-true"),
    ],
)
def test_rewrite_to_cache_leaves_warning_emitting_source_to_the_worker(
    body: str, tmp_path: Path, pytestconfig: pytest.Config
) -> None:
    # were it cached here, the worker would load the pyc without compiling and
    # the warning would never reach pytest's warnings summary
    source = _write_test_module(tmp_path / "test_warns.py", body)
    state = pytestconfig.stash[assertstate_key]

    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        assert not rewrite_to_cache(source, pytestconfig, state)
    assert not cached_pyc_path(source).exists()
    assert emitted == [], "the helper let the warning escape instead of bailing"


def _counts(result: PrewarmResult) -> PrewarmResult:
    """The result with its wall time zeroed, so it compares by field name."""
    assert result.seconds > 0 and result.skipped is None
    return result._replace(seconds=0.0)


@pytest.mark.skipif(sys.platform != "linux", reason="prewarm forks; Linux only")
# Under xdist the worker carries an execnet thread, so Python 3.12+ warns on
# fork(); the real controller path is kept warning-free by its thread guard.
@pytest.mark.filterwarnings(
    "ignore:This process .* is multi-threaded:DeprecationWarning"
)
def test_prewarm_files_rewrites_only_stale_and_reports(
    tmp_path: Path, pytestconfig: pytest.Config
) -> None:
    sources = [
        _write_test_module(tmp_path / f"test_{i}.py", _TEST_SOURCE + f"y = {i}\n")
        for i in range(5)
    ]
    state = pytestconfig.stash[assertstate_key]
    assert rewrite_to_cache(sources[0], pytestconfig, state)

    result = prewarm_files(sources, pytestconfig, processes=2)

    assert _counts(result) == PrewarmResult(
        candidates=5, stale=4, rewritten=4, processes=2, failed_processes=0, seconds=0.0
    )
    for source in sources:
        cached = _read_pyc(source, cached_pyc_path(source))
        assert cached is not None, f"no valid pyc for {source.name}"
        assert cached == _rewrite_test(source, pytestconfig)[1]

    # everything cached now: nothing to do, no children forked
    assert _counts(prewarm_files(sources, pytestconfig, processes=2)) == PrewarmResult(
        candidates=5, stale=0, rewritten=0, processes=0, failed_processes=0, seconds=0.0
    )

    # editing a source changes its size and content, so it invalidates its own
    # entry under either cache key (mtime+size or source hash), whatever the
    # mtime granularity
    sources[2].write_text(_TEST_SOURCE + "y = 'changed'\n")
    assert _counts(prewarm_files(sources, pytestconfig, processes=2)) == PrewarmResult(
        candidates=5, stale=1, rewritten=1, processes=1, failed_processes=0, seconds=0.0
    )
    refreshed = _read_pyc(sources[2], cached_pyc_path(sources[2]))
    assert refreshed is not None
    assert refreshed == _rewrite_test(sources[2], pytestconfig)[1]


def test_describe_reports_skip_reason_and_failures() -> None:
    assert PrewarmResult.skip("no fork here").describe() == "skipped (no fork here)"
    ran = PrewarmResult(
        candidates=10,
        stale=6,
        rewritten=4,
        processes=2,
        failed_processes=1,
        seconds=1.25,
    )
    assert ran.describe() == (
        "10 test modules, 6 stale, 4 rewritten by 2 processes in 1.2s; "
        "1 process(es) failed"
    )
