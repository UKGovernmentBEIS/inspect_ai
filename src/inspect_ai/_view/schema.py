import json
import os
import subprocess
from pathlib import Path
from typing import Any

from inspect_ai._eval.evalset import EvalSet
from inspect_ai.log import EvalLog

VIEW_DIR = Path(__file__).parent
APP_DIR = os.path.abspath((VIEW_DIR / "ts-mono" / "apps" / "inspect").as_posix())


def sync_view_schema() -> None:
    """Generate a JSON schema and Typescript types for EvalLog.

    This is useful for keeping log file viewer JS development
    in sync w/ Python development
    """
    # export schema file
    schema_path = VIEW_DIR / "log-schema.json"

    with open(schema_path, "w", encoding="utf-8") as f:
        # make everything required
        eval_set = EvalSet.model_json_schema()
        schema = EvalLog.model_json_schema()
        defs: dict[str, Any] = schema["$defs"]

        # Add EvalSetInfo to definitions and reference it in root schema
        defs["EvalSetInfo"] = eval_set
        if "$defs" in eval_set:
            defs.update(eval_set["$defs"])

        # Add optional EvalSetInfo reference to root schema for TypeScript generation
        if "properties" not in schema:
            schema["properties"] = {}
        schema["properties"]["eval_set_info"] = {
            "anyOf": [{"$ref": "#/$defs/EvalSetInfo"}, {"type": "null"}],
            "default": None,
        }

        for key in defs.keys():
            defs[key] = schema_to_strict(defs[key])
        f.write(json.dumps(schema, indent=2))
        f.write("\n")

        # generate types w/ json-schema-to-typescript
        subprocess.run(
            ["pnpm", "types:generate"],
            cwd=APP_DIR,
            check=True,
        )


def schema_to_strict(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", None)
    if properties:
        schema["required"] = list(properties.keys())
        schema["additionalProperties"] = False

    return schema


if __name__ == "__main__":
    sync_view_schema()
