from unittest.mock import MagicMock, patch

from inspect_sandbox_tools._remote_tools._exec_remote._job import _make_preexec_fn


def test_make_preexec_fn_no_user_still_sets_oom():
    """When user is None, preexec_fn only sets oom_score_adj."""
    fn = _make_preexec_fn(None)
    with patch("builtins.open", MagicMock()):
        with patch("os.getuid", return_value=0):
            fn()  # should not call setuid/setgid


def test_make_preexec_fn_with_user_when_root():
    """When user is set and we're root, preexec_fn drops privileges and sets env."""
    fn = _make_preexec_fn("testuser")
    mock_pw = MagicMock()
    mock_pw.pw_uid = 1000
    mock_pw.pw_gid = 1000
    mock_pw.pw_dir = "/home/testuser"
    mock_environ = {"HOME": "/root", "USER": "root", "LOGNAME": "root"}
    with patch("builtins.open", MagicMock()):
        with patch("os.getuid", return_value=0):
            with patch("pwd.getpwnam", return_value=mock_pw) as mock_getpw:
                with patch("os.setgid") as mock_setgid:
                    with patch("os.initgroups") as mock_initgroups:
                        with patch("os.setuid") as mock_setuid:
                            with patch.dict("os.environ", mock_environ):
                                fn()
                                mock_getpw.assert_called_once_with("testuser")
                                mock_setgid.assert_called_once_with(1000)
                                mock_initgroups.assert_called_once_with(
                                    "testuser", 1000
                                )
                                mock_setuid.assert_called_once_with(1000)
                                import os

                                assert os.environ["HOME"] == "/home/testuser"
                                assert os.environ["USER"] == "testuser"
                                assert os.environ["LOGNAME"] == "testuser"


def test_make_preexec_fn_user_not_found_exits_with_message():
    """When target user doesn't exist, preexec_fn writes stderr and calls os._exit."""
    fn = _make_preexec_fn("nonexistent")
    with patch("builtins.open", MagicMock()):
        with patch("os.getuid", return_value=0):
            with patch("pwd.getpwnam", side_effect=KeyError("nonexistent")):
                with patch("os._exit") as mock_exit:
                    with patch("os.write") as mock_write:
                        fn()
                        mock_write.assert_called_once()
                        assert mock_write.call_args[0][0] == 2  # stderr fd
                        assert b"nonexistent" in mock_write.call_args[0][1]
                        mock_exit.assert_called_once_with(126)


def test_make_preexec_fn_with_user_when_not_root():
    """When user is set but we're not root, preexec_fn skips privilege drop."""
    fn = _make_preexec_fn("testuser")
    with patch("builtins.open", MagicMock()):
        with patch("os.getuid", return_value=1000):
            with patch("os.setuid") as mock_setuid:
                fn()
                mock_setuid.assert_not_called()
