from inspect_ai._util.hooks import init_hooks
from inspect_ai._util.logger import init_http_rate_limit_count
from inspect_ai.model import GenerateConfig, Model
from inspect_ai.model._model import init_active_model, init_model_usage
from inspect_ai.util._concurrency import init_concurrency
from inspect_ai.util._subprocess import init_max_subprocesses


def init_eval_context(max_subprocesses: int | None = None) -> None:
    init_concurrency()
    init_max_subprocesses(max_subprocesses)
    init_http_rate_limit_count()
    init_hooks()


def init_task_context(model: Model, config: GenerateConfig = GenerateConfig()) -> None:
    init_active_model(model, config)
    init_model_usage()
