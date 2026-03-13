from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal, Sequence

from pydantic import BaseModel, Field

from inspect_ai._util.dateutil import UtcDatetime, datetime_now_utc

if TYPE_CHECKING:
    from inspect_ai.log._log import EvalLog, EvalSample


class ProvenanceData(BaseModel):
    """Metadata about who made an edit and why."""

    timestamp: UtcDatetime = Field(default_factory=datetime_now_utc)
    """Timestamp when the edit was made."""

    author: str
    """Author who made the edit."""

    reason: str | None = Field(default=None)
    """Reason for the edit."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Additional metadata about the edit."""


class LogEdit(BaseModel):
    """A single edit action on log tags and/or metadata."""


class TagsEdit(LogEdit):
    """Edit action for tags."""

    type: Literal["tags"] = "tags"

    tags_add: list[str] = Field(default_factory=list)
    """Tags to add."""

    tags_remove: list[str] = Field(default_factory=list)
    """Tags to remove."""


class MetadataEdit(LogEdit):
    """Edit action for metadata."""

    type: Literal["metadata"] = "metadata"

    metadata_set: dict[str, Any] = Field(default_factory=dict)
    """Metadata keys to set."""

    metadata_remove: list[str] = Field(default_factory=list)
    """Metadata keys to remove."""


LogEditType = Annotated[TagsEdit | MetadataEdit, Field(discriminator="type")]


class LogUpdate(BaseModel):
    """A group of edits that share provenance."""

    edits: list[LogEditType] = Field(default_factory=list)
    """List of edits in this update."""

    provenance: ProvenanceData
    """Provenance for this update."""


def edit_eval_log(
    log: EvalLog,
    edits: Sequence[LogEdit],
    provenance: ProvenanceData,
) -> EvalLog:
    """Apply edits to a log.

    ::: {.callout-note}
    Support for `edit_eval_log()` is available only in the development version of Inspect. Install the development version from GitHub with:

    ```python
    pip install git+https://github.com/UKGovernmentBEIS/inspect_ai.git
    ```
    :::

    Creates a LogUpdate from the edits and provenance, appends it to
    log.log_updates, and recomputes cached tags/metadata.
    Returns modified log (not persisted). Use write_eval_log() to save.

    Args:
        log: Eval log to edit.
        edits: List of edits to apply.
        provenance: Provenance data for the edits.

    Returns:
        Modified EvalLog with edits applied.
    """
    # validate and filter noop edits, advancing state after each edit
    current_tags = set(log.tags)
    current_metadata = dict(log.metadata)
    filtered: list[LogEditType] = []
    for edit in edits:
        if isinstance(edit, TagsEdit):
            for tag in edit.tags_add + edit.tags_remove:
                if not tag.strip():
                    raise ValueError("Tag must be a non-empty string.")
            overlap = set(edit.tags_add) & set(edit.tags_remove)
            if overlap:
                raise ValueError(
                    f"Tag(s) {overlap} appear in both tags_add and tags_remove."
                )
            tags_add = [t for t in edit.tags_add if t not in current_tags]
            tags_remove = [t for t in edit.tags_remove if t in current_tags]
            if tags_add or tags_remove:
                filtered.append(TagsEdit(tags_add=tags_add, tags_remove=tags_remove))
                current_tags -= set(tags_remove)
                current_tags |= set(tags_add)
        elif isinstance(edit, MetadataEdit):
            for key in list(edit.metadata_set.keys()) + edit.metadata_remove:
                if not key.strip():
                    raise ValueError("Metadata key must be a non-empty string.")
            overlap = set(edit.metadata_set.keys()) & set(edit.metadata_remove)
            if overlap:
                raise ValueError(
                    f"Metadata key(s) {overlap} appear in both metadata_set and metadata_remove."
                )
            metadata_set = {
                k: v
                for k, v in edit.metadata_set.items()
                if current_metadata.get(k) != v
            }
            metadata_remove = [k for k in edit.metadata_remove if k in current_metadata]
            if metadata_set or metadata_remove:
                filtered.append(
                    MetadataEdit(
                        metadata_set=metadata_set,
                        metadata_remove=metadata_remove,
                    )
                )
                for k in metadata_remove:
                    current_metadata.pop(k, None)
                current_metadata.update(metadata_set)

    if not filtered:
        return log

    update = LogUpdate(edits=filtered, provenance=provenance)
    log_updates = list(log.log_updates or [])
    log_updates.append(update)
    log = log.model_copy(update={"log_updates": log_updates})
    # recompute tags/metadata fields
    log.recompute_tags_and_metadata()
    return log


def _prepare_samples(
    log: EvalLog, sample_uuids: Sequence[str] | Literal["all"]
) -> dict[str, tuple[int, EvalSample]]:
    sample_uuid_map = {
        str(sample.uuid): (idx_sample, sample)
        for idx_sample, sample in enumerate(log.samples or [])
    }

    if sample_uuids == "all":
        sample_uuid_list = list(sample_uuid_map.keys())
    else:
        invalid_sample_uuids = [
            sample_uuid
            for sample_uuid in sample_uuids
            if sample_uuid not in sample_uuid_map
        ]
        if invalid_sample_uuids:
            raise ValueError(f"Samples {invalid_sample_uuids} not found in log")

        sample_uuid_list = list(sample_uuids)

    return {
        sample_uuid: sample_uuid_map[sample_uuid] for sample_uuid in sample_uuid_list
    }


def _update_sample_invalidation(
    log: EvalLog,
    sample_uuid_map: dict[str, tuple[int, EvalSample]],
    provenance: ProvenanceData | None = None,
) -> EvalLog:
    if not sample_uuid_map:
        return log

    samples = (log.samples or []).copy()
    for idx_sample, sample in sample_uuid_map.values():
        if provenance is None:
            if sample.invalidation is None:
                continue
            invalidation = None
        else:
            if sample.invalidation is not None:
                continue
            invalidation = provenance.model_copy()

        samples[idx_sample] = sample.model_copy(update={"invalidation": invalidation})

    return log.model_copy(update={"samples": samples})


def invalidate_samples(
    log: EvalLog,
    sample_uuids: Sequence[str] | Literal["all"],
    provenance: ProvenanceData,
) -> EvalLog:
    """Invalidate samples in the log.

    Additionally, sets `EvalLog.invalidated = True`. Logs with invalidated samples will be automatically retried when executing eval sets.

    The log with invalidated samples is returned but not persisted to storage. Use `write_eval_log()` to save the new log with invalidated samples.

    Args:
       log: Eval log
       sample_uuids: List of sample uuids to invalidate (or "all" to invaliate all samples).
       provenance: Timestamp and optional author, reason, and metadata for the invalidation.

    Returns:
       `EvalLog` with invalidated samples and `invalidated=True`.
    """
    sample_uuid_map = _prepare_samples(log, sample_uuids)
    if not sample_uuid_map:
        return log
    log = _update_sample_invalidation(log, sample_uuid_map, provenance=provenance)
    log.invalidated = True
    return log


def uninvalidate_samples(
    log: EvalLog, sample_uuids: Sequence[str] | Literal["all"]
) -> EvalLog:
    """Uninvalidate samples in the log.

    Additionally, sets `EvalLog.invalidated = False` if there are no more invalidated samples.

    The log with uninvalidated samples is returned but not persisted to storage. Use `write_eval_log()` to save the new log with uninvalidated samples.

    Args:
       log: Eval log
       sample_uuids: List of sample uuids to uninvalidate (or "all" to uninvalidate all samples).

    Returns:
       `EvalLog` with uninvalidate samples and updated global `invalidated` state.
    """
    sample_uuid_map = _prepare_samples(log, sample_uuids)
    if not sample_uuid_map:
        return log
    log = _update_sample_invalidation(log, sample_uuid_map, provenance=None)
    log.invalidated = any(
        sample.invalidation is not None for sample in log.samples or []
    )
    return log
