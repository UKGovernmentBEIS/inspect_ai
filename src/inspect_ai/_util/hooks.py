import importlib
import os
from typing import Any, Awaitable, Callable, Literal, cast

from rich import print

from .constants import PKG_NAME
from .error import PrerequisiteError

# Hooks are functions inside packages that are installed with an
# environment variable (e.g. INSPECT_TELEMETRY='mypackage.send_telemetry')
# If one or more hooks are enabled a message will be printed at startup
# indicating this, as well as which package/function implements each hook


# Telemetry (INSPECT_TELEMETRY)
#
# Telemetry can be optionally enabled by setting an INSPECT_TELEMETRY
# environment variable that points to a function in a package which
# conforms to the TelemetrySend signature below.

# There are currently two types of telemetry sent:
#    - model_usage (type ModelUsage)
#    - eval_log    (type EvalLog)

TelemetrySend = Callable[[str, str], Awaitable[None]]


async def send_telemetry(type: Literal["model_usage", "eval_log"], json: str) -> None:
    global _send_telemetry
    if _send_telemetry:
        await _send_telemetry(type, json)


_send_telemetry: TelemetrySend | None = None

# API Key Override (INSPECT_API_KEY_OVERRIDE)
#
# API Key overrides can be optionally enabled by setting an
# INSPECT_API_KEY_OVERRIDE environment variable which conforms to the
# ApiKeyOverride signature below.
#
# The api key override function will be called with the name and value
# of provider specified environment variables that contain api keys,
# and it can optionally return an override value.

ApiKeyOverride = Callable[[str, str], str | None]


def override_api_key(var: str, value: str) -> str | None:
    global _override_api_key
    if _override_api_key:
        return _override_api_key(var, value)
    else:
        return None


_override_api_key: ApiKeyOverride | None = None


def init_hooks() -> None:
    # messages we'll print for hooks if we have them
    messages: list[str] = []

    # telemetry
    global _send_telemetry
    if not _send_telemetry:
        result = init_hook(
            "telemetry",
            "INSPECT_TELEMETRY",
            "(eval logs and token usage will be recorded by the provider)",
        )
        if result:
            _send_telemetry, message = result
            messages.append(message)

    # api key override
    global _override_api_key
    if not _override_api_key:
        result = init_hook(
            "api key override",
            "INSPECT_API_KEY_OVERRIDE",
            "(api keys will be read and modified by the provider)",
        )
        if result:
            _override_api_key, message = result
            messages.append(message)

    # if any hooks are enabled, let the user know
    if len(messages) > 0:
        version = importlib.metadata.version(PKG_NAME)
        all_messages = "\n".join([f"- {message}" for message in messages])
        print(
            f"[blue][bold]inspect_ai v{version}[/bold][/blue]\n[bright_black]{all_messages}[/bright_black]\n"
        )


def init_hook(
    name: str, env: str, message: str
) -> tuple[Callable[..., Any], str] | None:
    hook = os.environ.get(env, "")
    if hook:
        # parse module/function
        module_name, function_name = hook.strip().rsplit(".", 1)
        # load (fail gracefully w/ clear error)
        try:
            module = importlib.import_module(module_name)
            return (
                cast(Callable[..., Any], getattr(module, function_name)),
                f"[bold]{name} enabled: {hook}[/bold]\n  {message}",
            )
        except (AttributeError, ModuleNotFoundError):
            raise PrerequisiteError(
                f"{env} provider not found: {hook}\n"
                + "Please correct (or undefine) this environment variable before proceeding."
            )
    else:
        return None
