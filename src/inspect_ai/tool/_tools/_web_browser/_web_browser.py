import re
from textwrap import dedent

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._sandbox import SandboxEnvironment, sandbox
from inspect_ai.util._sandbox.docker.internal import INSPECT_WEB_BROWSER_IMAGE

from ..._tool import Tool, ToolError, tool


def web_browser_tools(sandbox: str = "web_browser") -> list[Tool]:
    """Tools used for web browser navigation.

    Args:
      sandbox (str): Name of sandbox that the web
        browser is running within. Defaults to
        "web_browser"

    Returns:
       List of tools used for web browser navigation.

    """
    return [
        web_browser_go(sandbox),
        web_browser_click(sandbox),
        web_browser_scroll(sandbox),
        web_browser_forward(sandbox),
        web_browser_back(sandbox),
        web_browser_refresh(sandbox),
        web_browser_type(sandbox),
        web_browser_type_submit(sandbox),
    ]


@tool
def web_browser_go(sandbox: str = "web_browser") -> Tool:
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
           Web accessibility tree of the visible elements of the web page. The
           node_id of each element is displayed in brackets at the beginning
           of the line.
        """
        return await web_browser_cmd(sandbox, "web_go", url)

    return execute


@tool
def web_browser_click(sandbox: str = "web_browser") -> Tool:
    """Web Browser tool for clicking an element on a web page.

    Args:
       sandbox (str): Name of sandbox that the web
         browser is running within. Defaults to
         "web_browser"

    Returns:
       Web browser clicking tool.
    """

    async def execute(node_id: str) -> str:
        """Click an element on the page currently displayed by the web browser.

        Args:
           node_id (str): ID of the node to click.

        Returns:
           Web accessibility tree of the visible elements of the web page. The
           node_id of each element is displayed in brackets at the beginning
           of the line.
        """
        return await web_browser_cmd(sandbox, "web_click", node_id)

    return execute


@tool
def web_browser_scroll(sandbox: str = "web_browser") -> Tool:
    """Web Browser tool for scrolling up or down one page.

    Args:
       sandbox (str): Name of sandbox that the web
         browser is running within. Defaults to
         "web_browser"

    Returns:
       Web browser scrolling tool.
    """

    async def execute(direction: str) -> str:
        """Scroll the web browser up or down by one page.

        Args:
           direction (str): "up" or "down"

        Returns:
           Web accessibility tree of the visible elements of the web page. The
           node_id of each element is displayed in brackets at the beginning
           of the line.
        """
        return await web_browser_cmd(sandbox, "web_scroll", direction)

    return execute


@tool
def web_browser_forward(sandbox: str = "web_browser") -> Tool:
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
           Web accessibility tree of the visible elements of the web page. The
           node_id of each element is displayed in brackets at the beginning
           of the line.
        """
        return await web_browser_cmd(sandbox, "web_forward")

    return execute


@tool
def web_browser_back(sandbox: str = "web_browser") -> Tool:
    """Web Browser tool for navigating back in the browser history.

    Args:
       sandbox (str): Name of sandbox that the web
         browser is running within. Defaults to
         "web_browser"

    Returns:
       Web browser back navigation tool.
    """

    async def execute() -> str:
        """Navigate the web browser back in the browser history.

        Returns:
           Web accessibility tree of the visible elements of the web page. The
           node_id of each element is displayed in brackets at the beginning
           of the line.
        """
        return await web_browser_cmd(sandbox, "web_back")

    return execute


@tool
def web_browser_refresh(sandbox: str = "web_browser") -> Tool:
    """Web Browser tool for refreshing the current page.

    Args:
       sandbox (str): Name of sandbox that the web
         browser is running within. Defaults to
         "web_browser"

    Returns:
       Web browser page refresh tool.
    """

    async def execute() -> str:
        """Refresh the current page of the web browser.

        Returns:
           Web accessibility tree of the visible elements of the web page. The
           node_id of each element is displayed in brackets at the beginning
           of the line.
        """
        return await web_browser_cmd(sandbox, "web_refresh")

    return execute


@tool
def web_browser_type(sandbox: str = "web_browser") -> Tool:
    """Web Browser tool for typing into inputs.

    Args:
       sandbox (str): Name of sandbox that the web
         browser is running within. Defaults to
         "web_browser"

    Returns:
       Web browser typing tool.
    """

    async def execute(node_id: str, text: str) -> str:
        """Type text into an input on a web browser page.

        Args:
           node_id (str): ID of the node to type text into.
           text (str): Text to type.

        Returns:
           Web accessibility tree of the visible elements of the web page. The
           node_id of each element is displayed in brackets at the beginning
           of the line.
        """
        return await web_browser_cmd(sandbox, "web_type", node_id, text)

    return execute


@tool
def web_browser_type_submit(sandbox: str = "web_browser") -> Tool:
    """Web Browser tool for typing and submitting input.

    Args:
       sandbox (str): Name of sandbox that the web
         browser is running within. Defaults to
         "web_browser"

    Returns:
       Web browser type and submit tool.
    """

    async def execute(node_id: str, text: str) -> str:
        """Type text into a form input on a web browser page and press ENTER to submit the form.

        Args:
           node_id (str): ID of the node to type text into.
           text (str): Text to type.

        Returns:
           Web accessibility tree of the visible elements of the web page. The
           node_id of each element is displayed in brackets at the beginning
           of the line.
        """
        return await web_browser_cmd(sandbox, "web_type_submit", node_id, text)

    return execute


async def web_browser_cmd(sandbox: str, cmd: str, *args: str) -> str:
    result = await web_browser_sandbox(sandbox).exec(
        ["python3", "/app/web_browser/web_client.py", cmd] + list(args)
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
