"""Operator dispositions of landed samples: exclusion and zero."""

import math
from copy import deepcopy
from typing import NamedTuple, Sequence, TypeAlias

from inspect_ai.scorer._metric import UNCHANGED, Score, ScoreEdit, score_is_excluded

from ._edit import ProvenanceData
from ._log import EvalLog, EvalSample

SampleSelector: TypeAlias = int | str | tuple[int | str, int]
"""A sample id (every epoch of it) or an (id, epoch) pair.

A string id also matches an integer sample id with the same `str()`.
"""


class DispositionResult(NamedTuple):
    """Samples a disposition edited or left as they were."""

    applied: list[tuple[int | str, int]]
    """(id, epoch) of each sample edited now."""

    unchanged: list[tuple[int | str, int]]
    """(id, epoch) of each sample that was already excluded (exclusion only)."""


def exclude_samples(
    log: EvalLog,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
) -> DispositionResult:
    """Exclude samples from the log's metrics.

    Each score the sample holds is edited to an unscored `NaN` with the reason
    `"excluded"`, recording `provenance` and keeping the earlier score in
    `Score.history`. A sample that holds no score (for example one that errored
    before scoring) gets one, under the log's first scorer. Epoch reduction
    leaves excluded epochs out. The sample's transcript, output and error are
    not changed, so `eval-retry` still re-runs an errored sample.

    The log is edited in place and its metrics recomputed. Use
    `write_eval_log()` to save it.

    Metrics and epoch reducers are rebuilt from the log header without
    importing the task file. If the eval used a metric or reducer defined in
    its task file, import that module first.

    Args:
       log: Log read with its samples. It must not have status `"started"`.
       samples: Samples to exclude. A sample id selects every epoch of the
          sample, and an `(id, epoch)` pair selects one.
       provenance: Author and reason for the exclusion. `reason` is
          required, and is also used as the score's explanation.

    Returns:
       The (id, epoch) of each sample excluded now, and of each one already
       excluded (left unchanged).

    Raises:
       ValueError: The log has no samples or is still being written, the
          reason is empty, a selector matches no sample, or a sample with no
          score is in a log that names no scorer. Nothing is edited.
       LookupError: A metric or epoch reducer of the log is not registered.
          Nothing is edited.
    """
    _check_disposition(log, provenance)
    targets = _select_samples(log, samples)

    edits: list[tuple[EvalSample, list[str]]] = []
    unchanged: list[EvalSample] = []
    no_scorer: list[EvalSample] = []
    for sample in targets:
        if sample.scores:
            if all(score_is_excluded(score) for score in sample.scores.values()):
                unchanged.append(sample)
            else:
                edits.append((sample, list(sample.scores)))
        elif log.eval.scorers:
            edits.append((sample, [log.eval.scorers[0].name]))
        else:
            no_scorer.append(sample)
    if no_scorer:
        raise ValueError(
            "; ".join(
                f"sample {_label(sample)} holds no score and the log names no "
                "scorer to record the exclusion under"
                for sample in no_scorer
            )
        )

    _apply_edits(
        log,
        [
            (
                sample,
                {
                    name: ScoreEdit(
                        value=float("nan"),
                        reason="excluded",
                        explanation=provenance.reason,
                        provenance=provenance,
                    )
                    for name in names
                },
            )
            for sample, names in edits
        ],
    )

    return DispositionResult(
        applied=[(sample.id, sample.epoch) for sample, _ in edits],
        unchanged=[(sample.id, sample.epoch) for sample in unchanged],
    )


_EMPTY_ATTEMPT_SOLVERS = ("inspect_ai/empty_attempt", "empty_attempt")
"""Names the `empty_attempt()` solver is recorded under.

The registry name, or the bare name that `--solver empty_attempt` records.
"""

_SCANNER_REFERENCES = "scanner_references"


def zero_samples(
    log: EvalLog,
    empty: EvalLog,
    samples: Sequence[SampleSelector],
    provenance: ProvenanceData,
) -> DispositionResult:
    """Score samples as empty attempts, from the log of an empty attempt.

    `empty` is the log of an eval of the same task run with the
    `empty_attempt()` solver, which does nothing, so the task's scorers scored
    the untouched sample. Each score that the empty-attempt sample holds is
    copied into the matching sample of `log` under the same name, with the
    reason `"zeroed"` and `provenance`. The earlier score stays in
    `Score.history`, and the sample's transcript, output and error are not
    changed.

    Only samples with string ids can be zeroed, and only verdicts that count
    in metrics: a single value that is not `NaN` and cites no messages or
    events of the empty attempt's transcript. Other samples can be excluded
    instead (`exclude_samples()`).

    The log is edited in place and its metrics recomputed. Use
    `write_eval_log()` to save it.

    Metrics and epoch reducers are rebuilt from the log header without
    importing the task file. If the eval used a metric or reducer defined in
    its task file, import that module first.

    Args:
       log: Log read with its samples. It must not have status `"started"`.
       empty: Log of the empty attempt, read with its samples. It must have
          status `"success"`, the solver `empty_attempt()`, the task name of
          `log` and the same scorers, and hold every targeted sample and epoch.
       samples: Samples to zero. A sample id selects every epoch of the
          sample, and an `(id, epoch)` pair selects one.
       provenance: Author and reason for the zero. `reason` is required.

    Returns:
       The (id, epoch) of each sample zeroed. `unchanged` is always empty:
       zeroing a sample again applies the verdicts again.

    Raises:
       ValueError: Either log has no samples, `log` is still being written,
          the reason is empty, a selector matches no sample, the empty-attempt
          log does not match `log`, or a target has no counted verdict in the
          empty-attempt log. Nothing is edited.
       LookupError: A metric or epoch reducer of the log is not registered.
          Nothing is edited.
    """
    _check_disposition(log, provenance)
    targets = _select_samples(log, samples)
    _check_empty_attempt(log, empty)

    empty_samples = {
        (sample.id, sample.epoch): sample for sample in empty.samples or []
    }
    edits: list[tuple[EvalSample, dict[str, ScoreEdit]]] = []
    problems: list[str] = []
    for sample in targets:
        if not isinstance(sample.id, str):
            problems.append(
                f"sample {_label(sample)}: the id is an integer, which need not "
                "name the same sample in another run"
            )
            continue
        empty_sample = empty_samples.get((sample.id, sample.epoch))
        if empty_sample is None:
            problems.append(
                f"sample {_label(sample)}: the empty-attempt log has no such "
                "sample and epoch"
            )
            continue
        causes = _verdict_problems(sample, empty_sample)
        if causes:
            problems.extend(f"sample {_label(sample)}: {cause}" for cause in causes)
            continue
        edits.append(
            (
                sample,
                {
                    name: ScoreEdit(
                        value=verdict.value,
                        answer=verdict.answer,
                        explanation=verdict.explanation,
                        metadata=deepcopy(verdict.metadata or {}),
                        reason="zeroed",
                        provenance=provenance,
                    )
                    for name, verdict in (empty_sample.scores or {}).items()
                },
            )
        )
    if problems:
        raise ValueError(
            "Cannot zero these samples; nothing was edited. A sample without a "
            "counted verdict can be excluded instead.\n"
            + "\n".join(f"- {problem}" for problem in problems)
        )

    _apply_edits(log, edits)

    return DispositionResult(
        applied=[(sample.id, sample.epoch) for sample, _ in edits],
        unchanged=[],
    )


def _check_empty_attempt(log: EvalLog, empty: EvalLog) -> None:
    if empty.samples is None:
        raise ValueError(
            "The empty-attempt log has no samples. Read it whole (not "
            "header_only) first."
        )
    if empty.status != "success":
        raise ValueError(
            f"The empty-attempt log has status '{empty.status}', not 'success'."
        )
    if empty.eval.solver not in _EMPTY_ATTEMPT_SOLVERS:
        raise ValueError(
            f"The empty-attempt log was run with the solver {empty.eval.solver!r}, "
            f"not {_EMPTY_ATTEMPT_SOLVERS[0]!r}."
        )
    if empty.eval.task != log.eval.task:
        raise ValueError(
            f"The empty-attempt log is of the task {empty.eval.task!r}, not "
            f"{log.eval.task!r}."
        )
    log_scorers = [scorer.name for scorer in log.eval.scorers or []]
    empty_scorers = [scorer.name for scorer in empty.eval.scorers or []]
    if not log_scorers:
        raise ValueError("The log names no scorer, so it has no verdict to zero.")
    if empty_scorers != log_scorers:
        raise ValueError(
            f"The scorers of the empty-attempt log {empty_scorers} are not "
            f"those of the log {log_scorers}."
        )


def _verdict_problems(sample: EvalSample, empty_sample: EvalSample) -> list[str]:
    """Why the empty attempt holds no counted verdict for the sample, if so."""
    if empty_sample.error is not None:
        return [f"the empty attempt errored: {empty_sample.error.message}"]
    if empty_sample.limit is not None:
        return [f"the empty attempt hit its {empty_sample.limit.type} limit"]
    verdicts = empty_sample.scores or {}
    if not verdicts:
        return ["no verdict (the empty attempt holds no score)"]
    problems = [
        f"score {name!r}: {cause}"
        for name, verdict in verdicts.items()
        if (cause := _uncounted(verdict)) is not None
    ]
    problems.extend(
        f"score {name!r}: the empty attempt does not produce this score"
        for name in sample.scores or {}
        if name not in verdicts
    )
    return problems


def _uncounted(verdict: Score) -> str | None:
    """Why the verdict would not count as a zero, or None when it would."""
    value = verdict.value
    if not isinstance(value, str | int | float | bool):
        return "a dict or list value (zero supports single-value verdicts only)"
    if isinstance(value, float) and math.isnan(value):
        return (
            f"an unscored value (reason {verdict.reason!r}, explanation "
            f"{verdict.explanation!r})"
        )
    if (verdict.metadata or {}).get(_SCANNER_REFERENCES):
        return (
            "transcript references (the verdict cites messages or events of "
            "the empty attempt, which this sample's transcript does not hold)"
        )
    for field, text in (
        ("value", value),
        ("answer", verdict.answer),
        ("explanation", verdict.explanation),
    ):
        if text == UNCHANGED:
            return (
                f"the {field} is {UNCHANGED!r}, which a score edit reads as "
                "keeping the current one"
            )
    return None


def _apply_edits(
    log: EvalLog, edits: list[tuple[EvalSample, dict[str, ScoreEdit]]]
) -> None:
    """Apply the score edits, then recompute the log's metrics."""
    # imported here: they import the runner, which imports inspect_ai.log
    from ._metric import compute_log_metrics, resolve_log_metrics
    from ._score import edit_score

    if not edits:
        return
    # before any edit, so a missing metric or reducer leaves the log as is;
    # there is no trust_log option to advise
    resolved = resolve_log_metrics(log, trust_log_advice=False)
    for sample, score_edits in edits:
        for name, edit in score_edits.items():
            edit_score(
                log, sample.id, name, edit, recompute_metrics=False, epoch=sample.epoch
            )
    compute_log_metrics(log, resolved)


def _check_disposition(log: EvalLog, provenance: ProvenanceData) -> None:
    if log.samples is None:
        raise ValueError(
            "The log has no samples. Read it whole (not header_only) first."
        )
    if log.status == "started":
        raise ValueError(
            "The log is still being written (status 'started'). Run this once "
            "the eval finishes."
        )
    if not isinstance(provenance.reason, str) or not provenance.reason.strip():
        raise ValueError("A reason is required (provenance.reason).")


def _select_samples(
    log: EvalLog, selectors: Sequence[SampleSelector]
) -> list[EvalSample]:
    """Samples the selectors match, in selector order and without repeats.

    Raises:
        ValueError: A selector has another shape, or matches no sample.
    """
    samples = log.samples or []
    selected: dict[tuple[int | str, int], EvalSample] = {}
    unmatched: list[SampleSelector] = []
    for selector in selectors:
        if isinstance(selector, tuple):
            if (
                len(selector) != 2
                or not isinstance(selector[0], int | str)
                or not isinstance(selector[1], int)
            ):
                raise ValueError(
                    f"Sample selector {selector!r} is not an id or an (id, epoch) pair."
                )
            selector_id: int | str = selector[0]
            epoch: int | None = selector[1]
        elif isinstance(selector, int | str):
            selector_id, epoch = selector, None
        else:
            raise ValueError(
                f"Sample selector {selector!r} is not an id or an (id, epoch) pair."
            )
        matches = [
            sample
            for sample in samples
            if _id_matches(selector_id, sample.id)
            and (epoch is None or sample.epoch == epoch)
        ]
        if not matches:
            unmatched.append(selector)
        for sample in matches:
            selected.setdefault((sample.id, sample.epoch), sample)
    if unmatched:
        raise ValueError(
            "No sample matches: " + ", ".join(repr(s) for s in unmatched) + "."
        )
    return list(selected.values())


def _id_matches(selector_id: int | str, sample_id: int | str) -> bool:
    if isinstance(selector_id, str) and isinstance(sample_id, int):
        return str(sample_id) == selector_id
    return type(selector_id) is type(sample_id) and selector_id == sample_id


def _label(sample: EvalSample) -> str:
    return f"{sample.id!r} (epoch {sample.epoch})"
