from anyio.abc import TaskGroup

from inspect_ai._util.dotenv import init_dotenv
from inspect_ai._util.eval_task_group import init_eval_task_group
from inspect_ai._util.hooks import init_hooks
from inspect_ai._util.logger import init_logger
from inspect_ai.approval._apply import have_tool_approval, init_tool_approval
from inspect_ai.approval._human.manager import init_human_approval_manager
from inspect_ai.approval._policy import ApprovalPolicy
from inspect_ai.log._samples import init_active_samples
from inspect_ai.model import GenerateConfig, Model
from inspect_ai.model._model import (
    init_active_model,
    init_model_roles,
    init_model_usage,
)
from inspect_ai.util._concurrency import init_concurrency
from inspect_ai.util._subprocess import init_max_subprocesses


def init_eval_context(
    log_level: str | None,
    log_level_transcript: str | None,
    max_subprocesses: int | None = None,
    task_group: TaskGroup | None = None,
) -> None:
    init_dotenv()
    init_logger(log_level, log_level_transcript)
    init_concurrency()
    init_max_subprocesses(max_subprocesses)
    init_hooks()
    init_active_samples()
    init_human_approval_manager()
    init_eval_task_group(task_group)


def init_task_context(
    model: Model,
    model_roles: dict[str, Model] | None = None,
    approval: list[ApprovalPolicy] | None = None,
    config: GenerateConfig = GenerateConfig(),
) -> None:
    init_active_model(model, config)
    init_model_roles(model_roles or {})
    init_model_usage()
    if not have_tool_approval():
        init_tool_approval(approval)
