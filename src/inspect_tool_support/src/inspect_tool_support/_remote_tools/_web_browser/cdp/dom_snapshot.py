"""
Types and pure functional helpers associated with Chrome DevTools Protocol's 'DOMSnapshot' Domain

https://chromedevtools.github.io/devtools-protocol/tot/DOMSnapshot/
"""

from typing import Literal, NewType, TypedDict

from pydantic import BaseModel

from inspect_tool_support._remote_tools._web_browser.cdp.dom import DOMBackendNodeId

StringIndex = NewType("StringIndex", int)
Rectangle = tuple[float, ...]
ArrayOfStrings = tuple[StringIndex, ...]


class RareStringData(BaseModel, frozen=True):
    """Data that is only present on rare nodes."""

    index: tuple[int, ...]
    value: tuple[StringIndex, ...]


class RareIntegerData(BaseModel, frozen=True):
    index: tuple[int, ...]
    value: tuple[int, ...]


class RareBooleanData(BaseModel, frozen=True):
    index: tuple[int, ...]


class NodeTreeSnapshot(BaseModel, frozen=True):
    """Table containing nodes."""

    parentIndex: tuple[int, ...] | None = None
    """Parent node index."""
    nodeType: tuple[int, ...] | None = None
    """`Node`'s nodeType"""
    shadowRootType: RareStringData | None = None
    """Type of the shadow root the `Node` is in. String values are equal to the `ShadowRootType` enum."""
    nodeName: tuple[StringIndex, ...] | None = None
    """`Node`'s nodeName."""
    nodeValue: tuple[StringIndex, ...] | None = None
    """`Node`'s nodeValue."""
    backendNodeId: tuple[DOMBackendNodeId, ...] | None = None
    """`Node`'s id, corresponds to DOM.Node.backendNodeId."""
    attributes: tuple[ArrayOfStrings, ...] | None = None
    # attributes: list[int] | None = None
    """Attributes of an `Element` node. Flatten name, value pairs."""
    textValue: RareStringData | None = None
    """Only set for textarea elements, contains the text value."""
    inputValue: RareStringData | None = None
    """Only set for input elements, contains the input's associated text value."""
    inputChecked: RareBooleanData | None = None
    """Only set for radio and checkbox input elements, indicates if the element has been checked"""
    optionSelected: RareBooleanData | None = None
    """Only set for option elements, indicates if the element has been selected"""
    contentDocumentIndex: RareIntegerData | None = None
    """The index of the document in the list of the snapshot documents."""
    pseudoType: RareStringData | None = None
    """Type of a pseudo element node."""
    pseudoIdentifier: RareStringData | None = None
    """Pseudo element identifier for this node. Only present if there is a valid pseudoType."""
    isClickable: RareBooleanData | None = None
    """Whether this DOM node responds to mouse clicks. This includes nodes that have had click event listeners attached via JavaScript as well as anchor tags that naturally navigate when clicked."""
    currentSourceURL: RareStringData | None = None
    """The selected url for nodes with a srcset attribute."""
    originURL: RareStringData | None = None
    """The url of the script (if any) that generates this node."""


class LayoutTreeSnapshot(BaseModel, frozen=True):
    """Table of details of an element in the DOM tree with a `LayoutObject`."""

    nodeIndex: tuple[int, ...]
    """Index of the corresponding node in the `NodeTreeSnapshot` array returned by `captureSnapshot`."""
    styles: tuple[ArrayOfStrings, ...]
    """Array of indexes specifying computed style strings, filtered according to the computedStyles parameter passed to captureSnapshot."""
    bounds: tuple[Rectangle, ...]
    """The absolute position bounding box."""
    text: tuple[StringIndex, ...]
    """Contents of the `LayoutText`, if any."""
    stackingContexts: RareBooleanData
    """Stacking context information."""
    paintOrders: tuple[int, ...] | None = None
    """Global paint order index, which is determined by the stacking order of the nodes. Nodes that are painted together will have the same index. Only provided if `includePaintOrder` in `captureSnapshot` was true."""
    offsetRects: tuple[Rectangle, ...] | None = None
    """The offset rect of nodes. Only available when `includeDOMRects` is set to true"""
    scrollRects: tuple[Rectangle, ...] | None = None
    """The scroll rect of nodes. Only available when `includeDOMRects` is set to true"""
    clientRects: tuple[Rectangle, ...] | None = None
    """The client rect of nodes. Only available when `includeDOMRects` is set to true"""
    blendedBackgroundColors: tuple[StringIndex, ...] | None = None
    """The list of background colors that are blended with colors of overlapping elements. Experimental"""
    textColorOpacities: tuple[float, ...] | None = None
    """The list of computed text opacities. Experimental"""


class TextBoxSnapshot(BaseModel, frozen=True):
    """Table of details of the post layout rendered text positions. The exact layout should not be regarded as stable and may change between versions."""

    layoutIndex: tuple[int, ...]
    """Index of the layout tree node that owns this box collection."""
    bounds: tuple[Rectangle, ...]
    """The absolute position bounding box."""
    start: tuple[int, ...]
    """The starting index in characters, for this post layout textbox substring. Characters that would be represented as a surrogate pair in UTF-16 have length 2."""
    length: tuple[int, ...]
    """The number of characters in this post layout textbox substring. Characters that would be represented as a surrogate pair in UTF-16 have length 2."""


class DocumentSnapshot(BaseModel, frozen=True):
    documentURL: StringIndex
    """Document URL that `Document` or `FrameOwner` node points to."""
    title: StringIndex
    """Document title."""
    baseURL: StringIndex
    """Base URL that `Document` or `FrameOwner` node uses for URL completion."""
    contentLanguage: StringIndex
    """Contains the document's content language."""
    encodingName: StringIndex
    """Contains the document's character set encoding."""
    publicId: StringIndex
    """`DocumentType` node's publicId."""
    systemId: StringIndex
    """`DocumentType` node's systemId."""
    frameId: StringIndex
    """Frame ID for frame owner elements and also for the document node."""
    nodes: NodeTreeSnapshot
    """A table with dom nodes."""
    layout: LayoutTreeSnapshot
    """The nodes in the layout tree."""
    textBoxes: TextBoxSnapshot
    """The post-layout inline text nodes."""
    scrollOffsetX: float | None = None
    """Horizontal scroll offset."""
    scrollOffsetY: float | None = None
    """Vertical scroll offset."""
    contentWidth: float | None = None
    """Document content width."""
    contentHeight: float | None = None
    """Document content height."""


class DOMSnapshot(BaseModel, frozen=True):
    documents: tuple[DocumentSnapshot, ...]
    """The nodes in the DOM tree. The DOMNode at index 0 corresponds to the root document."""
    strings: tuple[str, ...]
    """Shared string table that all string properties refer to with indexes."""


NodeIndex = NewType("NodeIndex", int)
LayoutIndex = NewType("LayoutIndex", int)


class DOMSnapshotContext(TypedDict):
    dom_snapshot: DOMSnapshot
    node_id_to_node_index: dict[DOMBackendNodeId, NodeIndex]
    # Below are dicts to help with non-1:1 index mappings like layouts and RareStringData's
    node_index_to_layout_index: dict[NodeIndex, LayoutIndex]
    node_index_to_current_src_url_index: dict[NodeIndex, StringIndex]
    node_index_to_text_value_index: dict[NodeIndex, StringIndex]


def create_snapshot_context(dom_snapshot: DOMSnapshot) -> DOMSnapshotContext:
    """
    Creates a DOMSnapshotContext that can be used to efficiently extract data from a DOMSnapshot.

    Given the fact that a DOMSnapshot uses long flat correlated lists (see below), this context
    enables efficient lookups that avoid full list scans.

    NOTE: Currently, this context and associated code assumes document[0]

    The DOMSnapshot domain represents the DOM tree as as set of objects each containing
    parallel flat arrays — NodeTreeSnapshot, LayoutTreeSnapshot, etc.

    Each node in the DOM tree is represented in the NodeTreeSnapshot object by corresponding
    entries at the same index across multiple arrays (parentIndex, nodeType, backendNodeId, etc.):

    NodeTreeSnapshot:
                  │   0    │   1    |   2    |   3    |   4
    ──────────────┼────────┼────────┼────────┼────────┼────────
    actual tag    │ <html> │ <body> │ <div>  │  <p>   │ <span>
    parentIndex   │  -1    │   0    │   1    │   2    │   3
    backendNodeId │  666   │  745   │  103   │  421   │   7
    attributes    │  ...   │  ...   │  ...   │  ...   │  ...
    nodeValue     │  ...   │  ...   │  ...   │  ...   │  ...
    etc           │  ...   │  ...   │  ...   │  ...   │  ...


    Because layout is independent of node ordering, entries in the LayoutTreeSnapshot object maintain
    a reference back to their corresponding node through the nodeIndex field along with layout specific
    properties (bounds, paintOrders, etc).

    LayoutTreeSnapshot:
                  │   0    │    1   │   2    │   3    │   4
    ──────────────┼────────┼────────┼────────┼────────┼────────
    bounds        │  ...   │  ...   │  ...   │  ...   │  ...
    etc           │  ...   │  ...   │  ...   │  ...   │  ...
    nodeIndex     │   3    │   0    │   4    │   2    │   1
    ──────────────┼────────┼────────┼────────┼────────┼────────
                  │   ↓    │   ↓    │   ↓    │   ↓    │   ↓
    backendNodeId │  421   │  666   │   7    │  103   │  745
    actual tag    │  <p>   │ <html> │ <span> │ <div>  │ <body>
    """
    document = dom_snapshot.documents[0]
    return {
        "dom_snapshot": dom_snapshot,
        "node_id_to_node_index": {
            node_id: NodeIndex(index)
            for index, node_id in enumerate(document.nodes.backendNodeId or [])
        },
        "node_index_to_layout_index": {
            NodeIndex(node_index): LayoutIndex(layout_index)
            for layout_index, node_index in enumerate(document.layout.nodeIndex)
        },
        "node_index_to_current_src_url_index": (
            _dict_for_rare_string_data(document.nodes.currentSourceURL)
            if document.nodes.currentSourceURL
            else {}
        ),
        "node_index_to_text_value_index": (
            _dict_for_rare_string_data(document.nodes.textValue)
            if document.nodes.textValue
            else {}
        ),
    }


def index_for_node_id(
    node_id: DOMBackendNodeId, context: DOMSnapshotContext
) -> NodeIndex | None:
    return context["node_id_to_node_index"].get(node_id, None)


def bounds_for_node_index(
    node_index: NodeIndex, context: DOMSnapshotContext
) -> Rectangle | None:
    return (
        context["dom_snapshot"].documents[0].layout.bounds[layout_index]
        if (layout_index := _layout_index_for_node_index(node_index, context))
        is not None
        else None
    )


def current_url_src_for_node_index(
    node_index: NodeIndex, context: DOMSnapshotContext
) -> str | None:
    return _rare_string_for_node_index(
        node_index, "node_index_to_current_src_url_index", context
    )


def text_value_for_node_index(
    node_index: NodeIndex, context: DOMSnapshotContext
) -> str | None:
    return _rare_string_for_node_index(
        node_index, "node_index_to_text_value_index", context
    )


def _layout_index_for_node_index(
    node_index: NodeIndex, context: DOMSnapshotContext
) -> LayoutIndex | None:
    """Returns the index of the layout entry, if any, corresponding to the given node id."""
    return context["node_index_to_layout_index"].get(node_index, None)


def _rare_string_for_node_index(
    node_index: NodeIndex,
    dict_name: Literal[
        "node_index_to_text_value_index", "node_index_to_current_src_url_index"
    ],
    context: DOMSnapshotContext,
) -> str | None:
    return (
        _string_for_string_index(text_value_index, context)
        if (text_value_index := context[dict_name].get(node_index, None))
        else None
    )


def _string_for_string_index(index: StringIndex, context: DOMSnapshotContext) -> str:
    return context["dom_snapshot"].strings[index]


def _dict_for_rare_string_data(
    rare_string_data: RareStringData,
) -> dict[NodeIndex, StringIndex]:
    """Creates a dictionary from a RareStringData object enabling lookups given a node index."""
    return {
        NodeIndex(index): value
        for index, value in zip(
            rare_string_data.index, rare_string_data.value, strict=True
        )
    }
