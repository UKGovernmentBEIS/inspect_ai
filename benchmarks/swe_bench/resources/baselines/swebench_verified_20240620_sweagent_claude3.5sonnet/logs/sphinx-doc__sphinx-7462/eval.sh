#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff b3e26a6c851133b82b50f4b68b53692076574d13
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test]
git checkout b3e26a6c851133b82b50f4b68b53692076574d13 tests/test_domain_py.py tests/test_pycode_ast.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_domain_py.py b/tests/test_domain_py.py
--- a/tests/test_domain_py.py
+++ b/tests/test_domain_py.py
@@ -255,6 +255,13 @@ def test_parse_annotation():
                           [pending_xref, "int"],
                           [desc_sig_punctuation, "]"]))
 
+    doctree = _parse_annotation("Tuple[()]")
+    assert_node(doctree, ([pending_xref, "Tuple"],
+                          [desc_sig_punctuation, "["],
+                          [desc_sig_punctuation, "("],
+                          [desc_sig_punctuation, ")"],
+                          [desc_sig_punctuation, "]"]))
+
     doctree = _parse_annotation("Callable[[int, int], int]")
     assert_node(doctree, ([pending_xref, "Callable"],
                           [desc_sig_punctuation, "["],
diff --git a/tests/test_pycode_ast.py b/tests/test_pycode_ast.py
--- a/tests/test_pycode_ast.py
+++ b/tests/test_pycode_ast.py
@@ -54,6 +54,7 @@
     ("- 1", "- 1"),                             # UnaryOp
     ("- a", "- a"),                             # USub
     ("(1, 2, 3)", "1, 2, 3"),                   # Tuple
+    ("()", "()"),                               # Tuple (empty)
 ])
 def test_unparse(source, expected):
     module = ast.parse(source)

EOF_114329324912
tox --current-env -epy39 -v -- tests/test_domain_py.py tests/test_pycode_ast.py
git checkout b3e26a6c851133b82b50f4b68b53692076574d13 tests/test_domain_py.py tests/test_pycode_ast.py
