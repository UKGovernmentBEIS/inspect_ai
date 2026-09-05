"""Create-or-adopt verified framework-owned directories inside a sandbox.

Inspect places files it later trusts (the sandbox-tools tree, for example) at fixed
paths inside sandboxes. An untrusted principal in the sandbox (the agent running as
the default user) can pre-create an entry at such a path, so a successful
``mkdir -p`` followed by a path-based ``chmod`` proves nothing about who controls
the directory. This module provides the one audited primitive for preparing such a
directory and for running commands against it, plus the two entry operations built
on it that every consumer needs: checking what kind of entry a name holds
(:func:`stat_in_framework_directory`) and publishing a file there complete and in
its final mode (:func:`write_file_in_framework_directory`).

The contract for a private framework directory is:

- it is a real directory, not a symbolic link (nor reached through one at the leaf);
- it is owned by the uid the sandbox command runs as (the intended owner);
- its mode is exactly the mode the caller asked for (``0700`` by default, so no
  other principal can read or modify it). A caller may ask for a wider mode such
  as ``0755`` when other principals must be able to read and traverse the
  directory, but never one that lets group or others write to it: the owner
  stays the only principal who can add, replace, or remove entries;
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
caller (and ultimately the user) must decide what to do with it. The one exception
is opt-in: ``ensure_framework_directory(..., repair_mode=True)`` sets the mode
of a directory the current uid already owns to the requested one (every other
check still applies). It exists for rootless sandboxes, below.

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

Image requirement: the script runs under ``/bin/sh`` with ``PATH`` fixed to
``/usr/sbin:/usr/bin:/sbin:/bin``, so ``stat``, ``id``, ``mkdir``, ``chmod``, and
any command a caller wraps must live in one of those four directories. An image
whose coreutils live elsewhere (a Nix-style store, or only under ``/usr/local``)
fails with :class:`FrameworkDirectoryUnavailableError` naming the missing tool
rather than picking up whatever the inherited ``PATH`` offers.

Rootless sandboxes: when the command cannot run as root, the intended owner is the
sandbox's default uid. The contract still holds for that uid, but it does not
establish a boundary between the agent and the tools, because both run as the same
user. A wider mode on a directory that uid owns therefore never exposed anything the
agent could not already reach, which is why ``repair_mode`` is safe there: it lets a
directory left by an older install (which created it ``0755``) be reused instead of
refused.
"""

from logging import getLogger
from pathlib import PurePosixPath
from typing import NamedTuple

from inspect_ai._util.trace import trace_message
from inspect_ai.util._subprocess import ExecResult

from .environment import SandboxEnvironment

logger = getLogger(__name__)

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
# $3 = repair-mode flag (1/0), $4 = required mode (octal, as `stat -c %a` prints
# it), $5 = parent path, $6 = leaf name, $7.. = command to exec with the verified
# directory as cwd (optional). POSIX sh only (dash/BusyBox):
# no arrays, no [[ ]], no local. `stat -c %u/%a` is common to GNU coreutils and
# BusyBox. `umask 077` closes the window in BusyBox's non-atomic `mkdir -m`
# (mkdir(0777) then chmod) and also applies to whatever the wrapped command creates:
# a non-root `tar` extracts entries at 0700/0600 instead of the archive's modes
# (root's `tar` preserves them). Inside a 0700 directory used by one uid this changes
# nothing observable; a caller using a wider directory mode must widen the mode of
# anything it wants other principals to read itself (see
# `exec_in_framework_directory`). Tool output is captured with stderr discarded so a warning
# cannot be folded into a value; the error path re-runs the tool for its message.
# PATH is replaced outright with the four base system directories: the inherited
# value is not consulted at all, so a user-owned directory an image puts on PATH
# cannot supply `stat`/`id`/`mkdir` (or the wrapped command), a utility missing from
# those directories fails rather than falling through, and an empty component
# (which shells resolve from the cwd, here the possibly world-writable parent)
# cannot appear. `/usr/local/{bin,sbin}` are deliberately excluded: Dockerfiles
# routinely hand them to the non-root user (`chown -R user /usr/local` for
# `npm install -g` or venv-less `pip install`), and nothing the script or the
# sandbox tools need lives there. The shell itself is resolved by the provider
# before this runs, through the image's PATH, which is why the host launches it
# as `SHELL_PATH`.
_SCRIPT = """
set -u
umask 077
unset CDPATH
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
expect=$1 create=$2 repair=$3 want=$4 parent=$5 leaf=$6
shift 6
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
# Not a violation: the parent is outside the contract (see module docstring), and
# this is normally an environment problem (a root-owned 0700 parent seen by the
# default user) with nothing at $dir to remove.
err=$(cd -P -- "$parent" 2>&1) || unavailable "cannot enter parent directory $parent: $err"
cd -P -- "$parent" || unavailable "cannot enter parent directory $parent"
pstat=$(stat -c '%u %a' . 2>/dev/null) || unavailable "cannot stat parent directory $parent: $(stat -c '%u %a' . 2>&1 >/dev/null)"
puid=${pstat% *}
pmode=${pstat#* }
if [ "$puid" != "$me" ] && [ "$puid" != 0 ]; then
    if [ "$me" = 0 ]; then owner_want="uid 0"; else owner_want="uid $me or 0"; fi
    violation "parent directory $parent is owned by uid $puid (expected $owner_want), so its owner could replace $dir"
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
    if err=$(mkdir -m "$want" -- "$leaf" 2>&1); then
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
if [ "$mode" != "$want" ]; then
    if [ "$created" = 1 ] || [ "$repair" = 1 ]; then
        # Either we just created it (a setgid parent may have added bits) or the
        # caller asked for an owned directory to be put in the required mode. `.` is
        # the verified object we own. GNU chmod keeps a directory's set-id bits
        # across a numeric mode, so clear them by name first; BusyBox `o-t` is a
        # no-op, so clear the sticky bit with the bare `-t` both implementations
        # honour. The numeric mode then sets exactly the permission bits wanted.
        chmod u-s,g-s,-t . && chmod "$want" . || violation "could not set mode of $dir"
        mode=$(stat -c %a . 2>/dev/null) || unavailable "cannot stat $dir: $(stat -c %a . 2>&1 >/dev/null)"
    fi
fi
[ "$mode" = "$want" ] || violation "$dir has mode $mode, expected $want"
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


SHELL_PATH = "/bin/sh"
"""Absolute path of the shell that runs the verification script.

A bare ``sh`` would be resolved by the provider through the image's PATH before the
script can pin its own, so an image with a default-user-writable directory ahead of
``/bin`` would let the agent supply the shell that root runs. Callers that run
their own privileged scripts in a sandbox should launch them the same way.
"""


class FrameworkDirectoryError(RuntimeError):
    """A framework directory cannot be trusted or used.

    Raised when the entry at the path is a symlink, not a directory, owned by another
    uid, has a mode other than the one required (and repair was not requested), sits
    in a parent that lets other principals replace it, or could not be created or
    entered. Callers must not fall back to a weaker owner or continue privileged
    work when this is raised.

    The message distinguishes an untrustworthy entry (which the user should remove)
    from a plain creation failure such as a read-only filesystem or an unwritable
    parent, where there is nothing to remove.
    """


class FrameworkDirectoryNotFoundError(FrameworkDirectoryError):
    """Nothing exists at the framework directory path (and creation was not requested)."""


class FrameworkDirectoryUnavailableError(RuntimeError):
    """The verification script ran but could not perform the check.

    Raised when the script lacked a tool it needs (``stat`` or ``id``) or could not
    enter the parent directory (no search permission on it, or it is not a
    directory). Distinct from :class:`FrameworkDirectoryError`: this says nothing
    about the entry at the path, so there is nothing to remove. Also distinct
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


DEFAULT_MODE = 0o700
"""Mode of a private framework directory: readable and writable by its owner only."""


def expected_uid_for(user: str | None) -> int | None:
    """The uid the helper must actually run as for ``user``, if the host knows it.

    Only root has a uid known to the host. Pinning it makes a provider that ignores
    or downgrades ``user`` (``LocalSandboxEnvironment`` does) fail a root call
    instead of passing off the default user's directory as root's. For any other
    user, including the default user (``None``), no expectation is made.
    """
    return 0 if user == "root" else None


def framework_directory_mode(mode: int) -> str:
    """Validate a framework directory mode and return it as the script expects it.

    The result is the octal permission string ``stat -c %a`` prints for a directory
    in that mode (``"700"``, ``"755"``), which is also what ``chmod`` and
    ``mkdir -m`` accept.

    Raises:
        ValueError: ``mode`` carries set-id or sticky bits, does not give its owner
            read, write, and search permission, or lets group or others write to
            the directory (which would let another principal add or replace entries
            behind the owner's back, defeating the point of verifying it).
    """
    if mode & ~0o777:
        raise ValueError(
            f"framework directory mode {mode:#o} must not include set-id or sticky bits"
        )
    if mode & 0o700 != 0o700:
        raise ValueError(
            f"framework directory mode {mode:#o} must give the owner rwx permission"
        )
    if mode & 0o022:
        raise ValueError(
            f"framework directory mode {mode:#o} must not be writable by group or others"
        )
    return format(mode, "o")


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
    repair_mode: bool = False,
    mode: int,
    cmd: list[str],
    user: str | None,
    expected_uid: int | None,
    timeout: int | None,
    input: str | bytes | None = None,
) -> ExecResult[str]:
    parent, leaf = split_framework_path(path)
    want = framework_directory_mode(mode)
    expect = "" if expected_uid is None else str(expected_uid)
    result = await sandbox.exec(
        [
            SHELL_PATH,
            "-c",
            _SCRIPT,
            "sh",
            expect,
            "1" if create else "0",
            "1" if repair_mode else "0",
            want,
            parent,
            leaf,
            *cmd,
        ],
        user=user,
        input=input,
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
    repair_mode: bool = False,
    mode: int = DEFAULT_MODE,
    timeout: int | None = None,
) -> None:
    """Create or adopt ``path`` as a framework directory owned by ``user``.

    A missing directory is created with ``mode``; missing parent components are
    created with the conventional ``0755``. An existing entry is adopted only if it
    already satisfies the contract described in the module docstring:
    a real directory owned by the uid the command runs as, in exactly ``mode``, in a
    parent other principals cannot use to replace it. Only the immediate parent is
    checked; ``path`` must sit under root-owned ancestors (see the module
    docstring). Concurrent creation by another instance of this helper is tolerated
    (the survivor is verified like any other existing entry).

    Args:
        sandbox: Sandbox to operate in.
        path: Absolute path of the directory.
        user: User to run as (as for ``sandbox.exec``). ``None`` runs as the
            sandbox default user, whose uid then becomes the expected owner.
        expected_uid: If given, the uid the command must actually run as; the
            check fails before touching anything when ``id -u`` disagrees. Pass
            ``0`` with ``user="root"`` so a provider that ignores ``user`` cannot
            pass off a default-user directory as root's.
        repair_mode: Also accept an existing directory the command's uid owns but
            whose mode is not ``mode``, setting it to ``mode`` in place and
            keeping its contents. The ``chmod`` runs on the verified directory
            object after the owner check, so it can only touch something that uid
            already owns; the symlink, type, owner, and parent checks still apply.
            Use this only where the owner shares its uid with every other
            principal in the sandbox (a rootless install), so the directory's
            mode never protected anything. Leave it off for a privileged owner
            such as root: a root-owned directory in an unexpected mode may hold
            content other users placed there, and must be refused.
        mode: Permission bits the directory must have (default ``0700``, private
            to the owner). Use a wider mode such as ``0755`` only when other
            principals must read and traverse the directory; the mode can never
            let group or others write (see :func:`framework_directory_mode`).
            Every later check of the same directory must ask for the same mode.
        timeout: Optional timeout for the sandbox command.

    Raises:
        FrameworkDirectoryError: The entry violates the contract or could not be
            created or entered.
        FrameworkDirectoryUserError: The script ran as a uid other than
            ``expected_uid``; nothing was created.
        FrameworkDirectoryUnavailableError: The check itself could not be performed
            (missing ``stat``/``id`` in the sandbox, or the parent directory
            cannot be entered).
        RuntimeError: The script could not run at all (no ``sh``, or the provider
            refused the requested user).
        ValueError: ``path`` is not an absolute, non-root path free of ``..``, or
            ``mode`` is not an acceptable framework directory mode.
    """
    await _run_verified(
        sandbox,
        path,
        create=True,
        repair_mode=repair_mode,
        mode=mode,
        cmd=[],
        user=user,
        expected_uid=expected_uid,
        timeout=timeout,
    )


async def try_ensure_framework_directory_as_root(
    sandbox: SandboxEnvironment,
    path: str,
    *,
    mode: int = DEFAULT_MODE,
    trace_tag: str,
    timeout: int | None = None,
) -> bool:
    """Create or adopt ``path`` as a root-owned framework directory, if root works.

    Runs :func:`ensure_framework_directory` as ``root`` with ``expected_uid=0`` and
    returns ``True`` once the directory is verified root-owned. Returns ``False``
    when the sandbox cannot exec as root, which includes a provider that accepts
    ``user="root"`` but runs the command as someone else
    (``LocalSandboxEnvironment`` ignores ``user``): the helper reports the uid
    mismatch before creating anything. Providers that refuse root signal it with
    provider-specific exceptions or a failing exit status, so any other exception
    from the exec is also read as "no root" (the trade-off is that an unrelated
    probe failure selects the rootless path too). Each fallback is traced under
    ``trace_tag``.

    A contract violation reported by the helper (the entry exists but is a
    symlink, is owned by another uid, has the wrong mode, ...) and a check that
    could not be performed are re-raised rather than read as "no root": falling
    back to the default user there would let whoever planted the entry decide
    which user owns the framework's files. Callers decide what the rootless
    fallback does (for instance whether ``repair_mode`` is appropriate for the
    default user), which is why this helper stops at the verdict.

    Args:
        sandbox: Sandbox to operate in.
        path: Absolute path of the directory.
        mode: Permission bits the directory must have (see
            :func:`ensure_framework_directory`).
        trace_tag: Trace category for the fallback messages.
        timeout: Optional timeout for the sandbox command.

    Returns:
        ``True`` if the directory was created or adopted as root; ``False`` if the
        sandbox cannot run commands as root and the caller should install as the
        default user.

    Raises:
        FrameworkDirectoryError: The entry violates the contract or could not be
            created or entered as root.
        FrameworkDirectoryUnavailableError: The check itself could not be performed.
        ValueError: ``path`` is not an absolute, non-root path free of ``..``, or
            ``mode`` is not an acceptable framework directory mode.
    """
    try:
        await ensure_framework_directory(
            sandbox, path, user="root", expected_uid=0, mode=mode, timeout=timeout
        )
        return True
    except (FrameworkDirectoryError, FrameworkDirectoryUnavailableError, ValueError):
        raise
    except FrameworkDirectoryUserError as ex:
        trace_message(
            logger,
            trace_tag,
            f"sandbox does not run commands as root; using default user: {ex}",
        )
        return False
    except Exception as ex:
        # Broad catch is deliberate: providers signal "cannot exec as root" by
        # raising provider-specific exception types (or a failing exit status), so
        # no narrower type is available (see the docstring).
        trace_message(
            logger,
            trace_tag,
            f"root probe of {path} failed; falling back to default user: {ex}",
        )
        return False


async def verify_framework_directory(
    sandbox: SandboxEnvironment,
    path: str,
    *,
    user: str | None,
    expected_uid: int | None = None,
    mode: int = DEFAULT_MODE,
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
        mode: Permission bits the directory must have (see
            :func:`ensure_framework_directory`).
        timeout: Optional timeout for the sandbox command.

    Raises:
        FrameworkDirectoryNotFoundError: Nothing exists at ``path``.
        FrameworkDirectoryError: The entry violates the contract.
        FrameworkDirectoryUserError: The script ran as a uid other than
            ``expected_uid``.
        FrameworkDirectoryUnavailableError: The check itself could not be performed.
        RuntimeError: The script could not run at all.
        ValueError: ``path`` is not an absolute, non-root path free of ``..``, or
            ``mode`` is not an acceptable framework directory mode.
    """
    await _run_verified(
        sandbox,
        path,
        create=False,
        mode=mode,
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
    mode: int = DEFAULT_MODE,
    input: str | bytes | None = None,
    timeout: int | None = None,
) -> ExecResult[str]:
    """Verify ``path`` and then run ``cmd`` with the verified directory as cwd.

    The verification and the command run in the same ``sh`` process: the shell
    ``cd``s into the directory, checks it, and ``exec``s ``cmd`` from there. Relative
    paths in ``cmd`` therefore refer to the verified directory object itself, not to
    whatever ``path`` names by the time the command starts. The directory is never
    created here; use :func:`ensure_framework_directory` first. ``cmd`` inherits the
    script's ``umask 077``, so anything it creates is private to the owner; in a
    directory with a wider ``mode``, ``cmd`` must ``chmod`` whatever other
    principals are meant to read.

    Keep ``cmd``'s stderr well under the sandbox output limit
    (``SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE``). Providers keep the tail of
    an over-limit stream, so a command that floods stderr pushes the verified marker
    out of the capture and the call is misreported as "did not run" (a plain
    ``RuntimeError``, which callers may read as "this user is unavailable").

    Args:
        sandbox: Sandbox to operate in.
        path: Absolute path of the directory.
        cmd: Command to run; ``cmd[0]`` is resolved via the script's fixed
            system-directory ``PATH`` (never the sandbox's inherited one) unless it
            contains a slash (use ``./name`` for a program inside the directory).
        user: User to run as (as for ``sandbox.exec``); also the expected owner.
        expected_uid: If given, the uid the command must actually run as (see
            :func:`ensure_framework_directory`).
        mode: Permission bits the directory must have (see
            :func:`ensure_framework_directory`).
        input: Standard input for ``cmd`` (as for ``sandbox.exec``). The
            verification script reads nothing from stdin, so ``cmd`` receives it
            whole; this lets a caller stream content (an archive for ``tar``)
            into the verified directory without staging a file first.
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
        ValueError: ``path`` is not an absolute, non-root path free of ``..``,
            ``mode`` is not an acceptable framework directory mode, or ``cmd`` is
            empty.
    """
    if not cmd:
        raise ValueError("cmd must not be empty")
    return await _run_verified(
        sandbox,
        path,
        create=False,
        mode=mode,
        cmd=cmd,
        user=user,
        expected_uid=expected_uid,
        input=input,
        timeout=timeout,
    )


def _entry_name(name: str) -> str:
    """Validate ``name`` as a single path component inside a framework directory.

    Raises:
        ValueError: ``name`` is empty, is ``.`` or ``..``, or contains a slash (an
            entry operation acts on a direct child of the verified directory only).
    """
    if not name or name in (".", "..") or "/" in name:
        raise ValueError(
            f"framework directory entry name must be a single path component: {name!r}"
        )
    return name


# Prints the raw st_mode of $1 in hex (as `stat -c %f` does, without following a
# symlink) or the word "missing" when nothing is there, so absence and a stat
# failure are told apart by the host.
_STAT_ENTRY = (
    'if [ -e "$1" ] || [ -L "$1" ]; then stat -c %f -- "$1"; else echo missing; fi'
)


async def stat_in_framework_directory(
    sandbox: SandboxEnvironment,
    path: str,
    name: str,
    *,
    user: str | None,
    expected_uid: int | None = None,
    mode: int = DEFAULT_MODE,
    timeout: int | None = None,
) -> int | None:
    """Return the raw ``st_mode`` of ``name`` inside the verified ``path``.

    ``None`` means nothing exists at that name. Otherwise the result is the entry's
    own ``st_mode`` (a symbolic link is not followed, so it reports ``S_ISLNK``);
    test it with the ``stat`` module (``stat.S_ISREG`` and friends). The raw mode is
    read rather than a type name because GNU ``stat`` localizes ``%F``. Callers
    decide what an unexpected kind of entry means: the sandbox tools reinstall over
    it, the human agent refuses to.

    Args:
        sandbox: Sandbox to operate in.
        path: Absolute path of the framework directory.
        name: Name of the entry inside it (a single path component).
        user: User to run as (as for ``sandbox.exec``); also the expected owner.
        expected_uid: If given, the uid the command must actually run as (see
            :func:`ensure_framework_directory`).
        mode: Permission bits the directory must have (see
            :func:`ensure_framework_directory`).
        timeout: Optional timeout for the sandbox command.

    Raises:
        RuntimeError: ``stat`` failed on an existing entry, or printed something
            that is not a hexadecimal mode.
        ValueError: ``name`` is not a single path component.
        Everything :func:`exec_in_framework_directory` raises (the directory was not
        verified, or the check could not run).
    """
    name = _entry_name(name)
    result = await exec_in_framework_directory(
        sandbox,
        path,
        ["sh", "-c", _STAT_ENTRY, "sh", name],
        user=user,
        expected_uid=expected_uid,
        mode=mode,
        timeout=timeout,
    )
    if not result.success:
        raise RuntimeError(f"Cannot stat {path}/{name}: {result.stderr.strip()}")
    output = result.stdout.strip()
    if output == "missing":
        return None
    try:
        return int(output, 16)
    except ValueError:
        raise RuntimeError(
            f"Unexpected output from stat of {path}/{name}: {output!r}"
        ) from None


def framework_file_mode(mode: int) -> str:
    """Validate the mode of a file published into a framework directory.

    Returns the octal string ``chmod`` accepts (``"755"``, ``"600"``).

    Raises:
        ValueError: ``mode`` carries set-id or sticky bits, does not let the owner
            read the file, or lets group or others write to it (which would let
            another principal rewrite content the framework later trusts).
    """
    if mode & ~0o777:
        raise ValueError(
            f"framework file mode {mode:#o} must not include set-id or sticky bits"
        )
    if not mode & 0o400:
        raise ValueError(f"framework file mode {mode:#o} must be readable by the owner")
    if mode & 0o022:
        raise ValueError(
            f"framework file mode {mode:#o} must not be writable by group or others"
        )
    return format(mode, "o")


# Writes stdin to a temporary name ($1.tmp) in the verified directory, sets its mode
# to $2 (the helper's `umask 077` would otherwise leave it private to the owner),
# and publishes it as $1 with `ln`, which fails rather than replacing an existing
# entry (`mv` would replace one; `ln` also fails on a filesystem without hard
# links, which then surfaces as a write error). The temporary name is cleared
# first so a retry after an interrupted write is not blocked by the leftover, and
# `set -C` refuses to clobber a regular file (or a symlink to one) that appears at
# that name in between; it is not a full symlink guard (dash writes through a
# symlink to a non-regular target), but only the directory owner can create entries
# here. The temporary name is removed whether or not `ln` succeeded.
_WRITE_ENTRY = (
    'rm -f -- "$1.tmp" && set -C && cat > "$1.tmp" && chmod -- "$2" "$1.tmp" || exit; '
    'ln -- "$1.tmp" "$1"; rc=$?; rm -f -- "$1.tmp"; exit $rc'
)


async def write_file_in_framework_directory(
    sandbox: SandboxEnvironment,
    path: str,
    name: str,
    contents: str | bytes,
    *,
    user: str | None,
    expected_uid: int | None = None,
    mode: int = DEFAULT_MODE,
    file_mode: int,
    timeout: int | None = None,
) -> None:
    """Publish ``contents`` as ``name`` inside the verified ``path``, atomically.

    The file only ever exists under its final name complete and in ``file_mode``:
    the content is written under a temporary name in the verified directory (the
    write runs with that directory object as its cwd, so nothing is staged in a
    location another principal could replace), given its mode, and then linked
    into place. An entry already at ``name`` is never replaced; the call fails and
    leaves it untouched. A temporary file left by an interrupted earlier call is
    cleared first, so retrying is safe.

    Args:
        sandbox: Sandbox to operate in.
        path: Absolute path of the framework directory.
        name: Name of the file inside it (a single path component).
        contents: File content, passed on stdin (as for ``sandbox.exec``).
        user: User to run as (as for ``sandbox.exec``); also the expected owner.
        expected_uid: If given, the uid the command must actually run as (see
            :func:`ensure_framework_directory`).
        mode: Permission bits the directory must have (see
            :func:`ensure_framework_directory`).
        file_mode: Permission bits the published file gets (see
            :func:`framework_file_mode`). In a directory with a wider ``mode``,
            this is what lets other principals read or run the file.
        timeout: Optional timeout for the sandbox command.

    Raises:
        RuntimeError: The file could not be written or published (including when
            an entry already exists at ``name``).
        ValueError: ``name`` is not a single path component, or ``file_mode`` is
            not an acceptable framework file mode.
        Everything :func:`exec_in_framework_directory` raises (the directory was not
        verified, or the check could not run).
    """
    name = _entry_name(name)
    result = await exec_in_framework_directory(
        sandbox,
        path,
        ["sh", "-c", _WRITE_ENTRY, "sh", name, framework_file_mode(file_mode)],
        user=user,
        expected_uid=expected_uid,
        mode=mode,
        input=contents,
        timeout=timeout,
    )
    if not result.success:
        raise RuntimeError(f"Cannot write {path}/{name}: {result.stderr.strip()}")
