"""Best-effort identity lookup for the view server.

Used to prefill the Author field on the viewer's edit dialogs. This is
*not* an auth mechanism — the client can still send any author string
on `provenance.author`. The endpoint just saves the user a step.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess

from pydantic import BaseModel


class UserInfo(BaseModel):
    """Best-effort identity for the user running the view server."""

    name: str | None = None
    """Short identifier suitable for `provenance.author` (e.g. "ransom").

    Resolved in order: local-part of `git user.email`, then `git user.name`,
    then `getpass.getuser()`. The email local-part is preferred because the
    audit trail conventionally uses a handle-style alias rather than a
    legal name.
    """

    email: str | None = None
    """Email (git user.email), if known."""


def user_info() -> UserInfo:
    """Return the user's git alias, falling back to user.name / OS login."""
    name: str | None = None
    email: str | None = None

    git = shutil.which("git")
    if git is not None:
        email = _git_config(git, "user.email")
        # Prefer the email local-part — `ransom@meridianlabs.ai` → `ransom`.
        if email and "@" in email:
            local_part = email.split("@", 1)[0].strip()
            if local_part:
                name = local_part
        # Fall back to the configured display name if no usable email.
        if not name:
            name = _git_config(git, "user.name")

    if not name:
        try:
            name = getpass.getuser()
        except Exception:
            name = os.environ.get("USER") or os.environ.get("USERNAME")

    return UserInfo(name=name or None, email=email or None)


def _git_config(git: str, key: str) -> str | None:
    try:
        result = subprocess.run(
            [git, "config", "--get", key],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None
