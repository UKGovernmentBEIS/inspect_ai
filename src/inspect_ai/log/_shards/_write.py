"""Building the merged log's zip, recomputing metrics as samples pass through."""

import functools
import json
import re
import zipfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, BinaryIO, NamedTuple

import anyio

from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.json import to_json_safe
from inspect_ai._util.zipfile import zipfile_compress_kwargs
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.log._log import (
    EvalLog,
    EvalMetricDefinition,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
    EvalSampleScore,
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
from inspect_ai.scorer._reducer.types import ScoreReducer

from ._errors import ShardSetError

if TYPE_CHECKING:
    from inspect_ai._eval.task.results import ScorerInfo


class _SampleInputs(NamedTuple):
    """What metric recomputation keeps of a sample."""

    scores: dict[str, SampleScore]
    """The sample's scores, with its final metadata (`EvalSample.metadata`)."""
    initialized: bool
    """Whether the sample has a `SampleInitEvent`."""
    initial_metadata: dict[str, Any] | None
    """The dataset metadata its `SampleInitEvent` records, before any solver
    changed it."""
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

    unfinished: Callable[[], Awaitable[set[str]]]
    """The held sample ids whose shard has not finished (no recorded
    reductions yet); called only when a reduction is missing."""


class MergedScoring(NamedTuple):
    """What the merged header takes from the merged samples."""

    results: EvalResults | None
    invalidated: bool
    """Whether any merged sample is invalidated."""


def check_scoring_resolvable(header: EvalLog) -> None:
    """Refuse metrics the registry cannot resolve, and repeated scorer or reducer names.

    The merge never imports the log's `task_file`, so every scorer's metric
    must already be registered: built in, from an installed package, or
    imported by the caller. The header records the task's metrics
    (`eval.metrics`) with each scorer they replace; otherwise they apply only
    to solver-set scores, which the merge refuses (see
    :func:`_declared_inputs`), so they are not checked separately. Epoch
    reducers are not recreated (see :func:`_recompute_results`): their
    recorded reductions are told apart by name, so two reducers with one
    name (`at_least(1, value=0.5)` and `at_least(1)` are both `at_least_1`)
    are refused. A scorer declared twice is refused too (see
    :func:`_declared_inputs`).

    Raises:
        LookupError: A metric is not registered.
        ShardSetError: Two scorers or two epoch reducers have the same name.
    """
    from inspect_ai._util.registry import registry_lookup

    scorers = [scorer.name for scorer in header.eval.scorers or []]
    duplicated = sorted({name for name in scorers if scorers.count(name) > 1})
    if duplicated:
        raise ShardSetError(
            f"The task declares the scorer {', '.join(duplicated)} more than "
            "once, so its later scores are recorded under suffixed names "
            f"('{duplicated[0]}1'). The scorer a metric sees for those scores "
            "differs between a fresh run and a retry, so the merge cannot "
            "establish their metric inputs and does not merge such shards. "
            "Declare each scorer once."
        )

    names = header.eval.config.epochs_reducer or []
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ShardSetError(
            f"The epoch reducers {names} name {', '.join(repeated)} more than "
            "once. A log records its reducers by name only, so the merge cannot "
            "tell their reductions apart and does not merge such shards."
        )

    for scorer in header.eval.scorers or []:
        for metric in _metric_definitions(scorer.metrics):
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
    held_reductions: HeldReductions,
    make_header: Callable[[MergedScoring], EvalLog],
) -> EvalLog:
    """Write the merged log's members to `out` and return its header.

    Each sample is read with `read_member`, validated, written under the name
    rebuilt from its key and reduced to its metric inputs before the next is
    read. Then the summaries, the reductions and the header (made by
    `make_header` from the recomputed results and the samples'
    invalidation) are written. No journal is written: the merged log is
    always written finished.

    Raises:
        ShardSetError: A sample member's id or epoch does not match its name;
            a sample's metric inputs cannot be established (see
            :func:`_declared_inputs`); or a sample's epoch reduction cannot be
            taken from its log (see :func:`_recompute_results`).
        LookupError: A metric is not registered.
        pydantic.ValidationError: A sample member does not parse.
    """
    with zipfile.ZipFile(out, "w", **zipfile_compress_kwargs) as zf:
        inputs: list[_SampleInputs] = []
        for key in keys:
            data = await read_member(key)
            inputs.append(await anyio.to_thread.run_sync(_write_sample, zf, key, data))
        results, reductions = await _recompute_results(
            template, inputs, total_samples, held_reductions
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
    init = next((e for e in sample.events if isinstance(e, SampleInitEvent)), None)
    return _SampleInputs(
        scores={
            name: SampleScore(
                score=score, sample_id=sample.id, sample_metadata=sample.metadata
            )
            for name, score in scores.items()
        },
        initialized=init is not None,
        initial_metadata=init.sample.metadata if init is not None else None,
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
    held_reductions: HeldReductions,
) -> tuple[EvalResults | None, list[EvalSampleReductions] | None]:
    """Metrics over the merged samples, as `eval_results` computes them live.

    A log records its epoch reducers by name only, without their arguments
    (`at_least(1, value=0.5)` is `at_least_1`), so the merge never recreates
    them. Every epoch of a sample runs in one shard, so each sample's reduced
    scores are taken from the `reductions.json` of the log it is merged from,
    which a shard writes when it finishes. With no reducer recorded, the
    reducer is the default `mean`, which is applied as the live run applies
    it.

    When the samples whose reduction is not recorded all belong to shards
    that have not finished, the merged log (incomplete) is written without
    results, keeping the reductions recorded so far (decision: Ransom,
    2026-10-23). A finished shard (or the merged log) without a recorded
    reduction, a recovered attempt, and an edited score are refused: an
    edited score's recorded reduction predates the edit or was recomputed
    with a recreated reducer.

    Raises:
        ShardSetError: A reduction cannot be taken from its log, or see
            :func:`_declared_inputs` and :func:`_check_glob_key_sets`.
    """
    from inspect_ai._eval.score import resolve_scorers_info
    from inspect_ai._eval.task.results import RecordedReductions, eval_results

    # resolve_scorers_info imports the task file for an unregistered metric
    check_scoring_resolvable(template)
    infos = resolve_scorers_info(template)
    scores = _declared_inputs(infos, inputs, held_reductions.sources)
    _check_glob_key_sets(infos, scores, held_reductions.sources)
    # the names the worker scored samples under (each scorer is declared
    # once): aggregation must not derive them from earlier result names (a
    # per-key result can take a later name)
    scorer_names = [info.name for info in infos]
    names = template.eval.config.epochs_reducer
    reducers: RecordedReductions | list[ScoreReducer] | None = (
        None if names is None else []
    )
    if names:
        edited = [
            (str(sample.scores[name].sample_id), name)
            for sample in inputs
            for name in sorted(sample.edited)
        ]
        if edited:
            id, name = edited[0]
            raise ShardSetError(
                edited_score_message(name, id, held_reductions.sources[id])
            )
        # settled before any metric runs, so a running shard's samples never
        # reach a metric without their reductions
        by_view = _by_view(held_reductions.reductions)
        missing = _missing_reductions(
            _reduced_score_names(infos),
            names,
            _score_ids(scores),
            by_view,
        )
        if missing:
            unfinished = await held_reductions.unfinished()
            finished = [m for m in missing if m.sample_id not in unfinished]
            if finished:
                raise ShardSetError(
                    _missing_message(
                        finished[0], held_reductions.sources[finished[0].sample_id]
                    )
                    + " Re-run the shard holding the sample, or delete the merged "
                    "log so the next merge rebuilds it from the shards."
                )
            return None, held_reductions.reductions
        reducers = RecordedReductions(names, functools.partial(_recorded, by_view))
    return eval_results(
        samples=total_samples,
        scores=scores,
        reducers=reducers,
        scorers=infos,
        scorer_names=scorer_names,
        metrics=None,
        completed_samples=sum(1 for sample in inputs if not sample.error),
        headline_metric=template.eval.headline_metric,
    )


def _declared_inputs(
    declared: list["ScorerInfo"],
    inputs: list[_SampleInputs],
    sources: Mapping[str, str],
) -> list[dict[str, SampleScore]]:
    """The samples' scores as a fresh run passes them to metrics.

    A fresh run gives a declared scorer's scores the sample's dataset
    metadata, before any solver changed it, and the scorer's unqualified
    registry name, which the header keeps as the declared scorer's name. A
    retry reusing a sample passes its final metadata and score key instead;
    the merge follows the fresh run. The dataset metadata is taken from the
    sample's `SampleInitEvent`.

    A score with no declared scorer (set by a solver) is refused: a fresh
    run and a retry give its metrics different inputs, and no task in use
    sets one (decision: Ransom, 2026-10-28).

    Raises:
        ShardSetError: A sample has a score with no declared scorer, or has
            scores but no `SampleInitEvent`.
    """
    names = {info.name for info in declared}
    scores: list[dict[str, SampleScore]] = []
    for sample in inputs:
        if not sample.scores:
            continue
        id = str(next(iter(sample.scores.values())).sample_id)
        other = next((name for name in sample.scores if name not in names), None)
        if other is not None:
            raise ShardSetError(
                f"Sample {id!r} in {sources[id]} has the score '{other}', which "
                "no scorer the task declares produced (a solver set it). The "
                "merge cannot merge solver-set scores: a fresh run and a retry "
                "give their metrics different inputs. Score with a scorer "
                "declared on the task (Task(scorer=...)) and re-run the shards."
            )
        if not sample.initialized:
            raise ShardSetError(
                f"Sample {id!r} in {sources[id]} has no sample_init event, which "
                "records the dataset metadata a fresh run gives its scorers' "
                "metrics, so the merge cannot establish their inputs (a sample "
                "whose record could not be serialized is logged without its "
                "events). Re-run the shard holding the sample."
            )
        scores.append(
            {
                name: score.model_copy(
                    update={"scorer": name, "sample_metadata": sample.initial_metadata}
                )
                for name, score in sample.scores.items()
            }
        )
    return scores


# fnmatch's pattern characters, as `resolve_glob_metric_keys` matches keys
_GLOB_CHARS = re.compile(r"[*?[]")


def _check_glob_key_sets(
    declared: list["ScorerInfo"],
    scores: list[dict[str, SampleScore]],
    sources: Mapping[str, str],
) -> None:
    """Refuse dictionary scores with differing keys under a pattern metric key.

    A scorer's dictionary metric whose key is a pattern (`{"*": [mean()]}`)
    is expanded from the keys of the first sample's score. The merge orders
    samples by id and epoch, not as a single run does, so when the samples'
    keys differ the merged metrics could differ from the run's. With the same
    keys only the order of the result rows can differ (decision: Ransom,
    2026-10-28). Raw scores are checked, which also covers the reduced views.

    Raises:
        ShardSetError: Two samples' dictionary scores for such a scorer have
            different keys.
    """
    for info in declared:
        groups = info.metrics if isinstance(info.metrics, list) else [info.metrics]
        patterns = [
            key
            for group in groups
            if isinstance(group, dict)
            for key in group
            if _GLOB_CHARS.search(key)
        ]
        if not patterns:
            continue
        first: tuple[str, set[str]] | None = None
        for sample_scores in scores:
            score = sample_scores.get(info.name)
            if score is None or not isinstance(score.score.value, dict):
                continue
            id, keys = str(score.sample_id), set(score.score.value)
            if first is None:
                first = (id, keys)
            elif keys != first[1]:
                first_id, first_keys = first
                raise ShardSetError(
                    f"Sample {id!r} in {sources[id]} has the score '{info.name}' "
                    f"with the keys {sorted(keys)}, but sample {first_id!r} in "
                    f"{sources[first_id]} has {sorted(first_keys)}. The metrics "
                    f"for '{patterns[0]}' take their keys from the first sample, "
                    "which differs between the merge and a single run, so the "
                    "merge cannot merge these scores. Give every sample the "
                    "same keys, or name the keys in the scorer's metrics."
                )


def check_retained_reductions(
    header: EvalLog,
    score_ids: dict[str, set[str]],
    reductions: list[EvalSampleReductions],
    location: str,
) -> None:
    """Refuse a merged log whose `reductions.json` lacks a required reduction.

    Before shards are deleted by a pass that wrote nothing, the merged log's
    recorded reductions are the only copy of the shards' once the shards are
    gone. With epoch reducers recorded, every reduced view (a scorer with
    reduced metrics, times each reducer) must hold every sample that has the
    score. `score_ids` maps each score name in the merged samples to the ids
    of the samples holding it, in first-seen order.

    Raises:
        LookupError: A metric is not registered.
        ShardSetError: A required reduction is missing.
    """
    from inspect_ai._eval.score import resolve_scorers_info

    names = header.eval.config.epochs_reducer
    if not names:
        return
    check_scoring_resolvable(header)
    infos = resolve_scorers_info(header)
    missing = _missing_reductions(
        _reduced_score_names(infos),
        names,
        score_ids,
        _by_view(reductions),
    )
    if missing:
        raise ShardSetError(
            _missing_message(missing[0], location)
            + " Its shards were not deleted. Delete the merged log so the next "
            "merge rebuilds it from the shards."
        )


class _Missing(NamedTuple):
    sample_id: str
    scorer: str
    reducer: str


def _by_view(
    reductions: list[EvalSampleReductions],
) -> dict[tuple[str, str | None], dict[str, EvalSampleScore]]:
    return {
        (r.scorer, r.reducer): {str(s.sample_id): s for s in r.samples}
        for r in reductions
    }


def _score_ids(scores: list[dict[str, SampleScore]]) -> dict[str, set[str]]:
    ids: dict[str, set[str]] = {}
    for sample_scores in scores:
        for name, score in sample_scores.items():
            ids.setdefault(name, set()).add(str(score.sample_id))
    return ids


def _reduced_score_names(infos: list["ScorerInfo"]) -> list[str]:
    """The scorer names whose metrics include reduced ones (a reduced view)."""
    from inspect_ai._eval.task.results import _filter_metrics_by_scores

    return [
        info.name
        for info in infos
        if _filter_metrics_by_scores(info.metrics, {"auto", "reduced"}) is not None
    ]


def _missing_reductions(
    scorer_names: list[str],
    reducers: list[str],
    score_ids: dict[str, set[str]],
    by_view: dict[tuple[str, str | None], dict[str, EvalSampleScore]],
) -> list[_Missing]:
    """The (sample, scorer, reducer) reductions that are required but not recorded."""
    return [
        _Missing(id, scorer, reducer)
        for scorer in scorer_names
        for reducer in reducers
        for id in sorted(score_ids.get(scorer, set()))
        if id not in by_view.get((scorer, reducer), {})
    ]


def _missing_message(missing: _Missing, location: str) -> str:
    return (
        f"{location} records no epoch reduction ('{missing.reducer}') of score "
        f"'{missing.scorer}' for sample {missing.sample_id!r}. A log records its "
        "epoch reducers by name only, without their arguments, so the merge "
        "takes each sample's reduction from the log it merges the sample from."
    )


def edited_score_message(score: str, sample_id: str, location: str) -> str:
    """The refusal for an edited score when epoch reducers are recorded."""
    return (
        f"Score '{score}' of sample {sample_id!r} in {location} was edited. With "
        "an epoch reducer set, the merge takes each sample's reduced scores from "
        "the log it merges the sample from, and an edited score's recorded "
        "reduction may not match it: the log records its reducers by name only, "
        "so the merge cannot recompute it. Re-run the shard holding the sample, "
        "or, if the edit is in the merged log, delete the merged log so the "
        "next merge rebuilds it from the shards."
    )


def _recorded(
    by_view: dict[tuple[str, str | None], dict[str, EvalSampleScore]],
    scorer: str,
    reducer: str,
    scores: list[SampleScore],
) -> list[SampleScore]:
    """Each sample's recorded reduction (the `reduced` of `RecordedReductions`).

    Every one is present: `_missing_reductions` was checked first. A scorer
    with no scores (no sample scored yet) may have no recorded view.
    """
    recorded = by_view.get((scorer, reducer), {})
    firsts: dict[str, SampleScore] = {}
    for score in scores:
        firsts.setdefault(str(score.sample_id), score)
    return [
        SampleScore(
            score=Score(**recorded[id].model_dump(exclude={"sample_id"})),
            sample_id=first.sample_id,
            sample_metadata=first.sample_metadata,
        )
        for id, first in firsts.items()
    ]
