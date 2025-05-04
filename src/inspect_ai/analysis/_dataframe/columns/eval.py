from datetime import datetime

from ..extract import eval_log_location, list_as_str, scores_dict
from .columns import Column, Columns

EvalId: Columns = {
    "eval_id": Column("eval.eval_id", required=True),
}

EvalInfo: Columns = {
    "run_id": Column("eval.run_id", required=True),
    "task_id": Column("eval.task_id", required=True),
    "log": Column(eval_log_location),
    "created": Column("eval.created", type=datetime, required=True),
    "tags": Column("eval.tags", default="", value=list_as_str),
    "git_origin": Column("eval.revision.origin"),
    "git_commit": Column("eval.revision.commit"),
    "packages": Column("eval.packages"),
    "metadata": Column("eval.metadata"),
}
"""Eval identifiying columns."""

EvalTask: Columns = {
    "task_name": Column("eval.task", required=True),
    "task_version": Column("eval.task_version", required=True),
    "task_file": Column("eval.task_file"),
    "task_attribs": Column("eval.task_attribs"),
    "task_arg_*": Column("eval.task_args"),
    "solver": Column("eval.solver"),
    "solver_args": Column("eval.solver_args"),
    "sandbox_type": Column("eval.sandbox.type"),
    "sandbox_config": Column("eval.sandbox.config"),
}
"""Eval task configuration columns."""

EvalModel: Columns = {
    "model": Column("eval.model", required=True),
    "model_base_url": Column("eval.model_base_url"),
    "model_args": Column("eval.model_base_url"),
    "model_generate_config": Column("eval.model_generate_config"),
    "model_roles": Column("eval.model_roles"),
}
"""Eval model columns."""

EvalDataset: Columns = {
    "dataset_name": Column("eval.dataset.name"),
    "dataset_location": Column("eval.dataset.location"),
    "dataset_samples": Column("eval.dataset.samples"),
    "dataset_sample_ids": Column("eval.dataset.sample_ids"),
    "dataset_shuffled": Column("eval.dataset.shuffled"),
}
"""Eval dataset columns."""

EvalConfig: Columns = {
    "epochs": Column("eval.config.epochs"),
    "epochs_reducer": Column("eval.config.epochs_reducer"),
    "approval": Column("eval.config.approval"),
    "message_limit": Column("eval.config.message_limit"),
    "token_limit": Column("eval.config.token_limit"),
    "time_limit": Column("eval.config.time_limit"),
    "working_limit": Column("eval.config.working_limit"),
}
"""Eval configuration columns."""

EvalResults: Columns = {
    "status": Column("status", required=True),
    "error_message": Column("error.message"),
    "error_traceback": Column("error.traceback"),
    "total_samples": Column("results.total_samples", required=True),
    "completed_samples": Column("results.completed_samples", required=True),
    "score_headline_name": Column("results.scores[0].scorer"),
    "score_headline_metric": Column("results.scores[0].metrics.*.name"),
    "score_headline_value": Column("results.scores[0].metrics.*.value"),
}
"""Eval results columns."""

EvalScores: Columns = {
    "score_*_*": Column(scores_dict),
}
"""Eval scores (one score/metric per-columns)."""

EvalDefault: Columns = (
    EvalId
    | EvalInfo
    | EvalTask
    | EvalModel
    | EvalDataset
    | EvalConfig
    | EvalResults
    | EvalScores
)
"""Default fields to import for `evals_df()`."""
