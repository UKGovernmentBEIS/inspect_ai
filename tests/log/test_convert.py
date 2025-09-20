import pathlib
from typing import Literal

import pytest

from inspect_ai.log._convert import convert_eval_logs
from inspect_ai.log._file import read_eval_log
from inspect_ai.log._log import EvalLog

_TESTS_DIR = pathlib.Path(__file__).resolve().parent


@pytest.mark.parametrize(
    "stream", [True, False, 3], ids=["stream", "no-stream", "stream-3"]
)
@pytest.mark.parametrize("to", ["eval", "json"])
@pytest.mark.parametrize(
    "resolve_attachments",
    [True, False],
    ids=["resolve-attachments", "no-resolve-attachments"],
)
def test_convert_eval_logs(
    tmp_path: pathlib.Path,
    stream: bool | int,
    to: Literal["eval", "json"],
    resolve_attachments: bool,
):
    input_file = (
        _TESTS_DIR
        / "test_list_logs/2024-11-05T13-32-37-05-00_input-task_hxs4q9azL3ySGkjJirypKZ.eval"
    )

    convert_eval_logs(
        str(input_file),
        to,
        str(tmp_path),
        resolve_attachments=resolve_attachments,
        stream=stream,
    )

    output_file = (tmp_path / input_file.name).with_suffix(f".{to}")
    assert output_file.exists()
    assert isinstance(
        read_eval_log(str(output_file), resolve_attachments=resolve_attachments),
        EvalLog,
    )
