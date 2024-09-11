#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 9988d5ce267bf0df4791770b469431b1fb00dcdd
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test]
git checkout 9988d5ce267bf0df4791770b469431b1fb00dcdd tests/roots/test-ext-autodoc/target/docstring_signature.py tests/test_ext_autodoc_configs.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/roots/test-ext-autodoc/target/docstring_signature.py b/tests/roots/test-ext-autodoc/target/docstring_signature.py
--- a/tests/roots/test-ext-autodoc/target/docstring_signature.py
+++ b/tests/roots/test-ext-autodoc/target/docstring_signature.py
@@ -17,3 +17,9 @@ def __new__(cls):
 class D:
     def __init__(self):
         """D(foo, bar, baz)"""
+
+
+class E:
+    def __init__(self):
+        """E(foo: int, bar: int, baz: int) -> None \\
+        E(foo: str, bar: str, baz: str) -> None"""
diff --git a/tests/test_ext_autodoc_configs.py b/tests/test_ext_autodoc_configs.py
--- a/tests/test_ext_autodoc_configs.py
+++ b/tests/test_ext_autodoc_configs.py
@@ -346,6 +346,10 @@ def test_autoclass_content_and_docstring_signature_class(app):
         '',
         '.. py:class:: D()',
         '   :module: target.docstring_signature',
+        '',
+        '',
+        '.. py:class:: E()',
+        '   :module: target.docstring_signature',
         ''
     ]
 
@@ -375,6 +379,11 @@ def test_autoclass_content_and_docstring_signature_init(app):
         '',
         '.. py:class:: D(foo, bar, baz)',
         '   :module: target.docstring_signature',
+        '',
+        '',
+        '.. py:class:: E(foo: int, bar: int, baz: int) -> None',
+        '              E(foo: str, bar: str, baz: str) -> None',
+        '   :module: target.docstring_signature',
         ''
     ]
 
@@ -409,6 +418,11 @@ def test_autoclass_content_and_docstring_signature_both(app):
         '.. py:class:: D(foo, bar, baz)',
         '   :module: target.docstring_signature',
         '',
+        '',
+        '.. py:class:: E(foo: int, bar: int, baz: int) -> None',
+        '              E(foo: str, bar: str, baz: str) -> None',
+        '   :module: target.docstring_signature',
+        '',
     ]
 
 

EOF_114329324912
tox --current-env -epy39 -v -- tests/roots/test-ext-autodoc/target/docstring_signature.py tests/test_ext_autodoc_configs.py
git checkout 9988d5ce267bf0df4791770b469431b1fb00dcdd tests/roots/test-ext-autodoc/target/docstring_signature.py tests/test_ext_autodoc_configs.py
