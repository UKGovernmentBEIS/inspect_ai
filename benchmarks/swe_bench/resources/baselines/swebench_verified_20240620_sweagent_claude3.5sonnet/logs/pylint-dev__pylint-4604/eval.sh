#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 1e55ae64624d28c5fe8b63ad7979880ee2e6ef3f
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 1e55ae64624d28c5fe8b63ad7979880ee2e6ef3f tests/checkers/unittest_variables.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/checkers/unittest_variables.py b/tests/checkers/unittest_variables.py
--- a/tests/checkers/unittest_variables.py
+++ b/tests/checkers/unittest_variables.py
@@ -21,11 +21,13 @@
 import os
 import re
 import sys
+import unittest
 from pathlib import Path
 
 import astroid
 
 from pylint.checkers import variables
+from pylint.constants import IS_PYPY
 from pylint.interfaces import UNDEFINED
 from pylint.testutils import CheckerTestCase, Message, linter, set_config
 
@@ -191,6 +193,24 @@ def my_method(self) -> MyType:
         with self.assertNoMessages():
             self.walk(module)
 
+    @unittest.skipIf(IS_PYPY, "PyPy does not parse type comments")
+    def test_attribute_in_type_comment(self):
+        """Ensure attribute lookups in type comments are accounted for.
+
+        https://github.com/PyCQA/pylint/issues/4603
+        """
+        module = astroid.parse(
+            """
+        import foo
+        from foo import Bar, Boo
+        a = ... # type: foo.Bar
+        b = ... # type: foo.Bar[Boo]
+        c = ... # type: Bar.Boo
+        """
+        )
+        with self.assertNoMessages():
+            self.walk(module)
+
 
 class TestVariablesCheckerWithTearDown(CheckerTestCase):
 

EOF_114329324912
pytest -rA tests/checkers/unittest_variables.py
git checkout 1e55ae64624d28c5fe8b63ad7979880ee2e6ef3f tests/checkers/unittest_variables.py
