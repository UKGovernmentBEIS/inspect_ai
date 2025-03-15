import os

from inspect_ai.log._file import read_eval_log
from inspect_ai.model._chat_message import ChatMessageUser


def test_message_id_auto_assign():
    message = ChatMessageUser(content="foo")
    assert message.id


def test_message_id_no_deserialize():
    log = read_eval_log(log_path("log_formats.json"))
    assert log.samples
    assert log.samples[0].messages[0].id is None

    log = read_eval_log(log_path("log_formats.eval"))
    assert log.samples
    assert log.samples[0].messages[0].id is None


def log_path(file: str) -> str:
    return os.path.join("tests", "log", "test_eval_log", f"{file}")
