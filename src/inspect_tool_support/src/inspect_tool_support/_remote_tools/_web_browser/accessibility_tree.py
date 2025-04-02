from functools import reduce
from typing import Iterable, TypedDict

from inspect_tool_support._remote_tools._web_browser.accessibility_tree_node import (
    AccessibilityTreeNode,
)
from inspect_tool_support._remote_tools._web_browser.cdp.a11y import AXNode, AXNodeId
from inspect_tool_support._remote_tools._web_browser.cdp.dom_snapshot import (
    DOMSnapshot,
    create_snapshot_context,
)
from inspect_tool_support._remote_tools._web_browser.rectangle import Rectangle

_AccType = tuple[
    AXNode | None,
    dict[AXNodeId, AXNode],
]


class AccessibilityTree(TypedDict):
    root: AccessibilityTreeNode
    nodes: dict[AXNodeId, AccessibilityTreeNode]


def create_accessibility_tree(
    *,
    ax_nodes: Iterable[AXNode],
    dom_snapshot: DOMSnapshot,
    device_scale_factor: float,
    window_bounds: Rectangle,
) -> AccessibilityTree | None:
    """
    Creates an accessibility tree from the given Chrome DevTools Protocol AX nodes and DOM snapshot.

    Args:
      ax_nodes (Iterable[AXNode]): An iterable of AXNode objects representing the accessibility nodes.
      dom_snapshot (DOMSnapshot): A snapshot of the DOM at the time of accessibility tree creation.
      device_scale_factor (float): The scale factor of the device.
      window_bounds (Bounds): The bounds of the window.

    Returns:
      AccessibilityTree: The accessibility tree.
    """

    # first make a dict of AXNodeId's to AXNode's and find the root on the way
    def reducer(acc: _AccType, ax_node: AXNode) -> _AccType:
        root_node, nodes = acc
        nodes[ax_node.nodeId] = ax_node
        return (
            # TODO: What do we want for multiple roots?
            root_node or (ax_node if ax_node.parentId is None else None),
            nodes,
        )

    initial_acc: _AccType = (None, {})  # The inference engine is weak
    root_node, nodes = reduce(reducer, ax_nodes, initial_acc)

    if not root_node:
        return None

    # Now create the AccessibilityTreeNode hierarchy
    snapshot_context = create_snapshot_context(dom_snapshot)
    all_accessibility_tree_nodes: dict[AXNodeId, AccessibilityTreeNode] = {}

    return AccessibilityTree(
        root=AccessibilityTreeNode(
            ax_node=root_node,
            ax_nodes=nodes,
            parent=None,
            all_accessibility_tree_nodes=all_accessibility_tree_nodes,
            snapshot_context=snapshot_context,
            device_scale_factor=device_scale_factor,
            window_bounds=window_bounds,
        ),
        nodes=all_accessibility_tree_nodes,
    )
