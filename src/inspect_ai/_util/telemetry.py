import importlib
import os
from typing import Awaitable, Callable, Literal, cast

from rich import print

from .constants import PKG_NAME
from .error import PrerequisiteError

# Telemetry can be optionally enabled by setting an INSPECT_TELEMETRY
# environment variable that points to a function in a package which
# conforms to the TelemetrySend signature below. For example,
# 'mypackage.inspect.send_telemetry'. When telemetry is enabled a
# message will be printed at startup indicating this, as well as which
# package is registered for telemetry.
#
# There are currently two types of telemetry sent:
#   - model_usage (type ModelUsage)
#   - eval_log    (type EvalLog)

TelemetrySend = Callable[[str, str], Awaitable[None]]


def init_telemetry() -> None:
    global _send_telemetry
    if not _send_telemetry:
        telemetry = os.environ.get("INSPECT_TELEMETRY", "")
        if telemetry:
            # parse module/function
            module_name, function_name = telemetry.strip().rsplit(".", 1)
            # load (fail gracefully w/ clear error)
            try:
                module = importlib.import_module(module_name)
                _send_telemetry = cast(TelemetrySend, getattr(module, function_name))
            except (AttributeError, ModuleNotFoundError):
                raise PrerequisiteError(
                    f"INSPECT_TELEMETRY provider not found: {telemetry}\n"
                    + "Please correct (or undefine) this environment variable before proceeding.\n"
                )
            # let the user know that telemetry is enabled
            version = importlib.metadata.version(PKG_NAME)
            print(
                f"[blue][bold]inspect_ai v{version}\ntelemetry enabled: {telemetry}\n(eval logs and token usage will be recorded by provider)[/bold][/blue]\n"
            )


async def send_telemetry(type: Literal["model_usage", "eval_log"], json: str) -> None:
    global _send_telemetry
    if _send_telemetry:
        await _send_telemetry(type, json)


_send_telemetry: TelemetrySend | None = None
