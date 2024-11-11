"""A crawler implementation using Playwright.

Largely based on  https://github.com/web-arena-x/webarena
"""

from __future__ import annotations

import enum
import logging
import re
import time
from os import getenv
from typing import Any, Literal

import accessibility_node as at
from playwright.sync_api import sync_playwright

# Number of seconds to wait for page to load before processing it.
WAIT_FOR_PAGE_TIME = 2.0

# The waiting strategy to use between browser commands.
# see https://playwright.dev/docs/api/class-page.
WAIT_STRATEGY = "domcontentloaded"


class CrawlerOutputFormat(enum.Enum):
    # Raw HTML.
    HTML = 0
    # Raw Document Object Model.
    DOM = 1
    # Accessibility tree.
    AT = 2
    # A pixel-based rending of the webpage.
    PIXELS = 3


class PlaywrightBrowser:
    """Stores the browser and creates new contexts."""

    WIDTH = 1280
    HEIGHT = 1080
    _playwright_api = None

    def __init__(self):
        """Creates the browser."""
        if PlaywrightBrowser._playwright_api is None:
            PlaywrightBrowser._playwright_api = sync_playwright().start()

        logging.info("Starting chromium in headless mode.")

        self._browser = PlaywrightBrowser._playwright_api.chromium.launch(
            headless=True,
            # Required for Gmail signup see
            # https://stackoverflow.com/questions/65139098/how-to-login-to-google-account-with-playwright
            args=["--disable-blink-features=AutomationControlled"],
        )

    def get_new_context(self):
        return self._browser.new_context(
            geolocation={"longitude": -0.12, "latitude": 51},
            locale="en-GB",
            permissions=["geolocation"],
            timezone_id="Europe/London",
            viewport={"width": self.WIDTH, "height": self.HEIGHT},
            ignore_https_errors=getenv("IGNORE_HTTPS_ERRORS", "") != "",
        )

    def close(self):
        self._browser.close()
        if PlaywrightBrowser._playwright_api is not None:
            PlaywrightBrowser._playwright_api.stop()
            PlaywrightBrowser._playwright_api = None


class PlaywrightCrawler:
    """Stores the accessibility tree."""

    def __init__(self, browser_context):
        """Initialize the craweler."""
        self._context = browser_context

        self._page = None
        self._client = None
        self._root = None
        self._nodes = {}
        self._dom_tree = None

        self._initialize_context()

    def _initialize_context(self):
        """Creates playwright page, and client."""
        if self._page:
            # Close the previous page if it was open.
            self._page.close()

        self._page = self._context.new_page()

        # Enable chrome development tools, and accessabiltiy tree output.
        self._client = self._page.context.new_cdp_session(self._page)
        self._client.send("Accessibility.enable")

        # Start with an empty accessibility tree and DOM.
        self._root = None
        self._nodes = {}
        self._dom_tree = None

    def lookup_node(
        self, node_id_or_tag: int | str, include_ignored: bool = False
    ) -> at.AccessibilityNode:
        """Looks up the node by id or tag.

        Args:
          node_id_or_tag: Either the id number (as int or str), or <tag_name>
          include_ignored: If true will also lookup ignored (hidden) node.

        Returns:
          Node.

        Raise:
          Value error if node is not matched.
        """
        if re.match("^<.*>", str(node_id_or_tag)):
            tag = node_id_or_tag[1:-1]
            # This is a smart tag, try to resolve it.
            for node in self._nodes.values():
                # We match on anything that starts with the code, this is potentially
                # a little brittle, can be replaced with an RE if there are issues.
                if node.name.lower().startswith(tag.lower()):
                    if not node.is_ignored or include_ignored:
                        return node
            else:
                raise ValueError(
                    f"Could not find tag {node_id_or_tag} from"
                    + f" {[node.name for node in self._nodes.values() if node.name]}"
                )
        else:
            node_id = str(node_id_or_tag)
            node = self._nodes.get(node_id, None)
            if node and (include_ignored or not node.is_ignored):
                return node
            else:
                raise ValueError(f"Could not find element with id {node_id}")

    def update(self):
        """Updates the accessibility tree and DOM from current page."""
        # Wait for page to load.
        self._page.wait_for_load_state(WAIT_STRATEGY)
        time.sleep(WAIT_FOR_PAGE_TIME)

        # Get the DOM
        self._dom_tree = self._client.send(
            "DOMSnapshot.captureSnapshot",
            {
                "computedStyles": [],
                "includeDOMRects": True,
                "includePaintOrder": True,
            },
        )

        at_nodes = self._client.send("Accessibility.getFullAXTree", {})["nodes"]

        document = self._dom_tree["documents"][0]
        nodes = document["nodes"]
        layouts = document["layout"]
        srcs = nodes["currentSourceURL"]
        backendnode_ids = nodes["backendNodeId"]
        strings = self._dom_tree["strings"]

        text_value = nodes["textValue"]

        # Check current screen bounds.
        win_upper_bound = self._page.evaluate("window.pageYOffset")
        win_left_bound = self._page.evaluate("window.pageXOffset")
        win_width = self._page.evaluate("window.screen.width")
        win_height = self._page.evaluate("window.screen.height")
        window_bounds = at.NodeBounds(
            win_left_bound, win_upper_bound, win_width, win_height
        )

        # We have ids for the DOM and for the AT, and need to map between them.
        dom_to_at = {}

        # Build the AT tree.
        self._nodes: dict[str, at.AccessibilityNode] = {}
        self._root = None
        for at_node in at_nodes:
            node = at.AccessibilityNode(at_node)
            self._nodes[node.node_id] = node
            if not node.is_ignored:
                self._root = self._root or node
            dom_to_at[node.dom_id] = node.node_id
            # Default node to invisible. For it to be made visible it must turn up in
            # the layout below.
            node["is_visible"] = False
            # Also keep track of any AT nodes that did not show up in the DOM tree.
            node["is_matched"] = False

        # Create a lookup so that the matching below is not O(n^2)
        backend_index_lookup = {idx: index for index, idx in enumerate(backendnode_ids)}

        layout_from_backend = {}
        for i, key in enumerate(layouts["nodeIndex"]):
            layout_from_backend[key] = {
                k: layouts[k][i]
                for k in layouts.keys()
                if len(layouts[k]) == len(layouts["nodeIndex"])
            }

        text_from_backend = {
            index: value
            for index, value in zip(text_value["index"], text_value["value"])
        }

        src_from_backend = {
            index: value for index, value in zip(srcs["index"], srcs["value"])
        }

        # Set element bounds and visibility.
        # To do this we first lookup the position of an AT node's dom_id in the
        # backendNodeIds. We then lookup this index in layout_node_index, which
        # gives us the "index of the index" which is what we need to find the bounds
        # of this element.
        for node in self._nodes.values():
            if node.dom_id not in backend_index_lookup:
                # Sometimes we can not match, but that's fine, just ignore.
                node["is_matched"] = False
                continue

            backend_index = backend_index_lookup[node.dom_id]

            if src := src_from_backend.get(backend_index, None):
                node["src"] = strings[src]

            layout = layout_from_backend.get(backend_index, None)
            if layout:
                node.bounds = at.NodeBounds(*layout["bounds"])
                used_bounds = (
                    node.get_union_bounds() if at.USE_UNION_BOUNDS else node.bounds
                )
                has_bounds = used_bounds.area > 0
                on_screen = used_bounds.overlaps(window_bounds)
                node["is_visible"] = has_bounds and on_screen
            else:
                node["is_visible"] = False

            node["is_matched"] = True

        # For nodes that are editable also record their current input text.
        for node in filter(lambda x: x.is_editable, self._nodes.values()):
            # Sometimes a node will have it's input stored as 'value' othertimes we
            # need to go looking through the DOM tree to find its matching string.

            if node.value:
                node["input"] = node.value
            else:
                if node.dom_id not in backend_index_lookup:
                    # Sometimes web_at nodes don't appear in the DOM for some reason.
                    continue
                backend_index = backend_index_lookup[node.dom_id]
                text_index = text_from_backend.get(backend_index, -1)
                if text_index >= 0:
                    node["input"] = strings[text_index]

        # Map AT children and parents.
        for node in self._nodes.values():
            node.link_children(self._nodes)

        # Make menuitem's visible
        for node in [node for node in self._nodes.values() if node.role == "menuitem"]:
            node["is_visible"] = (
                node.role == "menuitem"
                and node.parent is not None
                and node.parent.is_expanded
            )

    def render(self, output_format: CrawlerOutputFormat) -> Any:
        """Returns the current webpage in the desired format.

        Only elements visible on the screen will be rendered.

        Args:
          output_format: The rending format to output.

        Returns:
          the currently active webpage rendered using given format.
        """
        match output_format:
            case CrawlerOutputFormat.AT:
                return self._render_at()
            case _:
                # TODO: Implement DOM, HTML, PIXELS formats
                raise NotImplementedError(
                    "Playwright crawler does not currently support"
                    f" {output_format} output."
                )

    def _render_at(self) -> str:
        """Render the current page's accessibility tree to text."""
        if self._root is None:
            return "<empty>"
        return self._root.to_string()

    def go_to_page(self, url: str) -> None:
        """Goes to the given url.

        Args:
          url: The url to redirect crawler to.
        """
        if "://" not in url:
            url = f"https://{url}"
        self._page.goto(url, wait_until=WAIT_STRATEGY)

    def click(self, element_id: int | str) -> None:
        """Clicks the element with the given id.

        Args:
          element_id: The id for the element we want to click on.
        """
        element = self.lookup_node(element_id)
        # Mouse.click() requires coordinates relative to the viewport:
        # https://playwright.dev/python/docs/api/class-mouse#mouse-click,
        # thus adjusting the Y coordinate since we only scroll up/down.
        scroll_y = self._page.evaluate("window.scrollY")
        self._page.mouse.click(
            element.bounds.center_x, element.bounds.center_y - scroll_y
        )

    def clear(self, element_id: int) -> None:
        """Clears text within a field."""
        self.click(element_id)
        self._page.keyboard.press("Control+A")
        self._page.keyboard.press("Backspace")

    def type(self, element_id: int | str, text: str) -> None:
        """Types into the element with the given id."""
        self.click(element_id)
        self._page.keyboard.type(text)

    def scroll(self, direction: Literal["up", "down"]) -> None:
        """Scrolls the page to the given direction.

        Args:
          direction: The direction to scroll in ('up' or 'down')
        """
        match direction.lower():
            case "up":
                self._page.evaluate(
                    "(document.scrollingElement || document.body).scrollTop ="
                    " (document.scrollingElement || document.body).scrollTop -"
                    " window.innerHeight;"
                )
            case "down":
                self._page.evaluate(
                    "(document.scrollingElement || document.body).scrollTop ="
                    " (document.scrollingElement || document.body).scrollTop +"
                    " window.innerHeight;"
                )

            case _:
                raise ValueError(f"Invalid scroll direction {direction}")

    def forward(self) -> None:
        """Move browser forward one history step."""
        self._page.go_forward(wait_until=WAIT_STRATEGY)

    def back(self) -> None:
        """Move browser backward one history step."""
        self._page.go_back(wait_until=WAIT_STRATEGY)

    def refresh(self) -> None:
        """Refresh (reload) the page."""
        self._page.reload(wait_until=WAIT_STRATEGY)

    @property
    def url(self) -> str:
        return self._page.url
