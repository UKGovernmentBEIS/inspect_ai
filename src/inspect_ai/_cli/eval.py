import functools
from typing import Any, Callable, cast

import click
from typing_extensions import Unpack

from inspect_ai import Epochs, eval, eval_retry
from inspect_ai._eval.evalset import eval_set
from inspect_ai._util.constants import (
    DEFAULT_EPOCHS,
    DEFAULT_LOG_BUFFER_LOCAL,
    DEFAULT_LOG_BUFFER_REMOTE,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_RETRIES,
)
from inspect_ai._util.file import filesystem
from inspect_ai._util.samples import parse_samples_limit
from inspect_ai.log._file import log_file_info
from inspect_ai.model import GenerateConfigArgs
from inspect_ai.scorer._reducer import create_reducers

from .common import CommonOptions, common_options, resolve_common_options
from .util import parse_cli_args, parse_sandbox

MAX_SAMPLES_HELP = "Maximum number of samples to run in parallel (default is running all samples in parallel)"
MAX_TASKS_HELP = "Maximum number of tasks to run in parallel (default is 1)"
MAX_SUBPROCESSES_HELP = (
    "Maximum number of subprocesses to run in parallel (default is os.cpu_count())"
)
NO_SANDBOX_CLEANUP_HELP = "Do not cleanup sandbox environments after task completes"
NO_LOG_SAMPLES_HELP = "Do not include samples in the log file."
LOG_IMAGES_HELP = (
    "Include base64 encoded versions of filename or URL based images in the log file."
)
LOG_BUFFER_HELP = f"Number of samples to buffer before writing log file (defaults to {DEFAULT_LOG_BUFFER_LOCAL} for local filesystems, and {DEFAULT_LOG_BUFFER_REMOTE} for remote filesystems)."
NO_SCORE_HELP = (
    "Do not score model output (use the inspect score command to score output later)"
)
MAX_CONNECTIONS_HELP = f"Maximum number of concurrent connections to Model API (defaults to {DEFAULT_MAX_CONNECTIONS})"
MAX_RETRIES_HELP = (
    f"Maximum number of times to retry request (defaults to {DEFAULT_MAX_RETRIES})"
)
TIMEOUT_HELP = "Request timeout (in seconds)."


def eval_options(func: Callable[..., Any]) -> Callable[..., click.Context]:
    @click.option(
        "--model",
        type=str,
        required=True,
        help="Model used to evaluate tasks.",
        envvar="INSPECT_EVAL_MODEL",
    )
    @click.option(
        "--model-base-url",
        type=str,
        help="Base URL for for model API",
    )
    @click.option(
        "-M",
        multiple=True,
        type=str,
        envvar=["INSPECT_EVAL_MODEL_ARGS"],
        help="One or more native model arguments (e.g. -M arg=value)",
    )
    @click.option(
        "-T",
        multiple=True,
        type=str,
        envvar="INSPECT_EVAL_TASK_ARGS",
        help="One or more task arguments (e.g. -T arg=value)",
    )
    @click.option(
        "--sandbox",
        type=str,
        help="Sandbox environment type (with optional config file). e.g. 'docker' or 'docker:compose.yml'",
        envvar="INSPECT_EVAL_SANDBOX",
    )
    @click.option(
        "--no-sandbox-cleanup",
        type=bool,
        is_flag=True,
        help=NO_SANDBOX_CLEANUP_HELP,
        envvar="INSPECT_EVAL_NO_SANDBOX_CLEANUP",
    )
    @click.option(
        "--limit",
        type=str,
        help="Limit samples to evaluate e.g. 10 or 10-20",
        envvar="INSPECT_EVAL_LIMIT",
    )
    @click.option(
        "--epochs",
        type=int,
        help=f"Number of times to repeat dataset (defaults to {DEFAULT_EPOCHS}) ",
        envvar="INSPECT_EVAL_EPOCHS",
    )
    @click.option(
        "--epochs-reducer",
        type=str,
        help="Method for reducing per-epoch sample scores into a single score. Built in reducers include 'mean', 'median', 'mode', 'max', and 'at_least_{n}'.",
        envvar="INSPECT_EVAL_EPOCHS_REDUCER",
    )
    @click.option(
        "--max-connections",
        type=int,
        help=MAX_CONNECTIONS_HELP,
        envvar="INSPECT_EVAL_MAX_CONNECTIONS",
    )
    @click.option(
        "--max-retries",
        type=int,
        help=MAX_RETRIES_HELP,
        envvar="INSPECT_EVAL_MAX_RETRIES",
    )
    @click.option(
        "--timeout", type=int, help=TIMEOUT_HELP, envvar="INSPECT_EVAL_TIMEOUT"
    )
    @click.option(
        "--max-samples",
        type=int,
        help=MAX_SAMPLES_HELP,
        envvar="INSPECT_EVAL_MAX_SAMPLES",
    )
    @click.option(
        "--max-tasks", type=int, help=MAX_TASKS_HELP, envvar="INSPECT_EVAL_MAX_TASKS"
    )
    @click.option(
        "--max-subprocesses",
        type=int,
        help=MAX_SUBPROCESSES_HELP,
        envvar="INSPECT_EVAL_MAX_SUBPROCESSES",
    )
    @click.option(
        "--max-messages",
        type=int,
        help="Maximum number of messages to allow in a task conversation.",
        envvar="INSPECT_EVAL_MAX_MESSAGES",
    )
    @click.option(
        "--fail-on-error",
        type=float,
        is_flag=False,
        flag_value=0.0,
        help="Threshold of sample errors to tolerage (by default, evals fail when any error occurs). Value between 0 to 1 to set a proportion; value greater than 1 to set a count.",
        envvar="INSPECT_EVAL_FAIL_ON_ERROR",
    )
    @click.option(
        "--no-fail-on-error",
        type=bool,
        is_flag=True,
        default=False,
        help="Do not fail the eval if errors occur within samples (instead, continue running other samples)",
        envvar="INSPECT_EVAL_NO_FAIL_ON_ERROR",
    )
    @click.option(
        "--no-log-samples",
        type=bool,
        is_flag=True,
        help=NO_LOG_SAMPLES_HELP,
        envvar="INSPECT_EVAL_NO_LOG_SAMPLES",
    )
    @click.option(
        "--log-images/--no-log-images",
        type=bool,
        default=False,
        is_flag=True,
        help=LOG_IMAGES_HELP,
    )
    @click.option(
        "--log-buffer", type=int, help=LOG_BUFFER_HELP, envvar="INSPECT_EVAL_LOG_BUFFER"
    )
    @click.option(
        "--no-score",
        type=bool,
        is_flag=True,
        help=NO_SCORE_HELP,
        envvar="INSPECT_EVAL_NO_SCORE",
    )
    @click.option(
        "--max-tokens",
        type=int,
        help="The maximum number of tokens that can be generated in the completion (default is model specific)",
        envvar="INSPECT_EVAL_MAX_TOKENS",
    )
    @click.option(
        "--system-message",
        type=str,
        help="Override the default system message.",
        envvar="INSPECT_EVAL_SYSTEM_MESSAGE",
    )
    @click.option(
        "--best-of",
        type=int,
        help="Generates best_of completions server-side and returns the 'best' (the one with the highest log probability per token). OpenAI only.",
        envvar="INSPECT_EVAL_BEST_OF",
    )
    @click.option(
        "--frequency-penalty",
        type=float,
        help="Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model's likelihood to repeat the same line verbatim. OpenAI and Groq only.",
        envvar="INSPECT_EVAL_FREQUENCY_PENALTY",
    )
    @click.option(
        "--presence-penalty",
        type=float,
        help="Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model's likelihood to talk about new topics. OpenAI and Groq only.",
        envvar="INSPECT_EVAL_PRESENCE_PENALTY",
    )
    @click.option(
        "--logit-bias",
        type=str,
        help='Map token Ids to an associated bias value from -100 to 100 (e.g. "42=10,43=-10")',
        envvar="INSPECT_EVAL_LOGIT_BIAS",
    )
    @click.option(
        "--seed", type=int, help="Random seed. OpenAI only.", envvar="INSPECT_EVAL_SEED"
    )
    @click.option(
        "--stop-seqs",
        type=str,
        help="Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence.",
        envvar="INSPECT_EVAL_STOP_SEQS",
    )
    @click.option(
        "--suffix",
        type=str,
        help="The suffix that comes after a completion of inserted text. OpenAI only.",
        envvar="INSPECT_EVAL_SUFFIX",
    )
    @click.option(
        "--temperature",
        type=float,
        help="What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic.",
        envvar="INSPECT_EVAL_TEMPERATURE",
    )
    @click.option(
        "--top-p",
        type=float,
        help="An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass.",
        envvar="INSPECT_EVAL_TOP_P",
    )
    @click.option(
        "--top-k",
        type=int,
        help="Randomly sample the next word from the top_k most likely next words. GDM only.",
        envvar="INSPECT_EVAL_TOP_K",
    )
    @click.option(
        "--num-choices",
        type=int,
        help="How many chat completion choices to generate for each input message.",
        envvar="INSPECT_EVAL_NUM_CHOICES",
    )
    @click.option(
        "--logprobs",
        type=bool,
        is_flag=True,
        help="Return log probabilities of the output tokens. OpenAI, TogetherAI, and Huggingface only.",
        envvar="INSPECT_EVAL_LOGPROBS",
    )
    @click.option(
        "--top-logprobs",
        type=int,
        help="Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI and Huggingface only.",
        envvar="INSPECT_EVAL_TOP_LOGPROBS",
    )
    @click.option(
        "--parallel-tool-calls/--no-parallel-tool-calls",
        type=bool,
        is_flag=True,
        default=True,
        help="Whether to enable parallel function calling during tool use (defaults to True) OpenAI and Groq only.",
        envvar="INSPECT_EVAL_PARALLEL_TOOL_CALLS",
    )
    @click.option(
        "--cache-prompt",
        type=click.Choice(["auto", "true", "false"]),
        help='Cache prompt prefix (Anthropic only). Defaults to "auto", which will enable caching for requests with tools.',
        envvar="INSPECT_EVAL_CACHE_PROMPT",
    )
    @common_options
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> click.Context:
        return cast(click.Context, func(*args, **kwargs))

    return wrapper


@click.command("eval")
@click.argument("tasks", nargs=-1)
@eval_options
def eval_command(
    tasks: tuple[str] | None,
    model: str,
    model_base_url: str | None,
    m: tuple[str] | None,
    t: tuple[str] | None,
    sandbox: str | None,
    no_sandbox_cleanup: bool | None,
    epochs: int | None,
    epochs_reducer: str | None,
    limit: str | None,
    max_retries: int | None,
    timeout: int | None,
    max_connections: int | None,
    max_tokens: int | None,
    system_message: str | None,
    best_of: int | None,
    frequency_penalty: float | None,
    presence_penalty: float | None,
    logit_bias: str | None,
    seed: int | None,
    stop_seqs: str | None,
    suffix: str | None,
    temperature: float | None,
    top_p: float | None,
    top_k: int | None,
    num_choices: int | None,
    logprobs: bool | None,
    top_logprobs: int | None,
    parallel_tool_calls: bool | None,
    cache_prompt: str | None,
    max_messages: int | None,
    max_samples: int | None,
    max_tasks: int | None,
    max_subprocesses: int | None,
    fail_on_error: bool | float | None,
    no_fail_on_error: bool | None,
    no_log_samples: bool | None,
    log_images: bool | None,
    log_buffer: int | None,
    no_score: bool | None,
    **kwargs: Unpack[CommonOptions],
) -> None:
    """Evaluate tasks."""
    # read config
    config = config_from_locals(dict(locals()))

    # resolve common options
    (log_dir, log_level) = resolve_common_options(kwargs)

    # exec eval
    eval_exec(
        tasks=tasks,
        log_level=log_level,
        log_dir=log_dir,
        model=model,
        model_base_url=model_base_url,
        m=m,
        t=t,
        sandbox=sandbox,
        no_sandbox_cleanup=no_sandbox_cleanup,
        epochs=epochs,
        epochs_reducer=epochs_reducer,
        limit=limit,
        max_messages=max_messages,
        max_samples=max_samples,
        max_tasks=max_tasks,
        max_subprocesses=max_subprocesses,
        fail_on_error=fail_on_error,
        no_fail_on_error=no_fail_on_error,
        debug_errors=kwargs["debug_errors"],
        no_log_samples=no_log_samples,
        log_images=log_images,
        log_buffer=log_buffer,
        no_score=no_score,
        is_eval_set=False,
        **config,
    )


@click.command("eval-set")
@click.argument("tasks", nargs=-1)
@click.option(
    "--retry-attempts",
    type=int,
    help="Maximum number of retry attempts before giving up (defaults to 10).",
    envvar="INSPECT_EVAL_RETRY_ATTEMPS",
)
@click.option(
    "--retry-wait",
    type=int,
    help="Time in seconds wait between attempts, increased exponentially. "
    + "(defaults to 30, resulting in waits of 30, 60, 120, 240, etc.). Wait time "
    + "per-retry will in no case by longer than 1 hour.",
    envvar="INSPECT_EVAL_RETRY_WAIT",
)
@click.option(
    "--retry-connections",
    type=float,
    help="Reduce max_connections at this rate with each retry (defaults to 0.5)",
    envvar="INSPECT_EVAL_RETRY_CONNECTIONS",
)
@click.option(
    "--no-retry-cleanup",
    type=bool,
    is_flag=True,
    help="Do not cleanup failed log files after retries",
    envvar="INSPECT_EVAL_NO_RETRY_CLEANUP",
)
@click.option(
    "--bundle-dir",
    type=str,
    is_flag=False,
    help="Bundle viewer and logs into output directory",
)
@click.option(
    "--bundle-overwrite",
    type=str,
    is_flag=True,
    help="Overwrite existing bundle dir.",
)
@eval_options
@click.pass_context
def eval_set_command(
    ctx: click.Context,
    tasks: tuple[str] | None,
    retry_attempts: int | None,
    retry_wait: int | None,
    retry_connections: float | None,
    no_retry_cleanup: bool | None,
    model: str,
    model_base_url: str | None,
    m: tuple[str] | None,
    t: tuple[str] | None,
    sandbox: str | None,
    no_sandbox_cleanup: bool | None,
    epochs: int | None,
    epochs_reducer: str | None,
    limit: str | None,
    max_retries: int | None,
    timeout: int | None,
    max_connections: int | None,
    max_tokens: int | None,
    system_message: str | None,
    best_of: int | None,
    frequency_penalty: float | None,
    presence_penalty: float | None,
    logit_bias: str | None,
    seed: int | None,
    stop_seqs: str | None,
    suffix: str | None,
    temperature: float | None,
    top_p: float | None,
    top_k: int | None,
    num_choices: int | None,
    logprobs: bool | None,
    top_logprobs: int | None,
    parallel_tool_calls: bool | None,
    cache_prompt: str | None,
    max_messages: int | None,
    max_samples: int | None,
    max_tasks: int | None,
    max_subprocesses: int | None,
    fail_on_error: bool | float | None,
    no_fail_on_error: bool | None,
    no_log_samples: bool | None,
    log_images: bool | None,
    log_buffer: int | None,
    no_score: bool | None,
    bundle_dir: str | None,
    bundle_overwrite: bool | None,
    **kwargs: Unpack[CommonOptions],
) -> int:
    """Evaluate a set of tasks."""
    # read config
    config = config_from_locals(dict(locals()))

    # resolve common options
    (log_dir, log_level) = resolve_common_options(kwargs)

    # exec eval
    success = eval_exec(
        tasks=tasks,
        log_level=log_level,
        log_dir=log_dir,
        model=model,
        model_base_url=model_base_url,
        m=m,
        t=t,
        sandbox=sandbox,
        no_sandbox_cleanup=no_sandbox_cleanup,
        epochs=epochs,
        epochs_reducer=epochs_reducer,
        limit=limit,
        max_messages=max_messages,
        max_samples=max_samples,
        max_tasks=max_tasks,
        max_subprocesses=max_subprocesses,
        fail_on_error=fail_on_error,
        no_fail_on_error=no_fail_on_error,
        debug_errors=kwargs["debug_errors"],
        no_log_samples=no_log_samples,
        log_images=log_images,
        log_buffer=log_buffer,
        no_score=no_score,
        is_eval_set=True,
        retry_attempts=retry_attempts,
        retry_wait=retry_wait,
        retry_connections=retry_connections,
        retry_cleanup=not no_retry_cleanup,
        bundle_dir=bundle_dir,
        bundle_overwrite=True if bundle_overwrite else False,
        **config,
    )

    # exit code indicating whether the evals are all complete
    ctx.exit(0 if success else 1)


def eval_exec(
    tasks: tuple[str] | None,
    log_level: str,
    log_dir: str,
    model: str,
    model_base_url: str | None,
    m: tuple[str] | None,
    t: tuple[str] | None,
    sandbox: str | None,
    no_sandbox_cleanup: bool | None,
    epochs: int | None,
    epochs_reducer: str | None,
    limit: str | None,
    max_messages: int | None,
    max_samples: int | None,
    max_tasks: int | None,
    max_subprocesses: int | None,
    fail_on_error: bool | float | None,
    no_fail_on_error: bool | None,
    debug_errors: bool | None,
    no_log_samples: bool | None,
    log_images: bool | None,
    log_buffer: int | None,
    no_score: bool | None,
    is_eval_set: bool = False,
    retry_attempts: int | None = None,
    retry_wait: int | None = None,
    retry_connections: float | None = None,
    retry_cleanup: bool | None = None,
    bundle_dir: str | None = None,
    bundle_overwrite: bool = False,
    **kwargs: Unpack[GenerateConfigArgs],
) -> bool:
    # parse params and model args
    task_args = parse_cli_args(t)
    model_args = parse_cli_args(m)

    # resolve epochs
    eval_epochs = (
        Epochs(epochs, create_reducers(parse_comma_separated(epochs_reducer)))
        if epochs
        else None
    )

    # resolve range
    eval_limit = parse_samples_limit(limit)

    # resolve fail_on_error
    if no_fail_on_error is True:
        fail_on_error = False
    elif fail_on_error == 0.0:
        fail_on_error = True

    # resolve negating options
    sandbox_cleanup = False if no_sandbox_cleanup else None
    log_samples = False if no_log_samples else None
    log_images = True if log_images else None
    score = False if no_score else True

    # build params
    params: dict[str, Any] = (
        dict(
            tasks=list(tasks) if tasks else None,
            model=model,
            model_base_url=model_base_url,
            model_args=model_args,
            task_args=task_args,
            sandbox=parse_sandbox(sandbox),
            sandbox_cleanup=sandbox_cleanup,
            log_level=log_level,
            log_dir=log_dir,
            limit=eval_limit,
            epochs=eval_epochs,
            fail_on_error=fail_on_error,
            debug_errors=debug_errors,
            max_messages=max_messages,
            max_samples=max_samples,
            max_tasks=max_tasks,
            max_subprocesses=max_subprocesses,
            log_samples=log_samples,
            log_images=log_images,
            log_buffer=log_buffer,
            score=score,
        )
        | kwargs
    )

    # evaluate
    if is_eval_set:
        params["retry_attempts"] = retry_attempts
        params["retry_wait"] = retry_wait
        params["retry_connections"] = retry_connections
        params["retry_cleanup"] = retry_cleanup
        params["bundle_dir"] = bundle_dir
        params["bundle_overwrite"] = bundle_overwrite
        success, _ = eval_set(**params)
        return success
    else:
        eval(**params)
        return True


def config_from_locals(locals: dict[str, Any]) -> GenerateConfigArgs:
    # build generate config
    config_keys = list(GenerateConfigArgs.__mutable_keys__)  # type: ignore
    config = GenerateConfigArgs()
    for key, value in locals.items():
        if key in config_keys and value is not None:
            if key == "stop_seqs":
                value = value.split(",")
            if key == "logprobs" and value is False:
                value = None
            if key == "logit_bias" and value is not None:
                value = parse_logit_bias(value)
            if key == "cache_prompt":
                if value.lower() == "true":
                    value = True
                elif value.lower() == "false":
                    value = False
            if key == "parallel_tool_calls":
                if value is not False:
                    value = None
            config[key] = value  # type: ignore
    return config


def parse_logit_bias(logit_bias: str | None) -> dict[int, float] | None:
    logit_biases = parse_cli_args(logit_bias.split(",")) if logit_bias else None
    if logit_biases:
        return dict(
            zip([int(key) for key in logit_biases.keys()], logit_biases.values())
        )
    else:
        return None


def parse_comma_separated(value: str | None) -> list[str] | None:
    if value is not None:
        return value.split(",")
    else:
        return None


@click.command("eval-retry")
@click.argument("log_files", nargs=-1, required=True)
@click.option(
    "--max-samples", type=int, help=MAX_SAMPLES_HELP, envvar="INSPECT_EVAL_MAX_SAMPLES"
)
@click.option(
    "--max-tasks", type=int, help=MAX_TASKS_HELP, envvar="INSPECT_EVAL_MAX_TASKS"
)
@click.option(
    "--max-subprocesses",
    type=int,
    help=MAX_SUBPROCESSES_HELP,
    envvar="INSPECT_EVAL_MAX_SUBPROCESSES",
)
@click.option(
    "--no-sandbox-cleanup",
    type=bool,
    is_flag=True,
    help=NO_SANDBOX_CLEANUP_HELP,
)
@click.option(
    "--no-log-samples",
    type=bool,
    is_flag=True,
    help=NO_LOG_SAMPLES_HELP,
    envvar="INSPECT_EVAL_LOG_SAMPLES",
)
@click.option(
    "--log-images/--no-log-images",
    type=bool,
    default=False,
    is_flag=True,
    help=LOG_IMAGES_HELP,
    envvar="INSPECT_EVAL_LOG_IMAGES",
)
@click.option(
    "--log-buffer", type=int, help=LOG_BUFFER_HELP, envvar="INSPECT_EVAL_LOG_BUFFER"
)
@click.option(
    "--no-score",
    type=bool,
    is_flag=True,
    help=NO_SCORE_HELP,
    envvar="INSPECT_EVAL_SCORE",
)
@click.option(
    "--max-connections",
    type=int,
    help=MAX_CONNECTIONS_HELP,
    envvar="INSPECT_EVAL_MAX_CONNECTIONS",
)
@click.option(
    "--max-retries", type=int, help=MAX_RETRIES_HELP, envvar="INSPECT_EVAL_MAX_RETRIES"
)
@click.option("--timeout", type=int, help=TIMEOUT_HELP, envvar="INSPECT_EVAL_TIMEOUT")
@common_options
def eval_retry_command(
    log_files: tuple[str],
    max_samples: int | None,
    max_tasks: int | None,
    max_subprocesses: int | None,
    no_sandbox_cleanup: bool | None,
    no_log_samples: bool | None,
    log_images: bool | None,
    log_buffer: int | None,
    no_score: bool | None,
    max_connections: int | None,
    max_retries: int | None,
    timeout: int | None,
    **kwargs: Unpack[CommonOptions],
) -> None:
    """Retry failed evaluation(s)"""
    # resolve common options
    (log_dir, log_level) = resolve_common_options(kwargs)

    # resolve negating options
    sandbox_cleanup = False if no_sandbox_cleanup else None
    log_samples = False if no_log_samples else None
    log_images = True if log_images else None
    score = False if no_score else True

    # resolve log file
    retry_log_files = [
        log_file_info(filesystem(log_file).info(log_file)) for log_file in log_files
    ]

    # retry
    eval_retry(
        retry_log_files,
        log_level=log_level,
        log_dir=log_dir,
        max_samples=max_samples,
        max_tasks=max_tasks,
        max_subprocesses=max_subprocesses,
        sandbox_cleanup=sandbox_cleanup,
        debug_errors=kwargs["debug_errors"],
        log_samples=log_samples,
        log_images=log_images,
        log_buffer=log_buffer,
        score=score,
        max_retries=max_retries,
        timeout=timeout,
        max_connections=max_connections,
    )
