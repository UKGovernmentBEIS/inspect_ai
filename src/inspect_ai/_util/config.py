import json
from typing import Any

import yaml

from inspect_ai.util._resource import resource

from .error import PrerequisiteError
from .file import filesystem


def resolve_args(args: dict[str, Any] | str) -> dict[str, Any]:
    # if its a file, read as JSON or YAML
    if isinstance(args, str):
        fs = filesystem(args)
        if not fs.exists(args):
            raise PrerequisiteError(f"The config file {args} does not exist.")
        args = read_config_object(resource(args, type="file"))

    return args


def parse_cli_args(
    args: tuple[str, ...] | list[str] | None,
    force_str: bool = False,
    split_lists: bool = True,
) -> dict[str, Any]:
    """Parse ``key=value`` CLI arguments into a dictionary.

    Args:
        args: The raw ``key=value`` strings to parse.
        force_str: Coerce every parsed value to ``str``.
        split_lists: When ``True`` (the default), a string value containing
            commas is split into a list (e.g. ``a,b,c`` -> ``["a", "b", "c"]``).
            Set to ``False`` to preserve comma-containing values verbatim, which
            is required for values that are single strings rather than lists
            (e.g. environment variables like ``NO_PROXY=localhost,127.0.0.1``).
    """
    params: dict[str, Any] = dict()
    if args:
        for arg in list(args):
            parts = arg.split("=")
            if len(parts) > 1:
                key = parts[0].replace("-", "_")
                value = yaml.safe_load("=".join(parts[1:]))
                if isinstance(value, str) and split_lists:
                    value = value.split(",")
                    value = value if len(value) > 1 else value[0]
                params[key] = str(value) if force_str else value
    return params


def read_config_object(obj: str) -> dict[str, Any]:
    # detect json vs. yaml
    is_json = obj.strip().startswith("{")
    config = json.loads(obj) if is_json else yaml.safe_load(obj)
    if not isinstance(config, dict):
        raise ValueError(f"The config is not a valid object: {obj}")
    else:
        return config
