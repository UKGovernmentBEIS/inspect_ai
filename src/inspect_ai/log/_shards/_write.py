"""Building the merged log's zip, recomputing metrics as samples pass through."""

import collections.abc
import enum
import functools
import inspect
import json
import sys
import types
import typing
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


def recreate_scorers(header: EvalLog) -> list["ScorerInfo"]:
    """The header's scorers with their metrics, recreated for the merge.

    Every merge path that recreates metrics calls this, and the writing
    passes call it before anything is written, so a refusal is raised from
    one place. It checks the header (see :func:`_restored_header`), then
    builds the metrics from the restored options.

    Raises:
        LookupError: A metric is not registered.
        ShardSetError: Two scorers or two epoch reducers have the same name,
            or a metric option cannot be recreated.
    """
    from inspect_ai._eval.score import resolve_scorers_info

    # every metric is registered, so this never imports the task file
    return resolve_scorers_info(_restored_header(header))


def _restored_header(header: EvalLog) -> EvalLog:
    """Refuse metrics the registry cannot resolve, and repeated scorer or reducer names.

    The merge never imports the log's `task_file`, so every scorer's metric
    must already be registered under the name the header records: built
    in, from an installed package, or imported by the caller. A lookup of a
    built-in's short name falls back to the built-in, so a task's own
    `@metric(name="mean")` resolves only when registered itself. Metrics
    embedded in a wrapper's options are recorded without the `inspect_ai/`
    prefix, so there a custom metric with a built-in's short name cannot be
    told from the built-in (decision: Ransom, 2026-10-29). The header
    records the task's metrics (`eval.metrics`) with each scorer they
    replace; otherwise they apply only to solver-set scores, which the merge
    refuses (see :func:`_declared_inputs`), so they are not checked
    separately. Epoch reducers are not recreated (see
    :func:`_recompute_results`): their recorded reductions are told apart by
    name, so two reducers with one name (`at_least(1, value=0.5)` and
    `at_least(1)` are both `at_least_1`) are refused. A scorer declared
    twice is refused too (see :func:`_declared_inputs`). So is a metric
    option, direct or embedded, that the merge cannot recreate (see
    :func:`_check_function_options`).

    Returns:
        A copy of the header whose metric options hold the values the
        metric factories receive (enum members restored), to recreate the
        metrics from. It is never written.

    Raises:
        LookupError: A metric is not registered.
        ShardSetError: Two scorers or two epoch reducers have the same name,
            or a metric option cannot be recreated.
    """
    from inspect_ai._util.registry import registry_info, registry_lookup

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

    scorers_copy = [
        scorer.model_copy(deep=True) for scorer in header.eval.scorers or []
    ]
    for scorer in scorers_copy:
        for metric in _metric_definitions(scorer.metrics):
            factory = registry_lookup("metric", metric.name)
            if factory is None or registry_info(factory).name != metric.name:
                raise LookupError(_unregistered("Metric", metric.name))
            options = _check_function_options(metric.name, factory, metric.options)
            metric.options = _check_embedded(options)
    if header.eval.scorers is None:
        return header
    return header.model_copy(
        update={"eval": header.eval.model_copy(update={"scorers": scorers_copy})}
    )


def _check_embedded(value: Any) -> Any:
    """Refuse unregistered registry objects in a metric's options.

    Wrappers such as `grouped()` and `aggregate()` record the metrics they
    wrap as registry dicts, at any depth, which `registry_arg` creates.
    Returns `value` with the options of embedded metrics checked and
    restored (see :func:`_check_function_options`).
    """
    from inspect_ai._util.registry import is_registry_dict, registry_lookup

    if is_registry_dict(value):
        factory = registry_lookup(value["type"], value["name"])
        if factory is None:
            kind = "Metric" if value["type"] == "metric" else value["type"]
            raise LookupError(_unregistered(kind, value["name"]))
        params = value["params"]
        if value["type"] == "metric":
            params = _check_function_options(value["name"], factory, params)
        return {**value, "params": _check_embedded(params)}
    elif isinstance(value, dict):
        return {key: _check_embedded(item) for key, item in value.items()}
    elif isinstance(value, (list, tuple)):
        return type(value)(_check_embedded(item) for item in value)
    return value


def _check_function_options(
    name: str, factory: object, options: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Refuse a metric option the merge cannot recreate; restore enum members.

    A log records a function option by its name only, so
    `mean(to_float=value_to_float(correct=2))` is recorded as
    `{"to_float": "to_float"}` and the merge cannot recreate it. A string
    option is accepted only when its parameter's own annotation resolves to
    a type whose values cannot be functions: `str`, a `Literal` of plain
    values, an enum, numbers, either with `None`. A parameter annotated with
    any other type (a function type, `Any`, `Hashable`, ...), one with no
    annotation or one whose annotation does not resolve, and an option that
    matches no named parameter (one passed through `**kwargs`) are refused
    (decision: Ransom, 2026-10-30). Each annotation is resolved on its own,
    so another parameter's or the return annotation does not affect it.
    Other scalar option values are checked only for an enum parameter.

    A log records the elements of a list, tuple or dictionary option only
    as plain values, and a tuple as a list. A container option is accepted
    only when its parameter's annotation resolves to lists, sequences and
    dictionaries (with `str` keys) whose elements are `str`, numbers,
    `None`, `Literal`s of those or such containers; anything else, an
    unannotated or unresolvable parameter, and a `**kwargs` option are
    refused (decision: Ransom, 2026-10-30). Embedded registered metrics,
    alone or in containers, are checked by :func:`_check_embedded`.

    A log records an enum option by its value when the enum derives from
    `str`, `int` or `float`, and by its member name otherwise; the option
    is restored to the member the factory received. A value that is not a
    member, or an enum in a union with other types, is refused.

    Returns:
        The options, with enum members restored.

    Raises:
        ShardSetError: An option cannot be recreated.
    """
    restored = dict(options or {})
    if not options or not callable(factory):
        return restored
    for argument, value in options.items():
        if _registered_only(value):
            continue
        resolved = _parameter_annotation(factory, argument)
        if isinstance(value, (list, tuple, dict)):
            reason = resolved.reason
            if reason is None and not _plain_container(resolved.annotation):
                reason = "whose element types are not plain"
            if reason is not None:
                kind = "a dictionary" if isinstance(value, dict) else "a list"
                raise ShardSetError(
                    f"The metric '{name}' was given {kind} for '{argument}', "
                    f"{reason}. A log records the elements of a list or "
                    "dictionary option only as plain values (strings, numbers, "
                    "booleans, None), so the merge cannot recreate other "
                    "elements and does not merge such shards. Annotate "
                    f"'{argument}' with plain element types, such as list[str] "
                    "or dict[str, float], or use a registered metric that "
                    "builds the configuration inside its factory."
                )
            continue
        if resolved.reason is None and _enums(resolved.annotation):
            if value is not None:
                restored[argument] = _restore_enum(
                    name, argument, resolved.annotation, value
                )
            continue
        if not isinstance(value, str):
            continue
        if resolved.reason is None and _is_function_type(resolved.annotation):
            raise ShardSetError(
                f"The metric '{name}' was given a function for '{argument}'. "
                "A log records a function option only by its name, not its "
                "configuration, so the merge cannot recreate the metric and "
                "does not merge such shards. Use a registered metric that "
                "creates the function inside its factory, such as an @metric "
                "that returns mean(to_float=value_to_float(correct=2))."
            )
        reason = resolved.reason
        if reason is None and not _holds_no_function(resolved.annotation):
            reason = "whose type can also hold a function"
        if reason is not None:
            raise ShardSetError(
                f"The metric '{name}' was given a string for '{argument}', "
                f"{reason}. A log records a function option only by its name, "
                "so the merge cannot tell a function's name from a string and "
                f"does not merge such shards. Annotate '{argument}' with a "
                "type the merge can resolve whose values cannot be functions, "
                "such as str, a Literal or an enum, or, if it takes a function, "
                "use a registered metric that creates the function inside its "
                "factory."
            )
    return restored


class _Annotation(NamedTuple):
    annotation: object
    reason: str | None
    """Why the parameter's annotation cannot be used, or None."""


def _parameter_annotation(factory: Callable[..., object], argument: str) -> _Annotation:
    """The resolved annotation of the factory's parameter `argument`.

    `inspect.signature` follows the `@metric` wrapper to the factory, and
    for a class gives its constructor's parameters (`__init__` or `__new__`,
    inherited or generated by a dataclass). The annotation is resolved
    alone, with nested and quoted forward references.
    """
    parameter = inspect.signature(factory).parameters.get(argument)
    if parameter is None or parameter.kind in (
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    ):
        return _Annotation(None, "which is not a named parameter of the metric")
    if parameter.annotation is inspect.Parameter.empty:
        return _Annotation(None, "which has no annotation")

    def alone() -> None:
        pass

    alone.__annotations__ = {argument: parameter.annotation}
    try:
        hints = typing.get_type_hints(alone, *_annotation_namespace(factory))
    except (NameError, AttributeError, SyntaxError, TypeError):
        return _Annotation(None, "whose annotation the merge cannot resolve")
    return _Annotation(_unannotated(hints[argument]), None)


def _annotation_namespace(
    factory: Callable[..., object],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The globals and locals a postponed parameter annotation resolves in."""
    target = inspect.unwrap(factory)
    if isinstance(target, type):
        # the class whose constructor the signature comes from
        for base in target.__mro__:
            if base is not object and (
                "__init__" in vars(base) or "__new__" in vars(base)
            ):
                module = sys.modules.get(base.__module__)
                return (vars(module) if module else {}), dict(vars(base))
        return {}, None
    return getattr(target, "__globals__", {}), None


def _unannotated(annotation: object) -> object:
    """`annotation` without `Annotated` metadata, at any depth of a union."""
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _unannotated(typing.get_args(annotation)[0])
    if origin is typing.Union or origin is types.UnionType:
        return typing.Union[tuple(_unannotated(a) for a in typing.get_args(annotation))]
    return annotation


def _members(annotation: object) -> tuple[object, ...]:
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        return typing.get_args(annotation)
    return (annotation,)


def _is_function_type(annotation: object) -> bool:
    """Whether the type names functions (`Callable`, alone or in a union)."""
    return any(
        member is collections.abc.Callable
        or typing.get_origin(member) is collections.abc.Callable
        for member in _members(annotation)
    )


_PLAIN = (str, int, float, bool, type(None))


def _holds_no_function(annotation: object) -> bool:
    """Whether no value of this type can be a function.

    Only `str`, numbers, `None`, enums and `Literal`s of those qualify;
    every other type is treated as able to hold one.
    """
    for member in _members(annotation):
        if typing.get_origin(member) is typing.Literal:
            if not all(type(value) in _PLAIN for value in typing.get_args(member)):
                return False
        elif not (
            isinstance(member, type)
            and (issubclass(member, _PLAIN) or issubclass(member, enum.Enum))
        ):
            return False
    return True


def _registered_only(value: object) -> bool:
    """Whether `value` is a registry dict, or a container of only those."""
    from inspect_ai._util.registry import is_registry_dict

    if is_registry_dict(value):
        return True
    if isinstance(value, dict):
        return bool(value) and all(_registered_only(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return bool(value) and all(_registered_only(v) for v in value)
    return False


def _plain_container(annotation: object) -> bool:
    """Whether a container recorded for a parameter of this type is restored.

    Every member of the union is :func:`_plain`, or a class (`type[...]`,
    recorded by name, so never a container).
    """
    return all(
        typing.get_origin(member) is type or _plain(member)
        for member in _members(_unannotated(annotation))
    )


def _plain(annotation: object) -> bool:
    """Whether every value of this type is recorded and restored unchanged.

    `str`, `int`, `float`, `bool`, `None` and `Literal`s of those, and
    lists, sequences and `str`-keyed dictionaries of such values, alone or
    in a union. Enums, tuples, sets and every other type are not.
    """
    for member in _members(_unannotated(annotation)):
        member = _unannotated(member)
        origin = typing.get_origin(member)
        args = typing.get_args(member)
        if origin is typing.Literal:
            plain = all(type(value) in _PLAIN for value in args)
        elif origin in (list, collections.abc.Sequence) and len(args) == 1:
            plain = _plain(args[0])
        elif origin in (dict, collections.abc.Mapping) and len(args) == 2:
            plain = _str_keys(args[0]) and _plain(args[1])
        else:
            plain = member in _PLAIN
        if not plain:
            return False
    return True


def _str_keys(annotation: object) -> bool:
    """Whether a dictionary key type survives the log's JSON unchanged."""
    return all(
        member is str
        or (
            typing.get_origin(member) is typing.Literal
            and all(type(value) is str for value in typing.get_args(member))
        )
        for member in _members(_unannotated(annotation))
    )


def _enums(annotation: object) -> list[type[enum.Enum]]:
    return [
        member
        for member in _members(annotation)
        if isinstance(member, type) and issubclass(member, enum.Enum)
    ]


def _restore_enum(
    name: str, argument: str, annotation: object, value: object
) -> enum.Enum:
    """The member the producer recorded as `value` (see `registry_params`).

    Raises:
        ShardSetError: `value` is not a member, or the enum is in a union
            with other types, whose values it cannot be told apart from.
    """
    enums = _enums(annotation)
    others = [m for m in _members(annotation) if m not in enums and m is not type(None)]
    if len(enums) == 1 and not others:
        try:
            if issubclass(enums[0], (str, int, float)):
                return enums[0](value)
            if isinstance(value, str):
                return enums[0][value]
        except (ValueError, KeyError):
            pass
    raise ShardSetError(
        f"The metric '{name}' records {value!r} for '{argument}', which the "
        "merge cannot restore to the enum member the metric was given, so it "
        "does not merge such shards. Annotate the parameter with a single "
        "enum (optionally with None), or use a registered metric that "
        "creates the option inside its factory."
    )


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
            :func:`_declared_inputs`.
    """
    from inspect_ai._eval.task.results import RecordedReductions, eval_results

    infos = recreate_scorers(template)
    scores = _declared_inputs(infos, inputs, held_reductions.sources)
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
    names = header.eval.config.epochs_reducer
    if not names:
        return
    infos = recreate_scorers(header)
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
