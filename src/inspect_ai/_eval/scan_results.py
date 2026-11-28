from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, cast

from inspect_ai._eval.task.log import resolve_scorer_metrics
from inspect_ai._eval.task.results import ScorerInfo, eval_results
from inspect_ai._eval.task.scan import verify_scout_prerequisites
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.log._headline import headline_metric_ref, resolve_headline_metric
from inspect_ai.log._log import EvalLog, EvalScorer
from inspect_ai.scorer import Metric, mean, stderr
from inspect_ai.scorer._metric import SampleScore, Score, Value
from inspect_ai.scorer._scorer import resolve_metrics

from .score import SCAN_IMPORT_METADATA, ScoreAction, reducers_from_log_header


class ScanImportError(ValueError):
    """Scan results that cannot be imported into the log."""


@dataclass
class _ImportedScanner:
    scanner_name: str
    score_name: str
    scores: dict[str, Score]


async def import_scan_results_async(
    log: EvalLog,
    scan_location: str,
    action: ScoreAction = "append",
    *,
    copy: bool = True,
) -> EvalLog:
    """Import completed Inspect Scout results into an evaluation log.

    Args:
        log: Evaluation log whose samples were scanned.
        scan_location: Scout scan directory (local or remote).
        action: Whether to append imported scores or overwrite existing scores.
        copy: Whether to deepcopy the log before updating it.

    Returns:
        The log with scanner results represented as ordinary sample scores.

    Raises:
        ScanImportError: If the scan is incomplete, contains errors, or includes rows
            that cannot be matched exactly to this log.
    """
    if log.samples is None:
        raise ScanImportError(
            "There are no samples in the log to import scan results into."
        )

    verify_scout_prerequisites()
    from inspect_scout.aio import scan_results_df_async

    scan = await scan_results_df_async(scan_location, rows="transcripts")
    if not scan.complete:
        raise ScanImportError(
            f"Cannot import incomplete scan results from '{scan_location}'. "
            "Complete or resume the scan first."
        )
    if scan.errors:
        raise ScanImportError(
            f"Cannot import scan results from '{scan_location}' because it "
            f"contains {len(scan.errors)} scan error(s)."
        )

    missing_uuids = sum(sample.uuid is None for sample in log.samples)
    if missing_uuids:
        raise ScanImportError(
            f"The evaluation log contains {missing_uuids} sample(s) without UUIDs, "
            "so scan results cannot be matched safely."
        )
    samples_by_uuid = {cast(str, sample.uuid): sample for sample in log.samples}
    if len(samples_by_uuid) != len(log.samples):
        raise ScanImportError(
            "The evaluation log contains duplicate sample UUIDs, so scan results "
            "cannot be matched safely."
        )

    used_score_names = (
        {score_name for sample in log.samples for score_name in (sample.scores or {})}
        if action == "append"
        else set()
    )
    if action == "append" and log.results is not None:
        used_score_names.update(score.name for score in log.results.scores)

    prepared: list[_ImportedScanner] = []
    for scanner_name in scan.scanners:
        frame = scan.scanners[scanner_name]
        if frame.empty:
            continue

        required_columns = {
            "transcript_id",
            "transcript_source_id",
            "value",
            "value_type",
        }
        missing_columns = required_columns.difference(frame.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ScanImportError(
                f"Scan results for scanner '{scanner_name}' are missing required "
                f"column(s): {missing}."
            )

        score_name = _unique_name(scanner_name, used_score_names)
        used_score_names.add(score_name)
        scanner_scores: dict[str, Score] = {}

        for row in frame.to_dict(orient="records"):
            transcript_id = _required_string(row.get("transcript_id"), "transcript_id")
            source_id = _required_string(
                row.get("transcript_source_id"), "transcript_source_id"
            )

            if source_id != log.eval.eval_id:
                raise ScanImportError(
                    f"Scan results for scanner '{scanner_name}' include transcript "
                    f"'{transcript_id}' from eval '{source_id}', not this log's eval "
                    f"'{log.eval.eval_id}'."
                )
            if transcript_id not in samples_by_uuid:
                raise ScanImportError(
                    f"Scan results for scanner '{scanner_name}' include transcript "
                    f"'{transcript_id}', which does not match any sample UUID in this log."
                )
            if transcript_id in scanner_scores:
                raise ScanImportError(
                    f"Scan results for scanner '{scanner_name}' contain multiple rows "
                    f"for transcript '{transcript_id}'. Only transcript-granularity "
                    "results can be imported."
                )
            if not _is_missing(row.get("scan_error")):
                raise ScanImportError(
                    f"Scan results for scanner '{scanner_name}' contain an error for "
                    f"transcript '{transcript_id}'."
                )

            score = _score_from_row(
                cast(Mapping[str, Any], row), scanner_name, transcript_id
            )
            if score is not None:
                scanner_scores[transcript_id] = score

        if scanner_scores:
            prepared.append(
                _ImportedScanner(
                    scanner_name=scanner_name,
                    score_name=score_name,
                    scores=scanner_scores,
                )
            )

    if not prepared:
        raise ScanImportError(
            f"No importable scan results were found in '{scan_location}'."
        )

    # Aggregate as score_async() does, through eval_results() with the log's
    # epoch reducers, so that recompute_metrics() later gives the same numbers.
    # The log is not changed until this has succeeded.
    scorers_info = [
        ScorerInfo(
            name=scanner.score_name,
            metrics=_default_metrics(scanner),
            metadata={SCAN_IMPORT_METADATA: scanner.scanner_name},
        )
        for scanner in prepared
    ]
    sample_scores: list[dict[str, SampleScore]] = []
    for sample in log.samples:
        uuid = cast(str, sample.uuid)
        imported = {
            scanner.score_name: SampleScore(
                score=scanner.scores[uuid],
                sample_id=sample.id,
                sample_metadata=sample.metadata,
            )
            for scanner in prepared
            if uuid in scanner.scores
        }
        if imported:
            sample_scores.append(imported)
    prior = log.results
    results, reductions = eval_results(
        len(log.samples),
        sample_scores,
        reducers_from_log_header(log),
        scorers_info,
        None,
        [scanner.score_name for scanner in prepared],
        early_stopping=prior.early_stopping if prior else None,
        metadata=prior.metadata if prior else None,
        logged_samples=prior.logged_samples if prior else None,
        completed_samples=sum(sample.error is None for sample in log.samples),
        headline_metric=None,
    )
    eval_scorers = [
        EvalScorer(
            name=info.name,
            metrics=resolve_scorer_metrics(resolve_metrics(info.metrics)),
            metadata=info.metadata,
        )
        for info in scorers_info
    ]

    imported_log = deepcopy(log) if copy else log
    assert imported_log.samples is not None
    for sample in imported_log.samples:
        if action == "overwrite":
            sample.scores = {}
        uuid = cast(str, sample.uuid)
        for scanner in prepared:
            if uuid in scanner.scores:
                sample.scores = sample.scores or {}
                sample.scores[scanner.score_name] = scanner.scores[uuid]

    # as in score_async(), a log with no results takes these as its results
    if action == "overwrite" or imported_log.results is None:
        imported_log.results = results
        imported_log.reductions = reductions
        imported_log.eval.scorers = eval_scorers
    else:
        imported_log.results.scores.extend(results.scores)
        if reductions:
            imported_log.reductions = (imported_log.reductions or []) + reductions
        imported_log.eval.scorers = (imported_log.eval.scorers or []) + eval_scorers

    headline = resolve_headline_metric(
        imported_log.results, imported_log.eval.headline_metric
    )
    imported_log.results.headline = headline_metric_ref(headline) if headline else None
    return imported_log


def _default_metrics(
    scanner: _ImportedScanner,
) -> list[Metric | dict[str, list[Metric]]]:
    """`mean()` and `stderr()` for numeric or boolean results, else no metrics."""
    numeric = all(
        isinstance(score.value, bool | int | float) for score in scanner.scores.values()
    )
    return [mean(), stderr()] if numeric else []


def _score_from_row(
    row: Mapping[str, Any], scanner_name: str, transcript_id: str
) -> Score | None:
    value_type = _required_string(row.get("value_type"), "value_type")
    value = _decode_value(row.get("value"), value_type)

    if value_type == "resultset":
        return _score_from_resultset(
            value,
            scanner_name,
            transcript_id,
            answer=_optional_string(row.get("answer")),
            explanation=_optional_string(row.get("explanation")),
            metadata=_json_object(row.get("metadata"), "metadata"),
            references=[
                *_json_list(row.get("message_references"), "message_references"),
                *_json_list(row.get("event_references"), "event_references"),
            ],
        )

    answer = _optional_string(row.get("answer"))
    explanation = _optional_string(row.get("explanation"))
    metadata = _json_object(row.get("metadata"), "metadata")
    references = [
        *_json_list(row.get("message_references"), "message_references"),
        *_json_list(row.get("event_references"), "event_references"),
    ]

    if value is None:
        if answer is None and explanation is None and not metadata and not references:
            return None
        score_value: Value = float("nan")
    else:
        score_value = _as_score_value(value)

    score_metadata = dict(metadata)
    score_metadata["scanner_references"] = references
    return Score(
        value=score_value,
        answer=answer,
        explanation=explanation,
        metadata=score_metadata,
    )


def _score_from_resultset(
    value: Any,
    scanner_name: str,
    transcript_id: str,
    *,
    answer: str | None,
    explanation: str | None,
    metadata: dict[str, Any],
    references: list[Any],
) -> Score:
    if not isinstance(value, list):
        raise ScanImportError(
            f"Result set from scanner '{scanner_name}' for transcript "
            f"'{transcript_id}' is not a JSON list."
        )

    result_values: dict[str, int | bool | float | str | None] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ScanImportError(
                f"Result set from scanner '{scanner_name}' for transcript "
                f"'{transcript_id}' contains a non-object item."
            )
        label = item.get("label")
        if not isinstance(label, str) or not label:
            raise ScanImportError(
                f"Result set from scanner '{scanner_name}' for transcript "
                f"'{transcript_id}' must have a label for every item."
            )
        if label in result_values:
            raise ScanImportError(
                f"Result set from scanner '{scanner_name}' for transcript "
                f"'{transcript_id}' contains duplicate label '{label}'."
            )
        item_value = item.get("value")
        result_values[label] = (
            to_json_str_safe(item_value)
            if isinstance(item_value, list | dict)
            else cast(int | bool | float | str | None, item_value)
        )

    score_metadata = dict(metadata)
    score_metadata["scanner_references"] = references
    if any(
        item.get("answer") is not None
        or item.get("explanation") is not None
        or item.get("metadata")
        or item.get("references")
        for item in value
        if isinstance(item, dict)
    ):
        score_metadata["scanner_results"] = value

    return Score(
        value=result_values,
        answer=answer,
        explanation=explanation,
        metadata=score_metadata,
    )


def _decode_value(value: Any, value_type: str) -> Any:
    if _is_missing(value) or value_type == "null":
        return None
    value = _python_scalar(value)

    if value_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise ScanImportError(f"Invalid boolean scan result value: {value!r}")
    if value_type == "number":
        if isinstance(value, bool):
            raise ScanImportError(f"Invalid numeric scan result value: {value!r}")
        if isinstance(value, int | float):
            return value
        if isinstance(value, str):
            # a column that mixes types is stored as text, and Scout writes
            # non-finite numbers as nan, inf and -inf
            for parse in (int, float):
                try:
                    return parse(value)
                except ValueError:
                    continue
        raise ScanImportError(f"Invalid numeric scan result value: {value!r}")
    if value_type in {"array", "object", "resultset"}:
        return json.loads(value) if isinstance(value, str) else value
    if value_type == "string":
        return str(value)

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return parsed if isinstance(parsed, list | dict) else value
    return value


def _as_score_value(value: Any) -> Value:
    if isinstance(value, list):
        return [
            item
            if isinstance(item, str | int | float | bool)
            else to_json_str_safe(item)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            str(key): item
            if isinstance(item, str | int | float | bool | None)
            else to_json_str_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, str | int | float | bool):
        return value
    raise ScanImportError(f"Unsupported scan result value: {value!r}")


def _json_object(value: Any, column: str) -> dict[str, Any]:
    parsed = _json_value(value, {})
    if not isinstance(parsed, dict):
        raise ScanImportError(
            f"Scan result column '{column}' must contain a JSON object."
        )
    return parsed


def _json_list(value: Any, column: str) -> list[Any]:
    parsed = _json_value(value, [])
    if not isinstance(parsed, list):
        raise ScanImportError(
            f"Scan result column '{column}' must contain a JSON list."
        )
    return parsed


def _json_value(value: Any, missing: Any) -> Any:
    if _is_missing(value):
        return missing
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as ex:
            raise ScanImportError(f"Scan result holds invalid JSON: {ex}") from ex
    return value


def _required_string(value: Any, column: str) -> str:
    value = _python_scalar(value)
    if _is_missing(value) or not isinstance(value, str) or not value:
        raise ScanImportError(f"Scan result column '{column}' must contain a string.")
    return value


def _optional_string(value: Any) -> str | None:
    value = _python_scalar(value)
    return None if _is_missing(value) else str(value)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, list | dict | tuple):
        return False
    from pandas import isna

    return bool(isna(value))


def _python_scalar(value: Any) -> Any:
    if hasattr(value, "item") and not isinstance(value, str | bytes):
        try:
            return value.item()
        except (TypeError, ValueError):
            return value
    return value


def _unique_name(name: str, used_names: set[str]) -> str:
    candidate = name
    count = 0
    while candidate in used_names:
        count += 1
        candidate = f"{name}-{count}"
    return candidate
