import math
import os
import tempfile

from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai.log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSpec,
    EvalStats,
    read_eval_log,
    write_eval_log,
)
from inspect_ai.log._log import EvalSample
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.scorer import Score

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


def _make_log_with_nan_score() -> EvalLog:
    """Build a minimal log whose sample JSON contains a NaN literal."""
    sample = EvalSample(
        id="s1",
        epoch=1,
        input="hello",
        target="world",
        messages=[ChatMessageUser(content="hi")],
        store={"k": "v"},
        scores={"match": Score(value=float("nan"), answer="Yes")},
    )
    return EvalLog(
        version=LOG_SCHEMA_VERSION,
        status="success",
        eval=EvalSpec(
            task="t",
            task_id="i",
            model="m",
            dataset=EvalDataset(name="d", samples=1),
            config=EvalConfig(),
            created="2025-01-01T00:00:00Z",
        ),
        plan=EvalPlan(),
        results=EvalResults(total_samples=1, completed_samples=1),
        stats=EvalStats(
            started_at="2025-01-01T00:00:00Z",
            completed_at="2025-01-01T00:01:00Z",
        ),
        samples=[sample],
    )


def test_read_eval_log_exclude_fields_nan_inf_fallback():
    """When NaNs are present, ijson fails and we fall back to json.loads.

    Make sure we still respect exclude_fields in that case.
    """
    log = _make_log_with_nan_score()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "nan.eval")
        write_eval_log(log, path)

        read_log = read_eval_log(path, exclude_fields={"messages", "store"})

    assert read_log.samples
    sample = read_log.samples[0]
    # excluded fields are still dropped on the json.loads fallback path
    assert not sample.messages
    assert not sample.store
    # the NaN value that forced the fallback is preserved
    assert math.isnan(sample.scores["match"].value)
    assert sample.scores["match"].answer == "Yes"
