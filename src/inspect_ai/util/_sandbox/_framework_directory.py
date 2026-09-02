"""Create-or-adopt verified framework-owned directories inside a sandbox.

Inspect places files it later trusts (the sandbox-tools tree, for example) at fixed
paths inside sandboxes. An untrusted principal in the sandbox (the agent running as
the default user) can pre-create an entry at such a path, so a successful
``mkdir -p`` followed by a path-based ``chmod`` proves nothing about who controls
the directory. This module provides the one audited primitive for preparing such a
directory and for running commands against it.

The contract for a private framework directory is:

- it is a real directory, not a symbolic link (nor reached through one at the leaf);
- it is owned by the uid the sandbox command runs as (the intended owner);
- its mode is exactly ``0700``, so no other principal can read or modify it;
- its parent is owned by that uid or by root, and is either not writable by
  group/others or is sticky, so no other principal can rename or unlink the
  directory out from under a verified path.

The contract stops at the immediate parent. Ancestors above it are not checked,
so callers must choose paths whose ancestors are root-owned and not writable by
others (``/var/tmp/<name>`` qualifies: ``/var`` and ``/`` are root-owned ``0755``).
A path beneath a directory another principal controls (a home directory, a
project checkout) gets no guarantee from this helper: that principal can swap
the whole subtree between calls, and a later call verifying the same pathname
would be looking at a different object. Extending the walk to every ancestor is
a deliberate non-goal for now; revisit when a call site needs it.

Any pre-existing entry that does not satisfy the contract makes the operation fail
with :class:`FrameworkDirectoryError`. Nothing is silently repaired or replaced: a
wrong-mode or wrong-owner directory may already contain planted content, so the
caller (and ultimately the user) must decide what to do with it.

Verification runs inside a single POSIX ``sh`` invocation in the sandbox. The script
``cd -P``s into the directory and performs every check on ``.``, so the checks and
any command run afterwards are bound to the verified directory object rather than
re-resolving a pathname that could be swapped underneath them. The symlink test is
a ``pwd -P`` comparison after the ``cd``, which catches a symlink placed at the
leaf even if it appeared after the earlier ``test -L``.

Provider requirement: the script's verdicts travel on stderr, so the sandbox's
``exec`` must return stderr separately from stdout (as the built-in providers do).
A provider that merges the streams or drops stderr makes every call here fail as
"did not run", and callers then treat the user as unavailable.

Rootless sandboxes: when the command cannot run as root, the intended owner is the
sandbox's default uid. The contract still holds for that uid, but it does not
establish a boundary between the agent and the tools, because both run as the same
user.
"""

from pathlib import PurePosixPath
from typing import NamedTuple

from inspect_ai.util._subprocess import ExecResult

from .environment import SandboxEnvironment

# The script reports a verdict with a marker line on stderr and announces successful
# verification with a marker line just before it execs the wrapped command. A
# verdict is only honoured when verification did not complete, so the wrapped
# command's own stderr cannot forge one. Each verdict also has its own exit status
# for anyone reading a log, but the host does not rely on it (see `_verdict`).
_VIOLATION_MARKER = "INSPECT_FRAMEWORK_DIRECTORY_VIOLATION"
_VIOLATION_EXIT = 3
_MISSING_MARKER = "INSPECT_FRAMEWORK_DIRECTORY_MISSING"
_MISSING_EXIT = 4
_UNAVAILABLE_MARKER = "INSPECT_FRAMEWORK_DIRECTORY_UNAVAILABLE"
_UNAVAILABLE_EXIT = 5
_USER_MISMATCH_MARKER = "INSPECT_FRAMEWORK_DIRECTORY_USER_MISMATCH"
_USER_MISMATCH_EXIT = 6
_CREATE_FAILED_MARKER = "INSPECT_FRAMEWORK_DIRECTORY_CREATE_FAILED"
_CREATE_FAILED_EXIT = 7
_VERIFIED_MARKER = "INSPECT_FRAMEWORK_DIRECTORY_VERIFIED"

# Arguments: $1 = expected uid (empty = no expectation), $2 = create flag (1/0),
# $3 = parent path, $4 = leaf name, $5.. = command to exec with the verified
# directory as cwd (optional). POSIX sh only (dash/BusyBox):
# no arrays, no [[ ]], no local. `stat -c %u/%a` is common to GNU coreutils and
# BusyBox. `umask 077` closes the window in BusyBox's non-atomic `mkdir -m`
# (mkdir(0777) then chmod) and also applies to whatever the wrapped command creates:
# a non-root `tar` extracts entries at 0700/0600 instead of the archive's modes
# (root's `tar` preserves them). Inside a 0700 directory used by one uid this changes
# nothing observable. Tool output is captured with stderr discarded so a warning
# cannot be folded into a value; the error path re-runs the tool for its message.
# PATH is replaced outright with the system directories: the inherited value is
# not consulted at all, so a user-owned directory an image puts on PATH cannot
# supply `stat`/`id`/`mkdir` (or the wrapped command), a utility missing from the
# system directories fails rather than falling through, and an empty component
# (which shells resolve from the cwd, here the possibly world-writable parent)
# cannot appear. The shell itself is resolved by the provider before this runs,
# through the image's PATH, which is why the host launches it as `_SHELL`.
_SCRIPT = """
set -u
umask 077
unset CDPATH
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
expect=$1 create=$2 parent=$3 leaf=$4
shift 4
case $parent in
    /) dir=/$leaf ;;
    *) dir=$parent/$leaf ;;
esac
report() {
    printf '%s: %s\\n' "$1" "$2" >&2
    exit "$3"
}
violation() { report @VIOLATION@ "$*" @VIOLATION_EXIT@; }
missing() { report @MISSING@ "$*" @MISSING_EXIT@; }
unavailable() { report @UNAVAILABLE@ "$*" @UNAVAILABLE_EXIT@; }
usermismatch() { report @USER_MISMATCH@ "$*" @USER_MISMATCH_EXIT@; }
createfailed() { report @CREATE_FAILED@ "$*" @CREATE_FAILED_EXIT@; }
me=$(id -u 2>/dev/null) || unavailable "cannot determine the current uid: $(id -u 2>&1 >/dev/null)"
case $me in ''|*[!0-9]*) unavailable "unexpected output from id -u: $me" ;; esac
if [ -n "$expect" ] && [ "$me" != "$expect" ]; then
    usermismatch "running as uid $me, expected uid $expect"
fi
if [ ! -e "$parent" ] && [ ! -L "$parent" ]; then
    if [ "$create" = 1 ]; then
        # Missing parents get the conventional 0755 (as `mkdir -p` under the
        # default umask would give), not the 0700 our umask would produce: a
        # root-only /var/tmp would lock the default user out of it.
        err=$(umask 022 && mkdir -p -- "$parent" 2>&1) || [ -e "$parent" ] || createfailed "parent directory $parent: $err"
    else
        missing "parent directory $parent does not exist"
    fi
fi
err=$(cd -P -- "$parent" 2>&1) || violation "cannot enter parent directory $parent: $err"
cd -P -- "$parent" || violation "cannot enter parent directory $parent"
pstat=$(stat -c '%u %a' . 2>/dev/null) || unavailable "cannot stat parent directory $parent: $(stat -c '%u %a' . 2>&1 >/dev/null)"
puid=${pstat% *}
pmode=${pstat#* }
if [ "$puid" != "$me" ] && [ "$puid" != 0 ]; then
    if [ "$me" = 0 ]; then want="uid 0"; else want="uid $me or 0"; fi
    violation "parent directory $parent is owned by uid $puid (expected $want), so its owner could replace $dir"
fi
if [ $((0$pmode & 022)) -ne 0 ] && [ $((0$pmode & 01000)) -eq 0 ]; then
    violation "parent directory $parent has mode $pmode (writable by others, not sticky), so other users could replace $dir"
fi
phys=$(pwd -P)
case $phys in
    /) expected=/$leaf ;;
    *) expected=$phys/$leaf ;;
esac
created=0
if [ "$create" = 1 ] && [ ! -e "$leaf" ] && [ ! -L "$leaf" ]; then
    if err=$(mkdir -m 0700 -- "$leaf" 2>&1); then
        created=1
    else
        [ -e "$leaf" ] || [ -L "$leaf" ] || createfailed "$err"
    fi
fi
if [ -L "$leaf" ]; then violation "$dir is a symbolic link"; fi
if [ ! -e "$leaf" ]; then missing "$dir does not exist"; fi
[ -d "$leaf" ] || violation "$dir is not a directory"
err=$(cd -P -- "$leaf" 2>&1) || violation "cannot enter $dir: $err"
cd -P -- "$leaf" || violation "cannot enter $dir"
now=$(pwd -P)
[ "$now" = "$expected" ] || violation "$dir resolves to $now through a symbolic link"
dstat=$(stat -c '%u %a' . 2>/dev/null) || unavailable "cannot stat $dir: $(stat -c '%u %a' . 2>&1 >/dev/null)"
uid=${dstat% *}
mode=${dstat#* }
[ "$uid" = "$me" ] || violation "$dir is owned by uid $uid, expected uid $me"
if [ "$created" = 1 ] && [ "$mode" != 700 ]; then
    # We just created it and own it; a setgid parent may have added bits to it
    # (a numeric chmod alone does not clear setgid on a directory).
    chmod u=rwx,g=,o=,g-s . || violation "could not set mode of $dir"
    mode=$(stat -c %a . 2>/dev/null) || unavailable "cannot stat $dir: $(stat -c %a . 2>&1 >/dev/null)"
fi
[ "$mode" = 700 ] || violation "$dir has mode $mode, expected 700"
printf '%s\\n' @VERIFIED@ >&2
[ $# -eq 0 ] || exec "$@"
"""

for _placeholder, _value in {
    "@VIOLATION@": _VIOLATION_MARKER,
    "@VIOLATION_EXIT@": str(_VIOLATION_EXIT),
    "@MISSING@": _MISSING_MARKER,
    "@MISSING_EXIT@": str(_MISSING_EXIT),
    "@UNAVAILABLE@": _UNAVAILABLE_MARKER,
    "@UNAVAILABLE_EXIT@": str(_UNAVAILABLE_EXIT),
    "@USER_MISMATCH@": _USER_MISMATCH_MARKER,
    "@USER_MISMATCH_EXIT@": str(_USER_MISMATCH_EXIT),
    "@CREATE_FAILED@": _CREATE_FAILED_MARKER,
    "@CREATE_FAILED_EXIT@": str(_CREATE_FAILED_EXIT),
    "@VERIFIED@": _VERIFIED_MARKER,
}.items():
    _SCRIPT = _SCRIPT.replace(_placeholder, _value)


_SHELL = "/bin/sh"
"""Absolute path of the shell that runs the verification script.

A bare ``sh`` would be resolved by the provider through the image's PATH before the
script can pin its own, so an image with a default-user-writable directory ahead of
``/bin`` would let the agent supply the shell that root runs.
"""


class FrameworkDirectoryError(RuntimeError):
    """A framework directory cannot be trusted or used.

    Raised when the entry at the path is a symlink, not a directory, owned by another
    uid, has a mode other than ``0700``, sits in a parent that lets other principals
    replace it, or could not be created or entered. Callers must not fall back to a
    weaker owner or continue privileged work when this is raised.

    The message distinguishes an untrustworthy entry (which the user should remove)
    from a plain creation failure such as a read-only filesystem or an unwritable
    parent, where there is nothing to remove.
    """


class FrameworkDirectoryNotFoundError(FrameworkDirectoryError):
    """Nothing exists at the framework directory path (and creation was not requested)."""


class FrameworkDirectoryUnavailableError(RuntimeError):
    """The verification script ran but lacked a tool it needs (``stat`` or ``id``).

    Distinct from :class:`FrameworkDirectoryError`: this says nothing about the
    entry at the path, only that the sandbox cannot perform the check. Also distinct
    from the plain ``RuntimeError`` raised when the script did not run at all (no
    ``sh``, or the provider refused the requested user), which callers may treat as
    "this user is not available" and try another.
    """


class FrameworkDirectoryUserError(RuntimeError):
    """The verification script ran as a different uid than the caller required.

    Raised when ``expected_uid`` was given and ``id -u`` inside the sandbox reported
    another uid: the provider ignored or downgraded the requested ``user``. Nothing
    was checked or created, and this says nothing about the entry at the path. It
    exists so a caller cannot mistake "verified, owned by whoever I ran as" for
    "verified, owned by the user I asked for". Callers may treat it as "that user is
    not available in this sandbox" and choose another.
    """


class FrameworkPath(NamedTuple):
    """An absolute framework directory path split for the verification script."""

    parent: str
    leaf: str


def split_framework_path(path: str) -> FrameworkPath:
    """Split an absolute POSIX path into its parent and leaf name.

    Redundant separators and ``.`` components are normalized away.

    Raises:
        ValueError: If the path is relative, is the filesystem root, or contains
            ``..`` (which would make the ``pwd -P`` comparison ambiguous).
    """
    pure = PurePosixPath(path)
    if not pure.is_absolute():
        raise ValueError(f"framework directory path must be absolute: {path!r}")
    if pure.parent == pure:
        raise ValueError("framework directory path must not be the filesystem root")
    if ".." in pure.parts:
        raise ValueError(f"framework directory path must not contain '..': {path!r}")
    return FrameworkPath(parent=str(pure.parent), leaf=pure.name)


def _verdict(result: ExecResult[str], marker: str) -> str | None:
    """Return the script's message if it reported ``marker``.

    The exit status is deliberately not consulted. With the verified marker absent,
    only the script (or the provider) wrote to stderr, so the marker alone is
    authoritative; requiring the status as well would let a provider that does not
    propagate exit codes turn a violation into a "did not run" result, which callers
    may legitimately treat as "this user is unavailable" and downgrade.
    """
    for line in result.stderr.splitlines():
        if line.startswith(marker + ":"):
            return line[len(marker) + 1 :].strip()
    return None


def _strip_verified_marker(result: ExecResult[str]) -> ExecResult[str]:
    """Return ``result`` with the verified-marker line removed from stderr."""
    stderr = "\n".join(
        line for line in result.stderr.splitlines() if line != _VERIFIED_MARKER
    )
    if result.stderr.endswith("\n") and stderr:
        stderr += "\n"
    return ExecResult(
        success=result.success,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=stderr,
    )


async def _run_verified(
    sandbox: SandboxEnvironment,
    path: str,
    *,
    create: bool,
    cmd: list[str],
    user: str | None,
    expected_uid: int | None,
    timeout: int | None,
) -> ExecResult[str]:
    parent, leaf = split_framework_path(path)
    expect = "" if expected_uid is None else str(expected_uid)
    result = await sandbox.exec(
        [
            _SHELL,
            "-c",
            _SCRIPT,
            "sh",
            expect,
            "1" if create else "0",
            parent,
            leaf,
            *cmd,
        ],
        user=user,
        timeout=timeout,
    )
    if _VERIFIED_MARKER in result.stderr.splitlines():
        # Verification completed; whatever follows is the wrapped command's own
        # outcome (so any verdict-shaped line it printed is not ours).
        return _strip_verified_marker(result)
    if (message := _verdict(result, _MISSING_MARKER)) is not None:
        raise FrameworkDirectoryNotFoundError(
            f"Sandbox framework directory {path} does not exist: {message}"
        )
    if (message := _verdict(result, _VIOLATION_MARKER)) is not None:
        raise FrameworkDirectoryError(
            f"Sandbox framework directory {path} cannot be trusted: {message}. "
            "Remove the entry (or correct its ownership and permissions) and retry."
        )
    if (message := _verdict(result, _CREATE_FAILED_MARKER)) is not None:
        raise FrameworkDirectoryError(
            f"Cannot create sandbox framework directory {path}: {message}"
        )
    if (message := _verdict(result, _UNAVAILABLE_MARKER)) is not None:
        raise FrameworkDirectoryUnavailableError(
            f"Cannot verify sandbox framework directory {path}: {message}"
        )
    if (message := _verdict(result, _USER_MISMATCH_MARKER)) is not None:
        raise FrameworkDirectoryUserError(
            f"Sandbox framework directory check for {path} did not run as the "
            f"requested user{f' {user}' if user else ''}: {message}"
        )
    raise RuntimeError(
        f"Sandbox framework directory check for {path} did not run"
        f"{f' as {user}' if user else ''}: "
        f"{result.stderr or result.stdout or f'exit status {result.returncode}'}"
    )


async def ensure_framework_directory(
    sandbox: SandboxEnvironment,
    path: str,
    *,
    user: str | None,
    expected_uid: int | None = None,
    timeout: int | None = None,
) -> None:
    """Create or adopt ``path`` as a private framework directory owned by ``user``.

    A missing directory is created with mode ``0700``; missing parent components are
    created with the conventional ``0755``. An existing entry is adopted only if it
    already satisfies the contract described in the module docstring:
    a real directory owned by the uid the command runs as, mode ``0700``, in a parent
    other principals cannot use to replace it. Only the immediate parent is checked;
    ``path`` must sit under root-owned ancestors (see the module docstring). Concurrent creation by another
    instance of this helper is tolerated (the survivor is verified like any other
    existing entry).

    Args:
        sandbox: Sandbox to operate in.
        path: Absolute path of the directory.
        user: User to run as (as for ``sandbox.exec``). ``None`` runs as the
            sandbox default user, whose uid then becomes the expected owner.
        expected_uid: If given, the uid the command must actually run as; the
            check fails before touching anything when ``id -u`` disagrees. Pass
            ``0`` with ``user="root"`` so a provider that ignores ``user`` cannot
            pass off a default-user directory as root's.
        timeout: Optional timeout for the sandbox command.

    Raises:
        FrameworkDirectoryError: The entry violates the contract or could not be
            created or entered.
        FrameworkDirectoryUserError: The script ran as a uid other than
            ``expected_uid``; nothing was created.
        FrameworkDirectoryUnavailableError: The check itself could not be performed
            (missing ``stat``/``id`` in the sandbox).
        RuntimeError: The script could not run at all (no ``sh``, or the provider
            refused the requested user).
        ValueError: ``path`` is not an absolute, non-root path free of ``..``.
    """
    await _run_verified(
        sandbox,
        path,
        create=True,
        cmd=[],
        user=user,
        expected_uid=expected_uid,
        timeout=timeout,
    )


async def verify_framework_directory(
    sandbox: SandboxEnvironment,
    path: str,
    *,
    user: str | None,
    expected_uid: int | None = None,
    timeout: int | None = None,
) -> None:
    """Check that ``path`` is an existing directory satisfying the contract.

    Like :func:`ensure_framework_directory` but never creates anything: a missing
    directory raises :class:`FrameworkDirectoryNotFoundError`. Use this to re-check a
    directory immediately before acting on its contents with elevated authority.

    Args:
        sandbox: Sandbox to operate in.
        path: Absolute path of the directory.
        user: User to run as (as for ``sandbox.exec``); also the expected owner.
        expected_uid: If given, the uid the command must actually run as (see
            :func:`ensure_framework_directory`).
        timeout: Optional timeout for the sandbox command.

    Raises:
        FrameworkDirectoryNotFoundError: Nothing exists at ``path``.
        FrameworkDirectoryError: The entry violates the contract.
        FrameworkDirectoryUserError: The script ran as a uid other than
            ``expected_uid``.
        FrameworkDirectoryUnavailableError: The check itself could not be performed.
        RuntimeError: The script could not run at all.
        ValueError: ``path`` is not an absolute, non-root path free of ``..``.
    """
    await _run_verified(
        sandbox,
        path,
        create=False,
        cmd=[],
        user=user,
        expected_uid=expected_uid,
        timeout=timeout,
    )


async def exec_in_framework_directory(
    sandbox: SandboxEnvironment,
    path: str,
    cmd: list[str],
    *,
    user: str | None,
    expected_uid: int | None = None,
    timeout: int | None = None,
) -> ExecResult[str]:
    """Verify ``path`` and then run ``cmd`` with the verified directory as cwd.

    The verification and the command run in the same ``sh`` process: the shell
    ``cd``s into the directory, checks it, and ``exec``s ``cmd`` from there. Relative
    paths in ``cmd`` therefore refer to the verified directory object itself, not to
    whatever ``path`` names by the time the command starts. The directory is never
    created here; use :func:`ensure_framework_directory` first. ``cmd`` inherits the
    script's ``umask 077``, so anything it creates is private to the owner.

    Args:
        sandbox: Sandbox to operate in.
        path: Absolute path of the directory.
        cmd: Command to run; ``cmd[0]`` is resolved via the script's fixed
            system-directory ``PATH`` (never the sandbox's inherited one) unless it
            contains a slash (use ``./name`` for a program inside the directory).
        user: User to run as (as for ``sandbox.exec``); also the expected owner.
        expected_uid: If given, the uid the command must actually run as (see
            :func:`ensure_framework_directory`).
        timeout: Optional timeout for the sandbox command.

    Returns:
        The command's own result. A failing command is returned, not raised.

    Raises:
        FrameworkDirectoryNotFoundError: Nothing exists at ``path``.
        FrameworkDirectoryError: The directory violates the contract; ``cmd`` was
            not run.
        FrameworkDirectoryUserError: The script ran as a uid other than
            ``expected_uid``; ``cmd`` was not run.
        FrameworkDirectoryUnavailableError: The check itself could not be performed.
        RuntimeError: The script could not run at all (no ``sh``, or the provider
            refused the requested user); ``cmd`` was not run.
        ValueError: ``path`` is not an absolute, non-root path free of ``..``, or
            ``cmd`` is empty.
    """
    if not cmd:
        raise ValueError("cmd must not be empty")
    return await _run_verified(
        sandbox,
        path,
        create=False,
        cmd=cmd,
        user=user,
        expected_uid=expected_uid,
        timeout=timeout,
    )
