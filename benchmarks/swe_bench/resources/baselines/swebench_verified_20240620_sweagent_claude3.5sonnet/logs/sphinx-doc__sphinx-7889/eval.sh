#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff ec9af606c6cfa515f946d74da9b51574f2f9b16f
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test]
git checkout ec9af606c6cfa515f946d74da9b51574f2f9b16f tests/test_ext_autodoc_mock.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_ext_autodoc_mock.py b/tests/test_ext_autodoc_mock.py
--- a/tests/test_ext_autodoc_mock.py
+++ b/tests/test_ext_autodoc_mock.py
@@ -11,6 +11,7 @@
 import abc
 import sys
 from importlib import import_module
+from typing import TypeVar
 
 import pytest
 
@@ -39,6 +40,7 @@ def test_MockObject():
     assert isinstance(mock.attr1.attr2, _MockObject)
     assert isinstance(mock.attr1.attr2.meth(), _MockObject)
 
+    # subclassing
     class SubClass(mock.SomeClass):
         """docstring of SubClass"""
 
@@ -51,6 +53,16 @@ def method(self):
     assert obj.method() == "string"
     assert isinstance(obj.other_method(), SubClass)
 
+    # parametrized type
+    T = TypeVar('T')
+
+    class SubClass2(mock.SomeClass[T]):
+        """docstring of SubClass"""
+
+    obj2 = SubClass2()
+    assert SubClass2.__doc__ == "docstring of SubClass"
+    assert isinstance(obj2, SubClass2)
+
 
 def test_mock():
     modname = 'sphinx.unknown'

EOF_114329324912
tox --current-env -epy39 -v -- tests/test_ext_autodoc_mock.py
git checkout ec9af606c6cfa515f946d74da9b51574f2f9b16f tests/test_ext_autodoc_mock.py
