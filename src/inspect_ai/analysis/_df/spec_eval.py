from datetime import datetime

from .spec import ImportSpec

EvalId: ImportSpec = {
    "run_id": ("$.eval.run_id", {"required": True}),
    "task_id": ("$.eval.task_id", {"required": True}),
    "log": "$.log",
    "created": ("$.eval.created", {"type": datetime, "required": True}),
    "git_origin": "$.eval.revision.origin",
    "git_commit": "$.eval.revision.commit",
    "tags": "$.eval.tags",
    "packages": "$.eval.packages",
    "metadata": "$.eval.metadata",
}
"""Import spec for eval identifiying fields."""

EvalTask: ImportSpec = {
    "task_name": ("$.eval.task", {"required": True}),
    "task_version": ("$.eval.task_version", {"required": True}),
    "task_file": "$.eval.task_file",
    "task_attribs": "$.eval.task_attribs",
    "task_args": "$.eval.task_args",
    "solver": "$.eval.solver",
    "solver_args": "$.eval.solver_args",
    "sandbox_type": "$.eval.sandbox.type",
    "sandbox_config": "$.eval.sandbox.config",
}
"""Import spec for eval task configuration."""

EvalModel: ImportSpec = {
    "model": ("$.eval.model", {"required": True}),
    "model_base_url": "$.eval.model_base_url",
    "model_args": "$.eval.model_base_url",
    "model_generate_config": ("$.eval.model_generate_config"),
    "model_roles": "$.eval.model_roles",
}
"""Import spec for eval model information."""

EvalDataset: ImportSpec = {
    "dataset_name": "$.eval.dataset.name",
    "dataset_location": "$.eval.dataset.location",
    "dataset_samples": "$.eval.dataset.samples",
    "dataset_sample_ids": "$.eval.dataset.sample_ids",
    "dataset_shuffled": "$.eval.dataset.shuffled",
}

EvalConfig: ImportSpec = {
    "epochs": "$.eval.config.epochs",
    "epochs_reducer": "$.eval.config.epochs_reducer",
    "approval": "$.eval.config.approval",
    "message_limit": "$.eval.config.message_limit",
    "token_limit": "$.eval.config.token_limit",
    "time_limit": "$.eval.config.time_limit",
    "working_limit": "$.eval.config.working_limit",
}
"""Import spec for eval configuration."""

EvalResults: ImportSpec = {
    "status": ("$.status", {"required": True}),
    "error_message": ("$.error.message"),
    "error_traceback": ("$.error.traceback"),
    "total_samples": ("$.results.total_samples", {"required": True}),
    "completed_samples": ("$.results.completed_samples", {"required": True}),
    "scorer_name": "$.results.scores[0].scorer",
    "scorer_metric": "$.results.scores[0].metrics.*.name",
    "scorer_value": "$.results.scores[0].metrics.*.value",
}
"""Import spec for eval results."""


EvalDefault: ImportSpec = (
    EvalId | EvalTask | EvalModel | EvalDataset | EvalConfig | EvalResults
)
"""Default fields to import for `evals_df()`."""
