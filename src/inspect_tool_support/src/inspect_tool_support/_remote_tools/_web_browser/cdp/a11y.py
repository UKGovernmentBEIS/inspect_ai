"""
Types and pure functional helpers associated with Chrome DevTools Protocol's 'Accessibility' Domain

https://chromedevtools.github.io/devtools-protocol/tot/Accessibility/
"""

from typing import Literal, NewType, Optional

from pydantic import BaseModel

from inspect_tool_support._remote_tools._web_browser.cdp.dom import DOMBackendNodeId

# brand these str's so that we don't confuse them with other str's
PageFrameId = NewType("PageFrameId", str)
AXNodeId = NewType("AXNodeId", str)


AXPropertyName = Literal[
    "actions",
    "busy",
    "disabled",
    "editable",
    "focusable",
    "focused",
    "hidden",
    "hiddenRoot",
    "invalid",
    "keyshortcuts",
    "settable",
    "roledescription",
    "live",
    "atomic",
    "relevant",
    "root",
    "autocomplete",
    "hasPopup",
    "level",
    "multiselectable",
    "orientation",
    "multiline",
    "readonly",
    "required",
    "valuemin",
    "valuemax",
    "valuetext",
    "checked",
    "expanded",
    "modal",
    "pressed",
    "selected",
    "activedescendant",
    "controls",
    "describedby",
    "details",
    "errormessage",
    "flowto",
    "labelledby",
    "owns",
    "url",
]


AXValueType = Literal[
    "boolean",
    "tristate",
    "booleanOrUndefined",
    "idref",
    "idrefList",
    "integer",
    "node",
    "nodeList",
    "number",
    "string",
    "computedString",
    "token",
    "tokenList",
    "domRelation",
    "role",
    "internalRole",
    "valueUndefined",
]


class AXRelatedNode(BaseModel, frozen=True):
    backendDOMNodeId: DOMBackendNodeId
    """The BackendNodeId of the related DOM node."""
    idref: str | None = None
    """The IDRef value provided, if any."""
    text: str | None = None
    """The text alternative of this node in the current context."""


AXValueSourceType = Literal[
    "attribute", "implicit", "stylet", "contents", "placeholder", "relatedElement"
]

AXValueNativeSourceType = Literal[
    "description",
    "figcaption",
    "label",
    "labelfor",
    "labelwrapped",
    "legend",
    "rubyannotation",
    "tablecaption",
    "title",
    "other",
]


class AXValueSource(BaseModel, frozen=True):
    """A single source for a computed AX property."""

    type: AXValueSourceType
    """What type of source this is."""
    value: Optional["AXValue"] = None
    """The value of this property source."""
    attribute: str | None = None
    """The name of the relevant attribute, if any."""
    attributeValue: Optional["AXValue"] = None
    """The value of the relevant attribute, if any."""
    superseded: bool | None = None
    """Whether this source is superseded by a higher priority source."""
    nativeSource: AXValueNativeSourceType | None = None
    """The native markup source for this value, e.g. a `<label>` element."""
    nativeSourceValue: Optional["AXValue"] = None
    """The value, such as a node or node list, of the native source."""
    invalid: bool | None = None
    """Whether the value for this property is invalid."""
    invalidReason: str | None = None
    """Reason for the value being invalid, if it is."""


class AXValue(BaseModel, frozen=True):
    """A single computed AX property."""

    type: AXValueType
    """The type of this value."""
    value: object | None = None
    """The computed value of this property."""
    relatedNodes: tuple[AXRelatedNode, ...] | None = None
    """One or more related nodes, if applicable."""
    sources: tuple[AXValueSource, ...] | None = None
    """The sources which contributed to the computation of this property."""


class AXProperty(BaseModel, frozen=True):
    name: AXPropertyName
    """The name of this property."""
    value: AXValue
    """The value of this property."""


# AXNode's ignoredReasons is documented to be a list[AXProperty]. However, that seems to
# be erroneous since the namespace for ignored reason names is completely separate from property names.
class AXIgnoredReason(BaseModel, frozen=True):
    # name: Literal[
    #     "uninteresting",
    #     "ariaHiddenSubtree",
    #     "ariaHiddenElement",
    #     "notRendered",
    #     "notVisible",
    #     "emptyAlt",
    # ]
    name: str  # since this is all undocumented, it's best to be loose
    """The name of this ignored reason."""
    value: AXValue
    """The value of this ignored reason."""


class AXNode(BaseModel, frozen=True):
    """A node in the accessibility tree."""

    nodeId: AXNodeId
    """Unique identifier for this node."""
    ignored: bool
    """Wether this node is ignore3d for accessibility"""
    ignoredReasons: tuple[AXIgnoredReason, ...] | None = None
    """Collection of reasons why this node is hidden."""
    role: AXValue | None = None
    """This `Node`'s role, wether explicit or implicit."""
    chromeRole: AXValue | None = None
    """This `Node`'s Chrome raw role."""
    name: AXValue | None = None
    """The accessible name for this `Node`."""
    description: AXValue | None = None
    """The accessible description for this `Node`."""
    value: AXValue | None = None
    """The value for this `Node`."""
    properties: tuple[AXProperty, ...] | None = None
    """All other properties"""
    parentId: AXNodeId | None = None
    """ID for this node's parent."""
    childIds: tuple[AXNodeId, ...] | None = None
    """IDs for each of this node's child nodes."""
    backendDOMNodeId: DOMBackendNodeId | None = None
    """The backend ID for the associated DOM node, if any."""
    frameId: PageFrameId | None = None
    """The frame ID for the frame associated with this nodes document."""


class AXTree(BaseModel, frozen=True):
    nodes: tuple[AXNode, ...]


# CDP defines `AXValue.value` as `Any`, so this is a coercion function
def string_from_ax_value(value: AXValue | None) -> str:
    """
    Coerces an AXValue to a string.

    Args:
      value (AXValue | None): The AXValue to be coerced.

    Returns:
      str: The string representation of the AXValue, or an empty string if the value is None or not a string.
    """
    return value.value if value and isinstance(value.value, str) else ""


def node_has_property(node: AXNode, property_name: AXPropertyName) -> bool:
    """
    Checks if an AXNode has a specific property.

    Args:
      node (AXNode): The AXNode to check.
      property_name (AXPropertyName): The name of the property to look for.

    Returns:
      bool: True if the node has the property, False otherwise.
    """
    return node_property(node, property_name) is not None


def node_property(node: AXNode, property_name: AXPropertyName) -> AXProperty | None:
    """
    Retrieves a specific property from an AXNode.

    Args:
      node (AXNode): The AXNode to retrieve the property from.
      property_name (AXPropertyName): The name of the property to retrieve.

    Returns:
      AXProperty | None: The property if found, otherwise None.
    """
    return next(
        (prop for prop in node.properties or () if prop.name == property_name), None
    )


def node_bool_property(node: AXNode, property_name: AXPropertyName) -> bool:
    """
    Retrieves a boolean property from an AXNode.

    Args:
      node (AXNode): The AXNode to retrieve the property from.
      property_name (AXPropertyName): The name of the property to retrieve.

    Returns:
      bool: The boolean value of the property, or False if the property is not found or not a boolean.
    """
    return bool(prop.value) if (prop := node_property(node, property_name)) else False


def node_str_property(node: AXNode, property_name: AXPropertyName) -> str | None:
    """
    Retrieves a str property from an AXNode.

    Args:
      node (AXNode): The AXNode to retrieve the property from.
      property_name (AXPropertyName): The name of the property to retrieve.

    Returns:
      str: The str value of the property, or None if the property is not found or not a str.
    """
    prop = node_property(node, property_name)
    if prop is None:
        return None
    v = prop.value
    return v.value if isinstance(v.value, str) else None
