from datetime import datetime
from typing import Any, Callable, Mapping, Type

from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai.log._log import EvalLog

from ..columns import Column, ColumnType
from ..extract import list_as_str
from ..validate import resolved_schema
from .extract import eval_log_location, eval_log_scores_dict


class EvalColumn(Column):
    """Column which maps to `EvalLog`."""

    def __init__(
        self,
        name: str,
        *,
        path: str | JSONPath | Callable[[EvalLog], JsonValue],
        required: bool = False,
        default: JsonValue | None = None,
        type: Type[ColumnType] | None = None,
        value: Callable[[JsonValue], JsonValue] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            path=path if not callable(path) else None,
            required=required,
            default=default,
            type=type,
            value=value,
        )
        self._extract_eval = path if callable(path) else None

    @override
    def path_schema(self) -> Mapping[str, Any]:
        return self.schema

    schema = resolved_schema(EvalLog)


EvalId: list[Column] = [
    EvalColumn("eval_id", path="eval.eval_id", required=True),
]
"""Eval id column."""

EvalInfo: list[Column] = [
    EvalColumn("run_id", path="eval.run_id", required=True),
    EvalColumn("task_id", path="eval.task_id", required=True),
    EvalColumn("log", path=eval_log_location),
    EvalColumn("created", path="eval.created", type=datetime, required=True),
    EvalColumn("tags", path="eval.tags", default="", value=list_as_str),
    EvalColumn("git_origin", path="eval.revision.origin"),
    EvalColumn("git_commit", path="eval.revision.commit"),
    EvalColumn("packages", path="eval.packages"),
    EvalColumn("metadata", path="eval.metadata"),
]
"""Eval basic information columns."""

EvalTask: list[Column] = [
    EvalColumn("task_name", path="eval.task", required=True),
    EvalColumn("task_version", path="eval.task_version", required=True),
    EvalColumn("task_file", path="eval.task_file"),
    EvalColumn("task_attribs", path="eval.task_attribs"),
    EvalColumn("task_arg_*", path="eval.task_args"),
    EvalColumn("solver", path="eval.solver"),
    EvalColumn("solver_args", path="eval.solver_args"),
    EvalColumn("sandbox_type", path="eval.sandbox.type"),
    EvalColumn("sandbox_config", path="eval.sandbox.config"),
]
"""Eval task configuration columns."""

EvalModel: list[Column] = [
    EvalColumn("model", path="eval.model", required=True),
    EvalColumn("model_base_url", path="eval.model_base_url"),
    EvalColumn("model_args", path="eval.model_base_url"),
    EvalColumn("model_generate_config", path="eval.model_generate_config"),
    EvalColumn("model_roles", path="eval.model_roles"),
]
"""Eval model columns."""

EvalDataset: list[Column] = [
    EvalColumn("dataset_name", path="eval.dataset.name"),
    EvalColumn("dataset_location", path="eval.dataset.location"),
    EvalColumn("dataset_samples", path="eval.dataset.samples"),
    EvalColumn("dataset_sample_ids", path="eval.dataset.sample_ids"),
    EvalColumn("dataset_shuffled", path="eval.dataset.shuffled"),
]
"""Eval dataset columns."""

EvalConfig: list[Column] = [
    EvalColumn("epochs", path="eval.config.epochs"),
    EvalColumn("epochs_reducer", path="eval.config.epochs_reducer"),
    EvalColumn("approval", path="eval.config.approval"),
    EvalColumn("message_limit", path="eval.config.message_limit"),
    EvalColumn("token_limit", path="eval.config.token_limit"),
    EvalColumn("time_limit", path="eval.config.time_limit"),
    EvalColumn("working_limit", path="eval.config.working_limit"),
]
"""Eval configuration columns."""

EvalResults: list[Column] = [
    EvalColumn("status", path="status", required=True),
    EvalColumn("error_message", path="error.message"),
    EvalColumn("error_traceback", path="error.traceback"),
    EvalColumn("total_samples", path="results.total_samples"),
    EvalColumn("completed_samples", path="results.completed_samples"),
    EvalColumn("score_headline_name", path="results.scores[0].scorer"),
    EvalColumn("score_headline_metric", path="results.scores[0].metrics.*.name"),
    EvalColumn("score_headline_value", path="results.scores[0].metrics.*.value"),
]
"""Eval results columns."""

EvalScores: list[Column] = [
    EvalColumn("score_*_*", path=eval_log_scores_dict),
]
"""Eval scores (one score/metric per-columns)."""

EvalColumns: list[Column] = (
    EvalInfo
    + EvalTask
    + EvalModel
    + EvalDataset
    + EvalConfig
    + EvalResults
    + EvalScores
)
"""Default columns to import for `evals_df()`."""
