from typing import Any

import yaml

from inspect_ai._util.config import resolve_args
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


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
