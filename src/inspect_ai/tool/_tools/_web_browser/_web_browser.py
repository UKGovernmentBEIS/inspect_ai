import re
from textwrap import dedent

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._sandbox import SandboxEnvironment, sandbox_with
from inspect_ai.util._sandbox.docker.internal import INSPECT_WEB_BROWSER_IMAGE_DOCKERHUB
from inspect_ai.util._store import store

from ..._tool import Tool, ToolError, tool
from ..._tool_call import ToolCall, ToolCallContent, ToolCallView
from ..._tool_info import parse_tool_info
from ..._tool_with import tool_with


def web_browser(interactive: bool = True) -> list[Tool]:
    """Tools used for web browser navigation.

    Args:
       interactive (bool): Provide interactive tools (enable
         clicking, typing, and submitting forms). Defaults
         to True.

    Returns:
       List of tools used for web browser navigation.

    """
    # start with go tool (excluding interactive docs if necessary)
    go = web_browser_go()
    if not interactive:
        go = go_without_interactive_docs(go)
    tools = [go]

    # add interactive tools if requested
    if interactive:
        tools = tools + [
            web_browser_click(),
            web_browser_type_submit(),
            web_browser_type(),
        ]

    # add navigational tools
    return tools + [
        web_browser_scroll(),
        web_browser_back(),
        web_browser_forward(),
        web_browser_refresh(),
    ]


@tool(parallel=False)
def web_browser_go() -> Tool:
    """Web Browser tool for navigation to a URL.

    Returns:
       Web browser navigation tool.
    """

    async def execute(url: str) -> str:
        """Navigate the web browser to a URL.

        Once you have navigated to a page, you will be presented with a web accessibilty tree of the elements on the page. Each element has an ID, which is displayed in brackets at the beginning of its line. For example:

        ```
        [1] RootWebArea "Google" [focused: True, url: https://www.google.com/]
          [76] link "About" [url: https://about.google/]
          [85] link "Gmail " [url: https://mail.google.com/mail/&ogbl]
            [4] StaticText "Gmail"
          [91] button "Google apps" [expanded: False]
          [21] combobox "Search" [editable: plaintext, autocomplete: both, hasPopup: listbox, required: False, expanded: False, controls: Alh6id]
        ```

        To execute a Google Search for 'dogs', you would type into the "Search" combobox with element ID 21 and then press ENTER using the web_browser_type_submit tool:

        web_browser_type_submit(21, "dogs")

        You should only attempt to navigate the web browser one page at a time (parallel calls to web browser tools are not permitted).

        Args:
          url (str): URL to navigate to.

        Returns:
          Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_go", url)

    return execute


def go_without_interactive_docs(tool: Tool) -> Tool:
    tool_info = parse_tool_info(tool)
    description_lines = tool_info.description.splitlines()
    description_lines = [
        line for line in description_lines if "web_browser_type_submit" not in line
    ]
    return tool_with(tool, description="\n".join(description_lines))


# custom viewer for interactive tool calls that shows a truncated
# version of current the web accessiblity tree if available

WEB_BROWSER_AT = "web_browser:at"


def web_at_viewer(call: ToolCall) -> ToolCallView:
    # get the web accessiblity tree, if we have it create a view from it
    web_at = store().get(WEB_BROWSER_AT, "")
    element_id = call.arguments.get("element_id", 0)
    if web_at and element_id:
        lines = web_at.splitlines()
        pattern = re.compile(rf"^\s+\[{element_id}\] .*$")
        for i, line in enumerate(lines):
            if pattern.match(line):
                snippet = (
                    lines[0:1]
                    + ["  ..."]
                    + lines[max(i - 2, 1) : i]
                    + [line.replace(" ", "*", 1)]
                    + lines[i + 1 : min(i + 3, len(lines))]
                    + ["  ..."]
                )

                return ToolCallView(
                    context=ToolCallContent(format="text", content="\n".join(snippet))
                )

    # no view found
    return ToolCallView()


@tool(viewer=web_at_viewer, parallel=False)
def web_browser_click() -> Tool:
    """Web Browser tool for clicking an element on a web page.

    Returns:
       Web browser clicking tool.
    """

    async def execute(element_id: int) -> str:
        """Click an element on the page currently displayed by the web browser.

        For example, with the following web accessibilty tree:

        ```
        [304] RootWebArea "Poetry Foundation" [focused: True, url: https://www.poetryfoundation.org/]
          [63] StaticText "POETRY FOUNDATION"
          [427] button "POEMS & POETS" [expanded: False]
          [434] button "FEATURES" [expanded: False]
        ```

        You could click on the "POEMS & POETS" button with:

        web_browser_click(427)

        Args:
           element_id (int): ID of the element to click.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_click", str(element_id))

    return execute


@tool(viewer=web_at_viewer, parallel=False)
def web_browser_type_submit() -> Tool:
    """Web Browser tool for typing and submitting input.

    Returns:
       Web browser type and submit tool.
    """

    async def execute(element_id: int, text: str) -> str:
        """Type text into a form input on a web browser page and press ENTER to submit the form.

        For example, to execute a search for "Yeats" from this page:

        ```
        [2] RootWebArea "Moon - Wikipedia" [focused: True, url: https://en.wikipedia.org/wiki/Moon]
          [91] StaticText "Jump to content"
          [682] button "Main menu" [hasPopup: menu]
          [751] searchbox "Search Wikipedia" [editable: plaintext, keyshortcuts: Alt+f]
          [759] button "Search"
          [796] button "Personal tools" [hasPopup: menu]
        ```

        You would type into the searchbox and press ENTER using the following tool call:

        web_browser_type_submit(751, "Yeats")

        Args:
           element_id (int): ID of the element to type text into.
           text (str): Text to type.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_type_submit", str(element_id), text)

    return execute


@tool(viewer=web_at_viewer, parallel=False)
def web_browser_type() -> Tool:
    """Web Browser tool for typing into inputs.

    Returns:
       Web browser typing tool.
    """

    async def execute(element_id: int, text: str) -> str:
        """Type text into an input on a web browser page.

        For example, to type "Norah" into the "First Name" search box on this page:

        ```
        [106] RootWebArea "My Profile" [focused: True, url: https://profile.example.com]
          [305] link "My library" [url: https://profile.example.com/library]
          [316] textbox "First Name" [focused: True, editable: plaintext, required: False]
          [316] textbox "Last Name" [focused: True, editable: plaintext, required: False]
        ```

        You would use the following command:

        web_browser_type(316, "Norah")

        Note that the web_browser_type_submit tool is typically much more useful than the web_browser_type tool since it enters input and submits the form. You would typically only need to use the web_browser_type tool to fill out forms with multiple inputs.

        Args:
           element_id (int): ID of the element to type text into.
           text (str): Text to type.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_type", str(element_id), text)

    return execute


@tool(parallel=False)
def web_browser_scroll() -> Tool:
    """Web Browser tool for scrolling up or down one page.

    Returns:
       Web browser scrolling tool.
    """

    async def execute(direction: str) -> str:
        """Scroll the web browser up or down by one page.

        Occasionally some very long pages don't display all of their content at once. To see additional content you can scroll the page down with:

        web_browser_scroll("down")

        You can then return to the previous scroll position with:

        web_browser_scroll("up")

        Args:
           direction (str): "up" or "down"

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_scroll", direction)

    return execute


@tool(parallel=False)
def web_browser_back() -> Tool:
    """Web Browser tool for navigating back in the browser history.

    Returns:
       Web browser back navigation tool.
    """

    async def execute() -> str:
        """Navigate the web browser back in the browser history.

        If you want to view a page that you have previously browsed (or perhaps just didn't find what you were looking for on a page and want to backtrack) use the web_browser_back tool.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_back")

    return execute


@tool(parallel=False)
def web_browser_forward() -> Tool:
    """Web Browser tool for navigating forward in the browser history.

    Returns:
       Web browser forward navigation tool.
    """

    async def execute() -> str:
        """Navigate the web browser forward in the browser history.

        If you have navigated back in the browser history and then want to navigate forward use the web_browser_forward tool.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_forward")

    return execute


@tool(parallel=False)
def web_browser_refresh() -> Tool:
    """Web Browser tool for refreshing the current page.

    Returns:
       Web browser page refresh tool.
    """

    async def execute() -> str:
        """Refresh the current page of the web browser.

        If you have interacted with a page by clicking buttons and want to reset it to its original state, use the web_browser_refresh tool.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await web_browser_cmd("web_refresh")

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
            web_at = (
                str(response.get("web_at")) or "(no web accessiblity tree available)"
            )
            store().set(WEB_BROWSER_AT, web_at)
            return web_at
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
                The web browser service was not found in any of the sandboxes for this sample. Please add the web browser service to your configuration. For example, the following Docker compose file uses the {INSPECT_WEB_BROWSER_IMAGE_DOCKERHUB} image as its default sandbox:

                services:
                  default:
                    image: "{INSPECT_WEB_BROWSER_IMAGE_DOCKERHUB}"
                    init: true

                Alternatively, this Docker compose file creates a dedicated image for the web browser service:

                services:
                  default:
                    image: "python:3.12-bookworm"
                    init: true
                    command: "tail -f /dev/null"

                  web_browser:
                    image: "{INSPECT_WEB_BROWSER_IMAGE_DOCKERHUB}"
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
