"""Unit tests for exec_remote Job user-switching logic."""

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest
from inspect_sandbox_tools._util.user_switch import make_preexec

_OOM_PATCH = "inspect_sandbox_tools._util.user_switch.set_oom_score_adj"


class TestMakePreexec:
    """Tests for the make_preexec function."""

    def test_no_user_only_sets_oom(self) -> None:
        """When username is None, preexec only sets OOM score."""
        preexec = make_preexec(None)
        with patch(_OOM_PATCH) as mock_oom, patch("os.setuid") as mock_setuid:
            preexec()
            mock_oom.assert_called_once()
            mock_setuid.assert_not_called()

    @patch("os.setuid")
    @patch("os.setgid")
    @patch("os.initgroups")
    @patch("pwd.getpwnam")
    def test_user_switches_in_correct_order(
        self,
        mock_getpwnam: MagicMock,
        mock_initgroups: MagicMock,
        mock_setgid: MagicMock,
        mock_setuid: MagicMock,
    ) -> None:
        """Verifies initgroups -> setgid -> setuid order and correct args."""
        pw = MagicMock()
        pw.pw_uid = 1000
        pw.pw_gid = 1000
        mock_getpwnam.return_value = pw

        call_order: list[str] = []
        mock_initgroups.side_effect = lambda *a: call_order.append("initgroups")
        mock_setgid.side_effect = lambda *a: call_order.append("setgid")
        mock_setuid.side_effect = lambda *a: call_order.append("setuid")

        preexec = make_preexec("testuser")
        with patch(_OOM_PATCH):
            preexec()

        mock_getpwnam.assert_called_once_with("testuser")
        mock_initgroups.assert_called_once_with("testuser", 1000)
        mock_setgid.assert_called_once_with(1000)
        mock_setuid.assert_called_once_with(1000)
        assert call_order == ["initgroups", "setgid", "setuid"]

    @patch("os._exit", side_effect=SystemExit(1))
    @patch("pwd.getpwnam", side_effect=KeyError("testuser"))
    def test_nonexistent_user_exits(
        self, mock_getpwnam: MagicMock, mock_exit: MagicMock
    ) -> None:
        """When the user doesn't exist in /etc/passwd, preexec calls os._exit(1)."""
        preexec = make_preexec("testuser")
        with patch(_OOM_PATCH), pytest.raises(SystemExit):
            preexec()
        mock_exit.assert_called_once_with(1)

    @patch("os._exit", side_effect=SystemExit(1))
    @patch("os.initgroups", side_effect=PermissionError("Operation not permitted"))
    @patch("pwd.getpwnam")
    def test_permission_error_exits(
        self,
        mock_getpwnam: MagicMock,
        mock_initgroups: MagicMock,
        mock_exit: MagicMock,
    ) -> None:
        """When setuid/setgid fails due to missing capabilities, calls os._exit(1)."""
        pw = MagicMock()
        pw.pw_uid = 1000
        pw.pw_gid = 1000
        mock_getpwnam.return_value = pw

        preexec = make_preexec("testuser")
        with patch(_OOM_PATCH), pytest.raises(SystemExit):
            preexec()
        mock_exit.assert_called_once_with(1)


class TestJobCreateHomeEnv:
    """Test that Job.create() sets HOME when switching users."""

    async def test_user_sets_home_from_passwd(self) -> None:
        """When switching user, HOME should be set from /etc/passwd."""
        from unittest.mock import AsyncMock

        from inspect_sandbox_tools._remote_tools._exec_remote._job import Job

        pw = MagicMock()
        pw.pw_uid = 65534
        pw.pw_gid = 65534
        pw.pw_dir = "/nonexistent"

        with (
            patch("pwd.getpwnam", return_value=pw),
            patch(
                "asyncio.create_subprocess_shell", new_callable=AsyncMock
            ) as mock_create,
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 1234
            mock_proc.stdout = None
            mock_proc.stderr = None
            mock_proc.stdin = None
            mock_proc.returncode = None
            mock_create.return_value = mock_proc

            await Job.create("echo hi", user="nobody", can_switch_user=True)

            _, kwargs = mock_create.call_args
            assert kwargs["env"]["HOME"] == "/nonexistent"

    async def test_no_user_does_not_override_home(self) -> None:
        """When not switching user, HOME should not be modified."""
        from inspect_sandbox_tools._remote_tools._exec_remote._job import Job

        job = await Job.create("echo hi", user=None, can_switch_user=False)
        await job.kill(ack_seq=0)
        # No assertion on env needed — just verify it doesn't crash.
        # The subprocess inherits os.environ unchanged when env=None.

    async def test_unknown_user_sets_home_to_slash(self) -> None:
        """When passwd lookup fails for HOME, fall back to '/'."""
        from unittest.mock import AsyncMock

        from inspect_sandbox_tools._remote_tools._exec_remote._job import Job

        # First call (in _is_current_user) returns a non-matching user,
        # second call (in create for HOME) raises KeyError
        call_count = 0

        def mock_getpwnam(name: str) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _is_current_user check — return non-matching uid
                pw = MagicMock()
                pw.pw_uid = 99999
                return pw
            raise KeyError(name)

        with (
            patch("pwd.getpwnam", side_effect=mock_getpwnam),
            patch(
                "asyncio.create_subprocess_shell", new_callable=AsyncMock
            ) as mock_create,
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 1234
            mock_proc.stdout = None
            mock_proc.stderr = None
            mock_proc.stdin = None
            mock_proc.returncode = None
            mock_create.return_value = mock_proc

            await Job.create("echo hi", user="ghost", can_switch_user=True)

            _, kwargs = mock_create.call_args
            assert kwargs["env"]["HOME"] == "/"


class TestJobCreateUserValidation:
    """Test that Job.create() rejects user when can_switch_user is False."""

    async def test_user_without_can_switch_raises(self) -> None:
        from inspect_sandbox_tools._remote_tools._exec_remote._job import Job
        from inspect_sandbox_tools._util.common_types import ToolException

        with pytest.raises(ToolException, match="Cannot switch to user"):
            await Job.create("echo hello", user="nobody", can_switch_user=False)

    async def test_no_user_without_can_switch_works(self) -> None:
        from inspect_sandbox_tools._remote_tools._exec_remote._job import Job

        job = await Job.create("echo hello", user=None, can_switch_user=False)
        assert job.pid > 0
        await job.kill(ack_seq=0)

    async def test_current_user_without_can_switch_works(self) -> None:
        """Requesting the current user should succeed even without root."""
        import getpass

        from inspect_sandbox_tools._remote_tools._exec_remote._job import Job

        current_user = getpass.getuser()
        job = await Job.create("echo hello", user=current_user, can_switch_user=False)
        assert job.pid > 0
        await job.kill(ack_seq=0)


class TestExecRemoteUserIntegration:
    """Integration tests requiring root. Skipped when not root."""

    @pytest.mark.skipif(os.getuid() != 0, reason="Requires root")
    async def test_run_as_nobody(self) -> None:
        from inspect_sandbox_tools._remote_tools._exec_remote._job import Job

        job = await Job.create("id -un", user="nobody", can_switch_user=True)
        result = await job.poll(ack_seq=0)
        for _ in range(50):
            if result.state == "completed":
                break
            await asyncio.sleep(0.1)
            result = await job.poll(ack_seq=result.seq)
        assert result.state == "completed"
        assert result.exit_code == 0
        assert result.stdout.strip() == "nobody"
