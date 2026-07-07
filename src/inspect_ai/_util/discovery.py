"""Generic per-process service-discovery primitives.

Inspect's ACP server and control-channel server each advertise
themselves by writing a small JSON file describing how to reach
them (``<inspect_data_dir>/<subdir>/<pid>.json``). CLI clients
enumerate that directory, check each PID's liveness, and pick a
target.

This module owns the filesystem mechanics — directory permissions,
stale-file cleanup, PID-keyed write, JSON enumeration — so each
subsystem only needs to provide its directory and its own schema.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from inspect_ai._util import process as _process

PidAliveFn = Callable[[int], bool]


def _resolve_pid_alive(pid_alive_fn: PidAliveFn | None) -> PidAliveFn:
    """Pick the liveness function to use.

    When no override is supplied, defer to ``_process.pid_alive`` via
    module attribute lookup at *call* time — so a test that monkey-
    patches ``inspect_ai._util.process.pid_alive`` actually affects the
    next call. Capturing the function at import time would freeze the
    original reference and break that patching contract.
    """
    if pid_alive_fn is not None:
        return pid_alive_fn
    return _process.pid_alive


# Permission constants. Discovery directories are owner-only so other
# users on the same machine can't even traverse into them; discovery
# JSON files are owner-only so the socket path / PID aren't leaked.
DISCOVERY_DIR_MODE = 0o700
DISCOVERY_FILE_MODE = 0o600


def prepare_discovery_dir(
    dir_path: Path,
    pid_alive_fn: PidAliveFn | None = None,
) -> Path:
    """Ready the discovery directory for a server bind.

    Three things in one call (always paired in practice, so no point
    making the caller spell them out):

    1. Create the directory if missing.
    2. Lock it to 0700 (defence-in-depth — see "Security model" in
       design/control-channel.md).
    3. Sweep any stale ``<pid>.json`` entries left behind by processes
       that crashed without cleaning up, plus their orphan socket
       nodes.

    Idempotent — safe to call on every server start. The chmod is
    re-applied every time so a previously-misconfigured directory
    (created before this hardening landed, or by another tool) gets
    locked down on the next bind.
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    try:
        dir_path.chmod(DISCOVERY_DIR_MODE)
    except OSError:
        # Some filesystems (notably FUSE / network mounts) ignore
        # chmod. Continue rather than fail the eval — the dir is
        # already under inspect_data_dir which is user-scoped, so
        # the loss of defence-in-depth here is bounded.
        pass
    _sweep_stale_entries(dir_path, _resolve_pid_alive(pid_alive_fn))
    return dir_path


def write_discovery_file(dir_path: Path, pid: int, payload: dict[str, Any]) -> Path:
    """Write ``<dir_path>/<pid>.json`` owner-only (0600), atomically.

    Two guarantees:

    - **Owner-only by construction.** The file is created via ``os.open`` with
      mode ``0600`` rather than written and then ``chmod``-ed, so it is never
      — even momentarily — more permissive than owner-only. The payload
      carries the socket path + PID; a separate ``chmod`` that could fail
      (and, if swallowed, silently leave the file readable) would defeat the
      point of locking it down. ``os.open`` caps the mode by the umask, so the
      file can only ever be *less* permissive, never more.
    - **Atomic publish.** Written to a same-PID temp in ``dir_path`` (so the
      ``replace`` is a same-filesystem rename) and renamed over the final
      path, so a concurrent enumerator (``inspect ctl tasks``) sees the complete
      file or no file — never a torn / partial-JSON read.

    Caller is responsible for the payload schema. Returns the path written.
    """
    path = dir_path / f"{pid}.json"
    tmp = dir_path / f".{pid}.json.tmp"

    # Create owner-only at open() time (via the opener) rather than chmod-ing
    # afterwards, so the file — which carries the socket path + PID — is never,
    # even momentarily, more permissive than 0600. umask can only make it less.
    def _owner_only(file: str, flags: int) -> int:
        return os.open(file, flags, DISCOVERY_FILE_MODE)

    # Remove any leftover temp first: the opener's mode only applies to a
    # freshly created file, so opening a straggler (e.g. left by an earlier
    # crash) would inherit its mode, not 0600. The dir is 0700 and the temp is
    # PID-keyed, so there is no concurrent writer to race here.
    tmp.unlink(missing_ok=True)
    with open(tmp, "w", encoding="utf-8", opener=_owner_only) as f:
        json.dump(payload, f)
    tmp.replace(path)
    return path


def list_alive_discovery_entries(
    dir_path: Path,
    pid_alive_fn: PidAliveFn | None = None,
) -> list[dict[str, Any]]:
    """Enumerate live discovery entries in ``dir_path``.

    Returns the parsed JSON dicts for every ``<pid>.json`` file whose
    ``pid`` field references a still-alive process. Stale entries and
    malformed files are silently skipped, matching the best-effort
    resilience contract used across discovery-directory reads and
    sweeps.

    Caller is responsible for filtering/validating the dicts against
    their subsystem's expected schema.

    ``pid_alive_fn`` lets subsystems pass their own (monkey-patchable
    in tests) liveness function. Defaults to
    :func:`inspect_ai._util.process.pid_alive`.
    """
    fn = _resolve_pid_alive(pid_alive_fn)
    if not dir_path.exists():
        return []
    results: list[dict[str, Any]] = []
    for path in dir_path.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            pid = int(data.get("pid", -1))
        except (TypeError, ValueError):
            continue
        if pid <= 0 or not fn(pid):
            continue
        results.append(data)
    return results


def _sweep_stale_entries(dir_path: Path, pid_alive_fn: PidAliveFn) -> None:
    """Sweep discovery files whose owning PID is no longer alive.

    Also unlinks the orphan socket node recorded in the stale file's
    ``socket_path`` field (if any) so subsequent binds on the same
    path don't trip over a leftover inode. Best-effort — malformed
    files / IO errors silently skipped.

    Internal helper called by :func:`prepare_discovery_dir`; not
    exposed because nothing legitimately needs to run the sweep
    without also creating + locking down the directory.
    """
    if not dir_path.exists():
        return
    for path in dir_path.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            pid = int(data.get("pid", -1))
            if pid <= 0 or pid_alive_fn(pid):
                continue
            path.unlink(missing_ok=True)
            sock = data.get("socket_path")
            if sock:
                try:
                    Path(sock).unlink(missing_ok=True)
                except OSError:
                    pass
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
            continue
