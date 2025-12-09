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


class SampleInvalidation(ProvenanceData):
    status: Literal["started", "complete", "error"]


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
    update_all: bool = False,
) -> EvalLog:
    if not sample_uuid_map:
        return log

    samples = (log.samples or []).copy()
    errors: dict[str, str] = {}
    status: Literal["started", "complete", "error", "invalidated"]
    for sample_uuid, (idx_sample, sample) in sample_uuid_map.items():
        if provenance is None:
            if sample.invalidation is None:
                if not update_all:
                    errors[sample_uuid] = "Sample is not invalidated"
                continue
            status = "started"
            invalidation = None
        else:
            if sample.status == "invalidated":
                if not update_all:
                    errors[sample_uuid] = "Sample is already invalidated"
                continue
            invalidation = SampleInvalidation(
                status=sample.status, **provenance.model_dump()
            )
            status = "invalidated"

        samples[idx_sample] = sample.model_copy(
            update={"status": status, "invalidation": invalidation}
        )

    if errors:
        raise ValueError(f"Errors updating invalidation: {errors}")

    return log.model_copy(update={"samples": samples})


def invalidate_samples(
    log: EvalLog,
    sample_uuids: Sequence[str] | Literal["all"],
    provenance: ProvenanceData,
) -> EvalLog:
    """Invalidate samples in the log."""
    sample_uuid_map = _prepare_samples(log, sample_uuids)
    if not sample_uuid_map:
        return log
    log = _update_sample_invalidation(
        log,
        sample_uuid_map,
        provenance=provenance,
        update_all=sample_uuids == "all",
    )
    log.invalidated = True
    return log


def uninvalidate_samples(
    log: EvalLog, sample_uuids: Sequence[str] | Literal["all"]
) -> EvalLog:
    """Uninvalidate samples in the log."""
    sample_uuid_map = _prepare_samples(log, sample_uuids)
    if not sample_uuid_map:
        return log
    log = _update_sample_invalidation(
        log,
        sample_uuid_map,
        provenance=None,
        update_all=sample_uuids == "all",
    )
    log.invalidated = any(
        sample.status == "invalidated" for sample in log.samples or []
    )
    return log
