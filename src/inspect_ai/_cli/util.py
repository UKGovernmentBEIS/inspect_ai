from typing import Any

import yaml


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


def parse_tool_env(tool_environment: str | None) -> str | tuple[str, str] | None:
    if tool_environment is not None:
        parts = tool_environment.split(":", maxsplit=1)
        if len(parts) == 1:
            return tool_environment
        else:
            return (parts[0], parts[1])
    else:
        return None
