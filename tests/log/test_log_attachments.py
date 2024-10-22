import os

from inspect_ai.log._file import read_eval_log


def test_log_attachments_migration():
    # check for old-style content ref
    log_file = log_path("log_images_tc.json")
    with open(log_file, "r") as f:
        contents = f.read()
        assert "tc://" in contents

    # read log and confirm we have migrated into attachments
    log = read_eval_log(log_path("log_images_tc.json"))
    assert log.samples
    assert list(log.samples[0].attachments.values())[0].startswith(
        "data:image/png;base64"
    )

    # confirm that there are no more tc:// references
    # print(log.model_dump_json(indent=2))
    # assert "tc://" not in log.model_dump_json()


def log_path(log: str) -> str:
    return os.path.join("tests", "log", "test_eval_log", log)
