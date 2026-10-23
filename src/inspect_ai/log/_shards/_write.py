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
)
from inspect_ai.log._recorders.eval import (
    HEADER_JSON,
    REDUCTIONS_JSON,
    SUMMARIES_JSON,
    _sample_filename,
)
from inspect_ai.log._recorders.recorder import SampleRecordKey
from inspect_ai.scorer._metric import Metric, SampleScore, Score
from inspect_ai.scorer._reducer.types import ScoreReducer

from ._errors import ShardSetError

if TYPE_CHECKING:
    from inspect_ai._eval.task.results import ScorerInfo


class _SampleInputs(NamedTuple):
    """What metric recomputation keeps of a sample."""

    scores: dict[str, SampleScore]
    error: bool
    edited: frozenset[str]
    """Names of the scores that carry an edit history (`edit_score`)."""
    invalidated: bool


class HeldReductions(NamedTuple):
    """The epoch reductions recorded for the samples a merge holds."""

    reductions: list[EvalSampleReductions]
    """Recorded reductions, each holding only the held samples it covers."""

    sources: dict[str, str]
    """The log each held sample id is taken from."""


class MergedScoring(NamedTuple):
    """What the merged header takes from the merged samples."""

    results: EvalResults | None
    invalidated: bool
    """Whether any merged sample is invalidated."""


def check_scoring_resolvable(header: EvalLog) -> None:
    """Refuse metrics the registry cannot resolve.

    The merge never imports the log's `task_file`, so every metric (of a
    scorer or of the task, `eval.metrics`) must already be registered: built
    in, from an installed package, or imported by the caller. Epoch reducers
    are not recreated (see :func:`_recompute_results`).

    Raises:
        LookupError: A metric is not registered.
    """
    from inspect_ai._util.registry import registry_lookup

    groups = [scorer.metrics for scorer in header.eval.scorers or []]
    for metrics in [*groups, header.eval.metrics]:
        for metric in _metric_definitions(metrics):
            if registry_lookup("metric", metric.name) is None:
                raise LookupError(_unregistered("Metric", metric.name))
            _check_embedded(metric.options)


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
    shard_results: Callable[[], Awaitable[Sequence[tuple[str, EvalResults]]]],
    held_reductions: HeldReductions,
    complete: bool,
    make_header: Callable[[MergedScoring], EvalLog],
) -> EvalLog:
    """Write the merged log's members to `out` and return its header.

    Each sample is read with `read_member`, validated, written under the name
    rebuilt from its key and reduced to its metric inputs before the next is
    read. Then the summaries, the reductions and the header (made by
    `make_header` from the recomputed results and the samples'
    invalidation) are written. No journal is written: the merged log is
    always written finished. `shard_results` returns the results each
    shard's current attempt recorded (as `(source, results)`), which show
    whether a score with no declared scorer or task metrics used the default
    metrics; it is called only when there is such a score. `complete` is
    whether the merged log is `success`.

    Raises:
        ShardSetError: A sample member's id or epoch does not match its name;
            a score with no declared scorer or task metrics is not the
            default case (see :func:`_default_metrics`); or a sample's epoch
            reduction cannot be taken from its log (see
            :func:`_recompute_results`).
        LookupError: A metric is not registered.
        pydantic.ValidationError: A sample member does not parse.
    """
    with zipfile.ZipFile(out, "w", **zipfile_compress_kwargs) as zf:
        inputs: list[_SampleInputs] = []
        for key in keys:
            data = await read_member(key)
            inputs.append(await anyio.to_thread.run_sync(_write_sample, zf, key, data))
        results, reductions = await _recompute_results(
            template, inputs, total_samples, shard_results, held_reductions, complete
        )
        header = make_header(
            MergedScoring(
                results=results,
                invalidated=any(sample.invalidated for sample in inputs),
            )
        )
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
    scores = sample.scores or {}
    return _SampleInputs(
        scores={
            name: SampleScore(
                score=score, sample_id=sample.id, sample_metadata=sample.metadata
            )
            for name, score in scores.items()
        },
        error=sample.error is not None,
        edited=frozenset(name for name, score in scores.items() if score.history),
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


async def _recompute_results(
    template: EvalLog,
    inputs: list[_SampleInputs],
    total_samples: int,
    shard_results: Callable[[], Awaitable[Sequence[tuple[str, EvalResults]]]],
    held_reductions: HeldReductions,
    complete: bool,
) -> tuple[EvalResults | None, list[EvalSampleReductions] | None]:
    """Metrics over the merged samples, as `eval_results` computes them live.

    A log records its epoch reducers by name only, without their arguments
    (`at_least(1, value=0.5)` is `at_least_1`), so the merge never recreates
    them. Every epoch of a sample runs in one shard, so each sample's reduced
    scores are taken from the `reductions.json` of the log it is merged from,
    which a shard writes when it finishes. With no reducer recorded, the
    reducer is the default `mean`, which is applied as the live run applies
    it.

    A sample whose reduction is not recorded (its shard has not finished)
    leaves an incomplete merged log without results and refuses a complete
    merge. An edited score refuses any merge: its recorded reduction
    predates the edit or was recomputed with a recreated reducer.

    Raises:
        ShardSetError: A reduction cannot be taken from its log, or see
            :func:`_default_metrics`.
    """
    from inspect_ai._eval.score import metrics_from_log_header, resolve_scorers_info
    from inspect_ai._eval.task.results import (
        RecordedReductions,
        ScorerInfo,
        _unique_scorer_names,
        eval_results,
    )

    # resolve_scorers_info imports the task file for an unregistered metric
    check_scoring_resolvable(template)
    metrics = metrics_from_log_header(template)
    scores = [sample.scores for sample in inputs if sample.scores]
    declared = resolve_scorers_info(template)
    others = _other_score_names(declared, scores)
    if metrics is not None:
        other_infos = [ScorerInfo(name=name, metrics=metrics) for name in others]
    elif others:
        recorded = await shard_results()
        other_infos = [
            ScorerInfo(name=name, metrics=_default_metrics(name, recorded, scores))
            for name in others
        ]
    else:
        other_infos = []
    names = template.eval.config.epochs_reducer
    reducers: RecordedReductions | list[ScoreReducer] | None = (
        None if names is None else []
    )
    lookup: _RecordedLookup | None = None
    if names:
        lookup = _RecordedLookup(held_reductions, inputs)
        reducers = RecordedReductions(names, lookup)
    results, reductions = eval_results(
        samples=total_samples,
        scores=scores,
        reducers=reducers,
        scorers=[*declared, *other_infos],
        # the names the worker scored samples under, as the task runner
        # resolves them once: aggregation must not derive them from
        # earlier result names (a per-key result can take a later name)
        scorer_names=[*_unique_scorer_names(declared), *others],
        metrics=metrics,
        completed_samples=sum(1 for sample in inputs if not sample.error),
        headline_metric=template.eval.headline_metric,
    )
    if lookup is not None and lookup.missing is not None:
        if complete:
            raise ShardSetError(lookup.missing)
        return None, held_reductions.reductions
    return results, reductions


class _RecordedLookup:
    """Each sample's recorded reduction (the `reduced` of `RecordedReductions`).

    A sample with no recorded reduction is left out, and `missing` describes
    the first one.
    """

    def __init__(self, held: HeldReductions, inputs: list[_SampleInputs]) -> None:
        self._sources = held.sources
        self._by_view = {
            (r.scorer, r.reducer): {str(s.sample_id): s for s in r.samples}
            for r in held.reductions
        }
        self._edited = {
            (str(sample.scores[name].sample_id), name)
            for sample in inputs
            for name in sample.edited
        }
        self.missing: str | None = None

    def __call__(
        self, scorer: str, reducer: str, scores: list[SampleScore]
    ) -> list[SampleScore]:
        """Raises ShardSetError for an edited score."""
        recorded = self._by_view.get((scorer, reducer), {})
        firsts: dict[str, SampleScore] = {}
        for score in scores:
            firsts.setdefault(str(score.sample_id), score)
        reduced: list[SampleScore] = []
        for id, first in firsts.items():
            source = self._sources[id]
            if (id, scorer) in self._edited:
                raise ShardSetError(
                    f"Score '{scorer}' of sample {id!r} in {source} was edited, so "
                    f"its recorded epoch reduction ('{reducer}') may not match "
                    "it. A log records its epoch reducers by name only, without "
                    "their arguments, so the merge cannot recompute it. Re-run "
                    "the shard holding the sample, or, if the edit is in the "
                    "merged log, delete the merged log so the next merge "
                    "rebuilds it from the shards."
                )
            entry = recorded.get(id)
            if entry is None:
                if self.missing is None:
                    self.missing = (
                        f"{source} records no epoch reduction ('{reducer}') of "
                        f"score '{scorer}' for sample {id!r}. A log records its "
                        "epoch reducers by name only, without their arguments, "
                        "so the merge takes each sample's reduction from the log "
                        "it merges the sample from. Re-run the shard holding the "
                        "sample, or delete the merged log so the next merge "
                        "rebuilds it from the shards."
                    )
                continue
            reduced.append(
                SampleScore(
                    score=Score(**entry.model_dump(exclude={"sample_id"})),
                    sample_id=first.sample_id,
                    sample_metadata=first.sample_metadata,
                )
            )
        return reduced


def _other_score_names(
    declared: list["ScorerInfo"], scores: list[dict[str, SampleScore]]
) -> list[str]:
    """Score names with no declared scorer (solver-set scores), in first-seen order.

    `eval_results` builds their scorer info with `ScorerInfo.from_name`,
    which loads a file-qualified name (`task.py@scorer`, or an existing
    file) as a module and falls back to `accuracy` and `stderr` when it
    cannot load the scorer. The merge imports nothing a log names and must
    not change a score's metrics, so it builds that info itself: the task
    metrics, as in `eval_results`, or else the default metrics when the
    shards recorded exactly those (:func:`_default_metrics`).
    """
    from inspect_ai._eval.task.results import _unique_scorer_names

    names = set(_unique_scorer_names(declared))
    others: list[str] = []
    for sample_scores in scores:
        for name, sample_score in sample_scores.items():
            if sample_score.scorer is None and name not in names:
                others.append(name)
                names.add(name)
    return others


def _default_metrics(
    name: str,
    recorded: Sequence[tuple[str, EvalResults]],
    scores: list[dict[str, SampleScore]],
) -> list[Metric | dict[str, list[Metric]]]:
    """`accuracy` and `stderr` for score `name`, when that is what the shards used.

    `name` has no declared scorer and the task declares no metrics. The
    merge supports only the default case: every current attempt that
    recorded results for `name` recorded exactly `accuracy` and `stderr`
    with their default parameters, and every merged value of `name` is a
    scalar. The results are a display record that cannot be read back into
    any other metric configuration (decision: Ransom, 2026-10-22).

    Raises:
        ShardSetError: Any other case.
    """
    from inspect_ai._util.registry import registry_log_name, registry_params
    from inspect_ai.scorer._metrics.accuracy import accuracy
    from inspect_ai.scorer._metrics.std import stderr

    defaults: list[Metric | dict[str, list[Metric]]] = [accuracy(), stderr()]
    expected = {
        (registry_log_name(m), json.dumps(registry_params(m), sort_keys=True))
        for m in [accuracy(), stderr()]
    }
    rows = [
        (source, score)
        for source, results in recorded
        for score in results.scores
        if score.scorer == name
    ]
    default = bool(rows) and all(
        score.name == name
        and len(score.metrics) == len(expected)
        and {
            (m.name, json.dumps(m.params, sort_keys=True))
            for m in score.metrics.values()
            if m.group is None
        }
        == expected
        for _, score in rows
    )
    scalar = all(
        not isinstance(sample_scores[name].score.value, dict | list)
        for sample_scores in scores
        if name in sample_scores
    )
    if not (default and scalar):
        raise ShardSetError(
            f"The metrics of score '{name}' cannot be established for merging. "
            "It has no declared scorer and the task declares no metrics, so the "
            "merge supports it only when the shards recorded the default "
            "metrics (accuracy and stderr) for a scalar score. Declare the "
            "task's metrics (Task(metrics=...)); shards already written "
            "without declared metrics have to be re-run."
        )
    return defaults
