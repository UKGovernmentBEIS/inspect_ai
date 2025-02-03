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


def read_config_object(obj: str) -> dict[str, Any]:
    # detect json vs. yaml
    is_json = obj.strip().startswith("{")
    config = json.loads(obj) if is_json else yaml.safe_load(obj)
    if not isinstance(config, dict):
        raise ValueError(f"The config is not a valid object: {obj}")
    else:
        return config
