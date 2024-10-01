import re
from textwrap import dedent

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool._tool import Tool, ToolError, tool
from inspect_ai.util._sandbox import SandboxEnvironment, sandbox_with
from inspect_ai.util._sandbox.docker.internal import INSPECT_WEB_BROWSER_IMAGE


def web_browser_tools() -> list[Tool]:
    """Tools used for web browser navigation.

    Returns:
       List of tools used for web browser navigation.

    """
    return [
        web_browser_go(),
        web_browser_click(),
        web_browser_scroll(),
        web_browser_forward(),
        web_browser_back(),
        web_browser_refresh(),
        web_browser_type(),
        web_browser_type_submit(),
    ]


@tool
def web_browser_go() -> Tool:
    """Web Browser tool for navigation to a URL.

    Returns:
       Web browser navigation tool.
    """

    async def execute(url: str) -> str:
        """Navigate the web browser to a URL.

        Args:
           url (str): URL to navigate to.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_go", url)

    return execute


@tool
def web_browser_click() -> Tool:
    """Web Browser tool for clicking an element on a web page.

    Returns:
       Web browser clicking tool.
    """

    async def execute(element_id: str) -> str:
        """Click an element on the page currently displayed by the web browser.

        Args:
           element_id (str): ID of the element to click.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_click", element_id)

    return execute


@tool
def web_browser_scroll() -> Tool:
    """Web Browser tool for scrolling up or down one page.

    Returns:
       Web browser scrolling tool.
    """

    async def execute(direction: str) -> str:
        """Scroll the web browser up or down by one page.

        Args:
           direction (str): "up" or "down"

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_scroll", direction)

    return execute


@tool
def web_browser_forward() -> Tool:
    """Web Browser tool for navigating forward in the browser history.

    Args:
       sandbox (str): Name of sandbox that the web
         browser is running within. Defaults to
         "web_browser"

    Returns:
       Web browser forward navigation tool.
    """

    async def execute() -> str:
        """Navigate the web browser forward in the browser history.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_forward")

    return execute


@tool
def web_browser_back() -> Tool:
    """Web Browser tool for navigating back in the browser history.

    Returns:
       Web browser back navigation tool.
    """

    async def execute() -> str:
        """Navigate the web browser back in the browser history.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_back")

    return execute


@tool
def web_browser_refresh() -> Tool:
    """Web Browser tool for refreshing the current page.

    Returns:
       Web browser page refresh tool.
    """

    async def execute() -> str:
        """Refresh the current page of the web browser.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_refresh")

    return execute


@tool
def web_browser_type() -> Tool:
    """Web Browser tool for typing into inputs.

    Returns:
       Web browser typing tool.
    """

    async def execute(element_id: str, text: str) -> str:
        """Type text into an input on a web browser page.

        Args:
           element_id (str): ID of the element to type text into.
           text (str): Text to type.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_type", element_id, text)

    return execute


@tool
def web_browser_type_submit() -> Tool:
    """Web Browser tool for typing and submitting input.

    Returns:
       Web browser type and submit tool.
    """

    async def execute(element_id: str, text: str) -> str:
        """Type text into a form input on a web browser page and press ENTER to submit the form.

        Args:
           element_id (str): ID of the element to type text into.
           text (str): Text to type.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_type_submit", element_id, text)

    return execute


WEB_CLIENT_SCRIPT = "/app/web_browser/web_client.py"


async def web_browser_cmd(cmd: str, *args: str) -> str:
    result = await (await web_browser_sandbox()).exec(
        ["python3", WEB_CLIENT_SCRIPT, cmd] + list(args)
    )
    if not result.success:
        raise RuntimeError(
            f"Error executing web browser command {cmd}({', '.join(args)}): {result.stderr}"
        )
    else:
        response = parse_web_browser_output(result.stdout)
        if "web_at" in response:
            return str(response.get("web_at")) or "(no web accessiblity tree available)"
        elif "error" in response:
            raise ToolError(str(response.get("error")) or "(unknown error)")
        else:
            raise RuntimeError(
                f"web_browser output must contain either 'error' or 'web_at' field: {result.stdout}"
            )


async def web_browser_sandbox() -> SandboxEnvironment:
    sb = await sandbox_with(WEB_CLIENT_SCRIPT)
    if sb:
        return sb
    else:
        msg = dedent(f"""
                The web browser service was not found in any of the sandboxes for this sample. Please add the web browser service to your configuration. For example, the following Docker compose file uses the {INSPECT_WEB_BROWSER_IMAGE} image as its default sandbox:

                services:
                  default:
                    image: "{INSPECT_WEB_BROWSER_IMAGE}"
                    init: true

                Alternatively, this Docker compose file creates a dedicated image for the web browser service:

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
