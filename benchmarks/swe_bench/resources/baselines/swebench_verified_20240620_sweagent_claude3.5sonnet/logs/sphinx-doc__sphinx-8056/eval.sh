#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff e188d56ed1248dead58f3f8018c0e9a3f99193f7
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test]
git checkout e188d56ed1248dead58f3f8018c0e9a3f99193f7 tests/test_ext_napoleon_docstring.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_ext_napoleon_docstring.py b/tests/test_ext_napoleon_docstring.py
--- a/tests/test_ext_napoleon_docstring.py
+++ b/tests/test_ext_napoleon_docstring.py
@@ -1230,7 +1230,7 @@ class NumpyDocstringTest(BaseDocstringTest):
         """
         Single line summary
 
-        :Parameters: * **arg1** (*str*) -- Extended description of arg1
+        :Parameters: * **arg1** (:class:`str`) -- Extended description of arg1
                      * **\\*args, \\*\\*kwargs** -- Variable length argument list and arbitrary keyword arguments.
         """
     ), (
@@ -1337,6 +1337,32 @@ def test_parameters_with_class_reference(self):
         expected = """\
 :param param1:
 :type param1: :class:`MyClass <name.space.MyClass>` instance
+"""
+        self.assertEqual(expected, actual)
+
+    def test_multiple_parameters(self):
+        docstring = """\
+Parameters
+----------
+x1, x2 : array_like
+    Input arrays, description of ``x1``, ``x2``.
+
+"""
+
+        config = Config(napoleon_use_param=False)
+        actual = str(NumpyDocstring(docstring, config))
+        expected = """\
+:Parameters: **x1, x2** (:class:`array_like`) -- Input arrays, description of ``x1``, ``x2``.
+"""
+        self.assertEqual(expected, actual)
+
+        config = Config(napoleon_use_param=True)
+        actual = str(NumpyDocstring(dedent(docstring), config))
+        expected = """\
+:param x1: Input arrays, description of ``x1``, ``x2``.
+:type x1: :class:`array_like`
+:param x2: Input arrays, description of ``x1``, ``x2``.
+:type x2: :class:`array_like`
 """
         self.assertEqual(expected, actual)
 

EOF_114329324912
tox --current-env -epy39 -v -- tests/test_ext_napoleon_docstring.py
git checkout e188d56ed1248dead58f3f8018c0e9a3f99193f7 tests/test_ext_napoleon_docstring.py
