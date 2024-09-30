import re
from textwrap import dedent

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._sandbox import SandboxEnvironment, sandbox
from inspect_ai.util._sandbox.docker.internal import INSPECT_WEB_BROWSER_IMAGE

from ..._tool import Tool, ToolError, tool


def web_browser(sandbox: str = "web_browser") -> list[Tool]:
    """Tools used for web browser navigation.

    Args:
      sandbox (str): Name of sandbox that the web
        browser is running within. Defaults to
        "web_browser"

    Returns:
       List of tools used for web browser navigation.

    """
    return [web_go(sandbox)]


@tool
def web_go(sandbox: str = "web_browser") -> Tool:
    """Web Browser tool for navigation to a URL.

    Args:
       sandbox (str): Name of sandbox that the web
         browser is running within. Defaults to
         "web_browser"

    Returns:
       Web browser navigation tool.
    """

    async def execute(url: str) -> str:
        """Navigate the web browser to a URL.

        Args:
           url (str): URL to navigate to.

        Returns:
           Web accessibility tree of the visible elements of the web page.
        """
        return await web_browser_cmd(sandbox, "web_go", url)

    return execute


async def web_browser_cmd(sandbox: str, cmd: str, *args: str) -> str:
    result = await web_browser_sandbox(sandbox).exec(
        ["python3", "web_client.py", cmd] + list(args)
    )
    if not result.success:
        raise RuntimeError(
            f"Error executing web browser command {cmd}({', '.join(args)}): {result.stderr}"
        )
    else:
        response = parse_web_browser_output(result.stdout)
        if "web_at" in response:
            return str(response.get("web_at"))
        elif "error" in response:
            raise ToolError(str(response.get("error")))
        else:
            raise RuntimeError(
                f"web_browser output must contain either 'error' or 'web_at' field: {result.stdout}"
            )


def web_browser_sandbox(name: str) -> SandboxEnvironment:
    try:
        return sandbox(name)
    except ValueError as ex:
        if name == "web_browser":
            msg = dedent(f"""
                The web_browser service has not been configured for this task. Please add the web_browser service to your configuration. For example, the following Docker compose file includes the web_browser service:

                services:
                  default:
                    image: "python:3.12-bookworm"
                    init: true
                    command: "tail -f /dev/null"

                  web_browser:
                    image: "{INSPECT_WEB_BROWSER_IMAGE}"
                    init: true
                """).strip()
            raise PrerequisiteError(msg)
        else:
            raise ex


def parse_web_browser_output(output: str) -> dict[str, str]:
    response: dict[str, str] = dict(web_url="", web_at="", info="", error="")
    active_field: str | None = None
    active_field_lines: list[str] = []

    def collect_active_field() -> None:
        if active_field is not None:
            response[active_field] = "\n".join(active_field_lines)
        active_field_lines.clear()

    for line in output.splitlines():
        field_match = re.match(r"^(error|web_at|web_url|info)\s*:\s*(.+)$", line)
        if field_match:
            collect_active_field()
            active_field = field_match.group(1)
            active_field_lines.append(field_match.group(2))
        else:
            active_field_lines.append(line)
    collect_active_field()

    return response
