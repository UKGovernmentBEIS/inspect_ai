"""A crawler implementation using Playwright.

Portions based on  https://github.com/web-arena-x/webarena
"""

from __future__ import annotations

import asyncio
import re
import typing
from typing import Literal

from playwright.async_api import CDPSession, Frame, Page

from inspect_tool_support._remote_tools._web_browser.accessibility_tree import (
    AccessibilityTree,
    create_accessibility_tree,
)
from inspect_tool_support._remote_tools._web_browser.accessibility_tree_node import (
    AccessibilityTreeNode,
)
from inspect_tool_support._remote_tools._web_browser.cdp.a11y import AXNodeId, AXTree
from inspect_tool_support._remote_tools._web_browser.cdp.dom_snapshot import DOMSnapshot
from inspect_tool_support._remote_tools._web_browser.rectangle import Rectangle

# Number of seconds to wait for possible click induced navigation before proceeding
_WAIT_FOR_NAVIGATION_TIME = 2.0

# The waiting strategy to use between browser commands.
# see https://playwright.dev/docs/api/class-page.
_WAIT_STRATEGY: Literal["domcontentloaded"] = "domcontentloaded"


class PageCrawler:
    @classmethod
    async def create(
        cls, page: Page, device_scale_factor: float | None = None
    ) -> PageCrawler:
        # Enable chrome development tools, and accessibility tree output.
        cdp_session = await page.context.new_cdp_session(page)
        await cdp_session.send("Accessibility.enable")
        return PageCrawler(
            page,
            cdp_session,
            device_scale_factor or await page.evaluate("window.devicePixelRatio"),
        )

    def __init__(
        self, page: Page, cdp_session: CDPSession, device_scale_factor: float
    ) -> None:
        self._page = page
        self._cdp_session = cdp_session

        # Start with an empty accessibility tree
        self._rendered_main_content: str | None = None
        self._rendered_accessibility_tree: str = ""
        self._accessibility_tree: AccessibilityTree | None = None
        self._device_scale_factor = device_scale_factor

    @property
    def page(self) -> Page:
        return self._page

    @property
    def url(self) -> str:
        return self._page.url

    def lookup_node(self, node_id_or_tag: int | str) -> AccessibilityTreeNode:
        """Looks up the node by id or tag.

        Args:
          node_id_or_tag: Either the id number (as int or str), or <tag_name>

        Returns:
          AccessibilityNode.

        Raise:
          LookupError if node is not matched.
        """
        node: AccessibilityTreeNode | None = None
        node_id_or_tag = str(node_id_or_tag)
        nodes = self._accessibility_tree["nodes"] if self._accessibility_tree else {}
        if re.match("^<.*>", node_id_or_tag):
            tag = node_id_or_tag[1:-1].lower()
            # This is a smart tag, try to resolve it.
            if node := next(
                # We match on anything that starts with the code, this is potentially
                # a little brittle, can be replaced with an RE if there are issues.
                (
                    n
                    for n in nodes.values()
                    if n.name.lower().startswith(tag) and not n.is_ignored
                ),
                None,
            ):
                return node
            else:
                raise LookupError(
                    f"Could not find tag {node_id_or_tag} from {[node.name for node in nodes.values() if node.name]}"
                )
        else:
            if (
                node := nodes.get(AXNodeId(node_id_or_tag), None)
            ) and not node.is_ignored:
                return node
            else:
                raise LookupError(f"Could not find element with id {node_id_or_tag}")

    async def update(self) -> None:
        """Updates the accessibility tree and DOM from current page."""
        await self._page.wait_for_load_state(_WAIT_STRATEGY)

        available_retries = 2
        retry_delay = 0.25
        while available_retries:
            self._accessibility_tree = create_accessibility_tree(
                ax_nodes=AXTree(
                    **await self._cdp_session.send("Accessibility.getFullAXTree", {})
                ).nodes,
                dom_snapshot=DOMSnapshot(
                    **await self._cdp_session.send(
                        "DOMSnapshot.captureSnapshot",
                        {
                            "computedStyles": [],
                            "includeDOMRects": True,
                        },
                    )
                ),
                device_scale_factor=self._device_scale_factor,
                window_bounds=Rectangle(
                    await self._page.evaluate("window.pageXOffset"),
                    await self._page.evaluate("window.pageYOffset"),
                    await self._page.evaluate("window.screen.width"),
                    await self._page.evaluate("window.screen.height"),
                ),
            )

            self._rendered_main_content, self._rendered_accessibility_tree = (
                (
                    self._accessibility_tree["root"].render_main_content(),
                    self._accessibility_tree["root"].render_accessibility_tree(),
                )
                if self._accessibility_tree
                else (None, "")
            )

            if self._rendered_accessibility_tree:
                return
            # sometimes, the entire tree is initially ignored. in such cases, it's typically
            # because we're sampling too soon. Waiting a small amount of time and trying again
            # resolves the issue.
            available_retries = available_retries - 1
            await asyncio.sleep(retry_delay)

    async def auto_click_cookies(self) -> None:
        """Autoclick any cookies popup."""
        try:
            accept_node = self.lookup_node("<Accept all>")
        except LookupError:
            return
        await self.click(accept_node.node_id)
        await self.update()

    def render_at(self) -> str:
        """Returns the current webpage accessibility tree.

        Only elements visible on the screen will be rendered.
        """
        return self._rendered_accessibility_tree

    def render_main_content(self) -> str | None:
        return self._rendered_main_content

    async def go_to_url(self, url: str) -> None:
        """Goes to the given url.

        Args:
          url: The url to redirect crawler to.
        """
        if "://" not in url:
            url = f"https://{url}"
        try:
            await self._page.goto(url, wait_until=_WAIT_STRATEGY)
        except Exception as e:
            print(f"caught {e}")
            raise

    async def click(self, element_id: int | str) -> None:
        """Clicks the element with the given id.

        Args:
          element_id: The id for the element we want to click on.
        """
        element = self.lookup_node(element_id)
        if element.bounds is None:
            raise LookupError(f"Element with id {element_id} has no layout info.")

        # Mouse.click() requires coordinates relative to the viewport:
        # https://playwright.dev/python/docs/api/class-mouse#mouse-click,
        # thus adjusting the Y coordinate since we only scroll up/down.
        x = element.bounds.center_x
        y = element.bounds.center_y - await self._page.evaluate("window.scrollY")

        await self._await_navigation_after_action(lambda: self._page.mouse.click(x, y))

    async def clear(self, element_id: int | str) -> None:
        """Clears text within a field."""
        await self.click(element_id)
        await self._page.keyboard.press("Control+A")
        await self._page.keyboard.press("Backspace")

    async def type(self, element_id: int | str, text: str) -> None:
        """Types into the element with the given id."""
        await self.click(element_id)
        await self._page.keyboard.type(text)

    async def submit(self, element_id: int | str, text: str) -> None:
        await self.clear(element_id)
        await self._await_navigation_after_action(
            lambda: self._page.keyboard.type(text + "\n")
        )

    async def scroll(self, direction: Literal["up", "down"]) -> None:
        """Scrolls the page to the given direction.

        Args:
          direction: The direction to scroll in ('up' or 'down')
        """
        match direction.lower():
            case "up":
                await self._page.evaluate(
                    "(document.scrollingElement || document.body).scrollTop ="
                    " (document.scrollingElement || document.body).scrollTop -"
                    " window.innerHeight;"
                )
            case "down":
                await self._page.evaluate(
                    "(document.scrollingElement || document.body).scrollTop ="
                    " (document.scrollingElement || document.body).scrollTop +"
                    " window.innerHeight;"
                )

            case _:
                raise ValueError(f"Invalid scroll direction {direction}")

    async def forward(self) -> None:
        """Move browser forward one history step."""
        await self._page.go_forward(wait_until=_WAIT_STRATEGY)

    async def back(self) -> None:
        """Move browser backward one history step."""
        await self._page.go_back(wait_until=_WAIT_STRATEGY)

    async def refresh(self) -> None:
        """Refresh (reload) the page."""
        await self._page.reload(wait_until=_WAIT_STRATEGY)

    async def _await_navigation_after_action(
        self, action: typing.Callable[[], typing.Awaitable[None]]
    ) -> None:
        """
        Performs the specified action and waits for navigation (if any) to occur.

        This function sets up event listeners to detect in-page navigation or
        new page navigation, performs the provided action, and waits for the
        navigation to complete within the specified timeout period.

        The point of this is to allow enough time to switch our page in the
        event of a new page being opened. The problem is that it takes some
        amount of time, and the challenge is determining how long to wait.

        A naïve approach would simply sleep for some amount of time. However,
        this time may not be long enough AND it would delay the common case by
        that delay waiting for a new page navigation that never comes.

        This approach accomplishes waiting the minimal amount of time in the
        common cases of an action inducing an in-page or new page navigation.
        The downside is that actions that do not induce navigation are delayed
        by the timeout. Since navigating actions are much more common, this is a
        reasonable approach.

        Args:
            action: A no-argument async callable that will be executed and may trigger navigation
        """
        future = asyncio.Future[None]()

        async def on_in_page_navigation(_frame: Frame) -> None:
            if not future.done():
                await self._page.wait_for_load_state(_WAIT_STRATEGY)
                future.set_result(None)

        async def on_new_page(new_page: Page) -> None:
            if not future.done():
                await new_page.wait_for_load_state(_WAIT_STRATEGY)
                future.set_result(None)

        self._page.once("framenavigated", on_in_page_navigation)
        self._page.context.once("page", on_new_page)

        await action()

        try:
            await asyncio.wait_for(future, timeout=_WAIT_FOR_NAVIGATION_TIME)
            # a navigation of some sort has occurred and gotten to domcontentloaded
        except (asyncio.TimeoutError, TimeoutError):
            # No navigation occurred within the timeout period
            pass
