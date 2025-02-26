from cdp.dom_snapshot import (
    DocumentSnapshot,
    DOMSnapshot,
    LayoutTreeSnapshot,
    NodeTreeSnapshot,
    RareBooleanData,
    StringIndex,
    TextBoxSnapshot,
)

simple_node_tree = NodeTreeSnapshot()
simple_layout_tree = LayoutTreeSnapshot(
    nodeIndex=(),
    styles=(),
    bounds=(),
    text=(),
    stackingContexts=RareBooleanData(index=()),
)
simple_text_boxes = TextBoxSnapshot(layoutIndex=(), bounds=(), start=(), length=())
simple_doc_snapshot = DocumentSnapshot(
    documentURL=StringIndex(0),
    title=StringIndex(1),
    baseURL=StringIndex(0),
    contentLanguage=StringIndex(2),
    encodingName=StringIndex(3),
    publicId=StringIndex(666),
    systemId=StringIndex(666),
    frameId=StringIndex(666),
    nodes=simple_node_tree,
    layout=simple_layout_tree,
    textBoxes=simple_text_boxes,
)
simple_dom_snapshot = DOMSnapshot(
    documents=(), strings=("documentUrl", "title", "contentLanguage", "encoding")
)

# THIS TEST MODULE IS DISABLED FOR NOW. IT WILL COME BACK

# def test_foo():
#     ax_node = cast(
#         AXNode,
#         {"nodeId": "666", "name": {"value": "Test"}, "role": {"value": "button"}},
#     )
#     ax_nodes = {ax_node.nodeId: ax_node}
#     nodes: dict[AXNodeId, AccessibilityTreeNode] = {}
#     snapshot_context = create_snapshot_context(simple_dom_snapshot)
#     window_bounds = Rectangle(0, 0, 1024, 768)

#     node = AccessibilityTreeNode(
#         ax_node={"name": {"value": "Test"}, "role": {"value": "button"}},
#         ax_nodes=ax_nodes,
#         parent=None,
#         all_accessibility_tree_nodes=nodes,
#         snapshot_context=snapshot_context,
#         device_scale_factor=1,
#         window_bounds=window_bounds,
#     )


# class TestAccessibilityTreeNode(absltest.TestCase):
#     def test_getitem(self):
#         node_data = {"name": {"value": "Test"}, "role": {"value": "button"}}
#         node = AccessibilityTreeNode(node_data)
#         self.assertEqual(node["name"], {"value": "Test"})
#         self.assertEqual(node["role"], {"value": "button"})
#         self.assertIsNone(node["invalid_key"])

#     def test_setitem(self):
#         node_data = {"name": {"value": "Test"}}
#         node = AccessibilityTreeNode(node_data)
#         node["role"] = {"value": "button"}
#         self.assertEqual(
#             node._node, {"name": {"value": "Test"}, "role": {"value": "button"}}
#         )

#     def test_str_role_name(self):
#         node_data = {
#             "nodeId": "1",
#             "role": {"value": "button"},
#             "name": {"value": "Test Button"},
#         }
#         node = AccessibilityTreeNode(node_data, bounds=Rectangle(10, 10, 20, 20))
#         self.assertIn('[1] button "Test Button"', str(node))

#     def test_str_image_src(self):
#         node_data = {
#             "nodeId": "1",
#             "role": {"value": "image"},
#             "name": {"value": "Test Image"},
#             "src": "image.png",
#         }
#         node = AccessibilityTreeNode(node_data, bounds=Rectangle(10, 10, 20, 20))
#         self.assertIn('[1] image "Test Image" image.png', str(node))

#     def test_str_property(self):
#         node_data = {
#             "nodeId": "1",
#             "role": {"value": "link"},
#             "name": {"value": "Test Link"},
#             "properties": [{"name": "url", "value": {"value": "www.example.com"}}],
#         }
#         node = AccessibilityTreeNode(node_data, bounds=Rectangle(10, 10, 20, 20))
#         self.assertIn('[1] link "Test Link" [url: www.example.com]', str(node))

#     def test_str_empty(self):
#         node_data = {"nodeId": "1"}
#         node = AccessibilityTreeNode(node_data)
#         self.assertIn('[*]  ""', str(node))

#     def test_link_children(self):
#         node_data = {"nodeId": "1", "childIds": [2, 3]}
#         node = AccessibilityTreeNode(node_data)
#         child1 = AccessibilityTreeNode({"nodeId": "2"})
#         child2 = AccessibilityTreeNode({"nodeId": "3"})
#         node_lookup = {2: child1, 3: child2}
#         node.link_children(node_lookup)

#         self.assertEqual(node.children, [child1, child2])
#         self.assertEqual(child1._parent, node)
#         self.assertEqual(child2._parent, node)

#     def test_get_property(self):
#         node_data = {"name": {"value": "Test"}, "role": {"value": "button"}}
#         node = AccessibilityTreeNode(node_data)
#         self.assertEqual(node.get_property("name"), {"value": "Test"})
#         self.assertEqual(node.get_property("role"), {"value": "button"})
#         self.assertIsNone(node.get_property("invalid_key"))

#     def test_render(self):
#         node_data = {
#             "nodeId": "1",
#             "ignored": False,
#             "childIds": [2],
#             "role": {"value": "button"},
#             "name": {"value": "Test Button"},
#         }
#         node = AccessibilityTreeNode(node_data, bounds=Rectangle(20, 20, 30, 30))
#         self.assertIn('[1] button "Test Button"', node.render())

#     def test_to_render_with_children(self):
#         node_data = {
#             "nodeId": "1",
#             "ignored": False,
#             "childIds": [2, 3],
#             "role": {"value": "button"},
#             "name": {"value": "Test Button"},
#         }
#         node = AccessibilityTreeNode(node_data, bounds=Rectangle(20, 20, 30, 30))
#         child_data = {
#             "nodeId": "2",
#             "ignored": False,
#             "role": {"value": "text"},
#             "name": {"value": "Child Text"},
#         }
#         child = AccessibilityTreeNode(child_data, bounds=Rectangle(20, 20, 30, 30))
#         ignored_child_data = {
#             "nodeId": "3",
#             "ignored": True,
#             "role": {"value": "text"},
#             "name": {"value": "Child Text"},
#         }
#         ignored_child = AccessibilityTreeNode(
#             ignored_child_data, bounds=Rectangle(20, 20, 30, 30)
#         )
#         node.link_children({2: child, 3: ignored_child})
#         self.assertIn('[2] text "Child Text"', node.render())
#         self.assertNotIn('[3] text "Child Text"', node.render())

#     def test_property_string(self):
#         node_data = {"properties": [{"name": "checked", "value": {"value": True}}]}
#         node = AccessibilityTreeNode(node_data)
#         self.assertEqual(node.property_string(), " [checked: True]")

#     def test_property_string_with_ignored_property(self):
#         node_data = {
#             "properties": [{"name": "focusable", "value": {"value": "some_value"}}]
#         }
#         node = AccessibilityTreeNode(node_data)
#         # 'focusable' is in _IGNORED_ACTREE_PROPERTIES
#         self.assertEqual(node.property_string(), "")
