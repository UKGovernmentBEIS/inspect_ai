import os
from logging import getLogger
from typing import Any, Tuple

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)

logger = getLogger(__name__)


def model_base_url(base_url: str | None, env_vars: str | list[str]) -> str | None:
    if base_url:
        return base_url

    if isinstance(env_vars, str):
        env_vars = [env_vars]

    for env_var in env_vars:
        base_url = os.getenv(env_var, None)
        if base_url:
            return base_url

    return os.getenv("INSPECT_EVAL_MODEL_BASE_URL", None)


def environment_prerequisite_error(
    client: str, env_vars: str | list[str]
) -> PrerequisiteError:
    def fmt(key: str) -> str:
        return f"[bold][blue]{key}[/blue][/bold]"

    env_vars = [env_vars] if isinstance(env_vars, str) else env_vars
    if len(env_vars) == 1:
        env_vars_list = fmt(env_vars[0])
    else:
        env_vars_list = (
            ", ".join([fmt(env_bar) for env_bar in env_vars[:-1]])
            + ("," if len(env_vars) > 2 else "")
            + " or "
            + fmt(env_vars[-1])
        )

    return PrerequisiteError(
        f"ERROR: Unable to initialise {client} client\n\nNo {env_vars_list} defined in the environment."
    )


def split_system_messages(
    input: list[ChatMessage],
) -> Tuple[
    list[ChatMessageSystem],
    list[ChatMessageUser | ChatMessageAssistant | ChatMessageTool],
]:
    # split messages
    system_messages = [m for m in input if isinstance(m, ChatMessageSystem)]
    messages = [m for m in input if not isinstance(m, ChatMessageSystem)]

    # return
    return system_messages, messages


def resolve_api_key(api_key_env_vars: list[str]) -> str | None:
    """
    Resolve API key from environment variables.

    Args:
        api_key_env_vars: List of environment variable names to check for API key.

    Returns:
        The API key if found, None otherwise.
    """
    for env_var in api_key_env_vars:
        api_key = os.environ.get(env_var)
        if api_key:
            return api_key
    return None


def normalize_stream_arg(value: Any, arg_name: str = "stream") -> bool | None:
    """Normalize a `stream`/`streaming` model arg to a bool or None ("auto").

    `-M` model args are YAML-parsed, so `true`/`false` arrive as bools but
    `auto` arrives as the string "auto" — it must map to the auto sentinel
    (None), not a truthy explicit setting. String bool spellings ("True",
    "false") are accepted for non-YAML callers. Anything else raises so a
    typo can't silently force streaming on or off.

    Args:
        value: The raw model arg value.
        arg_name: The model arg's name, for error messages.

    Returns:
        True/False for an explicit setting, None for auto/unset.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "auto":
            return None
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    raise ValueError(
        f"Unrecognized value for the {arg_name} model arg: {value!r} "
        '(expected true, false, or "auto")'
    )
