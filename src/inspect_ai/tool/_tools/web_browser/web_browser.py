from textwrap import dedent

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._sandbox import SandboxEnvironment, sandbox
from inspect_ai.util._sandbox.docker.internal import INSPECT_WEB_BROWSER_IMAGE

from ..._tool import Tool, tool


def web_browser(sandbox_name: str = "web_browser") -> list[Tool]:
    """Tools used for web browser navigation.

    Args:
      sandbox_name (str): Name of sandbox that the web
        browser is running within. Defaults to
        "web_browser"

    Returns:
       List of tools used for web browser navigation.

    """
    return [web_go(sandbox_name)]


@tool
def web_go(sandbox_name: str = "web_browser") -> Tool:
    """Web Browser tool for navigation to a URL.

    Args:
       sandbox_name (str): Name of sandbox that the web
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
           Accessibility tree of the visible elements of the web page.
        """
        return url

    return execute


async def web_browser_cmd(sandbox_name: str, cmd: str, *args: str) -> str:
    result = await web_browser_sandbox(sandbox_name).exec(
        ["python3", "web_client", cmd] + list(args)
    )

    return result.stdout


def web_browser_sandbox(name: str) -> SandboxEnvironment:
    try:
        return sandbox(name)
    except ValueError as ex:
        if name == "web_browser":
            msg = dedent(f"""
                The web_browser sandbox has not been configured for this task. Please add the web_browser service to your configuration. For example, the following Docker compose file includes the web_browser sandbox:

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
