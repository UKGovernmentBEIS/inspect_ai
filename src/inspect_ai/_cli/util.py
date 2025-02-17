from typing import Any, Callable

import click
import yaml

from inspect_ai._util.config import resolve_args
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


class PassthroughParam(click.ParamType):
    name = "passthrough"

    def convert(
        self, value: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> Any:
        if isinstance(value, tuple) and len(value) == 0:
            return None
        return value


def int_or_bool_flag_callback(
    true_value: int, false_value: int = 0
) -> Callable[[click.Context, click.Parameter | None, Any], int]:
    def callback(ctx: click.Context, param: click.Parameter | None, value: Any) -> int:
        if (
            param
            and param.name
            and (
                ctx.get_parameter_source(param.name)
                != click.core.ParameterSource.DEFAULT
            )
        ):
            if value is None:
                return true_value
            else:
                try:
                    print(value)
                    value = value[0] if isinstance(value, tuple) else value
                    return int(value)
                except ValueError:
                    value = str(value).lower()
                    if value in ("true", "t", "yes", "y"):
                        return true_value
                    if value in ("false", "f", "no", "n"):
                        return false_value
                    raise click.BadParameter("Not a valid integer or boolean value")
        else:
            return value

    return callback


class IntOrBoolOption(click.Option):
    def __init__(self, *args: Any, **kwargs: Any):
        kwargs["type"] = click.UNPROCESSED
        kwargs["is_flag"] = True  # Allow flag behavior
        kwargs["flag_value"] = "flag"  # Special value when used as flag
        super().__init__(*args, **kwargs)

    def parse_value(self, ctx: click.Context, value: Any) -> int | None:
        if value is None:
            return 0  # Default when not specified
        if value == "flag":  # When used as bare flag
            return 10
        try:
            return int(value)
        except ValueError:
            value = str(value).lower()
            if value in ("true", "t", "yes", "y"):
                return 10
            if value in ("false", "f", "no", "n"):
                return 0
            raise click.BadParameter("Not a valid integer or boolean value")


def int_or_bool_flag(
    ctx: click.Context, param: click.Parameter | None, value: Any
) -> int:
    if value is True:  # Flag used without value
        return 10
    if value is False:  # Flag not used
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        value = str(value).lower()
        if value in ("true", "t", "yes", "y"):
            return 10
        if value in ("false", "f", "no", "n"):
            return 0
        raise click.BadParameter("Not a valid integer or boolean value")


class IntOrBoolFlag(click.ParamType):
    name = "integer_or_boolean_flag"

    def __init__(self, true_value: int = 10, false_value: int = 0) -> None:
        self.true_value = true_value
        self.false_value = false_value

    def convert(
        self, value: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> int:
        if value is None:
            return self.false_value
        if (
            param is not None
            and hasattr(param, "flag_value")
            and value == getattr(param, "flag_value")
        ):
            return self.true_value
        if isinstance(value, bool):
            return self.true_value if value else self.false_value
        if isinstance(value, int):
            return value

        try:
            return int(value)
        except ValueError:
            value = value.lower()
            if value in ("true", "t", "yes", "y"):
                return self.true_value
            if value in ("false", "f", "no", "n"):
                return self.false_value
            self.fail(f"{value} is not a valid integer or boolean", param, ctx)


class IntOrBool(click.ParamType):
    name = "integer_or_boolean"

    def __init__(self, true_value: int = 10, false_value: int = 0) -> None:
        self.true_value = true_value
        self.false_value = false_value

    def convert(
        self, value: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> int:
        if isinstance(value, bool):
            return self.true_value if value else self.false_value
        if isinstance(value, int):
            return value

        try:
            # Try converting to int first
            return int(value)
        except ValueError:
            # If not an int, try converting to bool and then to int
            value = value.lower()
            if value in ("true", "t", "yes", "y"):
                return self.true_value
            if value in ("false", "f", "no", "n"):
                return self.false_value
            self.fail(f"{value} is not a valid integer or boolean", param, ctx)


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


def parse_cli_args(args: tuple[str] | list[str] | None) -> dict[str, Any]:
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
                params[key] = value
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
