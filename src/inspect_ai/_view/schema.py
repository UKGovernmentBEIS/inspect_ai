"""Generate TypeScript types from inspect_ai Python models.

Generates OpenAPI schema and TypeScript types:
  EvalLog → inspect-openapi.json → openapi-typescript → generated.ts

Usage:
    python src/inspect_ai/_view/schema.py
"""

import json
import os
import subprocess
from pathlib import Path

from pydantic import RootModel

from inspect_ai._util.citation import Citation as _Citation
from inspect_ai._view._openapi import build_openapi_schema
from inspect_ai._view.fastapi_server import view_server_app
from inspect_ai.event._event import Event as _Event
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


VIEW_DIR = Path(__file__).parent
TS_MONO_DIR = os.path.abspath((VIEW_DIR / "ts-mono").as_posix())
OUTPUT_PATH = VIEW_DIR / "inspect-openapi.json"


def _generate_new() -> None:
    """Generate OpenAPI schema and TypeScript types for inspect_ai.

    Uses the real server app (which has response_model on typed endpoints)
    plus stub endpoints for RootModel wrappers that give stable names to
    unions and literals.

    See design/type-generation-pipeline.md for the full pipeline docs.
    """
    app = view_server_app()
    app.title = "inspect_ai types"
    app.version = "0.1.0"

    # Stub endpoints for RootModel wrappers — not served by the real API.

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


if __name__ == "__main__":
    _generate_new()
