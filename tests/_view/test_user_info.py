"""Tests for the view server's user_info() helper.

The endpoint is best-effort and short-circuits in lots of ways, so these
tests pin the resolution order — email local-part → user.name → OS login
— rather than the exact shell-out behavior.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from unittest.mock import patch

from inspect_ai._view.user_info import user_info


def _patch_git(values: dict[str, str | None]) -> AbstractContextManager[object]:
    """Patch _git_config so user_info() doesn't shell out to a real git."""

    def fake(git: str, key: str) -> str | None:
        return values.get(key)

    return patch("inspect_ai._view.user_info._git_config", side_effect=fake)


def test_prefers_email_local_part_over_user_name() -> None:
    with _patch_git(
        {
            "user.name": "Ransom Richardson",
            "user.email": "ransom@meridianlabs.ai",
        }
    ):
        info = user_info()
    assert info.name == "ransom"
    assert info.email == "ransom@meridianlabs.ai"


def test_falls_back_to_user_name_when_no_email() -> None:
    with _patch_git({"user.name": "Ransom Richardson", "user.email": None}):
        info = user_info()
    assert info.name == "Ransom Richardson"
    assert info.email is None


def test_falls_back_to_user_name_when_email_has_no_at_sign() -> None:
    # An odd config but plausible — e.g. a CI machine with a placeholder.
    with _patch_git({"user.name": "ci-bot", "user.email": "ci-bot"}):
        info = user_info()
    assert info.name == "ci-bot"
    assert info.email == "ci-bot"


def test_empty_local_part_falls_back_to_user_name() -> None:
    # `@example.com` would split to "" — don't return an empty alias.
    with _patch_git({"user.name": "alice", "user.email": "@example.com"}):
        info = user_info()
    assert info.name == "alice"


def test_falls_back_to_os_user_when_git_returns_nothing() -> None:
    with _patch_git({"user.name": None, "user.email": None}):
        with patch(
            "inspect_ai._view.user_info.getpass.getuser", return_value="osuser"
        ):
            info = user_info()
    assert info.name == "osuser"
    assert info.email is None


def test_skips_git_when_unavailable() -> None:
    # shutil.which returns None when git isn't installed; should still
    # produce a non-empty name from getpass.
    with patch("inspect_ai._view.user_info.shutil.which", return_value=None):
        with patch(
            "inspect_ai._view.user_info.getpass.getuser", return_value="osuser"
        ):
            info = user_info()
    assert info.name == "osuser"
    assert info.email is None
