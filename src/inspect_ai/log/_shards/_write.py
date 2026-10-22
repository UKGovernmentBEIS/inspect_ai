"""Building the merged log's zip, recomputing metrics as samples pass through."""

import json
import zipfile
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, BinaryIO, NamedTuple

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
    EvalScore,
)
from inspect_ai.log._recorders.eval import (
    HEADER_JSON,
    REDUCTIONS_JSON,
    SUMMARIES_JSON,
    _sample_filename,
)
from inspect_ai.log._recorders.recorder import SampleRecordKey
from inspect_ai.scorer._metric import Metric, SampleScore

from ._errors import ShardSetError

if TYPE_CHECKING:
    from inspect_ai._eval.task.results import ScorerInfo


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
            _check_embedded(metric.options)
    for name in header.eval.config.epochs_reducer or []:
        try:
            create_reducers([name])
        except LookupError as ex:
            raise LookupError(_unregistered("Epoch reducer", name)) from ex


def _check_embedded(value: Any) -> None:
    """Refuse unregistered registry objects in a metric's options.

    Wrappers such as `grouped()` and `aggregate()` record the metrics they
    wrap as registry dicts, at any depth, which `registry_arg` creates.
    """
    from inspect_ai._util.registry import is_registry_dict, registry_lookup

    if is_registry_dict(value):
        if registry_lookup(value["type"], value["name"]) is None:
            kind = "Metric" if value["type"] == "metric" else value["type"]
            raise LookupError(_unregistered(kind, value["name"]))
        _check_embedded(value["params"])
    elif isinstance(value, dict):
        for item in value.values():
            _check_embedded(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_embedded(item)


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
    recorded: Sequence[tuple[str, EvalResults]],
    make_header: Callable[[EvalResults | None], EvalLog],
) -> EvalLog:
    """Write the merged log's members to `out` and return its header.

    Each sample is read with `read_member`, validated, written under the name
    rebuilt from its key and reduced to its metric inputs before the next is
    read. Then the summaries, the recomputed reductions and the header (made
    by `make_header` from the recomputed results) are written. No journal is
    written: the merged log is always written finished. `recorded` holds the
    results the shards recorded (as `(source, results)`), the metric source
    for scores with no declared scorer or task metrics.

    Raises:
        ShardSetError: A sample member's id or epoch does not match its name,
            or the metrics of a score with no declared scorer cannot be
            established from `recorded`.
        LookupError: A metric is not registered.
        pydantic.ValidationError: A sample member does not parse.
    """
    with zipfile.ZipFile(out, "w", **zipfile_compress_kwargs) as zf:
        inputs: list[_SampleInputs] = []
        for key in keys:
            data = await read_member(key)
            inputs.append(await anyio.to_thread.run_sync(_write_sample, zf, key, data))
        results, reductions = _recompute_results(
            template, inputs, total_samples, recorded
        )
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
    template: EvalLog,
    inputs: list[_SampleInputs],
    total_samples: int,
    recorded: Sequence[tuple[str, EvalResults]],
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
    metrics = metrics_from_log_header(template)
    scores = [sample.scores for sample in inputs if sample.scores]
    return eval_results(
        samples=total_samples,
        scores=scores,
        reducers=reducers_from_log_header(template),
        scorers=_scorer_infos(
            resolve_scorers_info(template), scores, metrics, recorded
        ),
        metrics=metrics,
        completed_samples=sum(1 for sample in inputs if not sample.error),
        headline_metric=template.eval.headline_metric,
    )


def _scorer_infos(
    declared: list["ScorerInfo"],
    scores: list[dict[str, SampleScore]],
    metrics: Any,
    recorded: Sequence[tuple[str, EvalResults]],
) -> list["ScorerInfo"]:
    """The declared scorers plus one for each other score name, in first-seen order.

    `eval_results` builds the others with `ScorerInfo.from_name`, which loads
    a file-qualified name (`task.py@scorer`, or an existing file) as a
    module and falls back to `accuracy` and `stderr` when it cannot load the
    scorer. The merge imports nothing a log names and must not change a
    score's metrics, so such a score takes the task metrics, as in
    `eval_results`, or else the metrics the shards recorded for it.
    """
    from inspect_ai._eval.task.results import ScorerInfo, _unique_scorer_names

    infos = list(declared)
    names = set(_unique_scorer_names(infos))
    for sample_scores in scores:
        for name, sample_score in sample_scores.items():
            if sample_score.scorer is None and name not in names:
                infos.append(
                    ScorerInfo(
                        name=name,
                        metrics=metrics
                        if metrics is not None
                        else _recorded_metrics(name, recorded),
                    )
                )
                names.add(name)
    return infos


def _recorded_metrics(
    name: str, recorded: Sequence[tuple[str, EvalResults]]
) -> list[Metric | dict[str, list[Metric]]]:
    """The metrics the shards recorded for score `name`, from the registry.

    Raises:
        ShardSetError: No shard recorded results for `name`, the shards
            recorded different metrics for it, or they recorded per-key metrics
            (a dictionary of metric lists), which this does not rebuild.
        LookupError: A recorded metric is not registered.
    """
    from inspect_ai._util.registry import registry_lookup
    from inspect_ai.scorer._metric import metric_create

    sources: dict[tuple[tuple[str, str], ...], list[str]] = {}
    for source, results in recorded:
        found = [score for score in results.scores if score.scorer == name]
        if not found:
            continue
        if any(score.name != name for score in found):
            raise ShardSetError(
                f"{source} records metrics per key for score '{name}', which has "
                "no declared scorer or task metrics; the merge cannot rebuild them."
            )
        identities = {_metric_identities(score) for score in found}
        if len(identities) > 1:
            raise ShardSetError(
                f"{source} records different metrics for the results of score "
                f"'{name}'; the merge cannot rebuild them."
            )
        sources.setdefault(identities.pop(), []).append(source)
    if not sources:
        raise ShardSetError(
            f"Score '{name}' has no declared scorer or task metrics, and no shard "
            "recorded results for it, so its metrics cannot be established. Merge "
            "once a shard holding it has finished."
        )
    if len(sources) > 1:
        raise ShardSetError(
            f"The shards record different metrics for score '{name}': "
            + "; ".join(
                f"{', '.join(m for m, _ in identity) or 'none'} in {', '.join(where)}"
                for identity, where in sources.items()
            )
        )
    [identity] = sources
    metrics: list[Metric | dict[str, list[Metric]]] = []
    for metric_name, params_json in identity:
        if registry_lookup("metric", metric_name) is None:
            raise LookupError(_unregistered("Metric", metric_name))
        params = json.loads(params_json)
        _check_embedded(params)
        metrics.append(metric_create(metric_name, **params))
    return metrics


def _metric_identities(score: EvalScore) -> tuple[tuple[str, str], ...]:
    """The metrics behind a recorded score, as (registry name, params) pairs.

    A metric with one value is recorded under its registry name; one with
    several values (a dict or list) is recorded as several entries sharing
    its name as their `group`.
    """
    identities: list[tuple[str, str]] = []
    for metric in score.metrics.values():
        identity = (
            metric.group or metric.name,
            json.dumps(metric.params, sort_keys=True),
        )
        if metric.group is None or not identities or identities[-1] != identity:
            identities.append(identity)
    return tuple(identities)
