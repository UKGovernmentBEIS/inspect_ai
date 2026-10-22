"""Building the merged log's zip, recomputing metrics as samples pass through."""

import json
import zipfile
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, BinaryIO, NamedTuple

import anyio

from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.json import to_json_safe
from inspect_ai._util.zipfile import zipfile_compress_kwargs
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
from inspect_ai.scorer._metric import SampleScore

from ._errors import ShardSetError


class _SampleInputs(NamedTuple):
    """What metric recomputation keeps of a sample."""

    scores: dict[str, SampleScore]
    error: bool


def check_scoring_resolvable(header: EvalLog) -> None:
    """Refuse metrics and epoch reducers the registry cannot resolve.

    The merge never imports the log's `task_file`, so every metric (of a
    scorer or of the task, `eval.metrics`) and every epoch reducer must
    already be registered: built in, from an installed package, or imported
    by the caller.

    Raises:
        LookupError: A metric or epoch reducer is not registered.
    """
    from inspect_ai._util.registry import registry_lookup
    from inspect_ai.scorer._reducer.registry import create_reducers

    groups = [scorer.metrics for scorer in header.eval.scorers or []]
    for metrics in [*groups, header.eval.metrics]:
        for metric in _metric_definitions(metrics):
            if registry_lookup("metric", metric.name) is None:
                raise LookupError(_unregistered("Metric", metric.name))
    for name in header.eval.config.epochs_reducer or []:
        try:
            create_reducers([name])
        except LookupError as ex:
            raise LookupError(_unregistered("Epoch reducer", name)) from ex


def _unregistered(kind: str, name: str) -> str:
    return (
        f"{kind} '{name}' is not registered, and the merge does not import the "
        "log's task file. Import the module that defines it, then merge from "
        "Python with merge_eval_log_shards()."
    )


def _metric_definitions(metrics: Any) -> list[EvalMetricDefinition]:
    if not metrics:
        return []
    groups = list(metrics.values()) if isinstance(metrics, dict) else list(metrics)
    definitions: list[EvalMetricDefinition] = []
    for group in groups:
        if isinstance(group, EvalMetricDefinition):
            definitions.append(group)
        elif isinstance(group, dict):
            for values in group.values():
                definitions.extend(values)
        else:
            definitions.extend(group)
    return definitions


async def write_merged_zip(
    out: BinaryIO,
    *,
    keys: Sequence[SampleRecordKey],
    read_member: Callable[[SampleRecordKey], Awaitable[bytes]],
    summaries: Sequence[EvalSampleSummary],
    template: EvalLog,
    total_samples: int,
    make_header: Callable[[EvalResults | None], EvalLog],
) -> EvalLog:
    """Write the merged log's members to `out` and return its header.

    Each sample is read with `read_member`, validated, written under the name
    rebuilt from its key and reduced to its metric inputs before the next is
    read. Then the summaries, the recomputed reductions and the header (made
    by `make_header` from the recomputed results) are written. No journal is
    written: the merged log is always written finished.

    Raises:
        ShardSetError: A sample member's id or epoch does not match its name.
        pydantic.ValidationError: A sample member does not parse.
    """
    with zipfile.ZipFile(out, "w", **zipfile_compress_kwargs) as zf:
        inputs: list[_SampleInputs] = []
        for key in keys:
            data = await read_member(key)
            inputs.append(await anyio.to_thread.run_sync(_write_sample, zf, key, data))
        results, reductions = _recompute_results(template, inputs, total_samples)
        header = make_header(results)
        await anyio.to_thread.run_sync(
            _write_members, zf, list(summaries), reductions, header
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
    return _SampleInputs(
        scores={
            name: SampleScore(
                score=score, sample_id=sample.id, sample_metadata=sample.metadata
            )
            for name, score in (sample.scores or {}).items()
        },
        error=sample.error is not None,
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


def _recompute_results(
    template: EvalLog, inputs: list[_SampleInputs], total_samples: int
) -> tuple[EvalResults | None, list[EvalSampleReductions] | None]:
    """Metrics over the merged samples, as `recompute_metrics` computes them."""
    from inspect_ai._eval.score import (
        metrics_from_log_header,
        reducers_from_log_header,
        resolve_scorers_info,
    )
    from inspect_ai._eval.task.results import eval_results

    # resolve_scorers_info imports the task file for an unregistered metric
    check_scoring_resolvable(template)
    scorers = resolve_scorers_info(template)
    return eval_results(
        samples=total_samples,
        scores=[sample.scores for sample in inputs if sample.scores],
        reducers=reducers_from_log_header(template),
        scorers=scorers,
        metrics=metrics_from_log_header(template),
        completed_samples=sum(1 for sample in inputs if not sample.error),
        headline_metric=template.eval.headline_metric,
    )
