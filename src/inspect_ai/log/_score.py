"""Score editing functionality."""

from typing import Any

from inspect_ai.event._score_edit import ScoreEditEvent
from inspect_ai.event._tree import EventTree, EventTreeSpan, event_tree, walk_node_spans
from inspect_ai.scorer._metric import Score, ScoreEdit

from ._log import EvalLog
from ._metric import recompute_metrics as _recompute_metrics


def edit_score(
    log: EvalLog,
    sample_id: int | str,
    score_name: str,
    edit: ScoreEdit,
    recompute_metrics: bool = True,
    epoch: int | None = None,
) -> None:
    """Edit or add a score in-place.

    Args:
        log: The evaluation log containing the samples and scores
        sample_id: ID of the sample containing the score to edit or add to
        score_name: Name of the score to edit. If the score does not exist,
            a new score will be created with this name.
        edit: The edit to apply to the score. When creating a new score,
            the 'value' field must be provided (cannot be UNCHANGED). A metadata
            dict on the edit replaces `Score.metadata` rather than merging into
            it -- carry over any scorer-recorded keys you want to keep (the
            pre-edit dict remains available via `Score.history`). When the edit
            sets `reason` explicitly, the legacy `unscored_reason` key is
            dropped from the supplied metadata so a log round-trip cannot
            resurrect the superseded reason.
        recompute_metrics: Whether to recompute aggregate metrics after editing
        epoch: Epoch number of the sample to edit (required when there are multiple epochs)

    Raises:
        ValueError: If the sample cannot be found, if epoch is not specified
            and there are multiple matching samples for an ID, or if creating
            a new score without providing a value.
    """
    if log.samples is None:
        raise ValueError("Log contains no samples")

    if epoch is not None:
        sample = next(
            (
                sample
                for sample in log.samples
                if sample.id == sample_id and sample.epoch == epoch
            ),
            None,
        )
        if sample is None:
            raise ValueError(f"Sample with id {sample_id} and epoch {epoch} not found")
    else:
        samples = [sample for sample in log.samples if sample.id == sample_id]

        if not samples:
            raise ValueError(f"Sample with id {sample_id} not found")

        if len(samples) > 1:
            raise ValueError(
                f"Multiple samples found with id {sample_id}. You must specify the epoch parameter."
            )

        sample = samples[0]

    if sample.scores is None:
        sample.scores = {}

    is_new_score = score_name not in sample.scores

    if is_new_score:
        if edit.value == "UNCHANGED":
            raise ValueError(
                f"Cannot add new score '{score_name}' without providing a value. "
                "The 'value' field is required when creating a new score."
            )

        new_metadata = edit.metadata if edit.metadata != "UNCHANGED" else None
        if edit.reason != "UNCHANGED":
            new_metadata = _drop_legacy_unscored_reason(new_metadata)

        new_score = Score(
            value=edit.value,
            answer=edit.answer if edit.answer != "UNCHANGED" else None,
            explanation=edit.explanation if edit.explanation != "UNCHANGED" else None,
            reason=edit.reason if edit.reason != "UNCHANGED" else None,
            metadata=new_metadata,
            history=[edit],
        )
        sample.scores[score_name] = new_score
    else:
        score = sample.scores[score_name]

        if not score.history:
            original = ScoreEdit(
                value=score.value,
                answer=score.answer,
                explanation=score.explanation,
                reason=score.reason,
                metadata=score.metadata or {},
            )
            score.history.append(original)

        if edit.value != "UNCHANGED":
            score.value = edit.value
        if edit.answer != "UNCHANGED":
            score.answer = edit.answer
        if edit.explanation != "UNCHANGED":
            score.explanation = edit.explanation
        if edit.reason != "UNCHANGED":
            score.reason = edit.reason
        if edit.metadata != "UNCHANGED":
            score.metadata = edit.metadata

        if edit.reason != "UNCHANGED":
            # An explicit edit to `reason` (including clearing it to None)
            # supersedes any legacy `metadata["unscored_reason"]` left over
            # from pre-#4567 logs - otherwise a future re-read of the
            # persisted log would resurrect the old reason via the
            # `_lift_unscored_reason` shim.
            score.metadata = _drop_legacy_unscored_reason(score.metadata)

        score.history.append(edit)

    final_scorers_node = _find_scorers_span(event_tree(sample.events))
    score_edit_event = ScoreEditEvent(score_name=score_name, edit=edit)

    if final_scorers_node:
        score_edit_event.span_id = final_scorers_node.begin.id

    # Insert event just before the end of the scorers span, or at end if no span
    end_index = len(sample.events)
    if final_scorers_node and final_scorers_node.end is not None:
        for i, ev in enumerate(reversed(sample.events)):
            if ev == final_scorers_node.end:
                end_index = len(sample.events) - 1 - i
                break

    sample.events.insert(end_index, score_edit_event)

    if recompute_metrics:
        _recompute_metrics(log)


def _find_scorers_span(tree: EventTree) -> EventTreeSpan | None:
    last_scorers_node = None
    for node in walk_node_spans(tree):
        if node.type == "scorers" and node.name == "scorers":
            last_scorers_node = node
    return last_scorers_node


def _drop_legacy_unscored_reason(
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return metadata with the legacy `unscored_reason` key removed.

    Returns a new dict rather than mutating in place, since the passed-in
    metadata may be aliased elsewhere (e.g. by `ScoreEdit.metadata` retained
    in `Score.history` or in the emitted `ScoreEditEvent`).
    """
    if not isinstance(metadata, dict) or "unscored_reason" not in metadata:
        return metadata
    return {k: v for k, v in metadata.items() if k != "unscored_reason"}
