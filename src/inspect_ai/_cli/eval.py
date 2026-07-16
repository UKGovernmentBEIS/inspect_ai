import contextlib
import functools
import json
import os
import sys
from collections.abc import Callable, Iterator
from typing import Any, Literal, TextIO, cast

import click
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)
from typing_extensions import Unpack

from inspect_ai import Epochs, eval, eval_retry
from inspect_ai._eval.evalset import eval_set
from inspect_ai._eval.handoff import LaunchHandoff, set_launch_handoff_listener
from inspect_ai._util.config import resolve_args
from inspect_ai._util.constants import (
    ALL_LOG_LEVELS,
    DEFAULT_BATCH_SIZE,
    DEFAULT_CACHE_DAYS,
    DEFAULT_EPOCHS,
    DEFAULT_LOG_LEVEL_TRANSCRIPT,
    DEFAULT_LOG_SHARED,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_RETRY_ON_ERROR,
)
from inspect_ai._util.error import PrerequisiteError, SilentException
from inspect_ai._util.file import filesystem
from inspect_ai._util.samples import parse_sample_id, parse_samples_limit
from inspect_ai.log._file import log_file_info
from inspect_ai.log._log import EvalConfig, EvalLog
from inspect_ai.model import GenerateConfig, GenerateConfigArgs, get_model
from inspect_ai.model._cache import CachePolicy
from inspect_ai.model._generate_config import (  # noqa: F811
    BatchConfig,
    ImageOutput,
    OutputModality,
    ResponseSchema,
)
from inspect_ai.model._model_config import ModelConfig
from inspect_ai.scorer._reducer import create_reducers
from inspect_ai.solver._solver import SolverSpec
from inspect_ai.util import AdaptiveConcurrency
from inspect_ai.util._checkpoint.parse_cli import parse_checkpoint
from inspect_ai.util._limit import TokenLimit
from inspect_ai.util._resource import resource
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec

from .common import (
    CommonOptions,
    common_options,
    process_common_options,
)
from .detach import DETACH_HELP, exec_detached
from .util import (
    SectionedCommand,
    ctl_server_flag_callback,
    int_bool_or_str_flag_callback,
    int_bool_or_str_retry_flag_callback,
    int_or_bool_flag_callback,
    parse_cli_args,
    parse_cli_config,
    parse_model_role_cli_args,
    parse_sandbox,
    token_limit_flag_callback,
)

_SCANNER_OPTION_NAMES = {
    "scanner",
    "scanner_arg",
    "scans",
    "scan_name",
    "scan_tags",
    "scan_metadata",
    "scan_filter",
    "scan_model",
    "scan_model_base_url",
    "scan_model_arg",
    "scan_model_config",
    "scan_model_role",
    "scan_generate_config",
}


class EvalCommand(SectionedCommand):
    """`inspect eval` / `inspect eval-set` command with grouped help output."""

    SECTIONS = {"Scanner Options": _SCANNER_OPTION_NAMES}


MAX_SAMPLES_HELP = "Maximum number of samples to run in parallel (default is running all samples in parallel)"
MAX_TASKS_HELP = "Maximum number of tasks to run in parallel (default is 1 for eval and 10 for eval-set)"
MAX_SUBPROCESSES_HELP = (
    "Maximum number of subprocesses to run in parallel (default is os.cpu_count())"
)
MAX_SANDBOXES_HELP = "Maximum number of sandboxes (per-provider) to run in parallel."
NO_SANDBOX_CLEANUP_HELP = "Do not cleanup sandbox environments after task completes"
FAIL_ON_ERROR_HELP = "Threshold of sample errors to tolerage (by default, evals fail when any error occurs). Value between 0 to 1 to set a proportion; value greater than 1 to set a count."
NO_LOG_SAMPLES_HELP = "Do not include samples in the log file."
NO_LOG_REALTIME_HELP = (
    "Do not log events in realtime (affects live viewing of samples in inspect view)"
)
NO_FAIL_ON_ERROR_HELP = "Do not fail the eval if errors occur within samples (instead, continue running other samples)"
CONTINUE_ON_FAIL_HELP = "Do not immediately fail the eval if the error threshold is exceeded (instead, continue running other samples until the eval completes, and then possibly fail the eval)."
RETRY_ON_ERROR_HELP = "Retry samples if they encounter errors (by default, no retries occur). Specify --retry-on-error to retry a single time, or specify e.g. `--retry-on-error=3` to retry multiple times."
SCORE_ON_ERROR_HELP = "Score samples that error rather than failing the eval mid-run. Errors still count toward the --fail-on-error threshold for marking the log as 'error'. Only fires after retries (if any) are exhausted."
LOG_IMAGES_HELP = (
    "Include base64 encoded versions of filename or URL based images in the log file."
)
LOG_MODEL_API_HELP = "Log raw model api requests and responses. Note that error requests/responses are always logged."
LOG_REFUSALS_HELP = "Log warnings for model refusals."
LOG_BUFFER_HELP = "Number of samples to buffer before writing log file. If not specified, an appropriate default for the format and filesystem is chosen (10 for most all cases, 100 for JSON logs on remote filesystems)."
LOG_SHARED_HELP = "Sync sample events to log directory so that users on other systems can see log updates in realtime (defaults to no syncing). If enabled will sync every 10 seconds (or pass a value to sync every `n` seconds)."
NO_SCORE_HELP = (
    "Do not score model output (use the inspect score command to score output later)"
)
NO_SCORE_DISPLAY = "Do not display scoring metrics in realtime."
MAX_CONNECTIONS_HELP = f"Maximum number of concurrent connections to Model API (defaults to {DEFAULT_MAX_CONNECTIONS})"
ADAPTIVE_CONNECTIONS_HELP = (
    "Adaptive concurrency for Model API connections, automatically scaling "
    "between bounds based on rate-limit feedback (default: enabled, with "
    "min=10, start=20, max=100). Pass `false` to opt out, an integer N for "
    "a custom max (e.g. `200`), or bounds as `min-max` (e.g. `4-80`) or "
    "`min-start-max` (e.g. `4-20-80`). Explicit `--max-connections` and "
    "`--batch` take precedence."
)
MAX_RETRIES_HELP = (
    "Maximum number of times to retry model API requests (defaults to unlimited)"
)
TIMEOUT_HELP = "Model API request timeout in seconds (defaults to no timeout)"
ATTEMPT_TIMEOUT_HELP = "Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries)."
CACHE_HELP = "Policy for caching of model generations. Specify --cache to cache with 7 day expiration (7D). Specify an explicit duration (e.g. (e.g. 1h, 3d, 6M) to set the expiration explicitly (durations can be expressed as s, m, h, D, W, M, or Y). Alternatively, pass the file path to a YAML or JSON config file with a full `CachePolicy` configuration."
BATCH_HELP = "Batch requests together to reduce API calls when using a model that supports batching (by default, no batching). Specify --batch to batch with default configuration,  specify a batch size e.g. `--batch=1000` to configure batches of 1000 requests, or pass the file path to a YAML or JSON config file with batch configuration."
CHECKPOINT_HELP = "Periodically checkpoint sample state so the eval can be resumed via `inspect eval retry`. Specify --checkpoint for the default (every 500k tokens), --checkpoint=token:N{k,m,b} / time:N{s,m,h,d} / turn:N / manual for a shorthand trigger, or pass a YAML/JSON file path for a full CheckpointConfig."


def _notification_callback(
    ctx: click.Context, param: click.Parameter, value: Any
) -> bool | str | None:
    """Resolve `--notification`: bare flag -> True, path -> str, absent -> None."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value if isinstance(value, bool) else None
    if value == "__bare__":
        return True
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return None
    return value


def scanner_options(func: Callable[..., Any]) -> Callable[..., click.Context]:
    """Click decorator: scanner CLI options shared by `eval` / `eval-set` / `eval-retry`."""

    @click.option(
        "--scanner",
        type=str,
        envvar="INSPECT_EVAL_SCANNER",
        help=(
            "Scanner(s) to apply after each sample. Pass a YAML/JSON "
            "config file (ScannerConfig schema), a Python file "
            "with @scanner functions (use file.py@func to pick one), "
            "or a registry reference (pkg/name)."
        ),
    )
    @click.option(
        "--scanner-arg",
        "scanner_arg",
        multiple=True,
        type=str,
        envvar="INSPECT_EVAL_SCANNER_ARGS",
        help="One or more scanner arguments (e.g. --scanner-arg key=value).",
    )
    @click.option(
        "--scans",
        type=str,
        envvar="INSPECT_EVAL_SCANS",
        help="Location to write scan results to (defaults to <log-dir>/scans/).",
    )
    @click.option(
        "--scan-name",
        type=str,
        envvar="INSPECT_EVAL_SCAN_NAME",
        help='Scan name written to _scan.json (defaults to "eval_set").',
    )
    @click.option(
        "--scan-tags",
        type=str,
        envvar="INSPECT_EVAL_SCAN_TAGS",
        help="Comma-separated tags written to the scan spec.",
    )
    @click.option(
        "--scan-metadata",
        multiple=True,
        type=str,
        envvar="INSPECT_EVAL_SCAN_METADATA",
        help="Metadata written to the scan spec (e.g. --scan-metadata key=value).",
    )
    @click.option(
        "-F",
        "--scan-filter",
        multiple=True,
        type=str,
        envvar="INSPECT_EVAL_SCAN_FILTER",
        help=(
            "SQL WHERE clause(s) applied per-sample to skip transcripts that "
            "don't match (e.g. -F \"error = ''\")."
        ),
    )
    @click.option(
        "--scan-model",
        type=str,
        envvar="INSPECT_EVAL_SCAN_MODEL",
        help="Model used by scanners' get_model() (overrides the eval model).",
    )
    @click.option(
        "--scan-model-base-url",
        type=str,
        envvar="INSPECT_EVAL_SCAN_MODEL_BASE_URL",
        help="Base URL for the scanner-side model API.",
    )
    @click.option(
        "--scan-model-arg",
        "scan_model_arg",
        multiple=True,
        type=str,
        envvar="INSPECT_EVAL_SCAN_MODEL_ARGS",
        help="One or more scanner-side model arguments (e.g. --scan-model-arg key=value).",
    )
    @click.option(
        "--scan-model-config",
        type=str,
        envvar="INSPECT_EVAL_SCAN_MODEL_CONFIG",
        help="YAML or JSON config file with scanner-side model arguments.",
    )
    @click.option(
        "--scan-model-role",
        multiple=True,
        type=str,
        envvar="INSPECT_EVAL_SCAN_MODEL_ROLE",
        help=(
            "Named scanner-side model role with model name or YAML/JSON config "
            "(e.g. --scan-model-role grader=mockllm/model)."
        ),
    )
    @click.option(
        "--scan-generate-config",
        type=str,
        envvar="INSPECT_EVAL_SCAN_GENERATE_CONFIG",
        help="YAML or JSON config file with GenerateConfig for scanner model calls.",
    )
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> click.Context:
        return cast(click.Context, func(*args, **kwargs))

    return wrapper


def eval_options(func: Callable[..., Any]) -> Callable[..., click.Context]:
    @click.option(
        "--model",
        type=str,
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
        envvar="INSPECT_EVAL_MODEL_ARGS",
        help="One or more native model arguments (e.g. -M arg=value)",
    )
    @click.option(
        "--model-config",
        type=str,
        envvar="INSPECT_EVAL_MODEL_CONFIG",
        help="YAML or JSON config file with model arguments.",
    )
    @click.option(
        "--run-config",
        type=str,
        envvar="INSPECT_EVAL_RUN_CONFIG",
        help="YAML or JSON file with full run configuration (task, model, model roles, generate config, solver, eval config). CLI flags override values from this file. Cannot be combined with --generate-config, --task-config, or --solver-config.",
    )
    @click.option(
        "--model-role",
        multiple=True,
        type=str,
        envvar="INSPECT_EVAL_MODEL_ROLE",
        help='Named model role with model name or YAML/JSON config, e.g. --model-role critic=openai/gpt-4o or --model-role grader="{model: mockllm/model, temperature: 0.5}"',
    )
    @click.option(
        "-T",
        multiple=True,
        type=str,
        envvar="INSPECT_EVAL_TASK_ARGS",
        help="One or more task arguments (e.g. -T arg=value)",
    )
    @click.option(
        "--task-config",
        type=str,
        envvar="INSPECT_EVAL_TASK_CONFIG",
        help="YAML or JSON config file with task arguments.",
    )
    @click.option(
        "--solver",
        type=str,
        envvar="INSPECT_EVAL_SOLVER",
        help="Solver to execute (overrides task default solver)",
    )
    @click.option(
        "-S",
        multiple=True,
        type=str,
        envvar="INSPECT_EVAL_SOLVER_ARGS",
        help="One or more solver arguments (e.g. -S arg=value)",
    )
    @click.option(
        "--solver-config",
        type=str,
        envvar="INSPECT_EVAL_SOLVER_CONFIG",
        help="YAML or JSON config file with solver arguments.",
    )
    @scanner_options
    @click.option(
        "--tags",
        type=str,
        help="Tags to associate with this evaluation run.",
        envvar="INSPECT_EVAL_TAGS",
    )
    @click.option(
        "--metadata",
        multiple=True,
        type=str,
        help="Metadata to associate with this evaluation run (more than one --metadata argument can be specified).",
        envvar="INSPECT_EVAL_METADATA",
    )
    @click.option(
        "--trace",
        type=bool,
        is_flag=True,
        hidden=True,
        envvar="INSPECT_EVAL_TRACE",
        help="Trace message interactions with evaluated model to terminal.",
    )
    @click.option(
        "--approval",
        type=str,
        envvar="INSPECT_EVAL_APPROVAL",
        help="Config file for tool call approval.",
    )
    @click.option(
        "--notification",
        "notification",
        is_flag=False,
        flag_value="__bare__",
        default=None,
        callback=_notification_callback,
        # Disable Click auto_envvar_prefix lookup for this option.
        # The root CLI sets ``auto_envvar_prefix="INSPECT"``, which
        # would otherwise auto-bind ``INSPECT_EVAL_NOTIFICATION`` as
        # this option's value — colliding with the same env var
        # ``build_apprise(True)`` reads as the URL/config payload.
        # The collision would let a user who exports the URL turn
        # notifications on without passing the flag, or crash plain
        # ``inspect eval`` runs when the env var holds a URL string
        # that ``build_apprise`` then rejects as a non-file path.
        allow_from_autoenv=False,
        help=(
            "Send out-of-band notifications when a human-in-the-loop "
            "interaction (`ask_user` or human approval) is posted. Bare "
            "`--notification` reads URL(s) from the "
            "`INSPECT_EVAL_NOTIFICATION` environment variable (a single "
            "Apprise URL, a comma-separated list, or a path to an Apprise "
            "config file). `--notification <path>` reads from an Apprise "
            "YAML/text config file. URLs are not accepted directly on the "
            "command line so secrets never end up in shell history. "
            "Requires `pip install apprise`."
        ),
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
        "--checkpoint",
        is_flag=False,
        flag_value="default",
        default=None,
        help=CHECKPOINT_HELP,
        envvar="INSPECT_EVAL_CHECKPOINT",
    )
    @click.option(
        "--acp-server",
        is_flag=False,
        flag_value="true",
        default=None,
        callback=int_bool_or_str_flag_callback(True, None),
        help=(
            "Expose this eval via an Agent Client Protocol server for various "
            "clients (e.g. the `inspect acp` command). Bare flag enables a "
            "default AF_UNIX socket; pass an integer to bind a TCP loopback "
            "port (e.g. `--acp-server=4444`); pass `host:port` to bind on a "
            "specific interface (e.g. `--acp-server=0.0.0.0:4444`); pass a "
            "filesystem path for a custom UNIX socket. When this flag is set, "
            "all human-in-the-loop interactions (`approver: human` and the "
            "`ask_user` tool) route exclusively through attached ACP clients; "
            "the in-proc Textual panel and console handlers are bypassed. If "
            "no client is connected when an interaction fires, the eval parks "
            "until one attaches."
        ),
        envvar="INSPECT_EVAL_ACP_SERVER",
    )
    @click.option(
        "--ctl-server",
        is_flag=False,
        flag_value="true",
        default=None,
        callback=ctl_server_flag_callback,
        help=(
            "Control-channel server for this eval process (default: enabled "
            "on an AF_UNIX socket — the endpoint the `inspect ctl` CLI, "
            "scripted agents, and TUIs query). Pass `false` to disable it. "
            "Pass `keep` to also keep the process running "
            "after the eval finishes so its state and results stay readable; "
            "the process exits when `inspect ctl process release` is run (or POST "
            "/release is sent to the control endpoint). Without `keep` "
            "the process exits as soon as the eval body returns, taking the "
            "control surface with it."
        ),
        envvar="INSPECT_EVAL_CTL_SERVER",
    )
    @click.option(
        "--limit",
        type=str,
        help="Limit samples to evaluate e.g. 10 or 10-20",
        envvar="INSPECT_EVAL_LIMIT",
    )
    @click.option(
        "--sample-id",
        type=str,
        help="Evaluate specific sample(s) (comma separated list of ids)",
        envvar="INSPECT_EVAL_SAMPLE_ID",
    )
    @click.option(
        "--sample-shuffle",
        is_flag=False,
        flag_value="true",
        default=None,
        callback=int_or_bool_flag_callback(-1),
        help="Shuffle order of samples (pass a seed to make the order deterministic)",
        envvar=["INSPECT_EVAL_SAMPLE_SHUFFLE"],
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
        is_flag=False,
        help="Method for reducing per-epoch sample scores into a single score. Built in reducers include 'mean', 'median', 'mode', 'max', and 'at_least_{n}'.",
        envvar="INSPECT_EVAL_EPOCHS_REDUCER",
    )
    @click.option(
        "--no-epochs-reducer",
        type=bool,
        is_flag=True,
        default=False,
        help="Do not reduce per-epoch sample scores.",
        envvar="INSPECT_EVAL_NO_EPOCHS_REDUCER",
    )
    @click.option(
        "--max-connections",
        type=int,
        help=MAX_CONNECTIONS_HELP,
        envvar="INSPECT_EVAL_MAX_CONNECTIONS",
    )
    @click.option(
        "--adaptive-connections",
        type=str,
        default=None,
        help=ADAPTIVE_CONNECTIONS_HELP,
        envvar="INSPECT_EVAL_ADAPTIVE_CONNECTIONS",
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
        "--attempt-timeout",
        type=int,
        help=ATTEMPT_TIMEOUT_HELP,
        envvar="INSPECT_EVAL_ATTEMPT_TIMEOUT",
    )
    @click.option(
        "--max-samples",
        type=int,
        help=MAX_SAMPLES_HELP,
        envvar="INSPECT_EVAL_MAX_SAMPLES",
    )
    @click.option(
        "--max-dataset-memory",
        type=click.IntRange(min=0),
        help="Maximum MB of dataset sample data to hold in memory per task. When exceeded, samples are paged to disk.",
        envvar="INSPECT_EVAL_MAX_DATASET_MEMORY",
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
        "--max-sandboxes",
        type=int,
        help=MAX_SANDBOXES_HELP,
        envvar="INSPECT_EVAL_MAX_SANDBOXES",
    )
    @click.option(
        "--message-limit",
        type=int,
        help="Limit on total messages used for each sample.",
        envvar="INSPECT_EVAL_MESSAGE_LIMIT",
    )
    @click.option(
        "--token-limit",
        type=str,
        callback=token_limit_flag_callback,
        help="Limit on tokens used for each sample (e.g. 500000, '500k', or '1m'; "
        "prefix with 'output:' to limit only output tokens, e.g. 'output:1m', or "
        "with a formula over 'input'/'output', e.g. '(input*0.1)+output:1m').",
        envvar="INSPECT_EVAL_TOKEN_LIMIT",
    )
    @click.option(
        "--turn-limit",
        type=int,
        help="Limit on total turns (model generations) used for each sample.",
        envvar="INSPECT_EVAL_TURN_LIMIT",
    )
    @click.option(
        "--cost-limit",
        type=float,
        help="Limit on total cost (in dollars) for each sample.",
        envvar="INSPECT_EVAL_COST_LIMIT",
    )
    @click.option(
        "--model-cost-config",
        type=str,
        help="YAML or JSON file with model prices for cost tracking.",
        envvar="INSPECT_EVAL_MODEL_COST_CONFIG",
    )
    @click.option(
        "--time-limit",
        type=int,
        help="Limit on total running time for each sample.",
        envvar="INSPECT_EVAL_TIME_LIMIT",
    )
    @click.option(
        "--working-limit",
        type=int,
        help="Limit on total working time (e.g. model generation, tool calls, etc.) for each sample.",
        envvar="INSPECT_EVAL_WORKING_LIMIT",
    )
    @click.option(
        "--fail-on-error",
        type=float,
        is_flag=False,
        flag_value=0.0,
        help=FAIL_ON_ERROR_HELP,
        envvar="INSPECT_EVAL_FAIL_ON_ERROR",
    )
    @click.option(
        "--no-fail-on-error",
        type=bool,
        is_flag=True,
        default=False,
        help=NO_FAIL_ON_ERROR_HELP,
        envvar="INSPECT_EVAL_NO_FAIL_ON_ERROR",
    )
    @click.option(
        "--continue-on-fail",
        type=bool,
        is_flag=True,
        default=None,
        help=CONTINUE_ON_FAIL_HELP,
        envvar="INSPECT_EVAL_CONTINUE_ON_FAIL",
    )
    @click.option(
        "--retry-on-error",
        is_flag=False,
        flag_value="true",
        default=None,
        callback=int_or_bool_flag_callback(DEFAULT_RETRY_ON_ERROR),
        help=RETRY_ON_ERROR_HELP,
        envvar="INSPECT_EVAL_RETRY_ON_ERROR",
    )
    @click.option(
        "--score-on-error",
        type=bool,
        is_flag=True,
        default=None,
        help=SCORE_ON_ERROR_HELP,
        envvar="INSPECT_EVAL_SCORE_ON_ERROR",
    )
    @click.option(
        "--no-log-samples",
        type=bool,
        is_flag=True,
        help=NO_LOG_SAMPLES_HELP,
        envvar="INSPECT_EVAL_NO_LOG_SAMPLES",
    )
    @click.option(
        "--no-log-realtime",
        type=bool,
        is_flag=True,
        help=NO_LOG_REALTIME_HELP,
        envvar="INSPECT_EVAL_NO_LOG_REALTIME",
    )
    @click.option(
        "--log-images/--no-log-images",
        type=bool,
        default=True,
        is_flag=True,
        help=LOG_IMAGES_HELP,
    )
    @click.option(
        "--log-model-api/--no-log-model-api",
        type=bool,
        default=None,
        is_flag=True,
        help=LOG_MODEL_API_HELP,
        envvar="INSPECT_EVAL_LOG_MODEL_API",
    )
    @click.option(
        "--log-refusals/--no-log-refusals",
        type=bool,
        default=False,
        is_flag=True,
        help=LOG_REFUSALS_HELP,
        envvar="INSPECT_EVAL_LOG_REFUSALS",
    )
    @click.option(
        "--log-buffer", type=int, help=LOG_BUFFER_HELP, envvar="INSPECT_EVAL_LOG_BUFFER"
    )
    @click.option(
        "--log-shared",
        is_flag=False,
        flag_value="true",
        default=None,
        callback=int_or_bool_flag_callback(DEFAULT_LOG_SHARED),
        help=LOG_SHARED_HELP,
        envvar=["INSPECT_LOG_SHARED", "INSPECT_EVAL_LOG_SHARED"],
    )
    @click.option(
        "--no-score",
        type=bool,
        is_flag=True,
        help=NO_SCORE_HELP,
        envvar="INSPECT_EVAL_NO_SCORE",
    )
    @click.option(
        "--no-score-display",
        type=bool,
        is_flag=True,
        help=NO_SCORE_DISPLAY,
        envvar="INSPECT_EVAL_SCORE_DISPLAY",
    )
    @click.option(
        "--generate-config",
        type=str,
        envvar="INSPECT_EVAL_GENERATE_CONFIG",
        help="YAML or JSON config file with GenerateConfig (alternatively, use the options for individual config values).",
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
        help="Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model's likelihood to repeat the same line verbatim. OpenAI, Google, Grok, Groq, llama-cpp-python and vLLM only.",
        envvar="INSPECT_EVAL_FREQUENCY_PENALTY",
    )
    @click.option(
        "--presence-penalty",
        type=float,
        help="Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model's likelihood to talk about new topics. OpenAI, Google, Grok, Groq, llama-cpp-python and vLLM only.",
        envvar="INSPECT_EVAL_PRESENCE_PENALTY",
    )
    @click.option(
        "--logit-bias",
        type=str,
        help='Map token Ids to an associated bias value from -100 to 100 (e.g. "42=10,43=-10"). OpenAI, Grok, and Grok only.',
        envvar="INSPECT_EVAL_LOGIT_BIAS",
    )
    @click.option(
        "--seed",
        type=int,
        help="Random seed. OpenAI, Google, Groq, Mistral, HuggingFace, and vLLM only.",
        envvar="INSPECT_EVAL_SEED",
    )
    @click.option(
        "--stop-seqs",
        type=str,
        help="Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence.",
        envvar="INSPECT_EVAL_STOP_SEQS",
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
        help="Randomly sample the next word from the top_k most likely next words. Anthropic, Google, HuggingFace, and vLLM only.",
        envvar="INSPECT_EVAL_TOP_K",
    )
    @click.option(
        "--num-choices",
        type=int,
        help="How many chat completion choices to generate for each input message. OpenAI, Grok, Google, TogetherAI, and vLLM only.",
        envvar="INSPECT_EVAL_NUM_CHOICES",
    )
    @click.option(
        "--logprobs",
        type=bool,
        is_flag=True,
        help="Return log probabilities of the output tokens. OpenAI, Google, TogetherAI, Huggingface, llama-cpp-python, and vLLM only.",
        envvar="INSPECT_EVAL_LOGPROBS",
    )
    @click.option(
        "--top-logprobs",
        type=int,
        help="Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI, Google, TogetherAI, Huggingface, and vLLM only.",
        envvar="INSPECT_EVAL_TOP_LOGPROBS",
    )
    @click.option(
        "--prompt-logprobs",
        type=int,
        help="Number of log probabilities to return per prompt token (1-20). vLLM only.",
        envvar="INSPECT_EVAL_PROMPT_LOGPROBS",
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
        "--internal-tools/--no-internal-tools",
        type=bool,
        is_flag=True,
        default=True,
        help="Whether to automatically map tools to model internal implementations (e.g. 'computer' for anthropic).",
        envvar="INSPECT_EVAL_INTERNAL_TOOLS",
    )
    @click.option(
        "--max-tool-output",
        type=int,
        help="Maximum size of tool output (in bytes). Defaults to 16 * 1024.",
        envvar="INSPECT_EVAL_MAX_TOOL_OUTPUT",
    )
    @click.option(
        "--cache-prompt",
        type=click.Choice(["auto", "true", "false"]),
        help="Whether to cache the prompt prefix. Enabled by default. Set to False to disable. Anthropic only.",
        envvar="INSPECT_EVAL_CACHE_PROMPT",
    )
    @click.option(
        "--fallback-models",
        type=str,
        help="Fallback models (comma-separated, tried in order) when the model's safety classifiers refuse the request. Anthropic Claude API only.",
        envvar="INSPECT_EVAL_FALLBACK_MODELS",
    )
    @click.option(
        "--verbosity",
        type=click.Choice(["low", "medium", "high"]),
        help='Constrains the verbosity of the model\'s response. Lower values will result in more concise responses, while higher values will result in more verbose responses. GPT 5.x models only (defaults to "medium" for OpenAI models)',
        envvar="INSPECT_EVAL_VERBOSITY",
    )
    @click.option(
        "--effort",
        type=click.Choice(["low", "medium", "high", "xhigh", "max"]),
        help="Control how many tokens are used for a response, trading off between response thoroughness and token efficiency. Claude 4.5, 4.6, 4.7 only (`max` only supported on 4.6+, `xhigh` only supported on 4.7).",
        envvar="INSPECT_EVAL_EFFORT",
    )
    @click.option(
        "--reasoning-effort",
        type=click.Choice(["none", "minimal", "low", "medium", "high", "xhigh", "max"]),
        help="Constrains effort on reasoning. Defaults vary by provider and model and not all models support all values (please consult provider documentation for details).",
        envvar="INSPECT_EVAL_REASONING_EFFORT",
    )
    @click.option(
        "--reasoning-mode",
        type=click.Choice(["standard", "pro"]),
        help='Reasoning mode. "pro" performs more model work for greater reliability on difficult tasks, at higher latency and token usage. OpenAI GPT-5.6+ models only ("standard" is the default).',
        envvar="INSPECT_EVAL_REASONING_MODE",
    )
    @click.option(
        "--reasoning-tokens",
        type=int,
        help="Maximum number of tokens to use for reasoning. Anthropic Claude models only.",
        envvar="INSPECT_EVAL_REASONING_TOKENS",
    )
    @click.option(
        "--reasoning-summary",
        type=click.Choice(["none", "concise", "detailed", "auto"]),
        help="Provide summary of reasoning steps (OpenAI reasoning models only). Use 'auto' to access the most detailed summarizer available for the current model (defaults to 'auto' if your organization is verified by OpenAI).",
        envvar="INSPECT_EVAL_REASONING_SUMMARY",
    )
    @click.option(
        "--reasoning-history",
        type=click.Choice(["none", "all", "last", "auto"]),
        help='Include reasoning in chat message history sent to generate (defaults to "auto", which uses the recommended default for each provider)',
        envvar="INSPECT_EVAL_REASONING_HISTORY",
    )
    @click.option(
        "--response-schema",
        type=str,
        help="JSON schema for desired response format (output should still be validated). OpenAI, Google, and Mistral only.",
        envvar="INSPECT_EVAL_RESPONSE_SCHEMA",
    )
    @click.option(
        "--cache",
        is_flag=False,
        flag_value="true",
        default=None,
        callback=int_bool_or_str_flag_callback(DEFAULT_CACHE_DAYS, None),
        help=CACHE_HELP,
        envvar="INSPECT_EVAL_CACHE",
    )
    @click.option(
        "--batch",
        is_flag=False,
        flag_value="true",
        default=None,
        callback=int_bool_or_str_flag_callback(DEFAULT_BATCH_SIZE, None),
        help=BATCH_HELP,
        envvar="INSPECT_EVAL_BATCH",
    )
    @click.option(
        "--modalities",
        type=str,
        help="Additional output modalities beyond text (e.g. 'image'). Comma-separated names or a YAML/JSON config file path. OpenAI and Google only.",
        envvar="INSPECT_EVAL_MODALITIES",
    )
    @click.option(
        "--log-format",
        type=click.Choice(["eval", "json"], case_sensitive=False),
        envvar=["INSPECT_LOG_FORMAT", "INSPECT_EVAL_LOG_FORMAT"],
        help="Format for writing log files.",
    )
    @click.option(
        "--log-level-transcript",
        type=click.Choice(
            [level.lower() for level in ALL_LOG_LEVELS],
            case_sensitive=False,
        ),
        default=DEFAULT_LOG_LEVEL_TRANSCRIPT,
        envvar="INSPECT_LOG_LEVEL_TRANSCRIPT",
        help=f"Set the log level of the transcript (defaults to '{DEFAULT_LOG_LEVEL_TRANSCRIPT}')",
    )
    @common_options
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> click.Context:
        return cast(click.Context, func(*args, **kwargs))

    return wrapper


@click.command("eval", cls=EvalCommand)
@click.argument("tasks", nargs=-1)
@click.option(
    "--json",
    "json_output",
    type=bool,
    is_flag=True,
    default=False,
    envvar="INSPECT_EVAL_JSON",
    help="Emit machine-readable launch output as JSON lines on stdout (implies --display none): a 'launch' record printed once the control-channel server is bound — reporting run_id, pid, log_dir, and the control socket path ('control' is null when the server is disabled or failed to bind, so its presence guarantees `inspect ctl` is usable) — and a 'done' record with each task's log location and status when the eval finishes. To launch in the background instead, use --detach (which implies --json).",
)
@click.option(
    "--detach",
    type=bool,
    is_flag=True,
    default=False,
    envvar="INSPECT_EVAL_DETACH",
    help=DETACH_HELP,
)
@eval_options
@click.pass_context
def eval_command(ctx: click.Context, /, **params: Any) -> None:
    """Evaluate tasks."""
    with _json_prerequisite_errors_to_stderr(params["json_output"] or params["detach"]):
        if params.pop("detach"):
            exec_detached(ctl_server=params["ctl_server"])
        # When --run-config is used, env-sourced CLI values (INSPECT_EVAL_*)
        # defer to the run config _for fields the run config actually
        # provides_. Env values still apply to fields the run config leaves
        # unset. Common-options env vars (INSPECT_LOG_LEVEL, INSPECT_LOG_DIR,
        # ...) are never cleared — they describe how the run is
        # logged/displayed, not what is run.
        if params.get("run_config"):
            from click.core import ParameterSource

            run_params = parse_run_config(params["run_config"])

            # Map Click parameter name -> the cli_params key it ultimately
            # produces in eval_exec. Most are identity; these are the
            # exceptions.
            click_to_cli_key = {
                "m": "model_args",
                "t": "task_args",
                "model_role": "model_roles",
                "no_sandbox_cleanup": "sandbox_cleanup",
                "s": "solver",
                "solver_config": "solver",
            }

            for param in ctx.command.params:
                name = param.name
                if name is None or name == "run_config":
                    continue
                envvar = getattr(param, "envvar", None)
                if not (isinstance(envvar, str) and envvar.startswith("INSPECT_EVAL_")):
                    continue
                if ctx.get_parameter_source(name) != ParameterSource.ENVIRONMENT:
                    continue
                cli_key = click_to_cli_key.get(name, name)
                if cli_key not in run_params:
                    continue
                value = params.get(name)
                params[name] = () if isinstance(value, tuple) else None

        _eval_command_impl(**params)


@contextlib.contextmanager
def _json_prerequisite_errors_to_stderr(json_output: bool) -> Iterator[None]:
    """Re-render ``PrerequisiteError``s to stderr when ``--json`` owns stdout.

    ``--json`` promises that stdout carries only JSON records, and the
    default ``PrerequisiteError`` handling breaks that twice over: the
    excepthook renders the message through the global rich console, which
    writes to *stdout* for failures raised before the display initializes
    (``parse_run_config``, the config conflict checks in ``eval_exec``,
    ...) and is reconfigured to quiet once ``display="none"`` takes
    effect inside ``eval()`` — silently dropping the diagnostic for
    every common launch failure (bad task path, missing API key, ...).
    So under ``--json`` print the message to stderr (builtin ``print``,
    matching the excepthook — a rich ``Console`` would interpret
    bracketed text in messages as markup and hard-wrap long paths) and
    exit non-zero via ``SilentException``. This wraps the whole command
    so pre-flight failures on either side of ``eval()`` behave
    identically. A no-op (errors propagate unchanged) without ``--json``.
    """
    try:
        yield
    except PrerequisiteError as ex:
        if not json_output:
            raise
        # flush: nothing else will — the process exits via the exception,
        # and captured/piped stderr is block-buffered
        print(f"\n{ex.message}\n", file=sys.stderr, flush=True)
        raise SilentException() from ex


def _eval_command_impl(
    tasks: tuple[str, ...] | None,
    solver: str | None,
    model: str | None,
    model_base_url: str | None,
    m: tuple[str, ...] | None,
    model_config: str | None,
    run_config: str | None,
    model_role: tuple[str, ...] | None,
    t: tuple[str, ...] | None,
    task_config: str | None,
    s: tuple[str, ...] | None,
    solver_config: str | None,
    scanner: str | None,
    scanner_arg: tuple[str, ...] | None,
    scans: str | None,
    scan_name: str | None,
    scan_tags: str | None,
    scan_metadata: tuple[str, ...] | None,
    scan_filter: tuple[str, ...] | None,
    scan_model: str | None,
    scan_model_base_url: str | None,
    scan_model_arg: tuple[str, ...] | None,
    scan_model_config: str | None,
    scan_model_role: tuple[str, ...] | None,
    scan_generate_config: str | None,
    tags: str | None,
    metadata: tuple[str, ...] | None,
    trace: bool | None,
    approval: str | None,
    notification: bool | str | None,
    sandbox: str | None,
    no_sandbox_cleanup: bool | None,
    checkpoint: str | None,
    acp_server: bool | int | str | None,
    ctl_server: bool | str | None,
    epochs: int | None,
    epochs_reducer: str | None,
    no_epochs_reducer: bool | None,
    limit: str | None,
    sample_id: str | None,
    sample_shuffle: int | None,
    generate_config: str | None,
    max_retries: int | None,
    timeout: int | None,
    attempt_timeout: int | None,
    max_connections: int | None,
    adaptive_connections: str | None,
    max_tokens: int | None,
    system_message: str | None,
    best_of: int | None,
    frequency_penalty: float | None,
    presence_penalty: float | None,
    logit_bias: str | None,
    seed: int | None,
    stop_seqs: str | None,
    temperature: float | None,
    top_p: float | None,
    top_k: int | None,
    num_choices: int | None,
    logprobs: bool | None,
    top_logprobs: int | None,
    prompt_logprobs: int | None,
    parallel_tool_calls: bool | None,
    internal_tools: bool | None,
    max_tool_output: int | None,
    cache_prompt: str | None,
    fallback_models: str | None,
    verbosity: Literal["low", "medium", "high"] | None,
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None,
    reasoning_effort: str | None,
    reasoning_mode: Literal["standard", "pro"] | None,
    reasoning_tokens: int | None,
    reasoning_summary: Literal["none", "concise", "detailed", "auto"] | None,
    reasoning_history: Literal["none", "all", "last", "auto"] | None,
    response_schema: ResponseSchema | None,
    cache: int | str | None,
    batch: int | str | None,
    modalities: str | None,
    message_limit: int | None,
    token_limit: int | TokenLimit | None,
    turn_limit: int | None,
    time_limit: int | None,
    working_limit: int | None,
    cost_limit: float | None,
    model_cost_config: str | None,
    max_samples: int | None,
    max_dataset_memory: int | None,
    max_tasks: int | None,
    max_subprocesses: int | None,
    max_sandboxes: int | None,
    fail_on_error: bool | float | None,
    no_fail_on_error: bool | None,
    continue_on_fail: bool | None,
    retry_on_error: int | None,
    score_on_error: bool | None,
    no_log_samples: bool | None,
    no_log_realtime: bool | None,
    log_images: bool | None,
    log_model_api: bool | None,
    log_refusals: bool | None,
    log_buffer: int | None,
    log_shared: int | None,
    no_score: bool | None,
    no_score_display: bool | None,
    log_format: Literal["eval", "json"] | None,
    log_level_transcript: str,
    json_output: bool,
    **common: Unpack[CommonOptions],
) -> None:
    # read config
    config = config_from_locals(dict(locals()))

    # --json owns stdout (JSON lines only), so route the display to the
    # quiet "none" renderer — including when --no-ansi would otherwise
    # promote it back to "rich" or --trace (/INSPECT_EVAL_TRACE) would
    # promote it to "conversation", which writes panels to stdout
    if json_output:
        common["display"] = "none"
        common["no_ansi"] = None
        trace = None

    # resolve common options
    process_common_options(common)

    # exec eval
    eval_exec(
        tasks=tasks,
        solver=solver,
        log_level=common["log_level"],
        log_level_transcript=log_level_transcript,
        log_dir=common["log_dir"],
        log_format=log_format,
        model=model,
        model_base_url=model_base_url,
        m=m,
        model_config=model_config,
        run_config=run_config,
        model_role=model_role,
        t=t,
        task_config=task_config,
        s=s,
        solver_config=solver_config,
        scanner=scanner,
        scanner_arg=scanner_arg,
        scans=scans,
        scan_name=scan_name,
        scan_tags=scan_tags,
        scan_metadata=scan_metadata,
        scan_filter=scan_filter,
        scan_model=scan_model,
        scan_model_base_url=scan_model_base_url,
        scan_model_arg=scan_model_arg,
        scan_model_config=scan_model_config,
        scan_model_role=scan_model_role,
        scan_generate_config=scan_generate_config,
        tags=tags,
        metadata=metadata,
        trace=trace,
        approval=approval,
        notification=notification,
        sandbox=sandbox,
        no_sandbox_cleanup=no_sandbox_cleanup,
        checkpoint=checkpoint,
        epochs=epochs,
        epochs_reducer=epochs_reducer,
        no_epochs_reducer=no_epochs_reducer,
        limit=limit,
        sample_id=sample_id,
        sample_shuffle=sample_shuffle,
        message_limit=message_limit,
        token_limit=token_limit,
        turn_limit=turn_limit,
        time_limit=time_limit,
        working_limit=working_limit,
        cost_limit=cost_limit,
        model_cost_config=model_cost_config,
        max_samples=max_samples,
        max_dataset_memory=max_dataset_memory,
        max_tasks=max_tasks,
        max_subprocesses=max_subprocesses,
        max_sandboxes=max_sandboxes,
        fail_on_error=fail_on_error,
        no_fail_on_error=no_fail_on_error,
        continue_on_fail=continue_on_fail,
        retry_on_error=retry_on_error,
        score_on_error=score_on_error,
        debug_errors=common["debug_errors"],
        no_log_samples=no_log_samples,
        no_log_realtime=no_log_realtime,
        log_images=log_images,
        log_model_api=log_model_api,
        log_refusals=log_refusals,
        log_buffer=log_buffer,
        log_shared=log_shared,
        no_score=no_score,
        no_score_display=no_score_display,
        acp_server=acp_server,
        ctl_server=ctl_server,
        is_eval_set=False,
        json_output=json_output,
        **config,
    )


@click.command("eval-set", cls=EvalCommand)
@click.argument("tasks", nargs=-1)
@click.option(
    "--json",
    "json_output",
    type=bool,
    is_flag=True,
    default=False,
    envvar="INSPECT_EVAL_JSON",
    help="Emit machine-readable launch output as JSON lines on stdout (implies --display none): a 'launch' record printed once the control-channel server is bound — reporting run_id, eval_set_id, pid, log_dir, and the control socket path ('control' is null when the server is disabled or failed to bind, so its presence guarantees `inspect ctl` is usable) — and a 'done' record with overall success and each task's log location and status when the eval set finishes (the exit code still reports success as usual). When every task is already complete no eval runs, so stdout carries only the 'done' record (except under --ctl-server=keep, whose park still binds a control endpoint and emits a 'launch' record with run_id null); with --no-retry-immediate each batch retry binds afresh and emits a fresh 'launch' record, and the 'done' record carries the last launch's run_id. To launch in the background instead, use --detach (which implies --json).",
)
@click.option(
    "--detach",
    type=bool,
    is_flag=True,
    default=False,
    envvar="INSPECT_EVAL_DETACH",
    help=DETACH_HELP,
)
@click.option(
    "--retry-attempts",
    type=int,
    help="Maximum number of retry attempts before giving up (defaults to 10).",
    envvar="INSPECT_EVAL_RETRY_ATTEMPS",
)
@click.option(
    "--retry-immediate/--no-retry-immediate",
    type=bool,
    default=None,
    help="Immediately retry tasks as they fail without waiting for all tasks to complete (the default). Pass --no-retry-immediate for the legacy behavior of waiting for all tasks to complete before retrying. When --retry-immediate is in effect, --retry-wait and --retry-connections are ignored.",
    envvar="INSPECT_EVAL_RETRY_IMMEDIATE",
)
@click.option(
    "--retry-wait",
    type=int,
    help="Time in seconds wait between attempts, increased exponentially. "
    + "(defaults to 30, resulting in waits of 30, 60, 120, 240, etc.). Wait time "
    + "per-retry will in no case by longer than 1 hour. "
    + "Only applies when --no-retry-immediate is set; otherwise ignored.",
    envvar="INSPECT_EVAL_RETRY_WAIT",
)
@click.option(
    "--retry-connections",
    type=float,
    help="Reduce max_connections at this rate with each retry (defaults to 1.0, which results in no reduction). Only applies when --no-retry-immediate is set; otherwise ignored.",
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
@click.option(
    "--embed-viewer",
    type=bool,
    is_flag=True,
    help="Embed a log viewer into the log directory.",
)
@click.option(
    "--log-dir-allow-dirty",
    type=bool,
    is_flag=True,
    help="Do not fail if the log-dir contains files that are not part of the eval set.",
)
@click.option(
    "--id",
    "eval_set_id",
    type=str,
    help="ID for the eval set. If not specified, a unique ID will be generated.",
)
@eval_options
@click.pass_context
def eval_set_command(
    ctx: click.Context,
    tasks: tuple[str, ...] | None,
    retry_attempts: int | None,
    retry_immediate: bool | None,
    retry_wait: int | None,
    retry_connections: float | None,
    no_retry_cleanup: bool | None,
    solver: str | None,
    trace: bool | None,
    approval: str | None,
    notification: bool | str | None,
    model: str | None,
    model_base_url: str | None,
    m: tuple[str, ...] | None,
    model_config: str | None,
    run_config: str | None,
    model_role: tuple[str, ...] | None,
    t: tuple[str, ...] | None,
    task_config: str | None,
    s: tuple[str, ...] | None,
    solver_config: str | None,
    scanner: str | None,
    scanner_arg: tuple[str, ...] | None,
    scans: str | None,
    scan_name: str | None,
    scan_tags: str | None,
    scan_metadata: tuple[str, ...] | None,
    scan_filter: tuple[str, ...] | None,
    scan_model: str | None,
    scan_model_base_url: str | None,
    scan_model_arg: tuple[str, ...] | None,
    scan_model_config: str | None,
    scan_model_role: tuple[str, ...] | None,
    scan_generate_config: str | None,
    tags: str | None,
    metadata: tuple[str, ...] | None,
    sandbox: str | None,
    no_sandbox_cleanup: bool | None,
    checkpoint: str | None,
    acp_server: bool | int | str | None,
    ctl_server: bool | str | None,
    epochs: int | None,
    epochs_reducer: str | None,
    no_epochs_reducer: bool | None,
    limit: str | None,
    sample_id: str | None,
    sample_shuffle: int | None,
    generate_config: str | None,
    max_retries: int | None,
    timeout: int | None,
    attempt_timeout: int | None,
    max_connections: int | None,
    adaptive_connections: str | None,
    max_tokens: int | None,
    system_message: str | None,
    best_of: int | None,
    frequency_penalty: float | None,
    presence_penalty: float | None,
    logit_bias: str | None,
    seed: int | None,
    stop_seqs: str | None,
    temperature: float | None,
    top_p: float | None,
    top_k: int | None,
    num_choices: int | None,
    logprobs: bool | None,
    top_logprobs: int | None,
    prompt_logprobs: int | None,
    parallel_tool_calls: bool | None,
    internal_tools: bool | None,
    max_tool_output: int | None,
    cache_prompt: str | None,
    fallback_models: str | None,
    verbosity: Literal["low", "medium", "high"] | None,
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None,
    reasoning_effort: str | None,
    reasoning_mode: Literal["standard", "pro"] | None,
    reasoning_tokens: int | None,
    reasoning_summary: Literal["none", "concise", "detailed", "auto"] | None,
    reasoning_history: Literal["none", "all", "last", "auto"] | None,
    response_schema: ResponseSchema | None,
    cache: int | str | None,
    batch: int | str | None,
    modalities: str | None,
    message_limit: int | None,
    token_limit: int | TokenLimit | None,
    turn_limit: int | None,
    time_limit: int | None,
    working_limit: int | None,
    cost_limit: float | None,
    model_cost_config: str | None,
    max_samples: int | None,
    max_dataset_memory: int | None,
    max_tasks: int | None,
    max_subprocesses: int | None,
    max_sandboxes: int | None,
    fail_on_error: bool | float | None,
    no_fail_on_error: bool | None,
    continue_on_fail: bool | None,
    retry_on_error: int | None,
    score_on_error: bool | None,
    no_log_samples: bool | None,
    no_log_realtime: bool | None,
    log_images: bool | None,
    log_model_api: bool | None,
    log_refusals: bool | None,
    log_buffer: int | None,
    log_shared: int | None,
    no_score: bool | None,
    no_score_display: bool | None,
    bundle_dir: str | None,
    bundle_overwrite: bool | None,
    embed_viewer: bool | None,
    log_dir_allow_dirty: bool | None,
    log_format: Literal["eval", "json"] | None,
    log_level_transcript: str,
    eval_set_id: str | None,
    json_output: bool,
    detach: bool,
    **common: Unpack[CommonOptions],
) -> int:
    """Evaluate a set of tasks with retries.

    Learn more about eval sets at https://inspect.aisi.org.uk/eval-sets.html.
    """
    with _json_prerequisite_errors_to_stderr(json_output or detach):
        if detach:
            exec_detached(ctl_server=ctl_server)

        # read config
        config = config_from_locals(dict(locals()))

        # --json owns stdout (JSON lines only), so route the display to the
        # quiet "none" renderer — including when --no-ansi would otherwise
        # promote it back to "rich" or --trace (/INSPECT_EVAL_TRACE) would
        # promote it to "conversation", which writes panels to stdout
        if json_output:
            common["display"] = "none"
            common["no_ansi"] = None
            trace = None

        # resolve common options
        process_common_options(common)

        # exec eval
        success = eval_exec(
            tasks=tasks,
            solver=solver,
            log_level=common["log_level"],
            log_level_transcript=log_level_transcript,
            log_dir=common["log_dir"],
            log_format=log_format,
            model=model,
            model_base_url=model_base_url,
            m=m,
            model_config=model_config,
            run_config=run_config,
            model_role=model_role,
            t=t,
            task_config=task_config,
            s=s,
            solver_config=solver_config,
            scanner=scanner,
            scanner_arg=scanner_arg,
            scans=scans,
            scan_name=scan_name,
            scan_tags=scan_tags,
            scan_metadata=scan_metadata,
            scan_filter=scan_filter,
            scan_model=scan_model,
            scan_model_base_url=scan_model_base_url,
            scan_model_arg=scan_model_arg,
            scan_model_config=scan_model_config,
            scan_model_role=scan_model_role,
            scan_generate_config=scan_generate_config,
            tags=tags,
            metadata=metadata,
            trace=trace,
            approval=approval,
            notification=notification,
            sandbox=sandbox,
            no_sandbox_cleanup=no_sandbox_cleanup,
            checkpoint=checkpoint,
            epochs=epochs,
            epochs_reducer=epochs_reducer,
            no_epochs_reducer=no_epochs_reducer,
            limit=limit,
            sample_id=sample_id,
            sample_shuffle=sample_shuffle,
            message_limit=message_limit,
            token_limit=token_limit,
            turn_limit=turn_limit,
            cost_limit=cost_limit,
            model_cost_config=model_cost_config,
            time_limit=time_limit,
            working_limit=working_limit,
            max_samples=max_samples,
            max_dataset_memory=max_dataset_memory,
            max_tasks=max_tasks,
            max_subprocesses=max_subprocesses,
            max_sandboxes=max_sandboxes,
            fail_on_error=fail_on_error,
            no_fail_on_error=no_fail_on_error,
            continue_on_fail=continue_on_fail,
            retry_on_error=retry_on_error,
            score_on_error=score_on_error,
            debug_errors=common["debug_errors"],
            no_log_samples=no_log_samples,
            no_log_realtime=no_log_realtime,
            log_images=log_images,
            log_model_api=log_model_api,
            log_refusals=log_refusals,
            log_buffer=log_buffer,
            log_shared=log_shared,
            no_score=no_score,
            no_score_display=no_score_display,
            acp_server=acp_server,
            ctl_server=ctl_server,
            is_eval_set=True,
            retry_attempts=retry_attempts,
            retry_immediate=retry_immediate,
            retry_wait=retry_wait,
            retry_connections=retry_connections,
            retry_cleanup=not no_retry_cleanup,
            bundle_dir=bundle_dir,
            bundle_overwrite=True if bundle_overwrite else False,
            embed_viewer=True if embed_viewer else False,
            log_dir_allow_dirty=log_dir_allow_dirty,
            eval_set_id=eval_set_id,
            json_output=json_output,
            **config,
        )

    # exit code indicating whether the evals are all complete
    ctx.exit(0 if success else 1)


class TaskInput(BaseModel):
    task: str
    args: dict[str, Any] = Field(default_factory=dict)


class SolverInput(BaseModel):
    solver: str
    args: dict[str, Any] = Field(default_factory=dict)


class RunConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str | TaskInput | None = None
    model: str | ModelConfig | None = None
    model_roles: dict[str, ModelConfig] = Field(default_factory=dict)
    generate_config: GenerateConfig = Field(default_factory=GenerateConfig)
    eval_config: EvalConfig = Field(default_factory=EvalConfig)
    solver: str | SolverInput | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    sandbox: str | SandboxEnvironmentSpec | None = None

    @field_validator("generate_config", mode="before")
    @classmethod
    def check_generate_config_fields(cls, v: Any) -> Any:
        if isinstance(v, dict):
            unknown = set(v.keys()) - set(GenerateConfig.model_fields.keys())
            if unknown:
                raise ValueError(f"Unknown generate_config fields: {unknown}")
        return v

    @field_validator("eval_config", mode="before")
    @classmethod
    def check_eval_config_fields(cls, v: Any) -> Any:
        if isinstance(v, dict):
            unknown = set(v.keys()) - set(EvalConfig.model_fields.keys())
            if unknown:
                raise ValueError(f"Unknown eval_config fields: {unknown}")
        return v

    def to_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {}

        # Task
        if self.task is not None:
            if isinstance(self.task, str):
                params["tasks"] = self.task
            else:
                params["tasks"] = self.task.task
                if self.task.args:
                    params["task_args"] = self.task.args

        # Model
        if self.model is not None:
            if isinstance(self.model, str):
                params["model"] = self.model
            else:
                params["model"] = self.model.model
                if self.model.base_url is not None:
                    params["model_base_url"] = self.model.base_url
                if self.model.args:
                    params["model_args"] = self.model.args
                model_gc = self.model.config.model_dump(exclude_none=True)
                if model_gc:
                    params.update(model_gc)

        # Top-level generate_config overrides any model-level config
        top_gc = self.generate_config.model_dump(exclude_none=True)
        if top_gc:
            params.update(top_gc)

        # Model roles
        if self.model_roles:
            params["model_roles"] = {
                role: get_model(
                    mc.model, config=mc.config, base_url=mc.base_url, **mc.args
                )
                for role, mc in self.model_roles.items()
            }

        # Solver
        if self.solver is not None:
            if isinstance(self.solver, str):
                params["solver"] = SolverSpec(self.solver, {}, {})
            else:
                params["solver"] = SolverSpec(
                    self.solver.solver, self.solver.args, self.solver.args
                )

        # Eval config — combine epochs + epochs_reducer into Epochs
        ec = self.eval_config.model_dump(exclude_none=True)
        epochs = ec.pop("epochs", None)
        epochs_reducer = ec.pop("epochs_reducer", None)
        if epochs is not None:
            ec["epochs"] = Epochs(epochs, create_reducers(epochs_reducer))
        params.update(ec)

        # Tags and metadata
        if self.tags:
            params["tags"] = self.tags
        if self.metadata:
            params["metadata"] = self.metadata

        # Sandbox
        if self.sandbox is not None:
            if isinstance(self.sandbox, str):
                params["sandbox"] = parse_sandbox(self.sandbox)
            else:
                params["sandbox"] = self.sandbox

        return params


def parse_run_config(config: str) -> dict[str, Any]:
    from jsonschema import Draft7Validator

    config_dict = resolve_args(config)
    try:
        run_config = RunConfigInput.model_validate(config_dict)
    except ValidationError as ex:
        # Surface a more readable error via Draft7Validator. Fall back to
        # pydantic's message when the JSON schema doesn't capture the
        # failure (e.g. custom field_validators on generate_config/eval_config).
        schema = RunConfigInput.model_json_schema()
        errors = list(Draft7Validator(schema).iter_errors(config_dict))
        if errors:
            message = "\n".join(
                [f"Invalid run config '{config}':"]
                + [f" - {error.message}" for error in errors]
            )
        else:
            message = f"Invalid run config '{config}': {ex}"
        raise PrerequisiteError(message)
    return run_config.to_params()


def merge_run_config_params(
    run_params: dict[str, Any], cli_params: dict[str, Any]
) -> dict[str, Any]:
    params = dict(run_params)
    for key, value in cli_params.items():
        if value is None or value == {}:
            continue
        if key == "score" and value is True:
            continue
        if key in ("task_args", "model_args") and key in params:
            params[key] = params[key] | value
        elif key == "model_roles" and key in params:
            params[key] = params[key] | value
        else:
            params[key] = value
    return params


def eval_exec(
    tasks: tuple[str, ...] | None,
    solver: str | None,
    log_level: str,
    log_level_transcript: str,
    log_dir: str,
    log_format: Literal["eval", "json"] | None,
    model: str | None,
    model_base_url: str | None,
    m: tuple[str, ...] | None,
    model_config: str | None,
    run_config: str | None,
    model_role: tuple[str, ...] | None,
    t: tuple[str, ...] | None,
    task_config: str | None,
    s: tuple[str, ...] | None,
    solver_config: str | None,
    scanner: str | None,
    scanner_arg: tuple[str, ...] | None,
    scans: str | None,
    scan_name: str | None,
    scan_tags: str | None,
    scan_metadata: tuple[str, ...] | None,
    scan_filter: tuple[str, ...] | None,
    scan_model: str | None,
    scan_model_base_url: str | None,
    scan_model_arg: tuple[str, ...] | None,
    scan_model_config: str | None,
    scan_model_role: tuple[str, ...] | None,
    scan_generate_config: str | None,
    tags: str | None,
    metadata: tuple[str, ...] | None,
    trace: bool | None,
    approval: str | None,
    notification: bool | str | None,
    sandbox: str | None,
    no_sandbox_cleanup: bool | None,
    checkpoint: str | None,
    acp_server: bool | int | str | None,
    ctl_server: bool | str | None,
    epochs: int | None,
    epochs_reducer: str | None,
    no_epochs_reducer: bool | None,
    limit: str | None,
    sample_id: str | None,
    sample_shuffle: int | None,
    message_limit: int | None,
    token_limit: int | TokenLimit | None,
    turn_limit: int | None,
    time_limit: int | None,
    working_limit: int | None,
    cost_limit: float | None,
    model_cost_config: str | None,
    max_samples: int | None,
    max_dataset_memory: int | None,
    max_tasks: int | None,
    max_subprocesses: int | None,
    max_sandboxes: int | None,
    fail_on_error: bool | float | None,
    no_fail_on_error: bool | None,
    continue_on_fail: bool | None,
    retry_on_error: int | None,
    score_on_error: bool | None,
    debug_errors: bool | None,
    no_log_samples: bool | None,
    no_log_realtime: bool | None,
    log_images: bool | None,
    log_model_api: bool | None,
    log_refusals: bool | None,
    log_buffer: int | None,
    log_shared: int | None,
    no_score: bool | None,
    no_score_display: bool | None,
    is_eval_set: bool = False,
    json_output: bool = False,
    retry_attempts: int | None = None,
    retry_immediate: bool | None = None,
    retry_wait: int | None = None,
    retry_connections: float | None = None,
    retry_cleanup: bool | None = None,
    bundle_dir: str | None = None,
    bundle_overwrite: bool = False,
    embed_viewer: bool = False,
    log_dir_allow_dirty: bool | None = None,
    eval_set_id: str | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> bool:
    if run_config and is_eval_set:
        raise PrerequisiteError("--run-config is only supported by inspect eval.")
    if run_config and task_config:
        raise PrerequisiteError("--run-config cannot be used with --task-config.")
    if run_config and solver_config:
        raise PrerequisiteError("--run-config cannot be used with --solver-config.")

    run_params = parse_run_config(run_config) if run_config else {}

    # parse task, solver, and model args
    task_args = parse_cli_config(t, task_config)
    solver_args = parse_cli_config(s, solver_config)
    model_args = parse_cli_config(m, model_config)

    # resolve scanner spec
    from inspect_ai._display.core.results import set_retry_args_suffix

    from ._scanner import resolve_cli_scanner, serialize_scanner_cli_args

    eval_scanner = resolve_cli_scanner(
        scanner,
        scanner_arg,
        scans=scans,
        scan_name=scan_name,
        scan_tags=scan_tags,
        scan_metadata=scan_metadata,
        scan_filter=scan_filter,
        scan_model=scan_model,
        scan_model_base_url=scan_model_base_url,
        scan_model_arg=scan_model_arg,
        scan_model_config=scan_model_config,
        scan_model_role=scan_model_role,
        scan_generate_config=scan_generate_config,
    )

    # preserve scanner flags on the suggested `eval-retry` command shown
    # if a task interrupts — so a copy-paste resumes against the same
    # scan dir with the same scanner config
    set_retry_args_suffix(
        serialize_scanner_cli_args(
            scanner,
            scanner_arg,
            scans=scans,
            scan_name=scan_name,
            scan_tags=scan_tags,
            scan_metadata=scan_metadata,
            scan_filter=scan_filter,
            scan_model=scan_model,
            scan_model_base_url=scan_model_base_url,
            scan_model_arg=scan_model_arg,
            scan_model_config=scan_model_config,
            scan_model_role=scan_model_role,
            scan_generate_config=scan_generate_config,
        )
    )

    # parse model roles
    eval_model_roles = parse_model_role_cli_args(model_role)

    # parse tags
    eval_tags = parse_comma_separated(tags)

    # parse metadata
    eval_metadata = parse_cli_args(metadata)

    # resolve epochs
    eval_epochs = (
        Epochs(
            epochs,
            []
            if no_epochs_reducer
            else create_reducers(parse_comma_separated(epochs_reducer)),
        )
        if epochs
        else None
    )

    # resolve range and sample id
    eval_limit = parse_samples_limit(limit)
    eval_sample_id = parse_sample_id(sample_id)

    # resolve sample_shuffle
    if sample_shuffle == -1:
        eval_sample_shuffle: Literal[True] | int | None = True
    elif sample_shuffle == 0:
        eval_sample_shuffle = None
    else:
        eval_sample_shuffle = sample_shuffle

    # resolve fail_on_error
    if no_fail_on_error is True:
        fail_on_error = False
    elif fail_on_error == 0.0:
        fail_on_error = True

    # resolve retry_on_error
    if retry_on_error == 0:
        retry_on_error = None

    # resolve negating options
    sandbox_cleanup = False if no_sandbox_cleanup else None
    log_samples = False if no_log_samples else None
    log_realtime = False if no_log_realtime else None
    log_images = False if log_images is False else None
    trace = True if trace else None
    score = False if no_score else True
    score_display = False if no_score_display else None

    # build params
    cli_params: dict[str, Any] = (
        dict(
            tasks=list(tasks) if tasks else None,
            model=model,
            model_base_url=model_base_url,
            model_args=model_args,
            model_roles=eval_model_roles,
            task_args=task_args,
            solver=SolverSpec(solver, solver_args, solver_args) if solver else None,
            scanner=eval_scanner,
            tags=eval_tags,
            metadata=eval_metadata,
            trace=trace,
            approval=approval,
            notification=notification,
            sandbox=parse_sandbox(sandbox),
            sandbox_cleanup=sandbox_cleanup,
            checkpoint=parse_checkpoint(checkpoint),
            log_level=log_level,
            log_level_transcript=log_level_transcript,
            log_dir=log_dir,
            log_format=log_format,
            limit=eval_limit,
            sample_id=eval_sample_id,
            sample_shuffle=eval_sample_shuffle,
            epochs=eval_epochs,
            fail_on_error=fail_on_error,
            continue_on_fail=continue_on_fail,
            retry_on_error=retry_on_error,
            score_on_error=score_on_error,
            debug_errors=debug_errors,
            message_limit=message_limit,
            token_limit=token_limit,
            turn_limit=turn_limit,
            time_limit=time_limit,
            working_limit=working_limit,
            cost_limit=cost_limit,
            model_cost_config=model_cost_config,
            max_samples=max_samples,
            max_dataset_memory=max_dataset_memory,
            max_tasks=max_tasks,
            max_subprocesses=max_subprocesses,
            max_sandboxes=max_sandboxes,
            log_samples=log_samples,
            log_realtime=log_realtime,
            log_images=log_images,
            log_model_api=log_model_api,
            log_refusals=log_refusals,
            log_buffer=log_buffer,
            log_shared=log_shared,
            score=score,
            score_display=score_display,
            acp_server=acp_server,
            ctl_server=ctl_server,
        )
        | kwargs
    )
    params = (
        merge_run_config_params(run_params, cli_params) if run_params else cli_params
    )

    # evaluate
    if is_eval_set:
        params["retry_attempts"] = retry_attempts
        params["retry_immediate"] = retry_immediate
        params["retry_wait"] = retry_wait
        params["retry_connections"] = retry_connections
        params["retry_cleanup"] = retry_cleanup
        params["bundle_dir"] = bundle_dir
        params["bundle_overwrite"] = bundle_overwrite
        params["embed_viewer"] = embed_viewer
        params["log_dir_allow_dirty"] = log_dir_allow_dirty
        params["eval_set_id"] = eval_set_id
        if json_output:
            return _eval_exec_json(lambda: eval_set(**params), is_eval_set=True)
        success, _ = eval_set(**params)
        return success
    else:
        params["log_header_only"] = True  # cli invocation doesn't need full log
        if json_output:
            _eval_exec_json(lambda: (True, eval(**params)))
        else:
            eval(**params)
        return True


def _eval_exec_json(
    run: Callable[[], tuple[bool, list[EvalLog]]], is_eval_set: bool = False
) -> bool:
    """Run an eval (via ``run``) emitting the agent-facing JSON lines on stdout.

    ``run`` executes the eval — ``eval()``, ``eval_set()``, or
    ``eval_retry()`` — and returns overall success plus the resulting
    logs (``eval()`` and ``eval_retry()`` report ``True`` like their
    exit codes: per-task outcomes live in the ``logs`` statuses).

    Two records, one per line (documented in the ``--json`` option help):

    - ``launch`` — printed by the launch-handoff listener the moment the
      control surface is bound (or definitively absent), before any task
      work begins. This is the synchronous launch handoff: an agent that
      has read this line can trust ``inspect ctl`` immediately — an empty
      task list means "no tasks registered yet", never "no server".
    - ``done`` — printed after ``eval()`` returns, with each task's log
      location and status (the live → ``inspect log`` handoff). A run
      that raises emits no ``done`` record and exits non-zero.

    For an eval set the same records apply, with a few wrinkles the
    option help documents: the ``done`` record additionally reports the resolved
    ``eval_set_id`` and overall ``success`` (all tasks completed
    successfully — what the exit code also reports), and a set whose
    tasks are all already complete runs no eval at all, so stdout may
    carry only the ``done`` record. In the legacy ``--no-retry-immediate``
    mode each batch retry makes a fresh ``eval()`` call, and each bind
    emits a fresh ``launch`` record; the ``done`` record then carries the
    *last* launch's ``run_id`` — the run that produced the final state,
    matching the most recent ``launch`` record an agent read
    (``eval_set_id`` is stable across batches).

    ``eval_retry`` runs each retried log file as its own eval with its
    own ``run_id``, so a multi-file retry emits one ``launch`` record
    per file (sequentially — each supersedes the previous) with the
    same last-launch ``done`` correlation.

    Stdout belongs exclusively to these records: ``eval()`` runs with
    stdout redirected to stderr (see ``_stdout_owned_for_json``) — an
    OS-level redirect, so both bare ``print`` writers inside the run
    (trailing scan status, cosmetic spacing, task/solver code, ...) and
    subprocesses spawned without capturing output land on stderr, where
    they remain visible as diagnostics, instead of corrupting the NDJSON
    stream. The records themselves are written to the saved real stdout.

    Pre-flight failures (``PrerequisiteError``) are re-rendered to
    stderr by ``_json_prerequisite_errors_to_stderr``, which wraps the
    whole command — covering failures raised both before ``eval()``
    (e.g. an invalid ``--run-config``) and inside it.
    """
    handoffs: list[LaunchHandoff] = []

    with _stdout_owned_for_json() as stdout:

        def on_launch(handoff: LaunchHandoff) -> None:
            handoffs.append(handoff)
            print(
                json.dumps(
                    {
                        "event": "launch",
                        "run_id": handoff.run_id,
                        "eval_set_id": handoff.eval_set_id,
                        "pid": handoff.pid,
                        "log_dir": handoff.log_dir,
                        "control": (
                            {"socket_path": handoff.control_socket}
                            if handoff.control_socket is not None
                            else None
                        ),
                    }
                ),
                file=stdout,
                flush=True,
            )

        set_launch_handoff_listener(on_launch)
        try:
            success, logs = run()
        finally:
            set_launch_handoff_listener(None)
            # stray prints redirected to stderr may sit in a buffered wrapper
            # (e.g. under CliRunner); surface them before the command returns
            sys.stderr.flush()

        # with multiple launches (legacy --no-retry-immediate batch retries)
        # report the last one — the run that produced the final state
        done: dict[str, Any] = {
            "event": "done",
            "run_id": handoffs[-1].run_id if handoffs else None,
        }
        if is_eval_set:
            # resolved id (may be generated / read from the log dir); fall
            # back to the log headers when no eval ran (all tasks reused)
            done["eval_set_id"] = (
                handoffs[-1].eval_set_id
                if handoffs
                else (logs[0].eval.eval_set_id if logs else None)
            )
            done["success"] = success
        done["logs"] = [
            {
                "task": log.eval.task,
                "task_id": log.eval.task_id,
                "eval_id": log.eval.eval_id,
                "status": log.status,
                "location": log.location,
            }
            for log in logs
        ]
        print(json.dumps(done), file=stdout, flush=True)

    return success


@contextlib.contextmanager
def _stdout_owned_for_json() -> Iterator[TextIO]:
    """Redirect stdout to stderr, yielding a handle on the real stdout.

    A Python-level ``redirect_stdout`` alone cannot own stdout: it only
    rebinds the ``sys.stdout`` object, while subprocesses spawned by
    task/solver code without capturing output inherit file descriptor 1
    and write straight into the NDJSON stream. So dup fd 1 for the JSON
    records, then ``dup2`` stderr's fd onto fd 1 for the duration —
    covering C-level and subprocess writers too. ``sys.stdout`` is also
    rebound to stderr so Python writers don't interleave through fd 1's
    buffer.

    Falls back to the Python-level redirect alone when the streams have
    no real file descriptors (in-process harnesses like click's
    ``CliRunner``), where subprocess capture is a non-issue for the
    contract (there is no real stdout to corrupt).
    """
    try:
        fds = (sys.stdout.fileno(), sys.stderr.fileno())
    except (ValueError, OSError):
        fds = None
    if fds is None:
        real_stdout = sys.stdout
        with contextlib.redirect_stdout(sys.stderr):
            yield real_stdout
        return

    stdout_fd, stderr_fd = fds
    sys.stdout.flush()
    with os.fdopen(os.dup(stdout_fd), "w") as saved_stdout:
        os.dup2(stderr_fd, stdout_fd)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                yield saved_stdout
        finally:
            os.dup2(saved_stdout.fileno(), stdout_fd)


def _parse_adaptive_connections_cli(
    value: str | None,
) -> bool | int | AdaptiveConcurrency | None:
    """Parse a CLI string into an adaptive_connections value.

    Accepts: None (passthrough), bool keywords ("true"/"yes" / "false"/"no",
    case-insensitive), a bare integer N (shorthand for
    `AdaptiveConcurrency(max=N)`), or a min-max / min-start-max shorthand
    like "4-80" / "4-20-80" delegated to AdaptiveConcurrency's parser.
    Raises `click.BadParameter` on invalid input so the CLI surfaces a
    clean usage message instead of a raw pydantic ValidationError.

    Note: `"1"`/`"0"` are treated as the integer-max shorthand, not as
    bool aliases. Users who want explicit on/off should pass `true`/`false`.
    """
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("true", "yes"):
        return True
    if v in ("false", "no"):
        return False
    # Bare integer → max shorthand.
    if v.isdigit():
        return int(v)
    try:
        return AdaptiveConcurrency.model_validate(value)
    except Exception as ex:
        raise click.BadParameter(
            f"{value!r} is not a valid value. Expected `true`, `false`, an "
            f"integer max (e.g. `200`), or bounds shorthand like `4-80` "
            f"or `4-20-80`.",
            param_hint="--adaptive-connections",
        ) from ex


def config_from_locals(locals: dict[str, Any]) -> GenerateConfigArgs:
    # start with config file if specified
    adapter = TypeAdapter(GenerateConfigArgs)
    run_config_file = locals.get("run_config")
    generate_config_file = locals.pop("generate_config", None)
    if run_config_file and generate_config_file:
        raise PrerequisiteError("--run-config cannot be used with --generate-config.")
    if generate_config_file:
        # read file
        generate_config = resolve_args(generate_config_file)

        # validate all the fields are valid
        extra_keys = generate_config.keys() - GenerateConfigArgs.__annotations__.keys()
        if extra_keys:
            raise PrerequisiteError(
                f"Unexpected GenerateConfig fields in {generate_config_file}: {extra_keys}"
            )

        # create base config
        base_config = adapter.validate_python(generate_config, strict=True)
    else:
        base_config = GenerateConfigArgs()

    # build generate config
    config_keys = list(GenerateConfigArgs.__mutable_keys__)  # type: ignore
    config = GenerateConfigArgs(**base_config)
    for key, value in locals.items():
        if key in config_keys and value is not None:
            if key == "stop_seqs":
                value = value.split(",")
            if key == "fallback_models":
                value = [m.strip() for m in value.split(",")]
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
            if key == "internal_tools":
                if value is not False:
                    value = None
            if key == "response_schema":
                if value is not None:
                    value = ResponseSchema.model_validate_json(value)
            if key == "cache":
                match value:
                    case str():
                        policy = CachePolicy.from_string(value)
                        if policy is not None:
                            value = policy
                        else:
                            value = CachePolicy.model_validate(resolve_args(value))
                    case int():
                        value = CachePolicy(expiry=f"{value}D")

            if key == "batch":
                match value:
                    case str():
                        value = BatchConfig.model_validate(resolve_args(value))

            if key == "adaptive_connections" and isinstance(value, str):
                value = _parse_adaptive_connections_cli(value)

            if key == "modalities":
                value = parse_modalities(value)

            config[key] = value  # type: ignore
    return config


def parse_modalities(value: str) -> list[Any]:
    """Parse modalities from comma-separated names or YAML/JSON file."""
    # Check if it's a file path
    fs = filesystem(value)
    if fs.exists(value):
        content = resource(value, type="file")
        is_json = content.strip().startswith("[") or content.strip().startswith("{")
        config = json.loads(content) if is_json else yaml.safe_load(content)
        if not isinstance(config, list):
            raise PrerequisiteError(
                f"Modalities config file must contain a list, got: {type(config).__name__}"
            )
        result: list[OutputModality] = []
        for item in config:
            if isinstance(item, str):
                result.append(item)  # type: ignore[arg-type]
            elif isinstance(item, dict):
                result.append(ImageOutput.model_validate(item))
            else:
                raise PrerequisiteError(f"Invalid modality item: {item}")
        return result
    else:
        # Check if it looks like a file path that doesn't exist
        if "/" in value or "\\" in value or value.endswith((".json", ".yaml", ".yml")):
            raise PrerequisiteError(f"Modalities file not found: {value}")
        # Comma-separated literal names (e.g. "image" or "image,audio")
        tokens = [m.strip() for m in value.split(",")]
        return [t for t in tokens if t]  # type: ignore[misc]


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


@click.command("eval-retry", cls=EvalCommand)
@click.argument("log_files", nargs=-1, required=True)
@click.option(
    "--json",
    "json_output",
    type=bool,
    is_flag=True,
    default=False,
    envvar="INSPECT_EVAL_JSON",
    help="Emit machine-readable launch output as JSON lines on stdout (implies --display none): a 'launch' record printed once the control-channel server is bound — reporting run_id, pid, log_dir, and the control socket path ('control' is null when the server is disabled or failed to bind, so its presence guarantees `inspect ctl` is usable) — and a 'done' record with each retried task's log location and status when the retry finishes. Each retried log file runs as its own eval, so a multi-file retry emits one 'launch' record per file (sequentially — each supersedes the previous), and the 'done' record carries the last launch's run_id. To launch in the background instead, use --detach (which implies --json and hands off on the first launch record).",
)
@click.option(
    "--detach",
    type=bool,
    is_flag=True,
    default=False,
    envvar="INSPECT_EVAL_DETACH",
    help=DETACH_HELP,
)
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
    "--max-sandboxes",
    type=int,
    help=MAX_SANDBOXES_HELP,
    envvar="INSPECT_EVAL_MAX_SANDBOXES",
)
@click.option(
    "--no-sandbox-cleanup",
    type=bool,
    is_flag=True,
    help=NO_SANDBOX_CLEANUP_HELP,
)
@click.option(
    "--trace",
    type=bool,
    is_flag=True,
    hidden=True,
    help="Trace message interactions with evaluated model to terminal.",
    envvar="INSPECT_EVAL_TRACE",
)
@click.option(
    "--fail-on-error",
    type=float,
    is_flag=False,
    flag_value=0.0,
    help=FAIL_ON_ERROR_HELP,
    envvar="INSPECT_EVAL_FAIL_ON_ERROR",
)
@click.option(
    "--no-fail-on-error",
    type=bool,
    is_flag=True,
    default=False,
    help=NO_FAIL_ON_ERROR_HELP,
    envvar="INSPECT_EVAL_NO_FAIL_ON_ERROR",
)
@click.option(
    "--continue-on-fail",
    type=bool,
    is_flag=True,
    default=None,
    help=CONTINUE_ON_FAIL_HELP,
    envvar="INSPECT_EVAL_CONTINUE_ON_FAIL",
)
@click.option(
    "--retry-on-error",
    is_flag=False,
    flag_value="true",
    default=None,
    callback=int_or_bool_flag_callback(DEFAULT_RETRY_ON_ERROR),
    help=RETRY_ON_ERROR_HELP,
    envvar="INSPECT_EVAL_RETRY_ON_ERROR",
)
@click.option(
    "--score-on-error",
    type=bool,
    is_flag=True,
    default=None,
    help=SCORE_ON_ERROR_HELP,
    envvar="INSPECT_EVAL_SCORE_ON_ERROR",
)
@click.option(
    "--no-log-samples",
    type=bool,
    is_flag=True,
    help=NO_LOG_SAMPLES_HELP,
    envvar="INSPECT_EVAL_LOG_SAMPLES",
)
@click.option(
    "--no-log-realtime",
    type=bool,
    is_flag=True,
    help=NO_LOG_REALTIME_HELP,
    envvar="INSPECT_EVAL_LOG_REALTIME",
)
@click.option(
    "--log-images/--no-log-images",
    type=bool,
    default=True,
    is_flag=True,
    help=LOG_IMAGES_HELP,
    envvar="INSPECT_EVAL_LOG_IMAGES",
)
@click.option(
    "--log-model-api/--no-log-model-api",
    type=bool,
    default=None,
    is_flag=True,
    help=LOG_MODEL_API_HELP,
    envvar="INSPECT_EVAL_LOG_MODEL_API",
)
@click.option(
    "--log-refusals/--no-log-refusals",
    type=bool,
    default=False,
    is_flag=True,
    help=LOG_REFUSALS_HELP,
    envvar="INSPECT_EVAL_LOG_REFUSALS",
)
@click.option(
    "--log-buffer", type=int, help=LOG_BUFFER_HELP, envvar="INSPECT_EVAL_LOG_BUFFER"
)
@click.option(
    "--log-shared",
    is_flag=False,
    flag_value="true",
    default=None,
    callback=int_or_bool_flag_callback(DEFAULT_LOG_SHARED),
    help=LOG_SHARED_HELP,
    envvar=["INSPECT_LOG_SHARED", "INSPECT_EVAL_LOG_SHARED"],
)
@click.option(
    "--no-score",
    type=bool,
    is_flag=True,
    help=NO_SCORE_HELP,
    envvar="INSPECT_EVAL_SCORE",
)
@click.option(
    "--no-score-display",
    type=bool,
    is_flag=True,
    help=NO_SCORE_DISPLAY,
    envvar="INSPECT_EVAL_SCORE_DISPLAY",
)
@click.option(
    "--acp-server",
    is_flag=False,
    flag_value="true",
    default=None,
    # Retry semantics: omitted → None (replay log); explicit false → False
    # (force disable, overriding the log). The standard callback would
    # collapse those two cases, leaving no way to turn ACP off on a retry
    # of a log that had it enabled.
    callback=int_bool_or_str_retry_flag_callback(True),
    help=(
        "Override the original eval's Agent Client Protocol server. "
        "Bare flag enables a default AF_UNIX socket; pass an integer "
        "to bind a TCP loopback port; pass `host:port` to bind on a "
        "specific interface (e.g. `0.0.0.0:4444`); pass a filesystem "
        "path for a custom UNIX socket; pass `false` to disable. Omit "
        "to replay whatever transport the original log used."
    ),
    envvar="INSPECT_EVAL_ACP_SERVER",
)
@click.option(
    "--ctl-server",
    is_flag=False,
    flag_value="true",
    default=None,
    callback=ctl_server_flag_callback,
    help=(
        "Control-channel server for the retried eval's process (default: "
        "enabled). Pass `false` to disable it; pass `keep` "
        "to keep the process running after the retried eval finishes so "
        "external clients (the `inspect ctl` CLI, scripted agents) can still "
        "query its state. Run `inspect ctl process release` to release."
    ),
    envvar="INSPECT_EVAL_CTL_SERVER",
)
@click.option(
    "--max-connections",
    type=int,
    help=MAX_CONNECTIONS_HELP,
    envvar="INSPECT_EVAL_MAX_CONNECTIONS",
)
@click.option(
    "--adaptive-connections",
    type=str,
    default=None,
    help=ADAPTIVE_CONNECTIONS_HELP,
    envvar="INSPECT_EVAL_ADAPTIVE_CONNECTIONS",
)
@click.option(
    "--max-retries", type=int, help=MAX_RETRIES_HELP, envvar="INSPECT_EVAL_MAX_RETRIES"
)
@click.option("--timeout", type=int, help=TIMEOUT_HELP, envvar="INSPECT_EVAL_TIMEOUT")
@click.option(
    "--attempt-timeout",
    type=int,
    help=ATTEMPT_TIMEOUT_HELP,
    envvar="INSPECT_EVAL_ATTEMPT_TIMEOUT",
)
@click.option(
    "--log-level-transcript",
    type=click.Choice(
        [level.lower() for level in ALL_LOG_LEVELS],
        case_sensitive=False,
    ),
    default=DEFAULT_LOG_LEVEL_TRANSCRIPT,
    envvar="INSPECT_LOG_LEVEL_TRANSCRIPT",
    help=f"Set the log level of the transcript (defaults to '{DEFAULT_LOG_LEVEL_TRANSCRIPT}')",
)
@click.option(
    "--checkpoint",
    is_flag=False,
    flag_value="default",
    default=None,
    help=CHECKPOINT_HELP
    + " For resume to find checkpoint files, pass the same `--checkpoint` value used on the original eval.",
    envvar="INSPECT_EVAL_CHECKPOINT",
)
@scanner_options
@common_options
def eval_retry_command(
    log_files: tuple[str, ...],
    json_output: bool,
    detach: bool,
    max_samples: int | None,
    max_tasks: int | None,
    max_subprocesses: int | None,
    max_sandboxes: int | None,
    no_sandbox_cleanup: bool | None,
    trace: bool | None,
    fail_on_error: bool | float | None,
    no_fail_on_error: bool | None,
    continue_on_fail: bool | None,
    retry_on_error: int | None,
    score_on_error: bool | None,
    no_log_samples: bool | None,
    no_log_realtime: bool | None,
    log_images: bool | None,
    log_model_api: bool | None,
    log_refusals: bool | None,
    log_buffer: int | None,
    log_shared: int | None,
    no_score: bool | None,
    no_score_display: bool | None,
    acp_server: bool | int | str | None,
    ctl_server: bool | str | None,
    max_connections: int | None,
    adaptive_connections: str | None,
    max_retries: int | None,
    timeout: int | None,
    attempt_timeout: int | None,
    log_level_transcript: str,
    checkpoint: str | None,
    scanner: str | None,
    scanner_arg: tuple[str, ...] | None,
    scans: str | None,
    scan_name: str | None,
    scan_tags: str | None,
    scan_metadata: tuple[str, ...] | None,
    scan_filter: tuple[str, ...] | None,
    scan_model: str | None,
    scan_model_base_url: str | None,
    scan_model_arg: tuple[str, ...] | None,
    scan_model_config: str | None,
    scan_model_role: tuple[str, ...] | None,
    scan_generate_config: str | None,
    **common: Unpack[CommonOptions],
) -> None:
    """Retry failed evaluation(s)"""
    with _json_prerequisite_errors_to_stderr(json_output or detach):
        if detach:
            exec_detached(ctl_server=ctl_server)

        # --json owns stdout (JSON lines only), so route the display to the
        # quiet "none" renderer — including when --no-ansi would otherwise
        # promote it back to "rich" or --trace (/INSPECT_EVAL_TRACE) would
        # promote it to "conversation", which writes panels to stdout
        if json_output:
            common["display"] = "none"
            common["no_ansi"] = None
            trace = None

        # resolve common options
        process_common_options(common)

        # resolve negating options
        sandbox_cleanup = False if no_sandbox_cleanup else None
        log_samples = False if no_log_samples else None
        log_realtime = False if no_log_realtime else None
        log_images = False if log_images is False else None
        log_refusals = True if log_refusals is True else None
        score = False if no_score else True
        score_display = False if no_score_display else None

        # resolve fail_on_error
        if no_fail_on_error is True:
            fail_on_error = False
        elif fail_on_error == 0.0:
            fail_on_error = True

        # resolve retry on error
        if retry_on_error == 0:
            retry_on_error = None

        # resolve log file
        retry_log_files = [
            log_file_info(filesystem(log_file).info(log_file)) for log_file in log_files
        ]

        # parse adaptive_connections (str → bool | AdaptiveConcurrency)
        adaptive_connections_value = _parse_adaptive_connections_cli(
            adaptive_connections
        )

        # resolve scanner spec (None unless --scanner was provided)
        from inspect_ai._display.core.results import set_retry_args_suffix

        from ._scanner import resolve_cli_scanner, serialize_scanner_cli_args

        eval_scanner = resolve_cli_scanner(
            scanner,
            scanner_arg,
            scans=scans,
            scan_name=scan_name,
            scan_tags=scan_tags,
            scan_metadata=scan_metadata,
            scan_filter=scan_filter,
            scan_model=scan_model,
            scan_model_base_url=scan_model_base_url,
            scan_model_arg=scan_model_arg,
            scan_model_config=scan_model_config,
            scan_model_role=scan_model_role,
            scan_generate_config=scan_generate_config,
        )

        # preserve scanner flags on any further `eval-retry` suggestion shown
        # if this retry itself interrupts
        set_retry_args_suffix(
            serialize_scanner_cli_args(
                scanner,
                scanner_arg,
                scans=scans,
                scan_name=scan_name,
                scan_tags=scan_tags,
                scan_metadata=scan_metadata,
                scan_filter=scan_filter,
                scan_model=scan_model,
                scan_model_base_url=scan_model_base_url,
                scan_model_arg=scan_model_arg,
                scan_model_config=scan_model_config,
                scan_model_role=scan_model_role,
                scan_generate_config=scan_generate_config,
            )
        )

        # retry
        def run_retry() -> list[EvalLog]:
            return eval_retry(
                retry_log_files,
                log_level=common["log_level"],
                log_level_transcript=log_level_transcript,
                log_dir=common["log_dir"],
                max_samples=max_samples,
                max_tasks=max_tasks,
                max_subprocesses=max_subprocesses,
                max_sandboxes=max_sandboxes,
                sandbox_cleanup=sandbox_cleanup,
                trace=trace,
                fail_on_error=fail_on_error,
                continue_on_fail=continue_on_fail,
                retry_on_error=retry_on_error,
                score_on_error=score_on_error,
                debug_errors=common["debug_errors"],
                log_samples=log_samples,
                log_realtime=log_realtime,
                log_images=log_images,
                log_model_api=log_model_api,
                log_refusals=log_refusals,
                log_buffer=log_buffer,
                log_shared=log_shared,
                score=score,
                score_display=score_display,
                acp_server=acp_server,
                ctl_server=ctl_server,
                scanner=eval_scanner,
                max_retries=max_retries,
                timeout=timeout,
                attempt_timeout=attempt_timeout,
                max_connections=max_connections,
                adaptive_connections=adaptive_connections_value,
                checkpoint=parse_checkpoint(checkpoint),
            )

        if json_output:
            _eval_exec_json(lambda: (True, run_retry()))
        else:
            run_retry()
