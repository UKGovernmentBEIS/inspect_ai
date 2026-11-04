"""Building the merged log's zip, computing results with the caller's task."""

import functools
import json
import zipfile
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, BinaryIO, NamedTuple

from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.json import to_json_safe
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai._util.zipfile import zipfile_compress_kwargs
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._span import SpanBeginEvent
from inspect_ai.log._log import (
    EvalLog,
    EvalMetricDefinition,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
    EvalSampleSummary,
)
from inspect_ai.log._recorders.eval import (
    HEADER_JSON,
    REDUCTIONS_JSON,
    SUMMARIES_JSON,
    _sample_filename,
)
from inspect_ai.log._recorders.recorder import SampleRecordKey
from inspect_ai.scorer._metric import SampleScore, Score

from ._errors import ShardSetError
from ._owned import run_owned

if TYPE_CHECKING:
    from inspect_ai._eval.task.task import Task


class _SampleInputs(NamedTuple):
    """What computing the results keeps of a sample."""

    id: int | str
    scores: dict[str, Score]
    initial_metadata: dict[str, Any] | None
    """The dataset metadata its `SampleInitEvent` records, before any solver
    changed it; None without that event."""
    initialized: bool
    """Whether the sample has a `SampleInitEvent`."""
    scoring_ran: bool
    """Whether a declared scorer ran on the sample (it has a `scorer` span),
    which a run with `score=False` never does."""
    error: bool
    invalidated: bool


class MergedScoring(NamedTuple):
    """What the merged header takes from the merged samples."""

    results: EvalResults | None
    invalidated: bool
    """Whether any merged sample is invalidated."""


def check_task_matches(task: "Task", header: EvalLog, source: str) -> None:
    """Refuse a task that is not the one the shards ran.

    Compares names only, not options: the task name, the scorer names, the
    metric names (each scorer's and the task's), the number of epochs and the
    epoch reducer names, where no reducer (the default mean) differs from an
    empty list (no reduction). Passing the task the shards ran, with the same
    options, is the caller's responsibility.

    Raises:
        ShardSetError: The task differs from what `header` records.
    """
    from inspect_ai._eval.task.log import resolve_eval_metrics, resolve_eval_scorers
    from inspect_ai.scorer._metric import to_metric_specs
    from inspect_ai.scorer._reducer import reducer_log_names
    from inspect_ai.scorer._scorer import as_scorer_spec

    recorded = header.eval
    scorers = resolve_eval_scorers(
        [as_scorer_spec(scorer) for scorer in task.scorer]
        if task.scorer is not None
        else None
    )
    metrics = resolve_eval_metrics(
        to_metric_specs(task.metrics) if task.metrics is not None else None
    )
    for field, given, ran in [
        ("task name", task.name, recorded.task),
        (
            "scorers",
            [s.name for s in scorers or []],
            [s.name for s in recorded.scorers or []],
        ),
        (
            "scorer metrics",
            [_metric_names(s.metrics) for s in scorers or []],
            [_metric_names(s.metrics) for s in recorded.scorers or []],
        ),
        ("task metrics", _metric_names(metrics), _metric_names(recorded.metrics)),
        ("epochs", task.epochs or 1, recorded.config.epochs or 1),
        (
            "epoch reducers",
            reducer_log_names(task.epochs_reducer),
            recorded.config.epochs_reducer,
        ),
    ]:
        if given != ran:
            raise ShardSetError(
                f"The task passed to the merge differs from the one {source} "
                f"ran in its {field} ({given!r}, not {ran!r}). Pass the task the "
                "shards ran."
            )


def _metric_names(metrics: Any) -> Any:
    """The metric names of a recorded metrics structure, without options."""

    def group(group: dict[str, list[EvalMetricDefinition]]) -> dict[str, list[str]]:
        return {key: [m.name for m in values] for key, values in group.items()}

    if metrics is None:
        return None
    if isinstance(metrics, dict):
        return group(metrics)
    return [group(item) if isinstance(item, dict) else item.name for item in metrics]


async def write_merged_zip(
    out: BinaryIO,
    *,
    keys: Sequence[SampleRecordKey],
    read_member: Callable[[SampleRecordKey], Awaitable[bytes]],
    summaries: Sequence[EvalSampleSummary],
    task: "Task",
    total_samples: int,
    make_header: Callable[[MergedScoring], EvalLog],
) -> EvalLog:
    """Write the merged log's members to `out` and return its header.

    Each sample is read with `read_member`, validated, written under the name
    rebuilt from its key and reduced to its scores before the next is read.
    Then the summaries, the reductions and the header (made by `make_header`
    from the results and the samples' invalidation) are written. No journal
    is written: the merged log is always written finished. The results are
    computed in the caller's model context: the merge builds no model from
    what the shards record.

    Raises:
        ShardSetError: A sample member's id or epoch does not match its name,
            a sample with a declared score has no `SampleInitEvent`, or some
            samples were scored and others ran without scoring.
        pydantic.ValidationError: A sample member does not parse.
    """
    with zipfile.ZipFile(out, "w", **zipfile_compress_kwargs) as zf:
        inputs: list[_SampleInputs] = []
        for key in keys:
            data = await read_member(key)
            inputs.append(
                await run_owned(functools.partial(_write_sample, zf, key, data))
            )
        results, reductions = _results(task, inputs, total_samples)
        header = make_header(
            MergedScoring(
                results=results,
                invalidated=any(sample.invalidated for sample in inputs),
            )
        )
        await run_owned(
            functools.partial(_write_members, zf, list(summaries), reductions, header)
        )
    return header


def _write_sample(
    zf: zipfile.ZipFile, key: SampleRecordKey, data: bytes
) -> _SampleInputs:
    sample = EvalSample.model_validate(
        json.loads(data), context=get_deserializing_context()
    )
    if str(sample.id) != key.sample_id or sample.epoch != key.epoch:
        raise ShardSetError(
            f"Sample member {_sample_filename(key.sample_id, key.epoch)} holds sample "
            f"{sample.id!r}, epoch {sample.epoch}."
        )
    zf.writestr(_sample_filename(key.sample_id, key.epoch), data)
    init = next((e for e in sample.events if isinstance(e, SampleInitEvent)), None)
    return _SampleInputs(
        id=sample.id,
        scores=dict(sample.scores or {}),
        initial_metadata=init.sample.metadata if init is not None else None,
        initialized=init is not None,
        scoring_ran=any(
            isinstance(event, SpanBeginEvent) and event.type == "scorer"
            for event in sample.events
        ),
        error=sample.error is not None,
        invalidated=sample.invalidation is not None,
    )


def _write_members(
    zf: zipfile.ZipFile,
    summaries: list[EvalSampleSummary],
    reductions: list[EvalSampleReductions] | None,
    header: EvalLog,
) -> None:
    zf.writestr(SUMMARIES_JSON, to_json_safe(summaries, indent=None))
    if reductions is not None:
        zf.writestr(REDUCTIONS_JSON, to_json_safe(reductions, indent=None))
    zf.writestr(HEADER_JSON, to_json_safe(header, indent=None))


def _results(
    task: "Task", inputs: list[_SampleInputs], total_samples: int
) -> tuple[EvalResults | None, list[EvalSampleReductions] | None]:
    """The merged samples' results and epoch reductions, computed with `task`.

    Through `eval_results`, with the task's scorers, metrics and epoch
    reducer, as a native run computes them. Each score is passed to the
    metrics as a fresh run passes it: with the sample's dataset metadata
    (from its `SampleInitEvent`) and the declared scorer's name.

    A score with no declared scorer (set by a solver) is refused: a fresh run
    and a retry give its metrics different inputs, and `eval_results` would
    load a scorer named after it (decision: Ransom, 2026-10-28).

    Shards run with `score=False` hold samples that completed without
    scoring. Their results have no scorer entries and no reductions, as a
    native unscored run's do. Samples that were scored beside samples that
    ran without scoring are refused, since the shards did not run alike.

    Raises:
        ShardSetError: A sample has a score with no declared scorer, or has
            scores but no `SampleInitEvent`, or some samples were scored and
            others ran without scoring.
    """
    from inspect_ai._eval.task.results import eval_results
    from inspect_ai.scorer._scorer import unique_scorer_name

    scorer_names: list[str] = []
    for scorer in task.scorer or []:
        scorer_names.append(unique_scorer_name(scorer, scorer_names))
    declared = {
        name: registry_unqualified_name(scorer)
        for name, scorer in zip(scorer_names, task.scorer or [])
    }
    unscored = next(
        (
            sample
            for sample in inputs
            if not (sample.scores or sample.scoring_ran or sample.error)
        ),
        None,
    )
    scored = next(
        (sample for sample in inputs if sample.scores or sample.scoring_ran), None
    )
    if unscored is not None and scored is not None:
        raise ShardSetError(
            f"Sample {str(scored.id)!r} was scored but sample "
            f"{str(unscored.id)!r} ran without scoring (score=False or "
            "--no-score), so the shards did not run with the same scoring. Re-run "
            "the shards so that all of them score, or none do."
        )
    scores: list[dict[str, SampleScore]] = []
    for sample in inputs:
        if not sample.scores:
            continue
        other = next((name for name in sample.scores if name not in declared), None)
        if other is not None:
            raise ShardSetError(
                f"Sample {str(sample.id)!r} has the score '{other}', which no "
                "scorer the task declares produced (a solver set it). The merge "
                "cannot merge solver-set scores: a fresh run and a retry give "
                "their metrics different inputs. Score with a scorer declared on "
                "the task (Task(scorer=...)) and re-run the shards."
            )
        if not sample.initialized:
            raise ShardSetError(
                f"Sample {str(sample.id)!r} has no sample_init event, which records "
                "the dataset metadata a fresh run gives its scorers' metrics (a "
                "sample whose record could not be serialized is logged without "
                "its events). Re-run the shard holding the sample."
            )
        scores.append(
            {
                name: SampleScore(
                    score=score,
                    sample_id=sample.id,
                    sample_metadata=sample.initial_metadata,
                    scorer=declared[name],
                )
                for name, score in sample.scores.items()
            }
        )
    return eval_results(
        samples=total_samples,
        scores=scores,
        reducers=task.epochs_reducer,
        scorers=task.scorer if unscored is None else None,
        metrics=task.metrics,
        scorer_names=(scorer_names or None) if unscored is None else None,
        completed_samples=sum(1 for sample in inputs if not sample.error),
        headline_metric=task.headline_metric,
    )
