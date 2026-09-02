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
    home: str
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
        os.initgroups(user, pw.pw_gid)
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
    else:
        os.setgroups(user.groups)
        os.setgid(user.gid)
        os.setuid(user.uid)


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
            if os.isatty(0):
                # Claim the pty as controlling tty before dropping privileges, else
                # an interactive shell running as another user gets no job control.
                with contextlib.suppress(OSError):
                    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
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
    if isinstance(user, RunAs):
        return user.home
    try:
        return pwd.getpwnam(user).pw_dir
    except KeyError:
        return "/"
