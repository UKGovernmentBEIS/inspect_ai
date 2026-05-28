"""Per-sample helpers shared between `task_run` and `SampleRunner`.

Lifted out of `_eval/task/run.py` so the dependency between `run.py` and
`sample_runner.py` is a DAG rather than a cycle (both import from here).
"""

from __future__ import annotations

import functools
import importlib
import time
from datetime import datetime, timezone

from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.working import sample_waiting_time
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalError, EvalSample
from inspect_ai.log._condense import condense_sample
from inspect_ai.log._log import EvalRetryError, EvalSampleLimit
from inspect_ai.log._recorders.streaming import materialize_streaming_sample
from inspect_ai.log._transcript import transcript
from inspect_ai.model._model import sample_model_usage, sample_role_usage
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.solver import TaskState

from .log import TaskLogger


def create_eval_sample(
    start_time: float | None,
    sample: Sample,
    state: TaskState,
    scores: dict[str, SampleScore],
    error: EvalError | None,
    limit: EvalSampleLimit | None,
    error_retries: list[EvalRetryError],
    started_at: datetime | None = None,
    include_events: bool = True,
) -> EvalSample:
    # sample must have id to be logged
    id = sample.id
    if id is None:
        raise ValueError(
            f"Samples without IDs cannot be logged: {to_json_str_safe(sample)}"
        )

    # construct sample for logging

    # compute total time if we can
    total_time = time.monotonic() - start_time if start_time is not None else None

    return EvalSample(
        id=id,
        epoch=state.epoch,
        input=sample.input,
        choices=sample.choices,
        target=sample.target,
        metadata=state.metadata or {},
        sandbox=sample.sandbox,
        files=list(sample.files.keys()) if sample.files else None,
        setup=sample.setup,
        messages=state.messages,
        output=state.output,
        scores={k: v.score for k, v in scores.items()},
        store=dict(state.store.items()),
        uuid=state.uuid,
        events=list(transcript().events) if include_events else [],
        timelines=list(transcript().timelines) or None,
        attachments=dict(transcript().attachments),
        model_usage=sample_model_usage(),
        role_usage=sample_role_usage(),
        started_at=started_at.isoformat() if started_at is not None else None,
        completed_at=datetime.now(timezone.utc).isoformat(),
        total_time=round(total_time, 3) if total_time is not None else None,
        working_time=round(total_time - sample_waiting_time(), 3)
        if total_time is not None
        else None,
        error=error,
        error_retries=error_retries,
        limit=limit,
    )


async def log_sample(
    eval_sample: EvalSample,
    logger: TaskLogger,
    log_images: bool,
) -> EvalSample:
    if logger.buffer_db is None:
        await logger.complete_sample(
            condense_sample(eval_sample, log_images), flush=True
        )
        return eval_sample

    logging_sample = condense_sample(
        eval_sample.model_copy(update={"events": [], "events_data": None}),
        log_images,
    )
    with logger.buffer_db.open_sample_history(
        eval_sample.id, eval_sample.epoch
    ) as history:
        materialized_sample = materialize_streaming_sample(eval_sample, history)
        await logger.complete_sample_streaming(logging_sample, history, flush=True)
    return materialized_sample


@functools.cache
def _has_package(name: str) -> bool:
    # `importlib.util.find_spec` walks importer paths (~3 ms per call). Cached
    # because package installation can't change during a process lifetime, so
    # the result is invariant. Without this, `init_sample_assistant_internal`
    # (called once per sample) was costing ~3 s per 500 samples in profiling.
    return importlib.util.find_spec(name) is not None


def init_sample_assistant_internal() -> None:
    if _has_package("openai"):
        try:
            from inspect_ai.model._openai_responses import (
                init_sample_openai_assistant_internal,
            )

            init_sample_openai_assistant_internal()
        except ImportError:
            pass

    if _has_package("anthropic"):
        try:
            from inspect_ai.model._providers.anthropic import (
                init_sample_anthropic_assistant_internal,
            )

            init_sample_anthropic_assistant_internal()
        except ImportError:
            pass


def eval_retry_error(error: EvalError) -> EvalRetryError:
    """Create retry error with events from the most recent ModelEvent onward."""
    from inspect_ai.event._model import ModelEvent

    events = transcript().events
    recent_events = list(events)
    for i in range(len(events) - 1, -1, -1):
        if isinstance(events[i], ModelEvent):
            recent_events = list(events[i:])
            break
    return EvalRetryError(
        message=error.message,
        traceback=error.traceback,
        traceback_ansi=error.traceback_ansi,
        events=recent_events,
    )
