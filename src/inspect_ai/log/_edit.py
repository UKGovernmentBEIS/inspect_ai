from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Sequence

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

    Additionally, sets `EvalLog.invalidated = False`. Logs with invalidated samples will be automatically retried when executing eval sets.

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

    Additionally, sets `EvalLog.invalidated = True` if there are no more invalidated samples.

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
