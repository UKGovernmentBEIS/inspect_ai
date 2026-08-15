from unittest.mock import MagicMock, call, patch

from inspect_sandbox_tools._util.pseudo_terminal import PseudoTerminalIO


def test_pseudo_terminal_cleanup_is_idempotent() -> None:
    writer = MagicMock()
    reader = MagicMock()
    terminal = PseudoTerminalIO(
        coordinator_fd=11,
        subprocess_fd=12,
        writer=writer,
        fd_reader=reader,
    )

    with patch("inspect_sandbox_tools._util.pseudo_terminal.os.close") as close:
        terminal.cleanup()
        terminal.cleanup()

    writer.transport.close.assert_called_once_with()
    reader.close.assert_called_once_with()
    assert close.call_args_list == [call(12), call(11)]
