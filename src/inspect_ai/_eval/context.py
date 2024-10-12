from inspect_ai._display.logger import init_logger
from inspect_ai._util.dotenv import init_dotenv
from inspect_ai._util.hooks import init_hooks
from inspect_ai._util.logger import init_http_rate_limit_count
from inspect_ai.model import GenerateConfig, Model
from inspect_ai.model._model import init_active_model, init_model_usage
from inspect_ai.util._concurrency import init_concurrency
from inspect_ai.util._subprocess import init_max_subprocesses
from inspect_ai.util._trace import init_trace


def init_eval_context(
    trace: bool | None,
    log_level: str | None,
    log_level_transcript: str | None,
    max_subprocesses: int | None = None,
) -> None:
    init_dotenv()
    init_logger(log_level, log_level_transcript)
    init_concurrency()
    init_max_subprocesses(max_subprocesses)
    init_http_rate_limit_count()
    init_hooks()
    init_trace(trace)


def init_task_context(model: Model, config: GenerateConfig = GenerateConfig()) -> None:
    init_active_model(model, config)
    init_model_usage()
