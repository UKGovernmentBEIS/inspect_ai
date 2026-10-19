"""Pre-populate pytest's assertion-rewrite pyc cache before xdist spawns workers.

pytest imports every test module through its assertion rewriter: parse, rewrite
the asserts, compile, and cache the result as a ``__pycache__/*-pytest-*.pyc``
keyed on the source's mtime and size. Under xdist every worker collects the
whole suite, and they start simultaneously against the same cold cache, so each
of the N workers redoes the identical rewrite of every test module (~24s of CPU
for this suite's ~620 modules, N times over). The controller, which does not
collect, sits idle meanwhile.

``prewarm_rewritten_pycs`` runs on the controller before the workers exist: it
forks one short-lived process per CPU, splits the not-yet-cached test modules
among them, and has each write the pyc pytest itself would have written (same
``_rewrite_test``, same ``_write_pyc``, same config). The workers then find a
valid cache for every module and skip straight to executing it. Only files
whose cache is missing or stale are rewritten; a warm tree costs one 16-byte
header read per file.

Keeps to pytest's own rewrite functions rather than reimplementing them, so the
cached code object is identical to what a worker would produce (the marshal
bytes can differ in reference-flag encoding; the unmarshalled code is equal).
Those functions are private; if a pytest upgrade removes or reshapes them the
prewarm is skipped with the reason in pytest's report header and the workers
rewrite as before. ``tests/test_pyc_prewarm.py`` pins the equivalence.
"""

from __future__ import annotations

import gc
import importlib.util
import os
import sys
import threading
import time
import warnings
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest
from _pytest.assertion.rewrite import (
    PYC_TAIL,
    _rewrite_test,
    _write_pyc,
    assertstate_key,
    get_cache_dir,
    try_makedirs,
)
from _pytest.pathlib import fnmatch_ex

if TYPE_CHECKING:
    from _pytest.assertion import AssertionState


class PrewarmResult(NamedTuple):
    """What a prewarm pass did, for pytest's report header and for tests."""

    candidates: int
    """Test modules pytest would rewrite on import."""

    stale: int
    """Of those, how many lacked a current cached pyc before the pass."""

    rewritten: int
    """Stale modules whose cached pyc is current after the pass."""

    processes: int
    """Child processes forked (0 when nothing was stale)."""

    failed_processes: int
    """Children that exited abnormally; their remaining files stay uncached."""

    seconds: float
    """Wall time of the pass, including the staleness scans."""

    skipped: str | None = None
    """Why nothing ran, when the pass was skipped."""

    @classmethod
    def skip(cls, reason: str) -> PrewarmResult:
        return cls(0, 0, 0, 0, 0, 0.0, reason)

    def describe(self) -> str:
        """One line for pytest's report header."""
        if self.skipped is not None:
            return f"skipped ({self.skipped})"
        line = (
            f"{self.candidates} test modules, {self.stale} stale, {self.rewritten} "
            f"rewritten by {self.processes} processes in {self.seconds:.1f}s"
        )
        if self.failed_processes:
            line += f"; {self.failed_processes} process(es) failed"
        return line


def rewrite_candidates(config: pytest.Config, args: Sequence[str]) -> list[Path]:
    """Files under ``args`` that pytest's import hook would assertion-rewrite.

    Mirrors ``AssertionRewritingHook._should_rewrite``: a file named on the
    command line is always rewritten; within a directory, ``conftest.py`` files
    and modules matching the ``python_files`` patterns are. Directories in
    ``norecursedirs`` are not excluded; rewriting a module pytest never
    collects is harmless (its pyc has a pytest-specific tag no plain import
    ever looks at). Paths are made absolute without resolving symlinks, as
    pytest does, so the cached code's filename matches the worker's. Sorted
    largest-first so a round-robin split balances.
    """
    patterns: list[str] = list(config.getini("python_files"))
    root = Path(config.invocation_params.dir)
    seen: set[Path] = set()
    for arg in args:
        path = root / arg.split("::", 1)[0]
        found: Iterator[Path]
        if path.is_dir():
            found = (
                p
                for p in path.rglob("*.py")
                if "__pycache__" not in p.parts
                and (
                    p.name == "conftest.py"
                    or any(fnmatch_ex(pat, p) for pat in patterns)
                )
            )
        elif path.is_file():
            found = iter([path])
        else:
            continue
        seen.update(Path(os.path.abspath(p)) for p in found)
    return sorted(seen, key=lambda p: p.stat().st_size, reverse=True)


def cached_pyc_path(source: Path) -> Path:
    """Where pytest caches the rewritten module for ``source``."""
    return get_cache_dir(source) / (source.name[:-3] + PYC_TAIL)


def pyc_is_current(source: Path) -> bool:
    """Whether ``source`` has a cached pyc whose header pytest would accept.

    Checks the same fields as pytest's ``_read_pyc`` (magic, zero flags, source
    mtime and size; PEP 552 layout) without unmarshalling the code, so scanning
    hundreds of warm files costs milliseconds rather than a third of a second.
    A false positive only means the worker rewrites that file itself.
    """
    try:
        stat = os.stat(source)
        with open(cached_pyc_path(source), "rb") as fp:
            header = fp.read(16)
    except OSError:
        return False
    return (
        len(header) == 16
        and header[:4] == importlib.util.MAGIC_NUMBER
        and header[4:8] == b"\x00\x00\x00\x00"
        and int.from_bytes(header[8:12], "little") == int(stat.st_mtime) & 0xFFFFFFFF
        and int.from_bytes(header[12:16], "little") == stat.st_size & 0xFFFFFFFF
    )


def rewrite_to_cache(
    source: Path, config: pytest.Config, state: AssertionState
) -> bool:
    """Write the rewritten pyc for ``source`` exactly as pytest's import hook would.

    Best effort: returns False (writing nothing) when the cache directory is
    unwritable, the source does not compile, or parsing/rewriting it emits any
    warning (a ``SyntaxWarning``, pytest's "assertion is always true"). The
    worker's own import then compiles that module under pytest's collection-
    time warning capture, so the error or warning is reported exactly as it
    would be without the prewarm; a child compiling it here would instead
    print the warning raw to stderr and leave it out of the warnings summary.
    """
    pyc = cached_pyc_path(source)
    try:
        if not try_makedirs(pyc.parent):
            return False
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            source_stat, code = _rewrite_test(source, config)
        return _write_pyc(state, code, source_stat, pyc)
    except Exception:
        return False


def prewarm_files(
    files: Sequence[Path], config: pytest.Config, processes: int
) -> PrewarmResult:
    """Rewrite every file in ``files`` lacking a current cached pyc, in parallel.

    Forks ``processes`` children (fewer if there is less work), each taking a
    round-robin slice of the stale files, and waits for all of them. A child
    that dies leaves the rest of its slice uncached, which the workers then
    rewrite themselves, and is counted in ``failed_processes``; ``rewritten``
    is verified against the cache after the children exit, never assumed.
    """
    started = time.perf_counter()
    state = config.stash[assertstate_key]
    stale = [f for f in files if not pyc_is_current(f)]
    procs = min(processes, len(stale))
    pids: list[int] = []
    failed = 0
    try:
        for i in range(procs):
            pid = os.fork()
            if pid == 0:
                # child: no shared state to restore, so exit without unwinding
                # the inherited interpreter (atexit handlers, pytest teardown)
                status = 0
                try:
                    gc.disable()
                    for f in stale[i::procs]:
                        rewrite_to_cache(f, config, state)
                except BaseException:
                    status = 1
                os._exit(status)
            pids.append(pid)
    finally:
        for pid in pids:
            _, wait_status = os.waitpid(pid, 0)
            if not (os.WIFEXITED(wait_status) and os.WEXITSTATUS(wait_status) == 0):
                failed += 1
    return PrewarmResult(
        candidates=len(files),
        stale=len(stale),
        rewritten=sum(1 for f in stale if pyc_is_current(f)),
        processes=len(pids),
        failed_processes=failed,
        seconds=time.perf_counter() - started,
    )


def prewarm_rewritten_pycs(config: pytest.Config) -> PrewarmResult | None:
    """Controller-side hook body: prewarm when this run will distribute to workers.

    Returns None on a worker and in non-distributed runs, where there is
    nothing to report. Returns a skipped result (reason in ``skipped``) when
    bytecode writing is off, off Linux (fork after import is only safe there),
    once any other thread exists (forking a multi-threaded process can deadlock
    the child), under ``--assert=plain``, or if the pass itself fails.
    """
    if hasattr(config, "workerinput"):
        return None
    numprocesses = getattr(config.option, "numprocesses", None)
    if not isinstance(numprocesses, int) or numprocesses < 1:
        return None
    if sys.dont_write_bytecode:
        return PrewarmResult.skip("bytecode writing is disabled")
    if sys.platform != "linux":
        return PrewarmResult.skip("fork after import is only safe on Linux")
    if threading.active_count() != 1:
        return PrewarmResult.skip("other threads are running")
    if assertstate_key not in config.stash:
        return PrewarmResult.skip("assertion rewriting is off")
    try:
        files = rewrite_candidates(config, config.args)
        return prewarm_files(files, config, len(os.sched_getaffinity(0)))
    except Exception as ex:
        return PrewarmResult.skip(repr(ex))
