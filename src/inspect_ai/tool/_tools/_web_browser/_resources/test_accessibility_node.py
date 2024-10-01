from absl.testing import absltest
from accessibility_node import AccessibilityNode, NodeBounds


class TestNodeBounds(absltest.TestCase):
    def test_union(self):
        bounds1 = NodeBounds(10, 20, 30, 40)
        bounds2 = NodeBounds(20, 30, 40, 50)
        union_bounds = bounds1.union(bounds2)
        self.assertEqual(union_bounds.left, 10)
        self.assertEqual(union_bounds.top, 20)
        self.assertEqual(union_bounds.right, 60)
        self.assertEqual(union_bounds.bottom, 80)

    def test_union_with_empty_bound(self):
        bounds = NodeBounds(10, 20, 30, 40)
        empty_bounds = NodeBounds(0, 0, 0, 0)
        union_bounds = bounds.union(empty_bounds)
        self.assertEqual(union_bounds.left, 10)
        self.assertEqual(union_bounds.top, 20)
        self.assertEqual(union_bounds.right, 40)
        self.assertEqual(union_bounds.bottom, 60)

    def test_is_inside(self):
        bounds = NodeBounds(10, 20, 30, 40)
        self.assertTrue(bounds.is_inside(20, 30))
        self.assertFalse(bounds.is_inside(5, 10))
        self.assertFalse(bounds.is_inside(50, 70))

    def test_overlaps(self):
        bounds1 = NodeBounds(10, 20, 30, 40)
        bounds2 = NodeBounds(20, 30, 40, 50)
        self.assertTrue(bounds1.overlaps(bounds2))
        bounds3 = NodeBounds(50, 60, 20, 30)
        self.assertFalse(bounds1.overlaps(bounds3))


class TestAccessibilityNode(absltest.TestCase):
    def test_getitem(self):
        node_data = {"name": {"value": "Test"}, "role": {"value": "button"}}
        node = AccessibilityNode(node_data)
        self.assertEqual(node["name"], {"value": "Test"})
        self.assertEqual(node["role"], {"value": "button"})
        self.assertIsNone(node["invalid_key"])

    def test_setitem(self):
        node_data = {"name": {"value": "Test"}}
        node = AccessibilityNode(node_data)
        node["role"] = {"value": "button"}
        self.assertEqual(
            node._node, {"name": {"value": "Test"}, "role": {"value": "button"}}
        )

    def test_str_role_name(self):
        node_data = {
            "nodeId": "1",
            "role": {"value": "button"},
            "name": {"value": "Test Button"},
        }
        node = AccessibilityNode(node_data, bounds=NodeBounds(10, 10, 20, 20))
        self.assertIn('[1] button "Test Button"', str(node))

    def test_str_image_src(self):
        node_data = {
            "nodeId": "1",
            "role": {"value": "image"},
            "name": {"value": "Test Image"},
            "src": "image.png",
        }
        node = AccessibilityNode(node_data, bounds=NodeBounds(10, 10, 20, 20))
        self.assertIn('[1] image "Test Image" image.png', str(node))

    def test_str_property(self):
        node_data = {
            "nodeId": "1",
            "role": {"value": "link"},
            "name": {"value": "Test Link"},
            "properties": [{"name": "url", "value": {"value": "www.example.com"}}],
        }
        node = AccessibilityNode(node_data, bounds=NodeBounds(10, 10, 20, 20))
        self.assertIn('[1] link "Test Link" [url: www.example.com]', str(node))

    def test_str_empty(self):
        node_data = {"nodeId": "1"}
        node = AccessibilityNode(node_data)
        self.assertIn('[*]  ""', str(node))

    def test_link_children(self):
        node_data = {"nodeId": "1", "childIds": [2, 3]}
        node = AccessibilityNode(node_data)
        child1 = AccessibilityNode({"nodeId": "2"})
        child2 = AccessibilityNode({"nodeId": "3"})
        node_lookup = {2: child1, 3: child2}
        node.link_children(node_lookup)

        self.assertEqual(node.children, [child1, child2])
        self.assertEqual(child1._parent, node)
        self.assertEqual(child2._parent, node)

    def test_get_union_bounds(self):
        node_data = {"nodeId": "1", "childIds": [2, 3]}
        node = AccessibilityNode(node_data, bounds=NodeBounds(10, 10, 20, 20))
        child1 = AccessibilityNode({"nodeId": "2"}, bounds=NodeBounds(20, 20, 30, 30))
        child2 = AccessibilityNode({"nodeId": "3"}, bounds=NodeBounds(5, 5, 10, 10))
        node.link_children({2: child1, 3: child2})  # Manually link children

        union_bounds = node.get_union_bounds()
        self.assertEqual(union_bounds.left, 5)
        self.assertEqual(union_bounds.top, 5)
        self.assertEqual(union_bounds.right, 50)
        self.assertEqual(union_bounds.bottom, 50)

    def test_get_property(self):
        node_data = {"name": {"value": "Test"}, "role": {"value": "button"}}
        node = AccessibilityNode(node_data)
        self.assertEqual(node.get_property("name"), {"value": "Test"})
        self.assertEqual(node.get_property("role"), {"value": "button"})
        self.assertIsNone(node.get_property("invalid_key"))

    def test_to_string(self):
        node_data = {
            "nodeId": "1",
            "ignored": False,
            "childIds": [2],
            "role": {"value": "button"},
            "name": {"value": "Test Button"},
        }
        node = AccessibilityNode(node_data, bounds=NodeBounds(20, 20, 30, 30))
        self.assertIn('[1] button "Test Button"', node.to_string())

    def test_to_string_with_children(self):
        node_data = {
            "nodeId": "1",
            "ignored": False,
            "childIds": [2, 3],
            "role": {"value": "button"},
            "name": {"value": "Test Button"},
        }
        node = AccessibilityNode(node_data, bounds=NodeBounds(20, 20, 30, 30))
        child_data = {
            "nodeId": "2",
            "ignored": False,
            "role": {"value": "text"},
            "name": {"value": "Child Text"},
        }
        child = AccessibilityNode(child_data, bounds=NodeBounds(20, 20, 30, 30))
        ignored_child_data = {
            "nodeId": "3",
            "ignored": True,
            "role": {"value": "text"},
            "name": {"value": "Child Text"},
        }
        ignored_child = AccessibilityNode(
            ignored_child_data, bounds=NodeBounds(20, 20, 30, 30)
        )
        node.link_children({2: child, 3: ignored_child})
        self.assertIn('[2] text "Child Text"', node.to_string())
        self.assertNotIn('[3] text "Child Text"', node.to_string())

        # Test with include_children=False
        self.assertNotIn(
            '[2] text "Child Text"', node.to_string(include_children=False)
        )

    def test_property_string(self):
        node_data = {"properties": [{"name": "checked", "value": {"value": True}}]}
        node = AccessibilityNode(node_data)
        self.assertEqual(node.property_string(), " [checked: True]")

    def test_property_string_with_ignored_property(self):
        node_data = {
            "properties": [{"name": "focusable", "value": {"value": "some_value"}}]
        }
        node = AccessibilityNode(node_data)
        # 'focusable' is in _IGNORED_ACTREE_PROPERTIES
        self.assertEqual(node.property_string(), "")
