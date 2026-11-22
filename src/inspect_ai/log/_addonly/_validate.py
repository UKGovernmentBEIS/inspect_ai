"""Checks the add-only store, and compares .eval files with it.

PROTOTYPE (tamper-evident eval logs, step 1). Runs outside the eval, with
read access to the store. Takes the store's location from its caller, never
from a .eval file.

A pass means the .eval fields the store holds (events, scores, which samples
exist, the eval's status, stats and results) match it, not that the run was
honest: records written after a compromise pass too. Other .eval fields
(sample messages and output, the sample summaries) are not checked.
"""

import json
import sqlite3
import tempfile
from collections import defaultdict
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, TypeAdapter, ValidationError

from inspect_ai._util._async import run_coroutine
from inspect_ai.event._validate import validate_events
from inspect_ai.log._file import (
    list_eval_logs,
    read_eval_log,
    read_eval_log_sample,
    read_eval_log_sample_summaries,
)
from inspect_ai.log._log import EvalSample
from inspect_ai.log._recorders import recorder_type_for_location
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.types import BufferRows
from inspect_ai.log._recorders.streaming import materialize_streaming_sample

from ._records import (
    CLOSING,
    START,
    EvalClosingRecord,
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
    "malformed_record",
    "unstored_eval",
    "duplicate_eval_file",
    "unstored_sample",
    "score_mismatch",
    "eval_mismatch",
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
    retried: list[str] = []
    """Attempts with no closing record whose sample has a later closed attempt
    (``retry_on_error``). Listed, not findings."""

    @property
    def passed(self) -> bool:
        return not self.findings


_record_adapter: TypeAdapter[StoreRecord] = TypeAdapter(StoreRecord)


class _EvalResult(NamedTuple):
    findings: list[Finding]
    samples_compared: int
    retried: list[str]


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
    findings.extend(
        Finding(
            kind="unstored_eval",
            eval_id=eval_id,
            message=f"{eval_file} has no records in the store.",
        )
        for eval_id, (eval_file, *_) in sorted(eval_files.items())
        if eval_id not in evals
    )
    findings.extend(
        Finding(
            kind="duplicate_eval_file",
            eval_id=eval_id,
            message=f"{len(names)} .eval files have this eval id: {names}. "
            "The first is compared.",
        )
        for eval_id, names in sorted(eval_files.items())
        if len(names) > 1
    )
    results = [
        _validate_eval(
            eval_id,
            keys,
            lambda rel: read(location.key(rel)),
            eval_files.get(eval_id, [None])[0],
        )
        for eval_id, keys in sorted(evals.items())
    ]
    findings.extend(f for result in results for f in result.findings)

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
        samples_compared=sum(result.samples_compared for result in results),
        retried=[key for result in results for key in result.retried],
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


def _eval_files(log_dir: str) -> dict[str, list[str]]:
    """Map eval id to the .eval files in ``log_dir`` that have it, sorted."""
    files: dict[str, list[str]] = defaultdict(list)
    for info in list_eval_logs(log_dir, formats=["eval"]):
        files[read_eval_log(info.name, header_only=True).eval.eval_id].append(info.name)
    return {eval_id: sorted(names) for eval_id, names in files.items()}


def _validate_eval(
    eval_id: str,
    keys: list[str],
    read: Any,
    eval_file: str | None,
) -> _EvalResult:
    findings: list[Finding] = []
    retried: list[str] = []

    def finding(kind: FindingKind, message: str, key: str | None = None) -> None:
        findings.append(Finding(kind=kind, eval_id=eval_id, key=key, message=message))

    # records the eval could have written; anything else is reported, so
    # that it cannot stop the validator
    stored: dict[str, StoreRecord] = {}
    for key in keys:
        record_type = _record_type(key)
        if record_type is None:
            finding("malformed_record", "Not a key the eval writes.", key)
            continue
        try:
            record = read(key)
            if isinstance(record, SampleRecord):
                validate_events([json.loads(row.data) for row in record.rows.events])
        except ValueError as ex:
            finding("malformed_record", f"Cannot read it: {_first_error(ex)}", key)
            continue
        if not isinstance(record, record_type):
            finding("malformed_record", f"Holds a {record.type} record.", key)
            continue
        stored[key] = record

    start = stored.get(f"{eval_id}/{START}")
    if start is None:
        finding("missing_start", "No start record.")
        return _EvalResult(findings, 0, retried)
    assert isinstance(start, StartRecord)
    nonce = start.nonce

    # attempts: "<eval>/<sample>.<epoch>/<attempt>/<seq|closing>"
    attempts: dict[tuple[str, str], dict[str, StoreRecord]] = defaultdict(dict)
    eval_closing: EvalClosingRecord | None = None
    for key, record in stored.items():
        if record.nonce != nonce:
            finding("nonce", "Nonce differs from the start record's.", key)
        parts = key.split("/")
        if isinstance(record, EvalClosingRecord):
            eval_closing = record
        elif len(parts) == 4:
            attempts[(parts[1], parts[2])][parts[3]] = record

    if eval_closing is None:
        finding("missing_eval_closing", "No closing record: the eval was cut short.")
    listed = {
        (sample_key_part(a.sample_id, a.epoch), str(a.attempt))
        for a in (eval_closing.samples if eval_closing else [])
    }

    closed = {
        (sample_part, int(attempt))
        for (sample_part, attempt), records in attempts.items()
        if CLOSING in records
    }
    final_attempts: dict[
        tuple[str, int], tuple[SampleClosingRecord, list[SampleRecord]]
    ] = {}
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
            if any(
                part == sample_part and later > int(attempt) for part, later in closed
            ):
                retried.append(prefix)
            else:
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
            if current is None or current[0].sample.attempt < ref.attempt:
                final_attempts[(str(ref.sample_id), ref.epoch)] = (
                    closing,
                    sample_records,
                )
        for message in _event_version_problems(sample_records):
            finding(*message, key=prefix)

    if eval_file is None:
        finding("missing_eval_file", "No .eval file in the log dir has this eval id.")
        return _EvalResult(findings, 0, retried)

    if eval_closing is not None:
        fields = {"status", "stats", "results"}
        header = read_eval_log(eval_file, header_only=True).model_dump(
            mode="json", include=fields
        )
        closing_fields = eval_closing.model_dump(mode="json", include=fields)
        if changed := sorted(
            f for f in fields if not _same_json(header.get(f), closing_fields.get(f))
        ):
            finding(
                "eval_mismatch",
                f"The .eval file's {changed} differ from the eval closing record's.",
            )

    stored_samples = {sample_part for sample_part, _ in attempts}
    for sample_part in sorted(_eval_file_samples(eval_file) - stored_samples):
        finding(
            "unstored_sample",
            "In the .eval file, with no records in the store.",
            f"{eval_id}/{sample_part}",
        )

    compared = 0
    for closing, sample_records in final_attempts.values():
        ref = closing.sample
        attempt_key = (
            f"{eval_id}/{sample_key_part(ref.sample_id, ref.epoch)}/{ref.attempt}"
        )
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
        stored_scores = {k: v.score for k, v in closing.scores.items()}
        if changed := _changed_keys(logged.scores or {}, stored_scores):
            finding(
                "score_mismatch",
                f"Scores {changed} differ from the sample closing record's.",
                attempt_key,
            )
        # a row the eval could not have written (a pool row that is not JSON,
        # a key stored twice) fails here, not when its record is read
        try:
            difference = _compare_events(logged, sample_records)
        except (ValueError, sqlite3.IntegrityError) as ex:
            finding(
                "malformed_record",
                f"Cannot rebuild the sample's events: {_first_error(ex)}",
                attempt_key,
            )
            continue
        compared += 1
        if difference is not None:
            finding(
                "event_mismatch",
                difference,
                attempt_key,
            )
    return _EvalResult(findings, compared, retried)


def _changed_keys(
    lhs: Mapping[str, BaseModel], rhs: Mapping[str, BaseModel]
) -> list[str]:
    """Keys whose values differ (as JSON) or are in only one mapping."""
    return sorted(
        key
        for key in lhs.keys() | rhs.keys()
        if key not in lhs
        or key not in rhs
        or not _same_json(
            lhs[key].model_dump(mode="json"), rhs[key].model_dump(mode="json")
        )
    )


def _same_json(lhs: Any, rhs: Any) -> bool:
    """Whether two JSON values are the same JSON text.

    Unlike ``==``, NaN equals NaN, and 1, 1.0 and true differ.
    """
    return json.dumps(lhs, sort_keys=True) == json.dumps(rhs, sort_keys=True)


def _eval_file_samples(eval_file: str) -> set[str]:
    """``<sample-id>.<epoch>`` of each sample in the .eval file.

    From the sample summaries (which the viewer lists) and the names of the
    sample members of the zip (which a full read returns), since an edit can
    add to one only. Member names, not the ids in the sample JSON: a member
    added under a new name can hold a stored sample's id.
    """
    summaries = read_eval_log_sample_summaries(eval_file)
    members = run_coroutine(
        recorder_type_for_location(eval_file).read_log_sample_keys(eval_file)
    )
    return {sample_key_part(s.id, s.epoch) for s in summaries} | {
        sample_key_part(m.sample_id, m.epoch) for m in members
    }


def _record_type(
    key: str,
) -> (
    type[StartRecord]
    | type[SampleRecord]
    | type[SampleClosingRecord]
    | type[EvalClosingRecord]
    | None
):
    """The record type a key under an eval holds, or None if the eval never writes the key."""
    match key.split("/"):
        case [_, "start"]:
            return StartRecord
        case [_, "closing"]:
            return EvalClosingRecord
        case [_, _, _, "closing"]:
            return SampleClosingRecord
        case [_, _, _, seq] if seq.isdigit():
            return SampleRecord
        case _:
            return None


def _first_error(ex: Exception) -> str:
    if isinstance(ex, ValidationError):
        error = ex.errors()[0]
        location = ".".join(map(str, error["loc"]))
        return f"{location}: {error['msg']}" if location else error["msg"]
    return str(ex)


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
        if not _same_json(lhs, rhs):
            fields = sorted(
                k
                for k in lhs.keys() | rhs.keys()
                if not _same_json(lhs.get(k), rhs.get(k))
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
