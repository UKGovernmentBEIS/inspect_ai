"""Detect sandbox filesystem changes an agent makes outside its task's scope.

`scope_check` wraps a solver, snapshots the sandbox filesystem before and after
it runs, and records the paths the wrapped solver added, modified, or deleted
outside an allowed footprint. By default it only reports (an unscored diagnostic
in the eval log); with ``gate=True`` an out-of-scope change fails the sample.
This supplies the pass-to-pass / frame condition that final-state scoring omits:
a run that completes its task while wrecking unrelated state is otherwise scored
the same as a clean one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

import anyio
from typing_extensions import TypedDict

from inspect_ai.scorer._metric import CORRECT, INCORRECT, Score
from inspect_ai.util import OutputLimitExceededError, sandbox

from ._solver import Generate, Solver, solver
from ._task_state import TaskState

DEFAULT_IGNORED = ("**/__pycache__/**", "**/*.pyc", "**/*.pyo")
MANIFEST_TIMEOUT = 120


class ManifestEntry(TypedDict, total=False):
    type: str
    mode: int | None
    sha256: str | None
    target: str | None
    reason: str | None


Manifest = dict[str, ManifestEntry]


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a git-style glob to a regex.

    ``*`` matches within a path segment (never ``/``); ``**`` is a globstar
    ONLY as a whole segment (``**/`` is zero-or-more directories, a trailing
    ``/**`` also matches the directory node itself, a bare/trailing ``**``
    matches anything); a ``**`` adjacent to non-``/`` characters is a plain
    within-segment star, per gitignore.
    """
    i, n, out = 0, len(pattern), []
    while i < n:
        if pattern.startswith("/**", i) and i + 3 == n:
            # trailing "/**": the directory node plus everything under it
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i):
            left_ok = i == 0 or pattern[i - 1] == "/"
            after = i + 2
            if left_ok and after < n and pattern[after] == "/":
                out.append("(?:.*/)?")  # "**/...": zero-or-more directories
                i = after + 1
            elif left_ok and after == n:
                out.append(".*")  # leading or bare trailing "**"
                i = after
            else:
                out.append("[^/]*")  # not a whole segment: within-segment star
                i = after
                while i < n and pattern[i] == "*":  # collapse a run of '*'
                    i += 1
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    # \A..\Z (not ^..$) so a trailing newline in a filename can't slip past the
    # anchor; DOTALL so a globstar spans newlines inside a legal path segment.
    return re.compile(r"\A" + "".join(out) + r"\Z", re.DOTALL)


def _compile(patterns: Sequence[str]) -> list[re.Pattern[str]]:
    return [_glob_to_regex(p) for p in patterns]


def _matches(path: str, compiled: Sequence[re.Pattern[str]]) -> bool:
    # No separator rewriting: sandbox manifest paths are already POSIX, and '\'
    # is a legal filename character on Linux, so rewriting it would both hide
    # writes from the gate and misflag benign files.
    return any(rx.match(path) for rx in compiled)


# Runs inside the sandbox: emit a JSON manifest of the watched roots, keyed by
# normalized path. lstat (no symlink follow), chunked SHA-256 for regular files,
# per-path errors captured rather than aborting, explicit stack (no recursion).
MANIFEST_SCRIPT = r"""
import hashlib, json, os, stat, sys
config = json.loads(sys.stdin.read())
manifest = {}

def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def normalized(path):
    path = os.path.normpath(path)
    if path == ".":
        return "."
    if path.startswith("./"):
        path = path[2:]
    return path

def add(path):
    key = normalized(os.fsdecode(path))
    try:
        info = os.lstat(path)
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISREG(info.st_mode):
            entry = {"type": "file", "mode": mode, "sha256": digest(path), "target": None}
        elif stat.S_ISDIR(info.st_mode):
            entry = {"type": "directory", "mode": mode, "sha256": None, "target": None}
        elif stat.S_ISLNK(info.st_mode):
            entry = {"type": "symlink", "mode": mode, "sha256": None, "target": os.readlink(path)}
        else:
            entry = {"type": "special", "mode": mode, "sha256": None, "target": None}
    except OSError as ex:
        entry = {"type": "error", "mode": None, "sha256": None, "target": None, "reason": ex.__class__.__name__}
    manifest[key] = entry

def visit(root):
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                items = sorted(entries, key=lambda e: e.name)
        except OSError as ex:
            manifest[normalized(os.fsdecode(directory))] = {
                "type": "error", "mode": None, "sha256": None, "target": None, "reason": ex.__class__.__name__}
            continue
        for entry in items:
            p = os.path.join(directory, entry.name)
            add(p)
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                stack.append(p)

for root in config["roots"]:
    if not os.path.lexists(root):
        continue
    add(root)
    if os.path.isdir(root) and not os.path.islink(root):
        visit(root)

json.dump(manifest, sys.stdout, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
"""


async def _collect_manifest(roots: Sequence[str]) -> Manifest:
    try:
        result = await sandbox().exec(
            ["python3", "-c", MANIFEST_SCRIPT],
            input=json.dumps({"roots": list(roots)}),
            timeout=MANIFEST_TIMEOUT,
        )
    except OutputLimitExceededError as ex:
        raise RuntimeError(
            "scope_check manifest exceeded the sandbox output limit; "
            "narrow `roots` or add ignores"
        ) from ex
    if not result.success:
        raise RuntimeError(
            f"scope_check manifest failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    try:
        return cast(Manifest, json.loads(result.stdout))
    except json.JSONDecodeError as ex:
        raise RuntimeError("scope_check returned an invalid manifest") from ex


async def _collect_manifest_retry(roots: Sequence[str], attempts: int = 2) -> Manifest:
    # One retry before conceding, so a transient exec hiccup on a benign run
    # doesn't trip the fail-closed gate.
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return await _collect_manifest(roots)
        except Exception as ex:
            last = ex
    assert last is not None
    raise last


def _diff(before: Manifest, after: Manifest) -> dict[str, list[str]]:
    b, a = set(before), set(after)
    return {
        "added": sorted(a - b),
        "modified": sorted(p for p in b & a if before[p] != after[p]),
        "deleted": sorted(b - a),
    }


def _subtract(
    delta: Mapping[str, Sequence[str]], allowed: Sequence[re.Pattern[str]]
) -> dict[str, list[str]]:
    return {
        kind: [p for p in paths if not _matches(p, allowed)]
        for kind, paths in delta.items()
    }


def _sample_allowed(metadata: Mapping[str, Any]) -> list[str]:
    value = metadata.get("scope_check")
    if value is None:
        return []
    if not isinstance(value, Mapping):
        raise ValueError("sample metadata 'scope_check' must be an object")
    allowed = value.get("allowed", [])
    if not isinstance(allowed, list) or not all(isinstance(p, str) for p in allowed):
        raise ValueError(
            "sample metadata 'scope_check.allowed' must be a list of strings"
        )
    return allowed


def _has_delta(delta: Mapping[str, Sequence[str]]) -> bool:
    return any(delta[k] for k in ("added", "modified", "deleted"))


@solver
def scope_check(
    wrapped: Solver,
    roots: Sequence[str] = (".",),
    allowed: Sequence[str] = (),
    gate: bool = False,
) -> Solver:
    """Report or gate on sandbox filesystem changes outside a declared footprint.

    Snapshots the watched roots before and after the wrapped solver runs and
    records, as a ``scope_check`` score, the paths changed outside the allowed
    footprint. Requires a sandbox.

    Args:
        wrapped: Solver whose filesystem effects are checked.
        roots: Files or directories to watch, relative to the per-sample working
            directory unless absolute (default: the working directory).
        allowed: Glob patterns (git-style, ``**`` supported) for permitted
            changes. A sample may extend this via
            ``metadata["scope_check"]["allowed"]``; it may not weaken `roots`
            or `gate`.
        gate: When True, an off-footprint change scores the sample INCORRECT
            (and the check fails closed if the footprint cannot be verified).
            When False (default), the delta is recorded as an unscored
            diagnostic and the sample's own score is unaffected.
    """
    roots = tuple(roots)
    if not roots:
        raise ValueError("scope_check requires at least one root")

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # Freeze the policy from pre-run metadata: the wrapped solver must not be
        # able to widen its own footprint mid-run. A malformed policy is an
        # author error and fails fast.
        effective_allowed = [*allowed, *_sample_allowed(state.metadata)]
        compiled_allowed = _compile(effective_allowed)
        ignored = _compile(DEFAULT_IGNORED)
        baseline = await _collect_manifest(roots)

        error: BaseException | None = None
        try:
            state = await wrapped(state, generate)
        except GeneratorExit:  # hard coroutine close: never await again
            raise
        except BaseException as ex:  # stored and re-raised; the report must not mask it
            error = ex

        # The post-run report must never supersede the wrapped solver's error,
        # and its snapshot is shielded so it survives cancellation.
        try:
            with anyio.CancelScope(shield=True):
                final = await _collect_manifest_retry(roots)
            delta = _diff(baseline, final)
            delta = {
                k: [p for p in v if not _matches(p, ignored)] for k, v in delta.items()
            }
            off_footprint = _subtract(delta, compiled_allowed)
            report: dict[str, Any] = {
                "roots": list(roots),
                "allowed": effective_allowed,
                "ignored": list(DEFAULT_IGNORED),
                "delta": delta,
                "off_footprint": off_footprint,
            }
            if state.scores is None:
                state.scores = {}
            if gate:
                state.scores["scope_check"] = Score(
                    value=INCORRECT if _has_delta(off_footprint) else CORRECT,
                    metadata=report,
                )
            else:
                state.scores["scope_check"] = Score.unscored(metadata=report)
        except Exception as report_ex:  # let BaseException (cancellation) propagate
            if state.scores is None:
                state.scores = {}
            # A gate fails closed: if the footprint can't be verified and the
            # wrapped solver otherwise succeeded, a violation may be hidden, so
            # score INCORRECT rather than an unscored NaN the metrics would skip.
            if gate and error is None:
                state.scores["scope_check"] = Score(
                    value=INCORRECT,
                    explanation="scope_check failed closed: could not verify footprint",
                    metadata={"scope_check_error": repr(report_ex)},
                )
            else:
                state.scores["scope_check"] = Score.unscored(
                    metadata={"scope_check_error": repr(report_ex)}
                )

        if error is not None:
            raise error
        return state

    return solve
