from __future__ import annotations

from typing import Any

# Properities to ignore when printing out the accessibility tree.
_IGNORED_ACTREE_PROPERTIES = (
    "focusable",
    "readonly",
    "level",
    "settable",
    "multiline",
    "invalid",
)

_IGNORED_AT_ROLES = (
    "generic",
    "list",
    "strong",
    "paragraph",
    "banner",
    "navigation",
    "Section",
    "LabelText",
    "Legend",
    "listitem",
)

# Typically we use the bounding rect provided by the DOM in order to track
# if an element is visible or not. However, sometimes it can be useful to
# instead take the union of the elements bounds and all its children's bounds.
# This process is a little slower, and is probably not needed, but can be
# enabled using this flag.
USE_UNION_BOUNDS = False

# The maximum length of the description 'tag' for each element.
# Tags longer than this will be truncated with an '...' appended.
MAX_NODE_TEXT_LENGTH = 120

# Used for debugging, include the elements bounding rect during output.
_INCLUDE_BOUNDS_IN_OUTPUT = False


class NodeBounds:
    """Class to hold bounding rect for notes."""

    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = int(x)
        self.y = int(y)
        self.width = int(width)
        self.height = int(height)

    @classmethod
    def from_lrtb(cls, left: int, right: int, top: int, bottom: int) -> NodeBounds:
        return cls(left, top, right - left, bottom - top)

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    @property
    def area(self) -> int:
        return self.width * self.height

    def __str__(self):
        return f"({self.left}, {self.top}, {self.width}, {self.height})"

    def union(self, other: NodeBounds) -> NodeBounds:
        """Return the (convex) union of two bounds."""
        # Special cases when one or the other is an empty bound.
        if self.area == 0:
            return other
        if other.area == 0:
            return self

        return self.from_lrtb(
            min(self.left, other.left),
            max(self.right, other.right),
            min(self.top, other.top),
            max(self.bottom, other.bottom),
        )

    def is_inside(self, x: int, y: int) -> bool:
        """Returns if given point is inside the bounds or not."""
        return x >= self.left and y >= self.top and x < self.right and y < self.bottom

    def overlaps(self, other: NodeBounds) -> bool:
        """Returns if the two bounds intersect."""
        return (
            other.left < self.right
            and other.right > self.left
            and other.top < self.bottom
            and other.bottom > self.top
        )


class AccessibilityNode:
    """A class for an accessibility node.

    Accessibility properties are specified here:
    https://chromedevtools.github.io/devtools-protocol/tot/Accessibility/#type-AXNode
    """

    def __init__(self, node: dict[str, Any], parent=None, bounds=None):
        self._node = node
        self._parent: AccessibilityNode | None = parent
        self.bounds = bounds or NodeBounds(0, 0, 0, 0)

    def __getitem__(self, key: str) -> Any:
        """Access the underlying node fields."""
        return self._node.get(key)

    def __setitem__(self, key: str, value: Any):
        """Set the underlying node fields."""
        self._node[key] = value

    def __str__(self):
        if _INCLUDE_BOUNDS_IN_OUTPUT:
            bounds_string = " " + str(
                self.get_union_bounds() if USE_UNION_BOUNDS else self.bounds
            )
        else:
            bounds_string = ""

        node_input = self.current_input
        if node_input:
            input_string = f' Current input: "{node_input}"'
        else:
            input_string = ""

        # Without bounds we can't click on the element, and therefore the ID
        # can not be used. Still useful to show these elements though (e.g.)
        # to let user know about options.
        id_string = "*" if self.bounds.area == 0 else self.node_id

        url_string = ""
        if self.role == "image" and self._node.get("src", ""):
            url_string = " " + self._node["src"]

        return (
            f'[{id_string}] {self.role} "{self.short_name}"'
            + url_string
            + input_string
            + self.property_string()
            + bounds_string
        )

    @property
    def node_id(self) -> str:
        return self._node["nodeId"]

    @property
    def value(self) -> str:
        value_field = self._node.get("value", "{}")
        if isinstance(value_field, dict):
            return value_field.get("value", "")
        else:
            return ""

    @property
    def parent(self) -> Any | None:
        """Returns the first visible parent."""
        parent = self._parent
        while parent and parent.is_ignored:
            parent = parent._parent
        return parent

    @property
    def role(self) -> str:
        if "role" in self._node:
            return self._node["role"].get("value", "")
        else:
            return ""

    @property
    def name(self) -> str:
        if "name" in self._node:
            return self._node["name"].get("value", "")
        else:
            return ""

    @property
    def short_name(self) -> str:
        short_name = self.name[:MAX_NODE_TEXT_LENGTH]
        if short_name != self.name:
            short_name = short_name[: MAX_NODE_TEXT_LENGTH - 3] + "..."
        return short_name

    @property
    def is_ignored(self) -> bool:
        return (
            self._node["ignored"]
            or self.role in _IGNORED_AT_ROLES
            or not self.is_visible
            or (not self.name and self.role != "textbox")
            or (self.parent and self.parent.name == self.name)
        )

    @property
    def children(self) -> list[Any]:
        return self._node.get("children", [])

    @property
    def is_visible(self) -> bool:
        return self._node.get("is_visible", True)

    def is_selected(self) -> bool:
        return self._node.get("selected", False)

    @property
    def is_editable(self) -> bool:
        for node_property in self.properties:
            if node_property["name"] == "editable":
                return True
        return False

    @property
    def is_expanded(self) -> bool:
        for node_property in self.properties:
            if node_property["name"] == "expanded":
                return bool(node_property["value"].get("value"))
        return False

    @property
    def properties(self) -> list[Any]:
        return self._node.get("properties", [])

    @property
    def dom_id(self) -> str:
        """Returns the backend DOM id associated with this node."""
        return self._node.get("backendDOMNodeId", -1)

    @property
    def current_input(self) -> str:
        # For some reason text edit boxes get 'input' but comboboxs get 'values'
        if self.role == "combobox":
            value = self.value
        else:
            value = self.get_property("input")
        return value

    def get_union_bounds(self) -> list[int]:
        """Returns the union of the bounds for this element all children."""
        bounds = self.bounds
        for child in self.children:
            child_union_bounds = child.get_union_bounds()
            bounds = bounds.union(child_union_bounds)
        return bounds

    def link_children(self, node_lookup: dict[str, Any]) -> None:
        """Creates links to children nodes.

        Nodes are referenced by id, but we want to add references to the
        AccessibilityNode. We also want add a reference to the parent node.

        To perform this task we need access to the complete list of nodes, and
        therefore it must be done on a second pass after initializing the nodes.

        Args:
          node_lookup: A dictionary mapping from node_id to node instances.
        """
        self._node["children"] = []
        for idx in self._node.get("childIds", []):
            self._node["children"].append(node_lookup[idx])
            node_lookup[idx]._parent = self

    def get_property(self, property_name: str) -> Any:
        """Query the property value of the underlying accessibility tree node."""
        return self._node.get(property_name)

    def to_string(self, indent: int = 0, include_children: bool = True) -> str:
        """Returns the string representation of the node."""
        result = ""
        if not self.is_ignored:
            result = "  " * indent + str(self) + "\n"
            indent += 1
        if include_children:
            children_strings = [child.to_string(indent) for child in self.children]
            result = result + "".join([s for s in children_strings if s])
        return result

    def property_string(self) -> str:
        properties = []
        for node_property in self.properties:
            try:
                if node_property["name"] in _IGNORED_ACTREE_PROPERTIES:
                    continue
                properties.append(
                    f"{node_property['name']}: {node_property['value'].get('value')}"
                )
            except KeyError:
                pass
        return " [" + ", ".join(properties) + "]" if properties else ""
