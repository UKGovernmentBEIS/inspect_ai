"""Checks the add-only store, and compares .eval files with it.

PROTOTYPE (tamper-evident eval logs, step 1). Runs outside the eval, with
read access to the store. Takes the store's location from its caller, never
from a .eval file.

A pass means each .eval file matches what was stored, not that the run was
honest: records written after a compromise pass too.
"""

import json
import tempfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, TypeAdapter

from inspect_ai.log._file import (
    list_eval_logs,
    read_eval_log,
    read_eval_log_sample,
)
from inspect_ai.log._log import EvalSample
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.types import BufferRows
from inspect_ai.log._recorders.streaming import materialize_streaming_sample

from ._records import (
    CLOSING,
    START,
    EvalClosingRecord,
    SampleAttemptRef,
    SampleClosingRecord,
    SampleRecord,
    StartRecord,
    StoreRecord,
)
from ._store import StoreLocation, s3_client, sample_key_part

FindingKind = Literal[
    "settings",
    "overwrite",
    "multipart",
    "missing_start",
    "nonce",
    "sequence_gap",
    "missing_closing",
    "record_count",
    "late_event_version",
    "event_without_uuid",
    "unlisted_attempt",
    "missing_eval_closing",
    "missing_eval_file",
    "missing_sample",
    "event_mismatch",
]


class Finding(BaseModel):
    kind: FindingKind
    eval_id: str | None = None
    key: str | None = None
    message: str


class StoredRecordInfo(BaseModel):
    key: str
    arrival: datetime
    """When S3 recorded the object's arrival (the host cannot set it)."""


class ValidationReport(BaseModel):
    evals: list[str]
    records: list[StoredRecordInfo]
    findings: list[Finding]
    samples_compared: int

    @property
    def passed(self) -> bool:
        return not self.findings


_record_adapter: TypeAdapter[StoreRecord] = TypeAdapter(StoreRecord)


class _Version(NamedTuple):
    key: str
    version_id: str
    arrival: datetime
    etag: str


def validate_store(
    store: str, log_dir: str, client: Any | None = None
) -> ValidationReport:
    """Check the add-only store at ``store`` and the .eval files in ``log_dir``.

    Args:
       store: ``s3://bucket/prefix`` of the add-only store (from the
          validator's own configuration, never from a .eval file).
       log_dir: Directory holding the .eval copies.
       client: boto3 S3 client with read access (default: from environment).
    """
    location = StoreLocation.parse(store)
    s3 = client if client is not None else s3_client()
    findings = _check_settings(s3, location.bucket)

    # every version of every key; a second version means an overwrite got
    # through, and a delete marker a delete
    # (the prefix is listed without its trailing "/": moto's signature check
    # fails on a "/" in this query parameter)
    prefix = location.key("")
    by_key: dict[str, list[_Version]] = defaultdict(list)
    for page in s3.get_paginator("list_object_versions").paginate(
        Bucket=location.bucket, Prefix=prefix.rstrip("/")
    ):
        for v in page.get("Versions", []):
            if v["Key"].startswith(prefix):
                by_key[v["Key"]].append(
                    _Version(v["Key"], v["VersionId"], v["LastModified"], v["ETag"])
                )
        for marker in page.get("DeleteMarkers", []):
            if marker["Key"].startswith(prefix):
                findings.append(
                    Finding(
                        kind="overwrite", key=marker["Key"], message="Delete marker."
                    )
                )
    for key, versions in by_key.items():
        if len(versions) > 1:
            findings.append(
                Finding(
                    kind="overwrite",
                    key=key,
                    message=f"{len(versions)} versions: an overwrite got through. "
                    "The earliest is used.",
                )
            )
        if any("-" in v.etag for v in versions):
            findings.append(
                Finding(
                    kind="multipart",
                    key=key,
                    message="Uploaded in parts: its arrival time is when the "
                    "upload started, not when it finished.",
                )
            )

    def read(key: str) -> StoreRecord:
        # S3 lists a key's versions newest first. Arrival times have whole
        # seconds, so they cannot order versions stored in the same second.
        earliest = by_key[key][-1]
        body = s3.get_object(
            Bucket=location.bucket, Key=key, VersionId=earliest.version_id
        )["Body"].read()
        return _record_adapter.validate_json(body)

    # group keys by eval id (the first part after the prefix)
    relative = {key: key.removeprefix(prefix) for key in by_key}
    evals: dict[str, list[str]] = defaultdict(list)
    for key, rel in relative.items():
        evals[rel.split("/", 1)[0]].append(rel)

    eval_files = _eval_files(log_dir)
    samples_compared = 0
    for eval_id, keys in sorted(evals.items()):
        eval_findings, compared = _validate_eval(
            eval_id,
            keys,
            lambda rel: read(location.key(rel)),
            eval_files.get(eval_id),
        )
        findings.extend(eval_findings)
        samples_compared += compared

    return ValidationReport(
        evals=sorted(evals),
        records=sorted(
            (
                StoredRecordInfo(key=v.key, arrival=v.arrival)
                for versions in by_key.values()
                for v in versions
            ),
            key=lambda r: (r.arrival, r.key),
        ),
        findings=findings,
        samples_compared=samples_compared,
    )


def _check_settings(s3: Any, bucket: str) -> list[Finding]:
    def finding(message: str) -> Finding:
        return Finding(kind="settings", message=message)

    findings: list[Finding] = []
    lock = s3.get_object_lock_configuration(Bucket=bucket).get(
        "ObjectLockConfiguration", {}
    )
    mode = lock.get("Rule", {}).get("DefaultRetention", {}).get("Mode")
    if lock.get("ObjectLockEnabled") != "Enabled" or mode != "COMPLIANCE":
        findings.append(finding(f"Object Lock is not in COMPLIANCE mode: {lock}"))
    if s3.get_bucket_versioning(Bucket=bucket).get("Status") != "Enabled":
        findings.append(finding("Versioning is not enabled."))
    try:
        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
    except s3.exceptions.ClientError:
        policy = {}
    if not any(_requires_if_none_match(st) for st in policy.get("Statement", [])):
        findings.append(
            finding("No bucket policy statement denies a put without If-None-Match.")
        )
    return findings


def _requires_if_none_match(statement: dict[str, Any]) -> bool:
    actions = statement.get("Action", [])
    actions = [actions] if isinstance(actions, str) else actions
    return (
        statement.get("Effect") == "Deny"
        and statement.get("Principal") in ("*", {"AWS": "*"})
        and any(a in ("s3:PutObject", "s3:*", "*") for a in actions)
        and statement.get("Condition", {}).get("Null", {}).get("s3:if-none-match")
        == "true"
    )


def _eval_files(log_dir: str) -> dict[str, str]:
    """Map eval id to .eval file in ``log_dir``."""
    return {
        read_eval_log(info.name, header_only=True).eval.eval_id: info.name
        for info in list_eval_logs(log_dir, formats=["eval"])
    }


def _validate_eval(
    eval_id: str,
    keys: list[str],
    read: Any,
    eval_file: str | None,
) -> tuple[list[Finding], int]:
    findings: list[Finding] = []

    def finding(kind: FindingKind, message: str, key: str | None = None) -> None:
        findings.append(Finding(kind=kind, eval_id=eval_id, key=key, message=message))

    if f"{eval_id}/{START}" not in keys:
        finding("missing_start", "No start record.")
        return findings, 0
    start = read(f"{eval_id}/{START}")
    assert isinstance(start, StartRecord)
    nonce = start.nonce

    # attempts: "<eval>/<sample>.<epoch>/<attempt>/<seq|closing>"
    attempts: dict[tuple[str, str], dict[str, StoreRecord]] = defaultdict(dict)
    eval_closing: EvalClosingRecord | None = None
    for key in keys:
        parts = key.split("/")
        if len(parts) == 2:
            record = read(key)
            if parts[1] == CLOSING:
                assert isinstance(record, EvalClosingRecord)
                eval_closing = record
        else:
            record = read(key)
            attempts[(parts[1], parts[2])][parts[3]] = record
        if record.nonce != nonce:
            finding("nonce", "Nonce differs from the start record's.", key)

    if eval_closing is None:
        finding("missing_eval_closing", "No closing record: the eval was cut short.")
    listed = {
        (sample_key_part(a.sample_id, a.epoch), str(a.attempt))
        for a in (eval_closing.samples if eval_closing else [])
    }

    final_attempts: dict[tuple[str, int], tuple[SampleAttemptRef, list[SampleRecord]]]
    final_attempts = {}
    for (sample_part, attempt), records in sorted(attempts.items()):
        prefix = f"{eval_id}/{sample_part}/{attempt}"
        if eval_closing is not None and (sample_part, attempt) not in listed:
            finding("unlisted_attempt", "Not in the eval's closing record.", prefix)
        sample_records = sorted(
            (r for r in records.values() if isinstance(r, SampleRecord)),
            key=lambda r: r.seq,
        )
        seqs = [r.seq for r in sample_records]
        if seqs != list(range(1, len(seqs) + 1)):
            finding("sequence_gap", f"Sequence numbers {seqs} have a gap.", prefix)
        closing = records.get(CLOSING)
        if closing is None:
            finding("missing_closing", "No closing record: cut short.", prefix)
        else:
            assert isinstance(closing, SampleClosingRecord)
            if seqs and max(seqs) > closing.records or len(seqs) != closing.records:
                finding(
                    "record_count",
                    f"Closing record counts {closing.records} records, "
                    f"store has {seqs}.",
                    prefix,
                )
            ref = closing.sample
            current = final_attempts.get((str(ref.sample_id), ref.epoch))
            if current is None or current[0].attempt < ref.attempt:
                final_attempts[(str(ref.sample_id), ref.epoch)] = (ref, sample_records)
        for message in _event_version_problems(sample_records):
            finding(*message, key=prefix)

    if eval_file is None:
        finding("missing_eval_file", "No .eval file in the log dir has this eval id.")
        return findings, 0

    compared = 0
    for ref, sample_records in final_attempts.values():
        try:
            logged = read_eval_log_sample(
                eval_file, ref.sample_id, ref.epoch, resolve_attachments="full"
            )
        except IndexError:
            finding(
                "missing_sample",
                f"Sample {ref.sample_id} epoch {ref.epoch} is not in {eval_file}.",
            )
            continue
        difference = _compare_events(logged, sample_records)
        compared += 1
        if difference is not None:
            finding(
                "event_mismatch",
                difference,
                f"{eval_id}/{sample_key_part(ref.sample_id, ref.epoch)}/{ref.attempt}",
            )
    return findings, compared


def _event_version_problems(
    records: list[SampleRecord],
) -> Iterator[tuple[FindingKind, str]]:
    """Events without a uuid, and event versions written after a boundary stored the event complete."""
    stored_complete: dict[str, int] = {}
    for record in records:
        completed_here: dict[str, int] = {}
        for row in record.rows.events:
            event = json.loads(row.data)
            if not row.event_id or event.get("uuid") != row.event_id:
                yield (
                    "event_without_uuid",
                    f"Record {record.seq}: buffer row id {row.event_id!r}, "
                    f"event uuid {event.get('uuid')!r}.",
                )
            if row.event_id in stored_complete:
                yield (
                    "late_event_version",
                    f"Record {record.seq}: new version of {event.get('event')} "
                    f"event {row.event_id}, stored complete in record "
                    f"{stored_complete[row.event_id]}.",
                )
            if not event.get("pending"):
                completed_here.setdefault(row.event_id, record.seq)
        stored_complete = {**completed_here, **stored_complete}


def _rebuild_rows(records: list[SampleRecord]) -> BufferRows:
    return BufferRows(
        events=[row for r in records for row in r.rows.events],
        attachments=[row for r in records for row in r.rows.attachments],
        message_pool=[row for r in records for row in r.rows.message_pool],
        call_pool=[row for r in records for row in r.rows.call_pool],
    )


def rebuild_sample(base: EvalSample, records: list[SampleRecord]) -> EvalSample:
    """Rebuild a sample's events from its records.

    Uses the code inspect_ai uses to log a sample whose events were evicted
    from memory: the rows go into a sample buffer, which is read back with
    ``open_sample_history`` and ``materialize_streaming_sample``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db = SampleBufferDatabase(
            location=str(Path(tmp) / "rebuild.eval"), db_dir=Path(tmp)
        )
        try:
            db.insert_sample_rows(base.id, base.epoch, _rebuild_rows(records))
            with db.open_sample_history(base.id, base.epoch) as history:
                return materialize_streaming_sample(
                    base.model_copy(update={"events": [], "events_data": None}),
                    history,
                )
        finally:
            db.cleanup()


def _compare_events(logged: EvalSample, records: list[SampleRecord]) -> str | None:
    """The first difference between the logged events and the stored ones, if any."""
    rebuilt = rebuild_sample(logged, records)
    logged_events = [e.model_dump(mode="json") for e in logged.events]
    stored_events = [e.model_dump(mode="json") for e in rebuilt.events]
    for index, (lhs, rhs) in enumerate(zip(logged_events, stored_events)):
        if lhs != rhs:
            fields = sorted(
                k for k in lhs.keys() | rhs.keys() if lhs.get(k) != rhs.get(k)
            )
            versions = sum(
                row.event_id == rhs.get("uuid")
                for r in records
                for row in r.rows.events
            )
            return (
                f"Event {index} ({rhs.get('event')} {rhs.get('uuid')}) differs in "
                f"{fields}; the store has {versions} version(s) of it."
            )
    if len(logged_events) != len(stored_events):
        return (
            f".eval has {len(logged_events)} events, the store has "
            f"{len(stored_events)}."
        )
    return None
