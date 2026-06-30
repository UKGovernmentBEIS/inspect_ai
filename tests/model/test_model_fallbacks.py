"""Tests for sample-level model fallback accumulation and surfacing."""

import contextvars
from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.analysis import samples_df
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, read_eval_log_sample_summaries
from inspect_ai.model import ModelFallback, ModelOutput, get_model
from inspect_ai.model._model import (
    init_sample_model_fallbacks,
    record_sample_model_fallback,
    sample_model_fallbacks,
)

REQUESTED_MODEL = "claude-fable-5"
FALLBACK_MODEL = "claude-opus-4-8"


def _fallback_output() -> ModelOutput:
    output = ModelOutput.from_content(model=FALLBACK_MODEL, content="served")
    output.fallback = ModelFallback(
        model=REQUESTED_MODEL,
        fallback_model=FALLBACK_MODEL,
        metadata={"handoffs": [{"from": REQUESTED_MODEL, "to": FALLBACK_MODEL}]},
    )
    return output


# ---------------------------------------------------------------------------
# unit: accumulation
# ---------------------------------------------------------------------------


def test_fallback_accumulation_aggregates_by_pair() -> None:
    def run() -> list[ModelFallback]:
        init_sample_model_fallbacks()
        record_sample_model_fallback(_fallback_output())
        record_sample_model_fallback(_fallback_output())
        other = _fallback_output()
        assert other.fallback is not None
        other.fallback.fallback_model = "claude-sonnet-4-6"
        record_sample_model_fallback(other)
        return sample_model_fallbacks()

    fallbacks = contextvars.Context().run(run)
    assert fallbacks == [
        ModelFallback(model=REQUESTED_MODEL, fallback_model=FALLBACK_MODEL, count=2),
        ModelFallback(
            model=REQUESTED_MODEL, fallback_model="claude-sonnet-4-6", count=1
        ),
    ]
    # per-call diagnostics are not carried into the rollup
    assert all(fallback.metadata is None for fallback in fallbacks)


def test_fallback_accumulation_noop_without_fallback() -> None:
    def run() -> list[ModelFallback]:
        init_sample_model_fallbacks()
        record_sample_model_fallback(
            ModelOutput.from_content(model=REQUESTED_MODEL, content="normal")
        )
        return sample_model_fallbacks()

    assert contextvars.Context().run(run) == []


def test_fallback_accumulation_noop_without_init() -> None:
    def run() -> list[ModelFallback]:
        # no init_sample_model_fallbacks() -- recording outside a sample
        record_sample_model_fallback(_fallback_output())
        return sample_model_fallbacks()

    assert contextvars.Context().run(run) == []


# ---------------------------------------------------------------------------
# end to end: eval -> EvalSample / summaries / dataframe
# ---------------------------------------------------------------------------


def _eval_log(tmp_path: Path, fallback: bool) -> EvalLog:
    output = _fallback_output() if fallback else None
    model = get_model(
        "mockllm/model",
        custom_outputs=[output] if output is not None else None,
    )
    task = Task(dataset=[Sample(input="Say hello.", target="hello")])
    return eval(task, model=model, log_dir=str(tmp_path), display="none")[0]


def test_fallback_recorded_on_sample(tmp_path: Path) -> None:
    log = _eval_log(tmp_path, fallback=True)
    assert log.samples is not None
    assert log.samples[0].model_fallbacks == [
        ModelFallback(model=REQUESTED_MODEL, fallback_model=FALLBACK_MODEL, count=1)
    ]

    # summary carries the field and round-trips through the log
    summaries = read_eval_log_sample_summaries(log.location)
    assert summaries[0].model_fallbacks == log.samples[0].model_fallbacks

    # dataframe exposes the total count
    df = samples_df(log.location)
    assert df["fallbacks"].tolist() == [1]


def test_no_fallback_recorded_when_absent(tmp_path: Path) -> None:
    log = _eval_log(tmp_path, fallback=False)
    assert log.samples is not None
    assert log.samples[0].model_fallbacks is None

    summaries = read_eval_log_sample_summaries(log.location)
    assert summaries[0].model_fallbacks is None

    df = samples_df(log.location)
    assert df["fallbacks"].tolist() == [0]
