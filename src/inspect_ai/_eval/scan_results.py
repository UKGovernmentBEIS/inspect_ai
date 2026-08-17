from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, cast

from inspect_ai._eval.task.results import Metrics, ScorerInfo, compute_eval_scores
from inspect_ai._eval.task.scan import verify_scout_prerequisites
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.log._log import (
    EvalLog,
    EvalMetric,
    EvalMetricDefinition,
    EvalResults,
    EvalScore,
    EvalScorer,
)
from inspect_ai.scorer import mean, stderr
from inspect_ai.scorer._metric import SampleScore, Score, Value

from .score import ScoreAction


@dataclass
class _ImportedScanner:
    scanner_name: str
    score_name: str
    scores: dict[str, Score]
    metrics: dict[str, dict[str, float]] | None


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
        ValueError: If the scan is incomplete, contains errors, or includes rows
            that cannot be matched exactly to this log.
    """
    if log.samples is None:
        raise ValueError("There are no samples in the log to import scan results into.")

    verify_scout_prerequisites()
    from inspect_scout.aio import scan_results_df_async

    scan = await scan_results_df_async(scan_location, rows="transcripts")
    if not scan.complete:
        raise ValueError(
            f"Cannot import incomplete scan results from '{scan_location}'. "
            "Complete or resume the scan first."
        )
    if scan.errors:
        raise ValueError(
            f"Cannot import scan results from '{scan_location}' because it "
            f"contains {len(scan.errors)} scan error(s)."
        )

    missing_uuids = sum(sample.uuid is None for sample in log.samples)
    if missing_uuids:
        raise ValueError(
            f"The evaluation log contains {missing_uuids} sample(s) without UUIDs, "
            "so scan results cannot be matched safely."
        )
    samples_by_uuid = {cast(str, sample.uuid): sample for sample in log.samples}
    if len(samples_by_uuid) != len(log.samples):
        raise ValueError(
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
            raise ValueError(
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
                raise ValueError(
                    f"Scan results for scanner '{scanner_name}' include transcript "
                    f"'{transcript_id}' from eval '{source_id}', not this log's eval "
                    f"'{log.eval.eval_id}'."
                )
            if transcript_id not in samples_by_uuid:
                raise ValueError(
                    f"Scan results for scanner '{scanner_name}' include transcript "
                    f"'{transcript_id}', which does not match any sample UUID in this log."
                )
            if transcript_id in scanner_scores:
                raise ValueError(
                    f"Scan results for scanner '{scanner_name}' contain multiple rows "
                    f"for transcript '{transcript_id}'. Only transcript-granularity "
                    "results can be imported."
                )
            if not _is_missing(row.get("scan_error")):
                raise ValueError(
                    f"Scan results for scanner '{scanner_name}' contain an error for "
                    f"transcript '{transcript_id}'."
                )

            score = _score_from_row(
                cast(Mapping[str, Any], row), scanner_name, transcript_id
            )
            if score is not None:
                scanner_scores[transcript_id] = score

        summary = scan.summary.scanners.get(scanner_name)
        metrics = summary.metrics if summary is not None else None
        if scanner_scores:
            prepared.append(
                _ImportedScanner(
                    scanner_name=scanner_name,
                    score_name=score_name,
                    scores=scanner_scores,
                    metrics=metrics,
                )
            )

    if not prepared:
        raise ValueError(f"No importable scan results were found in '{scan_location}'.")

    # Compute aggregate results before mutating the destination log. In particular,
    # this keeps copy=False atomic if default metric computation rejects a value.
    imported_eval_scores: list[EvalScore] = []
    imported_eval_scorers: list[EvalScorer] = []
    for scanner in prepared:
        sample_scores = [
            SampleScore(
                score=score,
                sample_id=samples_by_uuid[transcript_id].id,
                sample_metadata=samples_by_uuid[transcript_id].metadata,
                scorer=scanner.scanner_name,
            )
            for transcript_id, score in scanner.scores.items()
        ]
        eval_scores, eval_scorer = _scanner_results(scanner, sample_scores)
        imported_eval_scores.extend(eval_scores)
        imported_eval_scorers.append(eval_scorer)

    imported_log = deepcopy(log) if copy else log
    assert imported_log.samples is not None
    imported_samples = imported_log.samples
    imported_by_uuid = {
        sample.uuid: sample for sample in imported_samples if sample.uuid is not None
    }

    if action == "overwrite":
        for sample in imported_samples:
            sample.scores = {}

    for scanner in prepared:
        for transcript_id, score in scanner.scores.items():
            sample = imported_by_uuid[transcript_id]
            sample.scores = sample.scores or {}
            sample.scores[scanner.score_name] = score

    prior_results = imported_log.results
    if prior_results is None:
        prior_results = EvalResults(
            total_samples=len(imported_samples),
            completed_samples=sum(sample.error is None for sample in imported_samples),
        )

    if action == "overwrite" or imported_log.results is None:
        imported_log.results = prior_results.model_copy(
            update={"scores": imported_eval_scores}
        )
        imported_log.eval.scorers = imported_eval_scorers
        imported_log.reductions = None
    else:
        imported_log.results.scores.extend(imported_eval_scores)
        imported_log.eval.scorers = (
            imported_log.eval.scorers or []
        ) + imported_eval_scorers

    return imported_log


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
        raise ValueError(
            f"Result set from scanner '{scanner_name}' for transcript "
            f"'{transcript_id}' is not a JSON list."
        )

    result_values: dict[str, int | bool | float | str | None] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(
                f"Result set from scanner '{scanner_name}' for transcript "
                f"'{transcript_id}' contains a non-object item."
            )
        label = item.get("label")
        if not isinstance(label, str) or not label:
            raise ValueError(
                f"Result set from scanner '{scanner_name}' for transcript "
                f"'{transcript_id}' must have a label for every item."
            )
        if label in result_values:
            raise ValueError(
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


def _scanner_results(
    scanner: _ImportedScanner,
    sample_scores: list[SampleScore],
) -> tuple[list[EvalScore], EvalScorer]:
    if scanner.metrics is None:
        default_metrics: Metrics = [mean(), stderr()]
        default_scores = compute_eval_scores(
            sample_scores,
            default_metrics,
            scanner.score_name,
            ScorerInfo(scanner.score_name, default_metrics),
        )
        scorer = EvalScorer(
            name=scanner.score_name,
            metrics=[
                EvalMetricDefinition(name="mean"),
                EvalMetricDefinition(name="stderr"),
            ],
        )
        return default_scores, scorer

    summary_scores: list[EvalScore] = []
    metric_definitions: dict[str, list[EvalMetricDefinition]] = {}
    for result_name, metric_values in scanner.metrics.items():
        imported_result_name = (
            scanner.score_name if result_name == scanner.scanner_name else result_name
        )
        scored_samples, unscored_samples = _score_counts(
            sample_scores, result_name, scanner.scanner_name
        )
        summary_scores.append(
            EvalScore(
                name=imported_result_name,
                scorer=scanner.score_name,
                scored_samples=scored_samples,
                unscored_samples=unscored_samples,
                metrics={
                    metric_name: EvalMetric(name=metric_name, value=metric_value)
                    for metric_name, metric_value in metric_values.items()
                },
            )
        )
        metric_definitions[result_name] = [
            EvalMetricDefinition(name=name) for name in metric_values
        ]

    scorer_metrics: (
        list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]]
        | dict[str, list[EvalMetricDefinition]]
    )
    if set(metric_definitions) == {scanner.scanner_name}:
        scorer_metrics = cast(
            list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]],
            metric_definitions[scanner.scanner_name],
        )
    else:
        scorer_metrics = metric_definitions
    return summary_scores, EvalScorer(name=scanner.score_name, metrics=scorer_metrics)


def _score_counts(
    sample_scores: list[SampleScore], result_name: str, scanner_name: str
) -> tuple[int, int]:
    values: list[Any]
    if result_name == scanner_name:
        values = [sample_score.score.value for sample_score in sample_scores]
    else:
        values = [
            sample_score.score.value[result_name]
            for sample_score in sample_scores
            if isinstance(sample_score.score.value, dict)
            and result_name in sample_score.score.value
        ]
    scored = sum(
        not (isinstance(value, float) and math.isnan(value)) for value in values
    )
    return scored, len(values) - scored


def _decode_value(value: Any, value_type: str) -> Any:
    if _is_missing(value) or value_type == "null":
        return None
    value = _python_scalar(value)

    if value_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise ValueError(f"Invalid boolean scan result value: {value!r}")
    if value_type == "number":
        if isinstance(value, bool):
            raise ValueError(f"Invalid numeric scan result value: {value!r}")
        if isinstance(value, int | float):
            return value
        if isinstance(value, str):
            parsed = json.loads(value)
            if isinstance(parsed, int | float) and not isinstance(parsed, bool):
                return parsed
        raise ValueError(f"Invalid numeric scan result value: {value!r}")
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
    raise ValueError(f"Unsupported scan result value: {value!r}")


def _json_object(value: Any, column: str) -> dict[str, Any]:
    parsed = _json_value(value, {})
    if not isinstance(parsed, dict):
        raise ValueError(f"Scan result column '{column}' must contain a JSON object.")
    return parsed


def _json_list(value: Any, column: str) -> list[Any]:
    parsed = _json_value(value, [])
    if not isinstance(parsed, list):
        raise ValueError(f"Scan result column '{column}' must contain a JSON list.")
    return parsed


def _json_value(value: Any, missing: Any) -> Any:
    if _is_missing(value):
        return missing
    if isinstance(value, str):
        return json.loads(value)
    return value


def _required_string(value: Any, column: str) -> str:
    value = _python_scalar(value)
    if _is_missing(value) or not isinstance(value, str) or not value:
        raise ValueError(f"Scan result column '{column}' must contain a string.")
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
