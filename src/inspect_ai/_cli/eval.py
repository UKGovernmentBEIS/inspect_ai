import click
from typing_extensions import Unpack

from inspect_ai import eval, eval_retry
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

from .common import CommonOptions, common_options, resolve_common_options
from .util import parse_cli_args, parse_tool_env

MAX_SAMPLES_HELP = "Maximum number of samples to run in parallel (default is running all samples in parallel)"
MAX_SUBPROCESSES_HELP = (
    "Maximum number of subprocesses to run in parallel (default is os.cpu_count())"
)
NO_TOOL_CLEANUP_HELP = "Do not cleanup tool environments after task completes"
NO_LOG_SAMPLES_HELP = "Do not include samples in the log file."
NO_LOG_IMAGES_HELP = "Do not include base64 encoded versions of filename or URL based images in the log file."
LOG_BUFFER_HELP = f"Number of samples to buffer before writing log file (defaults to {DEFAULT_LOG_BUFFER_LOCAL} for local filesystems, and {DEFAULT_LOG_BUFFER_REMOTE} for remote filesystems)."
NO_SCORE_HELP = (
    "Do not score model output (use the inspect score command to score output later)"
)
MAX_CONNECTIONS_HELP = f"Maximum number of concurrent connections to Model API (defaults to {DEFAULT_MAX_CONNECTIONS})"
MAX_RETRIES_HELP = (
    f"Maximum number of times to retry request (defaults to {DEFAULT_MAX_RETRIES})"
)
TIMEOUT_HELP = "Request timeout (in seconds)."


@click.command("eval")
@click.argument("tasks", nargs=-1)
@click.option(
    "--model",
    type=str,
    required=True,
    envvar=["INSPECT_EVAL_MODEL", "INSPECT_MODEL_NAME"],
    help="Model used to evaluate tasks.",
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
    "--toolenv",
    type=str,
    help="Tool environment type (with optional config file). e.g. 'docker' or 'docker:compose.yml'",
)
@click.option(
    "--no-toolenv-cleanup",
    type=bool,
    is_flag=True,
    help=NO_TOOL_CLEANUP_HELP,
)
@click.option(
    "--limit",
    type=str,
    help="Limit samples to evaluate e.g. 10 or 10-20",
)
@click.option(
    "--epochs",
    type=int,
    help=f"Number of times to repeat dataset (defaults to {DEFAULT_EPOCHS}) ",
)
@click.option("--max-connections", type=int, help=MAX_CONNECTIONS_HELP)
@click.option("--max-retries", type=int, help=MAX_RETRIES_HELP)
@click.option("--timeout", type=int, help=TIMEOUT_HELP)
@click.option("--max-samples", type=int, help=MAX_SAMPLES_HELP)
@click.option("--max-subprocesses", type=int, help=MAX_SUBPROCESSES_HELP)
@click.option(
    "--max-messages",
    type=int,
    help="Maximum number of messages to allow in a task conversation.",
)
@click.option("--no-log-samples", type=bool, is_flag=True, help=NO_LOG_SAMPLES_HELP)
@click.option("--no-log-images", type=bool, is_flag=True, help=NO_LOG_IMAGES_HELP)
@click.option("--log-buffer", type=int, help=LOG_BUFFER_HELP)
@click.option(
    "--no-score",
    type=bool,
    is_flag=True,
    help=NO_SCORE_HELP,
)
@click.option(
    "--max-tokens",
    type=int,
    help="The maximum number of tokens that can be generated in the completion (default is model specific)",
)
@click.option(
    "--system-message",
    type=str,
    help="Override the default system message.",
)
@click.option(
    "--best-of",
    type=int,
    help="Generates best_of completions server-side and returns the 'best' (the one with the highest log probability per token). OpenAI only.",
)
@click.option(
    "--frequency-penalty",
    type=float,
    help="Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model's likelihood to repeat the same line verbatim. OpenAI only.",
)
@click.option(
    "--presence-penalty",
    type=float,
    help="Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model's likelihood to talk about new topics. OpenAI only.",
)
@click.option(
    "--logit-bias",
    type=str,
    help='Map token Ids to an associated bias value from -100 to 100 (e.g. "42=10,43=-10")',
)
@click.option("--seed", type=int, help="Random seed. OpenAI only.")
@click.option(
    "--stop-seqs",
    type=str,
    help="Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence.",
)
@click.option(
    "--suffix",
    type=str,
    help="The suffix that comes after a completion of inserted text. OpenAI only.",
)
@click.option(
    "--temperature",
    type=float,
    help="What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic.",
)
@click.option(
    "--top-p",
    type=float,
    help="An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass.",
)
@click.option(
    "--top-k",
    type=int,
    help="Randomly sample the next word from the top_k most likely next words. GDM only.",
)
@click.option(
    "--num-choices",
    type=int,
    help="How many chat completion choices to generate for each input message.",
)
@click.option(
    "--logprobs",
    type=bool,
    is_flag=True,
    help="Return log probabilities of the output tokens. OpenAI, TogetherAI, and Huggingface only.",
)
@click.option(
    "--top-logprobs",
    type=int,
    help="Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI and Huggingface only.",
)
@common_options
def eval_command(
    tasks: tuple[str] | None,
    model: str,
    model_base_url: str | None,
    m: tuple[str] | None,
    t: tuple[str] | None,
    toolenv: str | None,
    no_toolenv_cleanup: bool | None,
    epochs: int | None,
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
    max_messages: int | None,
    max_samples: int | None,
    max_subprocesses: int | None,
    no_log_samples: bool | None,
    no_log_images: bool | None,
    log_buffer: int | None,
    no_score: bool | None,
    **kwargs: Unpack[CommonOptions],
) -> None:
    """Evaluate one or more tasks."""
    # build generate config
    config_keys = list(GenerateConfigArgs.__mutable_keys__)  # type: ignore
    config = GenerateConfigArgs()
    for key, value in locals().items():
        if key in config_keys and value is not None:
            if key == "stop_seqs":
                value = value.split(",")
            if key == "logprobs" and value is False:
                value = None
            config[key] = value  # type: ignore
    # resolve common options
    (log_dir, log_level) = resolve_common_options(kwargs)

    # parse params and model args
    task_args = parse_cli_args(t)
    model_args = parse_cli_args(m)

    # resolve range
    eval_limit = parse_samples_limit(limit)

    # resolve logit_bias
    config["logit_bias"] = parse_logit_bias(logit_bias)

    # resolve negating options
    toolenv_cleanup = False if no_toolenv_cleanup else None
    log_samples = False if no_log_samples else None
    log_images = False if no_log_images else None
    score = False if no_score else True

    # evaluate
    eval(
        tasks=list(tasks) if tasks else None,
        model=model,
        model_base_url=model_base_url,
        model_args=model_args,
        task_args=task_args,
        toolenv=parse_tool_env(toolenv),
        toolenv_cleanup=toolenv_cleanup,
        log_level=log_level,
        log_dir=log_dir,
        limit=eval_limit,
        epochs=epochs,
        max_messages=max_messages,
        max_samples=max_samples,
        max_subprocesses=max_subprocesses,
        log_samples=log_samples,
        log_images=log_images,
        log_buffer=log_buffer,
        score=score,
        **config,
    )


def parse_logit_bias(logit_bias: str | None) -> dict[int, float] | None:
    logit_biases = parse_cli_args(logit_bias.split(",")) if logit_bias else None
    if logit_biases:
        return dict(
            zip([int(key) for key in logit_biases.keys()], logit_biases.values())
        )
    else:
        return None


@click.command("eval-retry")
@click.argument("log_files", nargs=-1, required=True)
@click.option(
    "--max-samples", type=int, help=MAX_SAMPLES_HELP, envvar="INSPECT_EVAL_MAX_SAMPLES"
)
@click.option(
    "--max-subprocesses",
    type=int,
    help=MAX_SUBPROCESSES_HELP,
    envvar="INSPECT_EVAL_MAX_SUBPROCESSES",
)
@click.option(
    "--no-toolenv-cleanup",
    type=bool,
    is_flag=True,
    help=NO_TOOL_CLEANUP_HELP,
)
@click.option(
    "--no-log-samples",
    type=bool,
    is_flag=True,
    help=NO_LOG_SAMPLES_HELP,
    envvar="INSPECT_EVAL_LOG_SAMPLES",
)
@click.option(
    "--no-log-images",
    type=bool,
    is_flag=True,
    help=NO_LOG_IMAGES_HELP,
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
    max_subprocesses: int | None,
    no_toolenv_cleanup: bool | None,
    no_log_samples: bool | None,
    no_log_images: bool | None,
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
    toolenv_cleanup = False if no_toolenv_cleanup else None
    log_samples = False if no_log_samples else None
    log_images = False if no_log_images else None
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
        max_subprocesses=max_subprocesses,
        toolenv_cleanup=toolenv_cleanup,
        log_samples=log_samples,
        log_images=log_images,
        log_buffer=log_buffer,
        score=score,
        max_retries=max_retries,
        timeout=timeout,
        max_connections=max_connections,
    )
