import re

from pydantic import BaseModel, Field

from inspect_ai._util.content import ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool._tool import Tool, ToolError, ToolResult, tool
from inspect_ai.tool._tool_call import ToolCall, ToolCallContent, ToolCallView
from inspect_ai.tool._tool_info import parse_tool_info
from inspect_ai.tool._tool_support_helpers import (
    exec_sandbox_rpc,
    tool_container_sandbox,
)
from inspect_ai.tool._tool_with import tool_with
from inspect_ai.util._store_model import StoreModel, store_as

from ._back_compat import old_web_browser_cmd


# These two models are cloned from the container code. If/when we decide to create
# a package that is shared between the inspect and tool-container codebases, we'll
# just have to live with it.
class NewSessionResult(BaseModel):
    session_name: str


class CrawlerResult(BaseModel):
    web_url: str
    main_content: str | None = None
    web_at: str
    error: str | None = None


def web_browser(interactive: bool = True) -> list[Tool]:
    """Tools used for web browser navigation.

     See documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-web-browser>.

    Args:
       interactive: Provide interactive tools (enable
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

    async def execute(url: str) -> ToolResult:
        """Navigate the web browser to a URL.

        Once you have navigated to a page, you will be presented with a web accessibility tree of the elements on the page. Each element has an ID, which is displayed in brackets at the beginning of its line. For example:

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
        return await _web_browser_cmd("web_go", locals())

    return execute


def go_without_interactive_docs(tool: Tool) -> Tool:
    tool_info = parse_tool_info(tool)
    description_lines = tool_info.description.splitlines()
    description_lines = [
        line for line in description_lines if "web_browser_type_submit" not in line
    ]
    return tool_with(tool, description="\n".join(description_lines))


# custom viewer for interactive tool calls that shows a truncated
# version of current the web accessibility tree if available


class WebBrowserStore(StoreModel):
    main_content: str = Field(default_factory=str)
    web_at: str = Field(default_factory=str)
    session_id: str = Field(default_factory=str)


def web_at_viewer(call: ToolCall) -> ToolCallView:
    # get the web accessibility tree, if we have it create a view from it
    web_at = store_as(WebBrowserStore).web_at
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

    async def execute(element_id: int) -> ToolResult:
        """Click an element on the page currently displayed by the web browser.

        For example, with the following web accessibility tree:

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
        return await _web_browser_cmd("web_click", locals())

    return execute


@tool(viewer=web_at_viewer, parallel=False)
def web_browser_type_submit() -> Tool:
    """Web Browser tool for typing and submitting input.

    Returns:
       Web browser type and submit tool.
    """

    async def execute(element_id: int, text: str) -> ToolResult:
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
        return await _web_browser_cmd("web_type_submit", locals())

    return execute


@tool(viewer=web_at_viewer, parallel=False)
def web_browser_type() -> Tool:
    """Web Browser tool for typing into inputs.

    Returns:
       Web browser typing tool.
    """

    async def execute(element_id: int, text: str) -> ToolResult:
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
        return await _web_browser_cmd("web_type", locals())

    return execute


@tool(parallel=False)
def web_browser_scroll() -> Tool:
    """Web Browser tool for scrolling up or down one page.

    Returns:
       Web browser scrolling tool.
    """

    async def execute(direction: str) -> ToolResult:
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
        return await _web_browser_cmd("web_scroll", locals())

    return execute


@tool(parallel=False)
def web_browser_back() -> Tool:
    """Web Browser tool for navigating back in the browser history.

    Returns:
       Web browser back navigation tool.
    """

    async def execute() -> ToolResult:
        """Navigate the web browser back in the browser history.

        If you want to view a page that you have previously browsed (or perhaps just didn't find what you were looking for on a page and want to backtrack) use the web_browser_back tool.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await _web_browser_cmd("web_back", locals())

    return execute


@tool(parallel=False)
def web_browser_forward() -> Tool:
    """Web Browser tool for navigating forward in the browser history.

    Returns:
       Web browser forward navigation tool.
    """

    async def execute() -> ToolResult:
        """Navigate the web browser forward in the browser history.

        If you have navigated back in the browser history and then want to navigate forward use the web_browser_forward tool.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await _web_browser_cmd("web_forward", locals())

    return execute


@tool(parallel=False)
def web_browser_refresh() -> Tool:
    """Web Browser tool for refreshing the current page.

    Returns:
       Web browser page refresh tool.
    """

    async def execute() -> ToolResult:
        """Refresh the current page of the web browser.

        If you have interacted with a page by clicking buttons and want to reset it to its original state, use the web_browser_refresh tool.

        Returns:
           Web accessibility tree of the visible elements of the web page. The element_id of each element is displayed in brackets at the beginning of the line.
        """
        return await _web_browser_cmd("web_refresh", locals())

    return execute


async def _web_browser_cmd(tool_name: str, params: dict[str, object]) -> ToolResult:
    try:
        sandbox_env = await tool_container_sandbox("web browser")
    except PrerequisiteError as e:
        # The user may have the old, incompatible, sandbox. If so, use that and
        # execute the old compatible code.
        try:
            return await old_web_browser_cmd(tool_name, *params)
        except PrerequisiteError:
            raise e

    store = store_as(WebBrowserStore)

    if not store.session_id:
        store.session_id = (
            await exec_sandbox_rpc(
                sandbox_env,
                "web_new_session",
                {"headful": False},
                NewSessionResult,
            )
        ).session_name

    params["session_name"] = store.session_id

    crawler_result = await exec_sandbox_rpc(
        sandbox_env, tool_name, params, CrawlerResult
    )
    if crawler_result.error and crawler_result.error.strip() != "":
        raise ToolError(crawler_result.error)
    else:
        main_content = crawler_result.main_content
        web_at = crawler_result.web_at or "(no web accessibility tree available)"
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
