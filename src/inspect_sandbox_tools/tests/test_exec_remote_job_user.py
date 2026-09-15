"""Unit tests for exec_remote Job user-switching logic."""

import asyncio
import json
import os
import pwd
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic
import pytest
from inspect_sandbox_tools._remote_tools._bash_session.tool_types import (
    NewSessionParams,
)
from inspect_sandbox_tools._remote_tools._exec_remote.tool_types import SubmitParams
from inspect_sandbox_tools._remote_tools._mcp.tool_types import LaunchServerParams
from inspect_sandbox_tools._util.user_switch import (
    RunAs,
    is_current_user,
    make_preexec,
)

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


@pytest.mark.parametrize(
    "model, required",
    [
        (NewSessionParams, {}),
        (SubmitParams, {"command": "true"}),
        (LaunchServerParams, {"server_params": {"command": "true"}}),
    ],
)
def test_user_param_is_username_or_identity(
    model: type[NewSessionParams | SubmitParams | LaunchServerParams],
    required: dict[str, object],
) -> None:
    """One `user` field carries both forms; every params model rejects unknown fields."""
    identity = {"uid": 1, "gid": 2, "groups": [3], "home": "/h"}
    assert model.model_validate({**required, "user": "nobody"}).user == "nobody"
    assert model.model_validate(
        {**required, "user": identity}
    ).user == RunAs.model_validate(identity)
    with pytest.raises(pydantic.ValidationError):
        model.model_validate({**required, "run_as": identity})


class TestCliRunAs:
    """The CLI strips its reserved `_run_as` param and switches only when needed."""

    def _view(self, run_as: object, tmp_path: Path, capsys: Any) -> dict[str, Any]:
        from inspect_sandbox_tools._cli.main import _exec

        request = {
            "jsonrpc": "2.0",
            "method": "text_editor",
            "id": 1,
            "params": {"command": "view", "path": str(tmp_path), "_run_as": run_as},
        }
        asyncio.run(_exec(json.dumps(request)))
        return cast(dict[str, Any], json.loads(capsys.readouterr().out))

    def test_current_identity_needs_no_switch(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        me = {"uid": os.getuid(), "gid": os.getgid(), "groups": os.getgroups()}
        home = os.environ.get("HOME")
        with patch("inspect_sandbox_tools._cli.main.switch_user") as mock_switch:
            response = self._view(me, tmp_path, capsys)
        mock_switch.assert_not_called()
        assert "error" not in response, response
        assert os.environ.get("HOME") == home

    def test_current_username_needs_no_switch(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        with patch("inspect_sandbox_tools._cli.main.switch_user") as mock_switch:
            response = self._view(pwd.getpwuid(os.getuid()).pw_name, tmp_path, capsys)
        mock_switch.assert_not_called()
        assert "error" not in response, response

    @pytest.mark.skipif(os.getuid() == 0, reason="root can switch")
    def test_other_identity_without_root_raises(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        from inspect_sandbox_tools._util.common_types import ToolException

        other = {"uid": os.getuid() + 1, "gid": 0, "groups": []}
        with pytest.raises(ToolException, match="Cannot switch to user"):
            self._view(other, tmp_path, capsys)

    def test_rejects_malformed_run_as(self, tmp_path: Path, capsys: Any) -> None:
        with pytest.raises(TypeError, match="_run_as must be"):
            self._view(42, tmp_path, capsys)


class TestRunAs:
    """Numeric identity (RunAs) switching shares the username plumbing."""

    def test_preexec_switches_numeric_identity(self) -> None:
        run_as = RunAs(uid=1000, gid=5, groups=[4, 20], home="/h")
        with (
            patch(_OOM_PATCH),
            patch("os.setgroups") as mock_setgroups,
            patch("os.setgid") as mock_setgid,
            patch("os.setuid") as mock_setuid,
        ):
            make_preexec(run_as)()
        mock_setgroups.assert_called_once_with([4, 20])
        mock_setgid.assert_called_once_with(5)
        mock_setuid.assert_called_once_with(1000)

    async def test_current_uid_is_noop_without_root(self) -> None:
        from inspect_sandbox_tools._remote_tools._exec_remote._job import Job

        run_as = RunAs(
            uid=os.getuid(), gid=os.getgid(), groups=os.getgroups(), home="/nowhere"
        )
        job = await Job.create("echo hi", user=run_as, can_switch_user=False)
        assert job.pid > 0
        await job.kill(ack_seq=0)

    def test_is_current_user_compares_full_identity(self) -> None:
        me = RunAs(uid=os.getuid(), gid=os.getgid(), groups=os.getgroups(), home="/")
        assert is_current_user(me)
        assert is_current_user(me.model_copy(update={"groups": me.groups[::-1]}))
        assert not is_current_user(me.model_copy(update={"uid": me.uid + 1}))
        assert not is_current_user(me.model_copy(update={"gid": me.gid + 1}))
        assert not is_current_user(me.model_copy(update={"groups": [*me.groups, 1]}))

    def test_home_falls_back_to_passwd_when_unset(self) -> None:
        from inspect_sandbox_tools._util.user_switch import get_home_dir

        me = RunAs(uid=os.getuid(), gid=os.getgid(), groups=[], home=None)
        assert get_home_dir(me) == pwd.getpwuid(os.getuid()).pw_dir
        assert get_home_dir(me.model_copy(update={"home": ""})) == ""
        assert get_home_dir(RunAs(uid=2**31 - 7, gid=0, groups=[], home=None)) == "/"

    def test_preexec_hands_tty_to_user_before_switching(self) -> None:
        run_as = RunAs(uid=1000, gid=5, groups=[], home="/h")
        calls: list[str] = []
        with (
            patch(_OOM_PATCH),
            patch("os.isatty", return_value=True),
            patch("os.fchown", side_effect=lambda *a: calls.append(f"fchown{a}")),
            patch("os.setgroups"),
            patch("os.setgid"),
            patch("os.setuid", side_effect=lambda *a: calls.append("setuid")),
        ):
            make_preexec(run_as)()
        assert calls == ["fchown(0, 1000, -1)", "setuid"]

    def test_preexec_leaves_non_tty_stdin_alone(self) -> None:
        with (
            patch(_OOM_PATCH),
            patch("os.isatty", return_value=False),
            patch("os.fchown") as mock_fchown,
            patch("os.setgroups"),
            patch("os.setgid"),
            patch("os.setuid"),
        ):
            make_preexec(RunAs(uid=1000, gid=5, groups=[], home="/h"))()
        mock_fchown.assert_not_called()

    async def test_other_uid_without_root_raises(self) -> None:
        from inspect_sandbox_tools._remote_tools._exec_remote._job import Job
        from inspect_sandbox_tools._util.common_types import ToolException

        run_as = RunAs(uid=os.getuid() + 1, gid=0, groups=[], home="/")
        with pytest.raises(ToolException, match="Cannot switch to user"):
            await Job.create("echo hi", user=run_as, can_switch_user=False)

    async def test_sets_home_from_identity(self) -> None:
        from inspect_sandbox_tools._remote_tools._exec_remote._job import Job

        run_as = RunAs(uid=os.getuid() + 1, gid=0, groups=[], home="/elsewhere")
        with patch(
            "asyncio.create_subprocess_shell", new_callable=AsyncMock
        ) as mock_create:
            mock_proc = MagicMock()
            mock_proc.pid = 1234
            mock_proc.stdout = None
            mock_proc.stderr = None
            mock_proc.stdin = None
            mock_proc.returncode = None
            mock_create.return_value = mock_proc

            await Job.create("echo hi", user=run_as, can_switch_user=True)
            _, kwargs = mock_create.call_args
            assert kwargs["env"]["HOME"] == "/elsewhere"
            assert kwargs["preexec_fn"] is not None

            await Job.create(
                "echo hi", env={"HOME": "/custom"}, user=run_as, can_switch_user=True
            )
            _, kwargs = mock_create.call_args
            assert kwargs["env"]["HOME"] == "/custom"


class TestMCPServerSessionUser:
    """MCPServerSession.create() shares the Job user-switching plumbing."""

    async def test_switches_user_and_sets_home(self) -> None:
        from inspect_sandbox_tools._remote_tools._mcp.jsonrpc_types import (
            StdioServerParameters,
        )
        from inspect_sandbox_tools._remote_tools._mcp.mcp_server_session import (
            MCPServerSession,
        )

        run_as = RunAs(uid=os.getuid() + 1, gid=0, groups=[], home="/elsewhere")
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = MagicMock(pid=1234, returncode=None)
            for env, expected in [
                ({"KEEP": "1"}, {"KEEP": "1", "HOME": "/elsewhere"}),
                ({"HOME": "/custom"}, {"HOME": "/custom"}),
            ]:
                params = StdioServerParameters(command="srv", env=env)
                await MCPServerSession.create(params, user=run_as, can_switch_user=True)
                _, kwargs = mock_create.call_args
                assert kwargs["env"] == expected
                assert kwargs["preexec_fn"] is not None

    async def test_other_user_without_root_raises(self) -> None:
        from inspect_sandbox_tools._remote_tools._mcp.jsonrpc_types import (
            StdioServerParameters,
        )
        from inspect_sandbox_tools._remote_tools._mcp.mcp_server_session import (
            MCPServerSession,
        )
        from inspect_sandbox_tools._util.common_types import ToolException

        run_as = RunAs(uid=os.getuid() + 1, gid=0, groups=[], home="/")
        with pytest.raises(ToolException, match="Cannot switch to user"):
            await MCPServerSession.create(
                StdioServerParameters(command="srv"), user=run_as, can_switch_user=False
            )


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
