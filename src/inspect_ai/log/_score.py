"""Score editing functionality."""

from inspect_ai.event._score_edit import ScoreEditEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.scorer._metric import ScoreEdit

from ._log import EvalLog
from ._metric import recompute_metrics as _recompute_metrics


def edit_score(
    log: EvalLog,
    sample_id: int | str,
    score_name: str,
    edit: ScoreEdit,
    recompute_metrics: bool = True,
) -> None:
    """Edit a score in-place.

    Args:
        log: The evaluation log containing the samples and scores
        sample_id: ID of the sample containing the score to edit
        score_name: Name of the score to edit
        edit: The edit to apply to the score
        recompute_metrics: Whether to recompute aggregate metrics after editing

    Raises:
        ValueError: If the sample or score cannot be found
    """
    if log.samples is None:
        raise ValueError("Log contains no samples")

    sample = next((sample for sample in log.samples if sample.id == sample_id), None)

    if sample is None:
        raise ValueError(f"Sample with id {sample_id} not found")

    if sample.scores is None:
        raise ValueError(f"Sample {sample_id} has no scores")

    if score_name not in sample.scores:
        raise ValueError(f"Score '{score_name}' not found in sample {sample_id}")

    score = sample.scores[score_name]

    # If history is empty, capture original state first
    if len(score.history) == 0:
        original = ScoreEdit(
            value=score.value,
            answer=score.answer,
            explanation=score.explanation,
            metadata=score.metadata or {},
        )
        score.history.append(original)

    # Apply the edit to the Score fields
    if edit.value != "UNCHANGED":
        score.value = edit.value
    if edit.answer != "UNCHANGED":
        score.answer = edit.answer
    if edit.explanation != "UNCHANGED":
        score.explanation = edit.explanation
    if edit.metadata != "UNCHANGED":
        score.metadata = edit.metadata

    score.history.append(edit)

    score_edit_event = ScoreEditEvent(score_name=score_name, edit=edit)

    # Build a map of span_id -> (begin_idx, end_idx) for scorers spans
    span_indexes = {}
    for i, event in enumerate(sample.events):
        if (
            isinstance(event, SpanBeginEvent)
            and event.type == "scorers"
            and event.name == "scorers"
            and event.id
        ):
            span_indexes[event.id] = [i, None]
        elif isinstance(event, SpanEndEvent) and event.id in span_indexes:
            span_indexes[event.id][1] = i

    # Find the last scorers span
    span_id = None
    end_index = None
    if span_indexes:
        last_span_id = max(span_indexes.keys(), key=lambda k: span_indexes[k][1] or -1)
        if span_indexes[last_span_id][1] is not None:
            span_id = last_span_id
            end_index = span_indexes[last_span_id][1]

    score_edit_event.span_id = span_id

    if end_index is not None:
        # Insert before the span end to keep it structurally inside the span
        sample.events.insert(end_index, score_edit_event)
    else:
        sample.events.append(score_edit_event)

    if recompute_metrics:
        _recompute_metrics(log)
