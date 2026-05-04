import os

from inspect_ai.log import read_eval_log

EVAL_LOG_FILE = os.path.join("tests", "log", "test_eval_log", "log_read_sample.eval")


def test_read_eval_log_exclude_fields_preserves_scores():
    log = read_eval_log(
        EVAL_LOG_FILE,
        exclude_fields={"messages", "events", "store", "attachments"},
    )
    assert log.samples
    sample = log.samples[0]
    assert not sample.messages
    assert not sample.events
    assert not sample.store
    assert not sample.attachments
    assert sample.scores
    score = sample.scores["match"]
    assert score.value == "C"
    assert score.answer == "Yes"
