import tempfile
from datetime import datetime, timezone
from os.path import dirname, join
from pathlib import Path

from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import (
    list_eval_logs,
    read_eval_log_sample,
    read_eval_log_sample_summaries,
)
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSpec,
    EvalStats,
)
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.log._util import thin_input
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    ContentReasoning,
    ContentText,
    ModelUsage,
)

file = Path(__file__)


def test_sample_summaries() -> None:
    logs = list_eval_logs(
        join(dirname(file), "test_list_logs"), formats=["eval", "json"]
    )

    for log in logs:
        summaries = read_eval_log_sample_summaries(log)
        assert len(summaries) > 0


def test_sample_summaries_thin_metadata() -> None:
    task = Task(
        dataset=[
            Sample(input="Say hello.", metadata={"dict": dict(), "long": "a" * 2000})
        ]
    )
    log = eval(task, model="mockllm/model")[0]

    summaries = read_eval_log_sample_summaries(log.location)
    assert len(summaries) > 0
    assert len(summaries[0].metadata["long"]) <= 1024


def test_thin_input_does_not_mutate_messages() -> None:
    # regression test for #4239: thin_input mutated shared ChatMessage objects
    long_text = "a" * 10000
    reasoning_message = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="raw chain of thought"),
            ContentText(text="visible response"),
        ]
    )
    long_message = ChatMessageUser(content=long_text)
    messages: list[ChatMessage] = [reasoning_message, long_message]

    thinned = thin_input(messages)

    # originals are intact
    assert isinstance(reasoning_message.content, list)
    assert reasoning_message.content[0] == ContentReasoning(
        reasoning="raw chain of thought"
    )
    assert long_message.content == long_text

    # thinned copies have placeholders/truncation
    assert isinstance(thinned, list)
    assert isinstance(thinned[0].content, list)
    assert thinned[0].content[0] == ContentText(text="(Reasoning)")
    assert isinstance(thinned[1].content, str)
    assert len(thinned[1].content) < len(long_text)


def test_sample_summary_does_not_mutate_sample_input() -> None:
    sample = EvalSample(
        id=1,
        epoch=1,
        input=[
            ChatMessageAssistant(
                content=[
                    ContentReasoning(reasoning="raw chain of thought"),
                    ContentText(text="visible response"),
                ]
            )
        ],
        target="y",
    )
    summary = sample.summary()

    assert isinstance(sample.input, list)
    assert isinstance(sample.input[0].content, list)
    assert sample.input[0].content[0] == ContentReasoning(
        reasoning="raw chain of thought"
    )
    assert isinstance(summary.input, list)
    assert isinstance(summary.input[0].content, list)
    assert summary.input[0].content[0] == ContentText(text="(Reasoning)")


def test_logged_sample_input_preserves_content() -> None:
    task = Task(
        dataset=[
            Sample(
                id="x",
                input=[
                    ChatMessageAssistant(
                        content=[
                            ContentReasoning(reasoning="raw chain of thought"),
                            ContentText(text="visible response"),
                        ]
                    )
                ],
            )
        ]
    )
    with tempfile.TemporaryDirectory() as log_dir:
        log = eval(task, model="mockllm/model", log_dir=log_dir)[0]
        logged = read_eval_log_sample(log.location, "x", 1)

    assert isinstance(logged.input, list)
    assert isinstance(logged.input[0].content, list)
    assert logged.input[0].content[0] == ContentReasoning(
        reasoning="raw chain of thought"
    )


def test_sample_summary_includes_role_usage() -> None:
    role_usage = {
        "grader": ModelUsage(input_tokens=100, output_tokens=50, total_tokens=150)
    }
    sample = EvalSample(
        id=1,
        epoch=1,
        input="x",
        target="y",
        model_usage={
            "mockllm/model": ModelUsage(
                input_tokens=10, output_tokens=5, total_tokens=15
            )
        },
        role_usage=role_usage,
    )
    summary = sample.summary()
    assert summary.model_usage == sample.model_usage
    assert summary.role_usage == role_usage


def _make_spec() -> EvalSpec:
    return EvalSpec(
        created=datetime.now(timezone.utc).isoformat(),
        task="dedup_test",
        task_id="abc123",
        run_id="run1",
        model="mockllm/model",
        dataset=EvalDataset(),
        config=EvalConfig(),
    )


def _make_sample(i: int) -> EvalSample:
    return EvalSample(id=i, epoch=1, input=f"input {i}", target=f"target {i}")


@skip_if_trio
async def test_sample_summaries_dedup_on_reinit() -> None:
    """Re-logging samples after log_init(clean=False) must not duplicate summaries.

    This is the eval_retry / score --overwrite flow: existing summaries are
    preloaded from the prior log, then completed samples are re-logged.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        spec = _make_spec()

        # first run: log 2 samples
        recorder = EvalRecorder(temp_dir)
        path = await recorder.log_init(spec)
        await recorder.log_start(spec, EvalPlan())
        await recorder.log_sample(spec, _make_sample(1))
        await recorder.log_sample(spec, _make_sample(2))
        await recorder.log_finish(
            spec, "cancelled", EvalStats(), EvalResults(), reductions=None
        )

        first = read_eval_log_sample_summaries(path)
        assert sorted((s.id, s.epoch) for s in first) == [(1, 1), (2, 1)]

        # retry: re-init same location (clean=False), re-log both completed
        # samples plus one new one
        recorder = EvalRecorder(temp_dir)
        await recorder.log_init(spec, location=path, clean=False)
        await recorder.log_start(spec, EvalPlan())
        await recorder.log_sample(spec, _make_sample(1))
        await recorder.log_sample(spec, _make_sample(2))
        await recorder.log_sample(spec, _make_sample(3))
        await recorder.log_finish(
            spec, "success", EvalStats(), EvalResults(), reductions=None
        )

        summaries = read_eval_log_sample_summaries(path)
        keys = sorted((s.id, s.epoch) for s in summaries)
        assert keys == [(1, 1), (2, 1), (3, 1)], (
            f"duplicate summaries after re-init: {keys}"
        )
