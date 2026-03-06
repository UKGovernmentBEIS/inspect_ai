import os
import shutil
import subprocess

from pydantic import BaseModel


class GitContext(BaseModel):
    origin: str
    commit: str
    dirty: bool


def git_context() -> GitContext | None:
    # skip git operations when running under pytest
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None

    # check for git
    git = shutil.which("git")
    if not git:
        return None

    # check for a git revision in this directory
    commit_result = subprocess.run(
        [git, "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    )
    if commit_result.returncode != 0:
        return None

    # check for git origin (if any)
    origin = subprocess.run(
        [git, "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    # check if working tree is dirty
    status_result = subprocess.run(
        [git, "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    dirty = bool(status_result.stdout.strip())

    # return context
    return GitContext(origin=origin, commit=commit_result.stdout.strip(), dirty=dirty)
