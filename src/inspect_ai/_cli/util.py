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


def parse_sandbox(sandbox: str | None) -> str | tuple[str, str] | None:
    if sandbox is not None:
        parts = sandbox.split(":", maxsplit=1)
        if len(parts) == 1:
            return sandbox
        else:
            return (parts[0], parts[1])
    else:
        return None
