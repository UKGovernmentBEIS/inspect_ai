import contextlib
import fcntl
import os
import pwd
import termios
from collections.abc import Callable

from pydantic import BaseModel


class RunAs(BaseModel):
    """Numeric identity of the sandbox's default exec user, captured by the host."""

    uid: int
    gid: int
    groups: list[int]
    home: str | None = None
    """HOME of the default exec; None when unset there (use the passwd home)."""
    model_config = {"extra": "forbid"}


def is_current_user(user: str | RunAs) -> bool:
    """Check if the given user matches the current process user (full identity for RunAs)."""
    if isinstance(user, RunAs):
        return (user.uid, user.gid, sorted(user.groups)) == (
            os.getuid(),
            os.getgid(),
            sorted(os.getgroups()),
        )
    try:
        return pwd.getpwnam(user).pw_uid == os.getuid()
    except KeyError:
        return False


def set_oom_score_adj() -> None:
    """Set oom_score_adj to make this process the preferred OOM-kill target."""
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("1000")
    except OSError:
        pass


def _switch(user: str | RunAs) -> None:
    """Switch identity; KeyError for an unknown username, OSError if denied."""
    if isinstance(user, str):
        pw = pwd.getpwnam(user)
        uid, gid = pw.pw_uid, pw.pw_gid
    else:
        uid, gid = user.uid, user.gid
    if os.isatty(0):
        # As container runtimes do for an exec with a tty: claim the pty as
        # controlling tty (else an interactive shell gets no job control) and hand
        # it to the new user so programs that re-open their terminal by path can.
        with contextlib.suppress(OSError):
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        with contextlib.suppress(OSError):
            os.fchown(0, uid, gid)
    if isinstance(user, str):
        os.initgroups(user, gid)
    else:
        os.setgroups(user.groups)
    os.setgid(gid)
    os.setuid(uid)


def switch_user(user: str | RunAs) -> None:
    """Switch the current process to the given user via setuid/setgid/groups.

    This only changes the Unix identity (uid/gid/groups). Callers are
    responsible for updating environment variables (e.g. HOME) as needed.
    This is irreversible and should only be used in short-lived CLI processes.
    Raises RuntimeError if the user doesn't exist or permission is denied.
    """
    try:
        _switch(user)
    except KeyError:
        raise RuntimeError(f"User {user!r} not found in /etc/passwd") from None
    except OSError:
        raise RuntimeError(
            f"Permission denied switching to user {user!r} "
            "(process may lack CAP_SETUID/CAP_SETGID)"
        ) from None


def make_preexec(user: str | RunAs | None) -> Callable[[], None]:
    """Build a preexec_fn that sets OOM score and optionally switches user.

    Args:
        user: If provided, switch to this user via setuid/setgid/groups.
            Requires the current process to be running as root.
    """

    def _preexec() -> None:
        set_oom_score_adj()
        if user is not None:
            try:
                _switch(user)
            except KeyError:
                os.write(
                    2,
                    f"sandbox-tools: user {user!r} not found in /etc/passwd\n".encode(),
                )
                os._exit(1)
            except OSError:
                os.write(
                    2,
                    f"sandbox-tools: permission denied switching to user {user!r} (server may lack CAP_SETUID/CAP_SETGID)\n".encode(),
                )
                os._exit(1)

    return _preexec


def get_home_dir(user: str | RunAs) -> str:
    """Get the user's home directory (from /etc/passwd for a username, defaulting to '/')."""
    if isinstance(user, RunAs) and user.home is not None:
        return user.home
    try:
        pw = pwd.getpwuid(user.uid) if isinstance(user, RunAs) else pwd.getpwnam(user)
        return pw.pw_dir
    except KeyError:
        return "/"
