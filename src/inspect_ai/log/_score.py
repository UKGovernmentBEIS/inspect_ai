"""Score editing functionality."""

from inspect_ai.event._score_edit import ScoreEditEvent
from inspect_ai.event._tree import SpanNode, event_tree, walk_node_spans
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

    # Add the edit to the history
    score.history.append(edit)

    # Find the last scorers span
    final_scorers_node: SpanNode | None = None
    sample_event_tree = event_tree(sample.events)
    for node in walk_node_spans(sample_event_tree):
        if node.type == "scorers" and node.name == "scorers":
            final_scorers_node = node

    # create the event
    score_edit_event = ScoreEditEvent(score_name=score_name, edit=edit)

    # attach this edit event to the scorers span (if present)
    if final_scorers_node:
        score_edit_event.span_id = final_scorers_node.begin.id

    # Find the index to insert the ScoreEditEvent (just before the end of
    # the final scorers span, or at the end if no such span exists)
    end_index = len(sample.events)
    if final_scorers_node:
        # Find the span end index
        for i, ev in enumerate(reversed(sample.events)):
            if ev == final_scorers_node.end if final_scorers_node else None:
                end_index = len(sample.events) - 1 - i
                break

    # Insert the event
    sample.events.insert(end_index, score_edit_event)

    # recompute metrics
    if recompute_metrics:
        _recompute_metrics(log)
