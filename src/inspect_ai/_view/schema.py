"""Generate TypeScript types from inspect_ai Python models.

Runs both type generation pipelines:
  1. Old: EvalLog → log-schema.json → json-schema-to-typescript → log.d.ts
  2. New: EvalLog → inspect-openapi.json → openapi-typescript → generated.ts

Usage:
    python src/inspect_ai/_view/schema.py
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import RootModel

from inspect_ai._eval.evalset import EvalSet
from inspect_ai._util.citation import Citation as _Citation
from inspect_ai._util.content import (
    ContentAudioFormat as _ContentAudioFormat,
)
from inspect_ai._util.content import (
    ContentVideoFormat as _ContentVideoFormat,
)
from inspect_ai._util.json import JsonChangeOp as _JsonChangeOp
from inspect_ai._view._openapi import build_openapi_schema
from inspect_ai.event._event import Event as _Event
from inspect_ai.log import EvalLog
from inspect_ai.log._log import EvalSampleLimitType as _EvalSampleLimitType
from inspect_ai.model import ChatMessage as _ChatMessage
from inspect_ai.model import Content as _Content
from inspect_ai.tool._tool_choice import ToolChoice as _ToolChoice

# RootModel wrappers give stable schema names to type aliases (unions, literals)
# that would otherwise be inlined with auto-generated, unstable names. The class
# name becomes the key in components/schemas. Original types are imported with _
# prefix aliases above to free up the bare names.
# See design/type-generation-pipeline.md.


class Content(RootModel[_Content]):
    pass


class ChatMessage(RootModel[_ChatMessage]):
    pass


class Event(RootModel[_Event]):
    pass


class Citation(RootModel[_Citation]):
    pass


class ToolChoice(RootModel[_ToolChoice]):
    pass


class JsonChangeOp(RootModel[_JsonChangeOp]):
    pass


class EvalSampleLimitType(RootModel[_EvalSampleLimitType]):
    pass


class ContentAudioFormat(RootModel[_ContentAudioFormat]):
    pass


class ContentVideoFormat(RootModel[_ContentVideoFormat]):
    pass


VIEW_DIR = Path(__file__).parent
TS_MONO_DIR = os.path.abspath((VIEW_DIR / "ts-mono").as_posix())
APP_DIR = os.path.abspath((VIEW_DIR / "ts-mono" / "apps" / "inspect").as_posix())
OUTPUT_PATH = VIEW_DIR / "inspect-openapi.json"


def _generate_old() -> None:
    """Generate JSON schema and TypeScript types for EvalLog via json-schema-to-typescript."""
    schema_path = VIEW_DIR / "log-schema.json"

    with open(schema_path, "w", encoding="utf-8") as f:
        eval_set = EvalSet.model_json_schema()
        schema = EvalLog.model_json_schema()
        defs: dict[str, Any] = schema["$defs"]

        defs["EvalSetInfo"] = eval_set
        if "$defs" in eval_set:
            defs.update(eval_set["$defs"])

        if "properties" not in schema:
            schema["properties"] = {}
        schema["properties"]["eval_set_info"] = {
            "anyOf": [{"$ref": "#/$defs/EvalSetInfo"}, {"type": "null"}],
            "default": None,
        }

        for key in defs.keys():
            defs[key] = _schema_to_strict(defs[key])
        f.write(json.dumps(schema, indent=2))
        f.write("\n")

        subprocess.run(
            ["pnpm", "types:generate"],
            cwd=APP_DIR,
            check=True,
        )


def _generate_new() -> None:
    """Generate OpenAPI schema and TypeScript types for inspect_ai.

    Stub endpoints pull type dependency trees into the schema. RootModel
    wrappers give stable names to unions and literals.

    See design/type-generation-pipeline.md for the full pipeline docs.
    """
    app = FastAPI(title="inspect_ai types", version="0.1.0")

    # Stub endpoints for schema generation — not served by the real API.

    @app.get("/eval-log")
    def _eval_log() -> EvalLog:
        raise NotImplementedError

    @app.get("/eval-set")
    def _eval_set() -> EvalSet:
        raise NotImplementedError

    @app.get("/content")
    def _content() -> Content:
        raise NotImplementedError

    @app.get("/chat-message")
    def _chat_message() -> ChatMessage:
        raise NotImplementedError

    @app.get("/event")
    def _event() -> Event:
        raise NotImplementedError

    @app.get("/citation")
    def _citation() -> Citation:
        raise NotImplementedError

    @app.get("/tool-choice")
    def _tool_choice() -> ToolChoice:
        raise NotImplementedError

    @app.get("/json-change-op")
    def _json_change_op() -> JsonChangeOp:
        raise NotImplementedError

    @app.get("/eval-sample-limit-type")
    def _eval_sample_limit_type() -> EvalSampleLimitType:
        raise NotImplementedError

    @app.get("/content-audio-format")
    def _content_audio_format() -> ContentAudioFormat:
        raise NotImplementedError

    @app.get("/content-video-format")
    def _content_video_format() -> ContentVideoFormat:
        raise NotImplementedError

    schema = build_openapi_schema(app)

    with OUTPUT_PATH.open("w") as f:
        json.dump(schema, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Wrote {OUTPUT_PATH.relative_to(VIEW_DIR.parent.parent.parent)}")

    subprocess.run(
        ["pnpm", "--filter", "@tsmono/inspect-common", "types:generate"],
        cwd=TS_MONO_DIR,
        check=True,
    )


def _schema_to_strict(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", None)
    if properties:
        schema["required"] = list(properties.keys())
        schema["additionalProperties"] = False
    return schema


if __name__ == "__main__":
    _generate_old()
    _generate_new()
