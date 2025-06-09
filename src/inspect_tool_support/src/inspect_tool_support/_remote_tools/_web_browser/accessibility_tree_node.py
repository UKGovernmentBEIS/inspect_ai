from functools import reduce
from typing import Optional

from inspect_tool_support._remote_tools._web_browser.cdp.a11y import (
    AXNode,
    AXNodeId,
    AXProperty,
    AXPropertyName,
    node_has_property,
    string_from_ax_value,
)
from inspect_tool_support._remote_tools._web_browser.cdp.dom_snapshot import (
    DOMSnapshotContext,
    bounds_for_node_index,
    current_url_src_for_node_index,
    index_for_node_id,
    text_value_for_node_index,
)
from inspect_tool_support._remote_tools._web_browser.rectangle import Rectangle

# Properties to ignore when printing out the accessibility tree.
_IGNORED_AT_PROPERTIES: set[AXPropertyName] = {
    "focusable",
    "readonly",
    "level",
    "settable",
    "multiline",
    "invalid",
}

# The AXRole enum is here (https://chromium.googlesource.com/chromium/chromium/+/HEAD/ui/accessibility/ax_enums.idl#62)
_ROLES_IGNORED = {"horizontal_rule", "ignored"}

# These are noisy and provide no real benefit unless there's a name associated with them
_ROLES_REQUIRING_A_NAME = {"generic", "paragraph", "div"}

# Used for debugging, include the elements bounding rect during output.
_INCLUDE_BOUNDS_IN_OUTPUT = False


class AccessibilityTreeNode:
    def __init__(
        self,
        *,
        ax_node: AXNode,
        ax_nodes: dict[AXNodeId, AXNode],
        parent: Optional["AccessibilityTreeNode"],
        all_accessibility_tree_nodes: dict[AXNodeId, "AccessibilityTreeNode"],
        snapshot_context: DOMSnapshotContext,
        device_scale_factor: float,
        window_bounds: Rectangle,
    ):
        all_accessibility_tree_nodes[ax_node.nodeId] = self

        self._is_expanded = node_has_property(ax_node, "expanded")
        self._ax_node = ax_node
        self._parent = parent
        self._is_ignored: bool | None = None
        self._bounds: Rectangle | None = None
        self._is_visible: bool | None = None
        self._current_src_url: str | None = None
        self._input: str | None = None
        self.__closest_non_ignored_parent: AccessibilityTreeNode | None = None

        dom_node_index = (
            index_for_node_id(ax_node.backendDOMNodeId, snapshot_context)
            if ax_node.backendDOMNodeId
            else None
        )

        # The following three variables (_bounds, _is_visible, and _current_src_url) depend on
        # info from the DOM element associated with this AXNode
        if dom_node_index:
            self._bounds = (
                Rectangle(*layout_bounds).scale(1 / device_scale_factor)
                if (
                    layout_bounds := bounds_for_node_index(
                        dom_node_index, snapshot_context
                    )
                )
                is not None
                else None
            )
            self._is_visible = (
                (self._bounds.has_area and self._bounds.overlaps(window_bounds))
                if self._bounds
                else None
            )
            self._current_src_url = (
                current_url_src_for_node_index(dom_node_index, snapshot_context)
                if self.role == "image"
                else None
            )

        if node_has_property(ax_node, "editable") or self.role == "combobox":
            # Sometimes a node will have it's input stored as 'value' other times we
            # need to go looking through the DOM tree to find its matching string.
            self._input = (
                string_from_ax_value(ax_node.value)
                if ax_node.value
                else (
                    text_value_for_node_index(dom_node_index, snapshot_context)
                    if dom_node_index is not None
                    else None
                )
            )

        # this is a little awkward, but the old code ensured that menuitems were visible in given the following condition
        if self.role == "menuitem" and parent is not None and parent.is_expanded:
            self._is_visible = True

        # It's important to set all other properties before creating children in case
        # the children sample parent.xxx
        self.children = (
            [
                AccessibilityTreeNode(
                    ax_node=ax_nodes[child_id],
                    ax_nodes=ax_nodes,
                    parent=self,
                    all_accessibility_tree_nodes=all_accessibility_tree_nodes,
                    snapshot_context=snapshot_context,
                    device_scale_factor=device_scale_factor,
                    window_bounds=window_bounds,
                )
                for child_id in ax_node.childIds
            ]
            if ax_node.childIds
            else None
        )

    def __str__(self) -> str:
        bounds_string = str(self.bounds) if _INCLUDE_BOUNDS_IN_OUTPUT else None

        input_string = f'Current input: "{self._input}"' if self._input else None

        name_string = f'"{self.name}"' if self.name else None
        # Without bounds we can't click on the element, and therefore the ID
        # can not be used. Still useful to show these elements though (e.g.)
        # to let user know about options.
        id_string = f"[{'*' if not self._bounds or not self._bounds.has_area else self._ax_node.nodeId}]"
        url_string = self._current_src_url if self._current_src_url else None

        url_string = _maybe_redact_base64_url(self._current_src_url)

        return " ".join(
            [
                item
                for item in [
                    id_string,
                    self.role,
                    name_string,
                    url_string,
                    input_string,
                    self._property_string(),
                    bounds_string,
                ]
                if item is not None
            ]
        )

    @property
    def node_id(self) -> AXNodeId:
        return self._ax_node.nodeId

    @property
    def name(self) -> str:
        return string_from_ax_value(self._ax_node.name)

    @property
    def is_expanded(self) -> bool:
        return self._is_expanded

    @property
    def is_visible(self) -> bool:
        return self._is_visible or False

    @property
    def bounds(self) -> Rectangle | None:
        return self._bounds

    @property
    def current_src_url(self) -> str | None:
        return self._current_src_url

    @property
    def input(self) -> str | None:
        return self._input

    @property
    def is_ignored(self) -> bool:
        # computing _is_ignored is very expensive, do it on demand and remember the result
        if self._is_ignored is None:
            self._is_ignored = self._compute_is_ignored()
        return self._is_ignored

    @property
    def role(self) -> str:
        return string_from_ax_value(self._ax_node.role)

    @property
    def _closest_non_ignored_parent(self) -> Optional["AccessibilityTreeNode"]:
        if self._parent and self.__closest_non_ignored_parent is None:
            self.__closest_non_ignored_parent = (
                None
                if not self._parent
                else (
                    self._parent
                    if not self._parent.is_ignored
                    else self._parent._closest_non_ignored_parent  # pylint: disable=protected-access
                )
            )
        return self.__closest_non_ignored_parent

    def render_accessibility_tree(self, indent: int = 0) -> str:
        """Returns the string representation of the node and its children."""
        result = ""
        if not self.is_ignored:
            result = "  " * indent + str(self) + "\n"
            indent += 1
        children_strings = [
            child.render_accessibility_tree(indent) for child in self.children or []
        ]
        result = result + "".join([s for s in children_strings if s])
        return result

    def render_main_content(self) -> str | None:
        return (
            main_node._extract_text()  # pylint: disable=protected-access
            if (main_node := self._get_main_content_node())
            else None
        )

    def _compute_is_ignored(self) -> bool:
        if self._ax_node.ignored or not self.is_visible or self.role in _ROLES_IGNORED:
            return True

        # if the parent is a link/button with a name, and this node is within the parent's bounds, we can ignore it.
        if (
            (closest_parent := self._closest_non_ignored_parent)
            and closest_parent.bounds
            and self.bounds
            and (closest_parent.role == "link" or closest_parent.role == "button")
            and closest_parent.name
            and self.bounds.within(closest_parent.bounds)
        ):
            return True

        if bool(self.name):  # excludes None or ""
            # This simplifies things like links/buttons whose contents are sub-elements
            # e.g.
            #   [158] button "Menu"
            #     [1166] StaticText "Menu"
            # becomes
            #   [158] button "Menu"
            return self._parent is not None and self._parent.name == self.name

        return self.role in _ROLES_REQUIRING_A_NAME

    def _get_main_content_node(self) -> Optional["AccessibilityTreeNode"]:
        if self.role == "main":
            return self

        return next(
            (
                result
                for child in self.children or []
                if (
                    result := child._get_main_content_node()  # pylint: disable=protected-access
                )
            ),
            None,
        )

    def _extract_text(self) -> str:
        """
        Recursively extracts and concatenates text from the accessibility tree nodes.

        This method traverses the accessibility tree starting from the current node,
        concatenating the text of each node.

        Returns:
          str: The concatenated text from the accessibility tree nodes, with
             appropriate spacing based on node roles.
        """
        if not self.is_visible:
            return ""

        def reducer(acc: str, child: AccessibilityTreeNode) -> str:
            child_text = child._extract_text()  # pylint: disable=protected-access
            return (
                acc
                + (
                    "\n\n"
                    if child.role
                    in {"paragraph", "note", "row", "div", "heading", "region"}
                    else " "
                )
                + child_text
            )

        return reduce(reducer, self.children or [], self.name).strip()

    def _property_string(self) -> str:
        properties = [
            (
                _prop_name_value_str(node_property)
                if node_property.value.value
                else f"{node_property.name}"
            )
            for node_property in self._ax_node.properties or ()
            if node_property.name not in _IGNORED_AT_PROPERTIES
        ]
        return " [" + ", ".join(properties) + "]" if properties else ""


def _prop_name_value_str(node_property: AXProperty) -> str:
    # pre-commit hook (debug-statements) crashes if value is inlined below
    value = (
        _maybe_redact_base64_url(node_property.value.value)
        if node_property.name == "url" and isinstance(node_property.value.value, str)
        else node_property.value.value
    )
    return f"{node_property.name}: {value}"


def _maybe_redact_base64_url(url: str | None) -> str | None:
    return (
        "data:<base64-data-removed>"
        if url and url.startswith("data:") and "base64" in url
        else url
    )
