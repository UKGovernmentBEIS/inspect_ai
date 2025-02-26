import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from inspect_ai.log import EvalLog

WWW_DIR = os.path.abspath((Path(__file__).parent / "www").as_posix())


def sync_view_schema() -> None:
    """Generate a JSON schema and Typescript types for EvalLog.

    This is useful for keeping log file viewer JS development
    in sync w/ Python development
    """
    # export schema file
    schema_path = Path(WWW_DIR, "log-schema.json")
    types_path = Path(WWW_DIR, "src", "types", "log.d.ts")
    vs_code_types_path = Path(
        WWW_DIR, "..", "..", "..", "..", "tools", "vscode", "src", "@types", "log.d.ts"
    )

    with open(schema_path, "w", encoding="utf-8") as f:
        # make everything required
        schema = EvalLog.model_json_schema()
        defs: dict[str, Any] = schema["$defs"]
        for key in defs.keys():
            defs[key] = schema_to_strict(defs[key])
        f.write(json.dumps(schema, indent=2))

        # generate types w/ json-schema-to-typescript
        subprocess.run(
            [
                "yarn",
                "json2ts",
                "--input",
                schema_path,
                "--output",
                types_path,
                "--additionalProperties",
                "false",
            ],
            cwd=WWW_DIR,
        )

        subprocess.run(["yarn", "prettier:write"], cwd=types_path.parent)

        shutil.copyfile(types_path, vs_code_types_path)


def schema_to_strict(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", None)
    if properties:
        schema["required"] = list(properties.keys())
        schema["additionalProperties"] = False

    return schema


if __name__ == "__main__":
    sync_view_schema()
