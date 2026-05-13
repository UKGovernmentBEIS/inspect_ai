from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

import click
import yaml

if TYPE_CHECKING:
    from inspect_ai.model import Model
    from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


def int_or_bool_flag_callback(
    true_value: int, false_value: int = 0, is_one_true: bool = True
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
        true_vals = {"true", "yes"}
        if is_one_true:
            true_vals.add("1")
        if lower_val in true_vals:
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
    args: tuple[str, ...] | list[str] | None, config: str | None
) -> dict[str, Any]:
    from inspect_ai._util.config import resolve_args

    # start with file if any
    cli_config: dict[str, Any] = {}
    if config is not None:
        cli_config = cli_config | resolve_args(config)

    # merge in cli args
    cli_args = parse_cli_args(args)
    cli_config.update(**cli_args)
    return cli_config


def parse_cli_args(
    args: tuple[str, ...] | list[str] | None, force_str: bool = False
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


def parse_model_role_cli_args(
    model_roles: tuple[str, ...] | None,
) -> dict[str, str | Model]:
    """Parse model roles from CLI args. Supports key-value, YAML, and JSON formats.

    Args:
        model_roles: Tuple of strings to parse as model roles.

    Returns:
        Dictionary of role names to model names or model instances.

    Examples:
        ("grader=mockllm/model",) -> {'grader': 'mockllm/model'}
        ("grader={model: mockllm/model, temperature: 0.5}",) -> {'grader': <Model>}
        ('grader={"model": "mockllm/model", "temperature": 0.5}',) -> {'grader': <Model>}
    """
    from pydantic import ValidationError

    from inspect_ai.model import GenerateConfig, get_model

    try:
        parsed_args = parse_cli_args(model_roles, force_str=False)
    except Exception as e:
        raise ValueError(
            "Could not parse model role arguments. Should be key-value pairs or valid YAML/JSON."
        ) from e
    for role_name, params in parsed_args.items():
        # if value is a dict, create a model instance
        if isinstance(params, dict):
            model_name = params.pop("model", None)
            model_args = params.pop("model_args", {})
            if not isinstance(model_args, dict):
                raise ValueError("model_args must be a dict")
            try:
                config = GenerateConfig(**params)
            except ValidationError as e:
                raise ValueError(
                    f"Invalid config for model role '{role_name}': {e}"
                ) from e
            parsed_args[role_name] = get_model(model_name, config=config, **model_args)
        # else assume it is just a model name and leave it as a string
    return parsed_args


class SectionedCommand(click.Command):
    """Click command that renders options grouped into named sections.

    Each option can be tagged with a section by calling
    `mark_section(option_name, section)` after registration. Tagged
    options render together under a separate header in `--help`;
    untagged options render under the default "Options" header.
    """

    SECTIONS: dict[str, set[str]] = {}
    """Subclasses populate as `{section_title: {option_name, ...}}`."""

    def format_options(
        self, ctx: click.Context, formatter: click.HelpFormatter
    ) -> None:
        # bucket each param into its section (or the default group)
        default: list[tuple[str, str]] = []
        sectioned: dict[str, list[tuple[str, str]]] = {
            title: [] for title in self.SECTIONS
        }

        for param in self.get_params(ctx):
            record = param.get_help_record(ctx)
            if record is None:
                continue
            for title, names in self.SECTIONS.items():
                if param.name in names:
                    sectioned[title].append(record)
                    break
            else:
                default.append(record)

        if default:
            with formatter.section("Options"):
                formatter.write_dl(default)
        for title, records in sectioned.items():
            if records:
                with formatter.section(title):
                    formatter.write_dl(records)


def parse_sandbox(sandbox: str | None) -> SandboxEnvironmentSpec | None:
    from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec

    if sandbox is not None:
        parts = sandbox.split(":", maxsplit=1)
        if len(parts) == 1:
            return SandboxEnvironmentSpec(sandbox)
        else:
            return SandboxEnvironmentSpec(parts[0], parts[1])
    else:
        return None
