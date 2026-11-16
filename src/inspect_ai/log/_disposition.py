"""Operator dispositions of landed samples: exclusion."""

from typing import NamedTuple, Sequence, TypeAlias

from inspect_ai.scorer._metric import ScoreEdit, score_is_excluded

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
    """(id, epoch) of each sample that was already excluded."""


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
    # imported here: they import the runner, which imports inspect_ai.log
    from ._metric import compute_log_metrics, resolve_log_metrics
    from ._score import edit_score

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

    if edits:
        # before any edit, so a missing metric or reducer leaves the log as is;
        # there is no trust_log option to advise
        resolved = resolve_log_metrics(log, trust_log_advice=False)
        for sample, names in edits:
            for name in names:
                edit_score(
                    log,
                    sample.id,
                    name,
                    ScoreEdit(
                        value=float("nan"),
                        reason="excluded",
                        explanation=provenance.reason,
                        provenance=provenance,
                    ),
                    recompute_metrics=False,
                    epoch=sample.epoch,
                )
        compute_log_metrics(log, resolved)

    return DispositionResult(
        applied=[(sample.id, sample.epoch) for sample, _ in edits],
        unchanged=[(sample.id, sample.epoch) for sample in unchanged],
    )


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
