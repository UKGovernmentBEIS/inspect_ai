"""This module provides the "old" client code for running against the, now deprecated, `aisiuk/inspect-web-browser-tool` image."""

import re
from logging import getLogger
from textwrap import dedent

from pydantic import Field

from inspect_ai._util.content import ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai.tool import ToolError, ToolResult
from inspect_ai.util import SandboxEnvironment, StoreModel, sandbox_with, store_as
from inspect_ai.util._sandbox.docker.internal import (
    INSPECT_WEB_BROWSER_IMAGE_DOCKERHUB_DEPRECATED,
)

logger = getLogger("web_browser")

WEB_CLIENT_REQUEST = "/app/web_browser/web_client.py"
WEB_CLIENT_NEW_SESSION = "/app/web_browser/web_client_new_session.py"


class WebBrowserStore(StoreModel):
    main_content: str = Field(default_factory=str)
    web_at: str = Field(default_factory=str)
    session_id: str = Field(default_factory=str)


async def old_web_browser_cmd(cmd: str, *args: str) -> ToolResult:
    sandbox_env = await _web_browser_sandbox()
    warn_once(
        logger,
        "WARNING: Use of the `aisiuk/inspect-web-browser-tool` image is deprecated. Please update your configuration to use the `aisiuk/inspect-tool-support` image or install the `inspect-tool-support` package into your own image.",
    )

    store = store_as(WebBrowserStore)
    if not store.session_id:
        result = await sandbox_env.exec(
            ["python3", WEB_CLIENT_NEW_SESSION], timeout=180
        )

        if not result.success:
            raise RuntimeError(
                f"Error creating new web browser session: {result.stderr}"
            )

        store.session_id = result.stdout.strip("\n")

    session_flag = f"--session_name={store.session_id}"

    arg_list = None
    if session_flag:
        arg_list = ["python3", WEB_CLIENT_REQUEST, session_flag, cmd] + list(args)
    else:
        arg_list = ["python3", WEB_CLIENT_REQUEST, cmd] + list(args)

    result = await sandbox_env.exec(arg_list, timeout=180)
    if not result.success:
        raise RuntimeError(
            f"Error executing web browser command {cmd}({', '.join(args)}): {result.stderr}"
        )
    else:
        response = _parse_web_browser_output(result.stdout)
        if "error" in response and response.get("error", "").strip() != "":
            raise ToolError(str(response.get("error")) or "(unknown error)")
        elif "web_at" in response:
            main_content = str(response.get("main_content")) or None
            web_at = (
                str(response.get("web_at")) or "(no web accessibility tree available)"
            )
            # Remove base64 data from images.
            web_at_lines = web_at.split("\n")
            web_at_lines = [
                line.partition("data:image/png;base64")[0] for line in web_at_lines
            ]

            store_as(WebBrowserStore).main_content = (
                main_content or "(no main text summary)"
            )
            store_as(WebBrowserStore).web_at = web_at

            web_at = "\n".join(web_at_lines)
            return (
                [
                    ContentText(text=f"main content:\n{main_content}\n\n"),
                    ContentText(text=f"accessibility tree:\n{web_at}"),
                ]
                if main_content
                else web_at
            )
        else:
            raise RuntimeError(
                f"web_browser output must contain either 'error' or 'web_at' field: {result.stdout}"
            )


async def _web_browser_sandbox() -> SandboxEnvironment:
    sb = await sandbox_with(WEB_CLIENT_REQUEST)
    if sb:
        return sb
    else:
        msg = dedent(f"""
                The web browser service was not found in any of the sandboxes for this sample. Please add the web browser service to your configuration. For example, the following Docker compose file uses the {INSPECT_WEB_BROWSER_IMAGE_DOCKERHUB_DEPRECATED} image as its default sandbox:

                services:
                  default:
                    image: "{INSPECT_WEB_BROWSER_IMAGE_DOCKERHUB_DEPRECATED}"
                    init: true

                Alternatively, this Docker compose file creates a dedicated image for the web browser service:

                services:
                  default:
                    image: "python:3.12-bookworm"
                    init: true
                    command: "tail -f /dev/null"

                  web_browser:
                    image: "{INSPECT_WEB_BROWSER_IMAGE_DOCKERHUB_DEPRECATED}"
                    init: true
                """).strip()
        raise PrerequisiteError(msg)


def _parse_web_browser_output(output: str) -> dict[str, str]:
    response: dict[str, str] = dict(
        web_url="", main_content="", web_at="", info="", error=""
    )
    active_field: str | None = None
    active_field_lines: list[str] = []

    def collect_active_field() -> None:
        if active_field is not None:
            response[active_field] = "\n".join(active_field_lines)
        active_field_lines.clear()

    for line in output.splitlines():
        field_match = re.match(
            r"^(error|main_content|web_at|web_url|info)\s*:\s*(.+)$", line
        )
        if field_match:
            collect_active_field()
            active_field = field_match.group(1)
            active_field_lines.append(field_match.group(2))
        else:
            active_field_lines.append(line)
    collect_active_field()

    return response
