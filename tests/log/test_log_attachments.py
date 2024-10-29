import os

from inspect_ai.log._condense import (
    ATTACHMENT_PROTOCOL,
    condense_sample,
    resolve_sample_attachments,
)
from inspect_ai.log._file import read_eval_log


def test_log_attachments_condense():
    # read and resolve attachments
    log_file = log_path("log_images.json")
    log = read_eval_log(log_file)
    assert log.samples
    log.samples = [resolve_sample_attachments(sample) for sample in log.samples]

    # confirm there are no attachment refs
    assert len(log.samples[0].attachments) == 0
    assert ATTACHMENT_PROTOCOL not in log.model_dump_json()

    # now condense and confirm we have attachment refs
    log.samples = [condense_sample(sample) for sample in log.samples]
    assert ATTACHMENT_PROTOCOL in log.model_dump_json()


def test_log_attachments_migration():
    # check for old-style content ref
    log_file = log_path("log_images_tc.json")
    assert "tc://" in log_str(log_file)

    # read log and confirm we have migrated into attachments
    log = read_eval_log(log_path("log_images_tc.json"))
    assert log.samples
    assert list(log.samples[0].attachments.values())[0].startswith(
        "data:image/png;base64"
    )

    # also confirm that we've preserved (now deprecated) transcript
    assert len(log.samples[0].transcript.events) > 0


def log_path(log: str) -> str:
    return os.path.join("tests", "log", "test_eval_log", log)


def log_str(log: str) -> str:
    with open(log, "r") as f:
        return f.read()
