import os
import pwd
from collections.abc import Callable


def is_current_user(username: str) -> bool:
    """Check if the given username matches the current process user."""
    try:
        return pwd.getpwnam(username).pw_uid == os.getuid()
    except KeyError:
        return False


def set_oom_score_adj() -> None:
    """Set oom_score_adj to make this process the preferred OOM-kill target."""
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("1000")
    except OSError:
        pass


def switch_user(username: str) -> None:
    """Switch the current process to the given user via setuid/setgid/initgroups.

    Also updates HOME, USER, and LOGNAME environment variables to match the
    target user. This is irreversible and should only be used in short-lived
    CLI processes. Raises RuntimeError if the user doesn't exist or permission
    is denied.
    """
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        raise RuntimeError(f"User {username!r} not found in /etc/passwd") from None
    try:
        os.initgroups(username, pw.pw_gid)
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
    except OSError:
        raise RuntimeError(
            f"Permission denied switching to user {username!r} "
            "(process may lack CAP_SETUID/CAP_SETGID)"
        ) from None
    os.environ["HOME"] = pw.pw_dir
    os.environ["USER"] = username
    os.environ["LOGNAME"] = username


def make_preexec(username: str | None) -> Callable[[], None]:
    """Build a preexec_fn that sets OOM score and optionally switches user.

    Args:
        username: If provided, switch to this user via setuid/setgid/initgroups.
            Requires the current process to be running as root.
    """

    def _preexec() -> None:
        set_oom_score_adj()
        if username is not None:
            try:
                pw = pwd.getpwnam(username)
            except KeyError:
                os.write(
                    2,
                    f"sandbox-tools: user {username!r} not found in /etc/passwd\n".encode(),
                )
                os._exit(1)
            try:
                os.initgroups(username, pw.pw_gid)
                os.setgid(pw.pw_gid)
                os.setuid(pw.pw_uid)
            except OSError:
                os.write(
                    2,
                    f"sandbox-tools: permission denied switching to user {username!r} (server may lack CAP_SETUID/CAP_SETGID)\n".encode(),
                )
                os._exit(1)

    return _preexec


def get_home_dir(username: str) -> str:
    """Get the home directory for a user from /etc/passwd, defaulting to '/'."""
    try:
        return pwd.getpwnam(username).pw_dir
    except KeyError:
        return "/"
