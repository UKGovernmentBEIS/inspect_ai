from unittest.mock import AsyncMock, patch

from inspect_ai.log import list_eval_logs, list_eval_logs_async


def test_list_eval_logs_reads_updated_env(monkeypatch, tmp_path):
    log_dir = str(tmp_path)

    monkeypatch.setenv("INSPECT_LOG_DIR", log_dir)

    with patch("inspect_ai.log._file.filesystem") as mock_fs:
        mock_fs.return_value.ls.return_value = []

        list_eval_logs()

        mock_fs.assert_called_once_with(log_dir, {})


async def test_list_eval_logs_async_reads_updated_env(monkeypatch, tmp_path):
    log_dir = str(tmp_path)

    monkeypatch.setenv("INSPECT_LOG_DIR", log_dir)

    with patch(
        "inspect_ai.log._file._list_eval_logs_async",
        new_callable=AsyncMock,
    ) as mock_list:
        mock_list.return_value = []

        await list_eval_logs_async()

        mock_list.assert_awaited_once_with(
            log_dir, None, True, True, {}
        )