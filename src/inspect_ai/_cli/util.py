from typing import Any, Callable

import click
import yaml

from inspect_ai._util.config import resolve_args
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


def int_or_bool_flag_callback(
    true_value: int, false_value: int = 0
) -> Callable[[click.Context, click.Parameter, Any], int]:
    def callback(ctx: click.Context, param: click.Parameter, value: Any) -> int:
        """Callback to parse the an option that can either be a boolean flag or integer.

        Desired behavior:
        - Not specified at all -> false_value
        - Specified with no value -> true_value
        - Specified with "true"/"false" -> true_value or false_value respectively
        - Specified with an integer -> that integer
        """
        # 1. If this parameter was never given on the command line,
        #    then we return 0.
        source = ctx.get_parameter_source(param.name) if param.name else ""
        if source == click.core.ParameterSource.DEFAULT:
            # Means the user did NOT specify the flag at all
            return false_value

        # 2. The user did specify the flag. If value is None,
        #    that means they used the flag with no argument, e.g. --my-flag
        if value is None:
            return true_value

        # 3. If there is a value, try to parse booleans or an integer.
        lower_val = value.lower()
        if lower_val in ("true", "yes", "1"):
            return true_value
        elif lower_val in ("false", "no", "0"):
            return false_value
        else:
            # 4. Otherwise, assume it is an integer
            try:
                return int(value)
            except ValueError:
                raise click.BadParameter(
                    f"Expected 'true', 'false', or an integer for --{param.name}. Got: {value}"
                )

    return callback


def int_bool_or_str_flag_callback(
    true_value: int, false_value: int | None = None
) -> Callable[[click.Context, click.Parameter, Any], int | str | None]:
    """Callback to parse an option that can be a boolean flag, integer, or string.

    This is an extended version of int_or_bool_flag_callback that also supports
    string values when the input cannot be parsed as a boolean or integer.

    Args:
        true_value: Value to return when flag is specified without argument or with "true"
        false_value: Value to return when flag is not specified or with "false"

    Returns:
        A click callback function that returns int, str, or None
    """

    def callback(
        ctx: click.Context, param: click.Parameter, value: Any
    ) -> int | str | None:
        """Callback to parse an option that can be a boolean flag, integer, or string.

        Desired behavior:
        - Not specified at all -> false_value
        - Specified with no value -> true_value
        - Specified with "true"/"false" -> true_value or false_value respectively
        - Specified with an integer -> that integer
        - Specified with any other string -> that string
        """
        # 1. If this parameter was never given on the command line,
        #    then we return false_value.
        source = ctx.get_parameter_source(param.name) if param.name else ""
        if source == click.core.ParameterSource.DEFAULT:
            # Means the user did NOT specify the flag at all
            return false_value

        # 2. The user did specify the flag. If value is None,
        #    that means they used the flag with no argument, e.g. --my-flag
        if value is None:
            return true_value

        # 3. If there is a value, try to parse booleans first.
        lower_val = value.lower()
        if lower_val in ("true", "yes", "1"):
            return true_value
        elif lower_val in ("false", "no", "0"):
            return false_value
        else:
            # 4. Try to parse as an integer
            try:
                return int(value)
            except ValueError:
                return str(value)

    return callback


def parse_cli_config(
    args: tuple[str] | list[str] | None, config: str | None
) -> dict[str, Any]:
    # start with file if any
    cli_config: dict[str, Any] = {}
    if config is not None:
        cli_config = cli_config | resolve_args(config)

    # merge in cli args
    cli_args = parse_cli_args(args)
    cli_config.update(**cli_args)
    return cli_config


def parse_cli_args(
    args: tuple[str] | list[str] | None, force_str: bool = False
) -> dict[str, Any]:
    params: dict[str, Any] = dict()
    if args:
        for arg in list(args):
            parts = arg.split("=")
            if len(parts) > 1:
                key = parts[0].replace("-", "_")
                value = yaml.safe_load("=".join(parts[1:]))
                if isinstance(value, str):
                    value = value.split(",")
                    value = value if len(value) > 1 else value[0]
                params[key] = str(value) if force_str else value
    return params


def parse_sandbox(sandbox: str | None) -> SandboxEnvironmentSpec | None:
    if sandbox is not None:
        parts = sandbox.split(":", maxsplit=1)
        if len(parts) == 1:
            return SandboxEnvironmentSpec(sandbox)
        else:
            return SandboxEnvironmentSpec(parts[0], parts[1])
    else:
        return None
