"""Checks the add-only store, and compares .eval files with it.

Tamper-evident logs. Runs outside the eval, with
read access to the store. Takes the store's location from its caller, never
from a .eval file.

A pass means the .eval fields the store holds (events, scores, which samples
exist, the eval's status, stats and results) match it, and that each
sample summary has its sample's scores, not that the run was honest: records
written after a compromise pass too. Other .eval fields (for example sample
messages and output, the summaries' other fields) are not checked.

A rescored .eval file names its latest rescore in each sample's events. Its
expected samples are the original run's, with each rescore of the chain
applied by ``inspect score``'s own functions; its results come from the
latest rescore's closing record.
"""

import json
import sqlite3
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from functools import reduce
from pathlib import Path
from typing import Any, Literal, NamedTuple, TypeVar

from botocore.exceptions import ClientError
from pydantic import BaseModel, ValidationError

from inspect_ai._eval.score import (
    ScoreAction,
    _get_updated_events,
    _get_updated_scores,
)
from inspect_ai._util._async import run_coroutine
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai.event import Event
from inspect_ai.event._validate import validate_events
from inspect_ai.log._condense import mark_attachments_resolved
from inspect_ai.log._file import (
    list_eval_logs,
    read_eval_log,
    read_eval_log_sample,
    read_eval_log_sample_summaries,
)
from inspect_ai.log._log import EvalResults, EvalSample, EvalSampleSummary
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.types import BufferRows
from inspect_ai.log._recorders.eval import (
    SAMPLES_DIR,
    SUMMARIES_JSON,
    _parse_summaries,
    _read_member_json,
    _sample_filename,
    _sample_key,
)
from inspect_ai.log._recorders.streaming import materialize_streaming_sample
from inspect_ai.scorer._metric import Score

from ._records import (
    CLOSING,
    RESCORES,
    START,
    STORE_VERSION,
    EvalClosingRecord,
    RescoreClosingRecord,
    RescoreRef,
    RescoreSampleRecord,
    RescoreStartRecord,
    SampleClosingRecord,
    SampleRecord,
    StartRecord,
    latest_marker,
)
from ._store import StoreLocation, error_code, s3_client, sample_key_part

FindingKind = Literal[
    "settings",
    "overwrite",
    "missing_start",
    "nonce",
    "record_count",
    "late_event_version",
    "unlisted_attempt",
    "missing_eval_closing",
    "missing_eval_file",
    "missing_sample",
    "event_mismatch",
    "malformed_record",
    "unstored_eval",
    "unstored_sample",
    "score_mismatch",
    "eval_mismatch",
    "missing_rescore",
    "rescore_mismatch",
    "summary_mismatch",
    "record_version",
]


_STORE_READ_REFUSED = {
    "AccessDenied",
    "AllAccessDisabled",
    "NoSuchBucket",
    "InvalidAccessKeyId",
    "SignatureDoesNotMatch",
    "ExpiredToken",
    "InvalidToken",
}
"""S3 error codes of a record read that stop the validator: its keys or the
bucket, not the record. So does a server error (HTTP 5xx, after botocore's
retries). Any other refusal is the record's malformed_record."""


class NewerStoreVersionError(Exception):
    """A record has a store format version later than this inspect_ai reads."""


class Finding(BaseModel):
    kind: FindingKind
    eval_id: str | None = None
    key: str | None = None
    message: str


class StoredRecordInfo(BaseModel):
    key: str
    arrival: datetime
    """When S3 recorded the object's arrival (the host cannot set it)."""


class RescoreInfo(BaseModel):
    eval_id: str
    rescore_id: str
    arrival: datetime
    """When S3 recorded the rescore's start record."""
    action: ScoreAction
    original_results: EvalResults | None
    """The eval closing record's results (None without one)."""


class ValidationReport(BaseModel):
    evals: list[str]
    records: list[StoredRecordInfo]
    findings: list[Finding]
    samples_compared: int
    stopped: list[str] = []
    """Evals and sample attempts with no closing record: cut short, or their
    host stopped writing. Listed, not findings. Their records are still
    checked. A sample in a .eval file still needs a closed attempt, and a
    finished .eval file its eval closing record."""
    not_logged: list[str] = []
    """Closed samples not in the .eval file of a stopped eval (one with no
    eval closing record and a .eval file still "started"): the eval stopped
    before it logged them. Listed, not findings."""
    prior_without_file: dict[str, list[str]] = {}
    """Evals with no .eval file, with the later evals that name each one as
    their prior eval. Listed, not findings: eval_set's ``retry_cleanup``
    deletes these files, but eval-host keys can forge a later eval that
    names any eval."""
    rescores: list[RescoreInfo] = []
    """Each rescore with a start record, oldest first. Listed, not findings:
    a rescore is a claim by whoever could add to the store."""

    @property
    def passed(self) -> bool:
        return not self.findings


_EvalRecord = StartRecord | SampleRecord | SampleClosingRecord | EvalClosingRecord
_RescoreRecord = RescoreStartRecord | RescoreSampleRecord | RescoreClosingRecord


class _FinalAttempt(NamedTuple):
    closing: SampleClosingRecord
    events: list[Event] | None
    """Rebuilt from the records (None if they cannot be: a malformed_record)."""


class _StoredEval(NamedTuple):
    """One eval's records, checked; what the .eval comparison needs."""

    findings: list[Finding]
    stopped: list[str]
    """The eval id and attempt prefixes with no closing record."""
    closing: EvalClosingRecord | None
    final_attempts: dict[str, _FinalAttempt]
    """The last closed attempt of each sample, by ``<sample-id>.<epoch>``."""
    prior_eval_id: str | None
    """The eval a retry reuses samples from (the start record's)."""
    nonce: str | None
    """The start record's nonce (None without a start record)."""


class _StoredRescore(NamedTuple):
    """One rescore's records, checked."""

    findings: list[Finding]
    start: RescoreStartRecord | None
    closing: RescoreClosingRecord | None
    samples: dict[str, RescoreSampleRecord]
    """By ``<sample-id>.<epoch>``."""


class _RescoreStep(NamedTuple):
    action: ScoreAction
    record: RescoreSampleRecord


class _ToCompare(NamedTuple):
    """A .eval sample and the closed attempt it is compared with."""

    key: str
    """For findings."""
    note: str
    """For messages."""
    source: str
    """The eval that closed the attempt: the file's eval, or an earlier one
    for a reused sample."""
    final: _FinalAttempt


class _Version(NamedTuple):
    key: str
    version_id: str
    arrival: datetime


def validate_store(
    store: str, log_dir: str, client: Any | None = None
) -> ValidationReport:
    """Check the add-only store at ``store`` and the .eval files in ``log_dir``.

    Args:
       store: ``s3://bucket/prefix`` of the add-only store (from the
          validator's own configuration, never from a .eval file).
       log_dir: Directory holding the .eval copies.
       client: boto3 S3 client with read access (default: from environment).

    Raises:
       NewerStoreVersionError: A record has a later store format version
          than this inspect_ai reads.
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
                    _Version(v["Key"], v["VersionId"], v["LastModified"])
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

    def read(key: str) -> bytes:
        """The key's earliest version.

        Raises:
           ValueError: S3 refused this record only (for example its storage
              class), which eval-host keys can cause; a malformed_record.
           ClientError: The validator cannot read the store, or S3 failed.
        """
        # S3 lists a key's versions newest first. Arrival times have whole
        # seconds, so they cannot order versions stored in the same second.
        earliest = by_key[key][-1]
        try:
            body: bytes = s3.get_object(
                Bucket=location.bucket, Key=key, VersionId=earliest.version_id
            )["Body"].read()
        except ClientError as ex:
            status = ex.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            if error_code(ex) in _STORE_READ_REFUSED or status >= 500:
                raise
            raise ValueError(f"S3 refused the read: {error_code(ex)}.") from ex
        return body

    # group keys by eval id (the first part after the prefix), and rescore
    # keys ("rescores/<eval-id>/<rescore-id>/<last>") by eval and rescore id
    evals: dict[str, list[str]] = defaultdict(list)
    rescore_keys: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key in by_key:
        rel = key.removeprefix(prefix)
        parts = rel.split("/")
        if parts[0] != RESCORES:
            evals[parts[0]].append(rel)
        elif len(parts) == 4:
            rescore_keys[(parts[1], parts[2])].append(parts[3])
        else:
            findings.append(
                Finding(
                    kind="malformed_record",
                    key=key,
                    message="Not a key a rescore writes.",
                )
            )

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
    stored = {
        eval_id: _read_eval(eval_id, keys, lambda rel: read(location.key(rel)))
        for eval_id, keys in sorted(evals.items())
    }
    rescores = {
        (eval_id, rescore_id): _read_rescore(
            eval_id,
            rescore_id,
            lasts,
            lambda rel: read(location.key(rel)),
            stored[eval_id].nonce if eval_id in stored else None,
        )
        for (eval_id, rescore_id), lasts in sorted(rescore_keys.items())
    }
    # every .eval file with the eval id (for example an original and its
    # rescored copy)
    compared = {
        eval_id: [
            _compare_eval_file(eval_id, stored, rescores, eval_file)
            for eval_file in eval_files.get(eval_id, [None])
        ]
        for eval_id in stored
    }
    findings.extend(
        f
        for eval_id in stored
        for f in [
            *stored[eval_id].findings,
            *(f for c in compared[eval_id] for f in c.findings),
        ]
    )
    findings.extend(f for r in rescores.values() for f in r.findings)

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
        samples_compared=sum(
            c.samples_compared for cs in compared.values() for c in cs
        ),
        stopped=[
            *(key for e in stored.values() for key in e.stopped),
            *(
                _rescore_name(*ids)
                for ids, r in rescores.items()
                if r.start is not None and r.closing is None
            ),
        ],
        not_logged=[
            key for cs in compared.values() for c in cs for key in c.not_logged
        ],
        prior_without_file={
            eval_id: c.named_by
            for eval_id, cs in compared.items()
            for c in cs
            if c.named_by
        },
        rescores=sorted(
            (
                RescoreInfo(
                    eval_id=eval_id,
                    rescore_id=rescore_id,
                    arrival=by_key[
                        location.key(_rescore_name(eval_id, rescore_id), START)
                    ][-1].arrival,
                    action=r.start.action,
                    original_results=_original_results(stored.get(eval_id)),
                )
                for (eval_id, rescore_id), r in rescores.items()
                if r.start is not None
            ),
            key=lambda info: (info.arrival, info.rescore_id),
        ),
    )


def read_eval_nonce(store: str, eval_id: str, client: Any | None = None) -> str:
    """The eval's nonce, from the latest version of its start record.

    A rescore of the eval writes it in each record. A second version is an
    ``overwrite`` finding, and a rescore with its nonce gets ``nonce``
    findings. Needs the validator's read access.

    Raises:
       ValueError: The store has no readable start record for the eval.
    """
    location = StoreLocation.parse(store)
    s3 = client if client is not None else s3_client()
    try:
        body = s3.get_object(Bucket=location.bucket, Key=location.key(eval_id, START))[
            "Body"
        ].read()
    except ClientError as ex:
        raise ValueError(
            f"Cannot read the start record of eval {eval_id}: {error_code(ex)}."
        ) from ex
    return StartRecord.model_validate_json(body).nonce


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


def _read_eval(
    eval_id: str, keys: list[str], read: Callable[[str], bytes]
) -> _StoredEval:
    findings: list[Finding] = []
    stopped: list[str] = []

    def finding(kind: FindingKind, message: str, key: str | None = None) -> None:
        findings.append(Finding(kind=kind, eval_id=eval_id, key=key, message=message))

    # records the eval could have written; anything else is reported, so
    # that it cannot stop the validator
    stored: dict[str, _EvalRecord] = {}
    for key in keys:
        record_type = _record_type(key)
        if record_type is None:
            finding("malformed_record", "Not a key the eval writes.", key)
            continue
        try:
            record = _parse_record(record_type, key, read(key))
            if isinstance(record, SampleRecord):
                validate_events([json.loads(row.data) for row in record.rows.events])
        except _NoVersion as ex:
            finding("record_version", str(ex), key)
            continue
        except ValueError as ex:
            finding("malformed_record", f"Cannot read it: {_first_error(ex)}", key)
            continue
        stored[key] = record

    start = stored.get(f"{eval_id}/{START}")
    if start is None:
        finding("missing_start", "No start record.")
        return _StoredEval(findings, stopped, None, {}, None, None)
    assert isinstance(start, StartRecord)
    nonce = start.nonce

    # attempts: "<eval>/<sample>.<epoch>/<attempt>/<seq|closing>"
    attempts: dict[tuple[str, str], dict[str, _EvalRecord]] = defaultdict(dict)
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
        stopped.append(eval_id)
    listed = {
        (sample_key_part(a.sample_id, a.epoch), str(a.attempt))
        for a in (eval_closing.samples if eval_closing else [])
    }

    # the eval closing record names every attempt that started, also one
    # stopped before its first record
    final_attempts: dict[str, _FinalAttempt] = {}
    for sample_part, attempt in sorted(attempts.keys() | listed):
        records = attempts.get((sample_part, attempt), {})
        prefix = f"{eval_id}/{sample_part}/{attempt}"
        if eval_closing is not None and (sample_part, attempt) not in listed:
            finding("unlisted_attempt", "Not in the eval's closing record.", prefix)
        sample_records = sorted(
            (r for r in records.values() if isinstance(r, SampleRecord)),
            key=lambda r: r.seq,
        )
        seqs = [r.seq for r in sample_records]
        # a row the eval could not have written (a pool row that is not JSON,
        # a key stored twice) fails here, not when its record is read
        events: list[Event] | None = None
        try:
            events = rebuild_events(sample_records)
        except (ValueError, sqlite3.IntegrityError) as ex:
            finding(
                "malformed_record",
                f"Cannot rebuild the sample's events: {_first_error(ex)}",
                prefix,
            )
        closing = records.get(CLOSING)
        if closing is None:
            stopped.append(prefix)
        else:
            assert isinstance(closing, SampleClosingRecord)
            if seqs != list(range(1, closing.records + 1)):
                finding(
                    "record_count",
                    f"Closing record counts {closing.records} records, "
                    f"store has {seqs}.",
                    prefix,
                )
            current = final_attempts.get(sample_part)
            if (
                current is None
                or current.closing.sample.attempt < closing.sample.attempt
            ):
                final_attempts[sample_part] = _FinalAttempt(closing, events)
        for message in _event_version_problems(sample_records):
            finding(*message, key=prefix)

    return _StoredEval(
        findings,
        stopped,
        eval_closing,
        final_attempts,
        start.prior_eval_id,
        nonce,
    )


class _Compared(NamedTuple):
    findings: list[Finding]
    samples_compared: int
    named_by: list[str] = []
    """The later evals that name the eval as prior, if it has no .eval file."""
    not_logged: list[str] = []
    """Closed samples not in the .eval file of a stopped eval."""


def _compare_eval_file(
    eval_id: str,
    evals: Mapping[str, _StoredEval],
    rescores: Mapping[tuple[str, str], _StoredRescore],
    eval_file: str | None,
) -> _Compared:
    """Compare a .eval file of the eval with its records.

    A .eval sample with no closed attempt of its own is one a retry reused:
    it is compared with the records of the earlier eval that ran it. A
    rescored sample is compared with its records after the rescores its
    markers name.
    """
    findings: list[Finding] = []

    def finding(kind: FindingKind, message: str, key: str | None = None) -> None:
        findings.append(Finding(kind=kind, eval_id=eval_id, key=key, message=message))

    stored = evals[eval_id]
    if stored.nonce is None:
        return _Compared(findings, 0)
    if eval_file is None:
        # eval_set's retry_cleanup deletes a retried eval's .eval file; the
        # retry's own .eval holds the samples it reused from it
        named_by = sorted(
            other_id
            for other_id, e in evals.items()
            if other_id != eval_id and e.prior_eval_id == eval_id
        )
        # an eval that stopped before its first .eval file write has no
        # closed attempt (the write comes before any sample runs)
        if not named_by and (stored.closing is not None or stored.final_attempts):
            finding(
                "missing_eval_file", "No .eval file in the log dir has this eval id."
            )
        return _Compared(findings, 0, named_by)

    header = read_eval_log(eval_file, header_only=True).model_dump(
        mode="json", include={"status", "stats", "results"}
    )

    # an eval stopped before it finished its .eval file (or its host
    # stopped writing) may not have logged every sample it closed
    not_logged: list[str] = []

    def missing_sample(message: str, key: str) -> None:
        if stored.closing is None and header["status"] == "started":
            not_logged.append(key)
        else:
            finding("missing_sample", message, key)

    to_compare = [
        _ToCompare(
            f"{eval_id}/{sample_part}/{final.closing.sample.attempt}",
            "",
            eval_id,
            final,
        )
        for sample_part, final in stored.final_attempts.items()
    ]
    summaries, members, other_members, repeated_summaries = _eval_file_samples(
        eval_file
    )
    eval_file_samples = summaries.keys() | members
    for name in other_members:
        finding(
            "unstored_sample",
            "A sample member under a name the eval never writes (it writes "
            "samples/<id>_epoch_<epoch>.json). A full read of the log returns "
            "it; it is not compared with the store.",
            f"{eval_id}/{name}",
        )
    for sample_part in repeated_summaries:
        finding(
            "summary_mismatch",
            "summaries.json has more than one row for this sample. The "
            "viewer can list each.",
            f"{eval_id}/{sample_part}",
        )
    unstored: set[str] = set()
    for sample_part in sorted(eval_file_samples - stored.final_attempts.keys()):
        earlier = _earlier_attempt(evals, stored.prior_eval_id, sample_part)
        if earlier is None:
            unstored.add(sample_part)
            finding(
                "unstored_sample",
                "In the .eval file, with no closed attempt in the store"
                + (
                    f" for this eval, the prior eval {stored.prior_eval_id} "
                    "or the evals it reused from."
                    if stored.prior_eval_id
                    else "."
                ),
                f"{eval_id}/{sample_part}",
            )
            continue
        source, final = earlier
        to_compare.append(
            _ToCompare(
                f"{eval_id}/{sample_part}",
                f" (reused from {source}/{sample_part}/{final.closing.sample.attempt})",
                source,
                final,
            )
        )

    # the .eval file holds the samples the eval closing record lists, and no
    # others; one the eval closed is compared above
    if stored.closing is not None:
        listed = set(stored.closing.logged)
        for sample_part in sorted(
            listed - stored.final_attempts.keys() - eval_file_samples
        ):
            finding(
                "missing_sample",
                f"Not in {eval_file}. The eval closing record lists it as in the "
                ".eval file when the eval finished.",
                f"{eval_id}/{sample_part}",
            )
        for sample_part in sorted(eval_file_samples - listed - unstored):
            finding(
                "unstored_sample",
                "In the .eval file, but the eval closing record does not list it "
                "as in the .eval file when the eval finished.",
                f"{eval_id}/{sample_part}",
            )

    compared = 0
    # the latest rescore of this eval each sample names (None: not rescored)
    file_rescores: set[RescoreRef | None] = set()
    prior_path = list(_prior_evals(evals, eval_id))
    for key, note, source, final in to_compare:
        ref = final.closing.sample
        try:
            logged = read_eval_log_sample(
                eval_file, ref.sample_id, ref.epoch, resolve_attachments="full"
            )
        except IndexError:
            missing_sample(
                f"Sample {ref.sample_id} epoch {ref.epoch} is not in {eval_file}"
                f"{note}.",
                key,
            )
            continue
        # the viewer's sample list and samples_df read the summaries
        summary = summaries.get(sample_key_part(ref.sample_id, ref.epoch))
        if summary is None:
            finding(
                "summary_mismatch",
                f"Sample {ref.sample_id} epoch {ref.epoch} has no sample summary "
                f"in {eval_file}{note}.",
                key,
            )
        elif changed := _changed_keys(
            summary.scores or {}, _summary_scores(logged.scores or {})
        ):
            finding(
                "summary_mismatch",
                f"Scores {changed} of the sample summary differ from the "
                f"sample's{note}.",
                key,
            )
        marker = latest_marker(logged.events)
        latest = marker.rescore if marker else None
        file_rescores.add(latest if latest and latest.eval_id == eval_id else None)
        chain = _rescore_chain(
            rescores,
            latest,
            sample_key_part(ref.sample_id, ref.epoch),
            set(prior_path[: prior_path.index(source) + 1]),
        )
        if isinstance(chain, str):
            finding("missing_rescore", f"{chain}{note}", key)
            continue
        if chain:
            names = ", ".join(step.record.rescore_id for step in chain)
            note = f"{note} (after rescores {names})"
        expected = reduce(
            _rescored,
            chain,
            EvalSample(
                id=ref.sample_id,
                epoch=ref.epoch,
                input="",
                target="",
                scores={k: v.score for k, v in final.closing.scores.items()},
                events=final.events or [],
            ),
        )
        if changed := _changed_keys(logged.scores or {}, expected.scores or {}):
            finding(
                "score_mismatch",
                f"Scores {changed} differ from the sample closing record's{note}.",
                key,
            )
        # records that cannot be rebuilt have a malformed_record finding
        if final.events is None:
            continue
        compared += 1
        if difference := _compare_events(logged, expected.events):
            finding("event_mismatch", f"{difference}{note}", key)

    # status and stats come from the eval closing record, results from the
    # closing record of the latest rescore the samples name
    mixed = len(file_rescores) > 1
    if mixed:
        latest_names = sorted(
            _rescore_name(r.eval_id, r.rescore_id) if r else "none"
            for r in file_rescores
        )
        finding(
            "rescore_mismatch",
            f"The samples of {eval_file} name different latest rescores: "
            f"{latest_names}.",
        )
    file_rescore = None if mixed else next(iter(file_rescores), None)

    def compare(source: str, closing: BaseModel, fields: set[str]) -> None:
        closing_fields = closing.model_dump(mode="json", include=fields)
        if changed := sorted(
            f for f in fields if not _same_json(header.get(f), closing_fields.get(f))
        ):
            finding(
                "eval_mismatch",
                f"The .eval file's {changed} differ from the {source}'s.",
            )

    # a .eval file that is not still "started" was finished, and the eval
    # (or the rescore) writes its closing record before or after that
    if stored.closing is None:
        if header["status"] != "started":
            finding(
                "missing_eval_closing",
                f"The .eval file's status is {header['status']}, and the store "
                "has no eval closing record.",
            )
    else:
        compare(
            "eval closing record",
            stored.closing,
            {"status", "stats"} | (set() if mixed or file_rescore else {"results"}),
        )
    rescore = file_rescore and rescores.get(
        (file_rescore.eval_id, file_rescore.rescore_id)
    )
    # a rescore not in the store has a missing_rescore finding
    if rescore and rescore.start is not None:
        assert file_rescore is not None
        name = _rescore_name(file_rescore.eval_id, file_rescore.rescore_id)
        if rescore.closing is not None:
            compare(f"rescore closing record ({name})", rescore.closing, {"results"})
        elif header["status"] != "started":
            finding(
                "missing_eval_closing",
                f"The .eval file's status is {header['status']}, and its "
                f"samples name rescore {name}, which has no closing record.",
            )
    return _Compared(findings, compared, not_logged=not_logged)


def _rescore_name(eval_id: str, rescore_id: str) -> str:
    return f"{RESCORES}/{eval_id}/{rescore_id}"


def _original_results(stored: _StoredEval | None) -> EvalResults | None:
    return stored.closing.results if stored and stored.closing else None


def _read_rescore(
    eval_id: str,
    rescore_id: str,
    lasts: list[str],
    read: Callable[[str], bytes],
    eval_nonce: str | None,
) -> _StoredRescore:
    """Read and check one rescore's records (``lasts``: the last key parts).

    Each record must have the eval's nonce (``eval_nonce``; None when the
    store has no start record of the eval, and then it is not checked).
    """
    name = _rescore_name(eval_id, rescore_id)
    findings: list[Finding] = []

    def finding(kind: FindingKind, message: str, key: str) -> None:
        findings.append(Finding(kind=kind, eval_id=eval_id, key=key, message=message))

    stored: dict[str, _RescoreRecord] = {}
    for last in lasts:
        key = f"{name}/{last}"
        record_type: type[_RescoreRecord] = (
            RescoreStartRecord
            if last == START
            else RescoreClosingRecord
            if last == CLOSING
            else RescoreSampleRecord
        )
        try:
            stored[last] = _parse_record(record_type, key, read(key))
        except _NoVersion as ex:
            finding("record_version", str(ex), key)
        except ValueError as ex:
            finding("malformed_record", f"Cannot read it: {_first_error(ex)}", key)

    findings.extend(
        Finding(
            kind="nonce",
            eval_id=eval_id,
            key=f"{name}/{last}",
            message="Nonce differs from the eval's start record's.",
        )
        for last, record in stored.items()
        if eval_nonce is not None and record.nonce != eval_nonce
    )
    start = stored.pop(START, None)
    if start is None:
        finding("missing_start", "No start record.", name)
        return _StoredRescore(findings, None, None, {})
    assert isinstance(start, RescoreStartRecord)
    closing = stored.pop(CLOSING, None)
    assert closing is None or isinstance(closing, RescoreClosingRecord)
    samples = {
        last: record
        for last, record in stored.items()
        if isinstance(record, RescoreSampleRecord)
    }
    return _StoredRescore(findings, start, closing, samples)


def _rescore_chain(
    rescores: Mapping[tuple[str, str], _StoredRescore],
    latest: RescoreRef | None,
    sample_part: str,
    eval_ids: set[str],
) -> list[_RescoreStep] | str:
    """The rescores to apply to the sample, oldest first, or why they cannot be.

    Each must be a rescore of one of ``eval_ids``: the evals the sample's
    copy came through.
    """
    chain: list[_RescoreStep] = []
    ref = latest
    while ref is not None:
        name = _rescore_name(ref.eval_id, ref.rescore_id)
        if ref.eval_id not in eval_ids:
            return (
                f"The sample names rescore {name}, of an eval this copy of the "
                "sample did not come through."
            )
        rescore = rescores.get((ref.eval_id, ref.rescore_id))
        if rescore is None or rescore.start is None:
            return f"The sample names rescore {name}, which is not in the store."
        record = rescore.samples.get(sample_part)
        if record is None:
            return f"The sample names rescore {name}, which has no record of it."
        if any(step.record is record for step in chain):
            return f"The sample's rescores name each other in a loop at {name}."
        chain.append(_RescoreStep(rescore.start.action, record))
        ref = record.built_on
    return chain[::-1]


def _rescored(sample: EvalSample, step: _RescoreStep) -> EvalSample:
    """The sample after one rescore, as ``inspect score`` changes it."""
    return sample.model_copy(
        update={
            "scores": _get_updated_scores(sample, step.record.scores, step.action),
            "events": _get_updated_events(sample, step.record.events, step.action),
        }
    )


def _earlier_attempt(
    evals: Mapping[str, _StoredEval], eval_id: str | None, sample_part: str
) -> tuple[str, _FinalAttempt] | None:
    """The nearest earlier eval that closed a reused sample, and its last closed attempt.

    A retry of a retry reuses the sample from the first retry, which reused
    it in turn. A retry that stopped running the sample keeps the copy it
    reused, so the search goes past it.
    """
    return next(
        (
            (prior_id, evals[prior_id].final_attempts[sample_part])
            for prior_id in _prior_evals(evals, eval_id)
            if sample_part in evals[prior_id].final_attempts
        ),
        None,
    )


def _prior_evals(
    evals: Mapping[str, _StoredEval], eval_id: str | None
) -> Iterator[str]:
    """``eval_id``, then each eval its start record's prior eval id leads to."""
    seen: set[str] = set()
    while eval_id is not None and eval_id in evals and eval_id not in seen:
        seen.add(eval_id)
        yield eval_id
        eval_id = evals[eval_id].prior_eval_id


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


class _EvalFileSamples(NamedTuple):
    """The samples of a .eval file, by ``<sample-id>.<epoch>``."""

    summaries: dict[str, EvalSampleSummary]
    """The sample summaries (which the viewer lists)."""
    members: set[str]
    """From the names of the sample members of the zip (which a full read
    returns), not the ids in the sample JSON: a member added under a new name
    can hold a stored sample's id."""
    other_members: list[str]
    """Names of ``samples/*.json`` members the eval does not write (not
    ``_sample_filename`` of the id and epoch in the name): a full read
    returns them too, and they are not compared."""
    repeated_summaries: list[str]
    """Samples with more than one summaries.json row. inspect_ai keeps the
    last row per ``(str(id), epoch)``; the viewer keys rows by the JSON id
    (1 and "1" differ), so it can list another row too."""


class _ZipContents(NamedTuple):
    sample_members: list[str]
    summary_rows: list[EvalSampleSummary]
    """summaries.json's rows, not deduplicated (none in a log still running)."""


def _eval_file_samples(eval_file: str) -> _EvalFileSamples:
    """The .eval file's samples, from its summaries and its members.

    Both, since an edit can add to one only.
    """

    async def read_zip() -> _ZipContents:
        async with AsyncFilesystem() as fs:
            reader = AsyncZipReader(fs, eval_file)
            names = [e.filename for e in (await reader.entries()).entries]
            rows = (
                _parse_summaries(
                    await _read_member_json(reader, SUMMARIES_JSON), SUMMARIES_JSON
                )
                if SUMMARIES_JSON in names
                else []
            )
        # the members a full read loads; a re-logged sample repeats its name
        return _ZipContents(
            list(
                dict.fromkeys(
                    name
                    for name in names
                    if name.startswith(f"{SAMPLES_DIR}/") and name.endswith(".json")
                )
            ),
            rows,
        )

    names, rows = run_coroutine(read_zip())
    keys = {name: _sample_key(name) for name in names}
    canonical = {
        name: key
        for name, key in keys.items()
        if key is not None and _sample_filename(key.sample_id, key.epoch) == name
    }
    row_counts = Counter(sample_key_part(row.id, row.epoch) for row in rows)
    return _EvalFileSamples(
        {
            sample_key_part(s.id, s.epoch): s
            for s in read_eval_log_sample_summaries(eval_file)
        },
        {sample_key_part(k.sample_id, k.epoch) for k in canonical.values()},
        [name for name in names if name not in canonical],
        sorted(key for key, count in row_counts.items() if count > 1),
    )


def _summary_scores(scores: dict[str, Score]) -> dict[str, Score]:
    """Scores as a sample summary holds them (long text and metadata thinned)."""
    return (
        EvalSampleSummary(id=0, epoch=0, input="", target="", scores=scores).scores
        or {}
    )


class _NoVersion(ValueError):
    """A record with no store format version, or a value that is not one."""


_R = TypeVar("_R", bound=BaseModel)


def _parse_record(record_type: type[_R], key: str, body: bytes) -> _R:
    """Parse a record of store format version 1 to ``STORE_VERSION``.

    Raises:
       NewerStoreVersionError: The record has a later version.
       _NoVersion: The record has no version, or one that is not 1 or more.
       ValueError: The record is not a ``record_type``.
    """
    data = json.loads(body)
    if isinstance(data, dict):
        if "version" not in data:
            raise _NoVersion("The record has no store format version.")
        version = data["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise _NoVersion(f"{json.dumps(version)} is not a store format version.")
        if version > STORE_VERSION:
            raise NewerStoreVersionError(
                f"Record {key} has store format version {version}. This "
                f"inspect_ai reads versions up to {STORE_VERSION}: upgrade "
                "inspect_ai to validate it."
            )
    return record_type.model_validate_json(body)


def _record_type(key: str) -> type[_EvalRecord] | None:
    """The record type a key under an eval holds, or None if the eval never writes the key."""
    match key.split("/"):
        case [_, "start"]:
            return StartRecord
        case [_, "closing"]:
            return EvalClosingRecord
        case [_, _, attempt, "closing"] if attempt.isdecimal():
            return SampleClosingRecord
        case [_, _, attempt, seq] if attempt.isdecimal() and seq.isdigit():
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
    """Event versions written after a boundary stored the event complete."""
    stored_complete: dict[str, int] = {}
    for record in records:
        completed_here: dict[str, int] = {}
        for row in record.rows.events:
            event = json.loads(row.data)
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


def rebuild_events(records: list[SampleRecord]) -> list[Event]:
    """Rebuild a sample's events from its records, with attachments resolved.

    Uses the code inspect_ai uses to log a sample whose events were evicted
    from memory: the rows go into a sample buffer, which is read back with
    ``open_sample_history`` and ``materialize_streaming_sample``. The events
    match a logged sample's read with ``resolve_attachments="full"``.
    """
    base = mark_attachments_resolved(
        EvalSample(id="rebuild", epoch=1, input="", target=""), "full"
    )
    with tempfile.TemporaryDirectory() as tmp:
        db = SampleBufferDatabase(
            location=str(Path(tmp) / "rebuild.eval"), db_dir=Path(tmp)
        )
        try:
            db.insert_sample_rows(base.id, base.epoch, _rebuild_rows(records))
            with db.open_sample_history(base.id, base.epoch) as history:
                return materialize_streaming_sample(base, history).events
        finally:
            db.cleanup()


def _compare_events(logged: EvalSample, expected: list[Event]) -> str | None:
    """The first difference between the logged events and the expected ones, if any."""
    logged_events = [e.model_dump(mode="json") for e in logged.events]
    stored_events = [e.model_dump(mode="json") for e in expected]
    for index, (lhs, rhs) in enumerate(zip(logged_events, stored_events)):
        if not _same_json(lhs, rhs):
            fields = sorted(
                k
                for k in lhs.keys() | rhs.keys()
                if not _same_json(lhs.get(k), rhs.get(k))
            )
            return (
                f"Event {index} ({rhs.get('event')} {rhs.get('uuid')}) differs in "
                f"{fields}."
            )
    if len(logged_events) != len(stored_events):
        return (
            f".eval has {len(logged_events)} events, the store has "
            f"{len(stored_events)}."
        )
    return None
