#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 5e6da19f0e44a0ae83944fb6ce18f18f781e1a6e
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test]
git checkout 5e6da19f0e44a0ae83944fb6ce18f18f781e1a6e tests/test_ext_autodoc_private_members.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_ext_autodoc_private_members.py b/tests/test_ext_autodoc_private_members.py
--- a/tests/test_ext_autodoc_private_members.py
+++ b/tests/test_ext_autodoc_private_members.py
@@ -60,3 +60,24 @@ def test_private_field_and_private_members(app):
         '   :meta private:',
         '',
     ]
+
+
+@pytest.mark.sphinx('html', testroot='ext-autodoc')
+def test_private_members(app):
+    app.config.autoclass_content = 'class'
+    options = {"members": None,
+               "private-members": "_public_function"}
+    actual = do_autodoc(app, 'module', 'target.private', options)
+    assert list(actual) == [
+        '',
+        '.. py:module:: target.private',
+        '',
+        '',
+        '.. py:function:: _public_function(name)',
+        '   :module: target.private',
+        '',
+        '   public_function is a docstring().',
+        '',
+        '   :meta public:',
+        '',
+    ]

EOF_114329324912
tox --current-env -epy39 -v -- tests/test_ext_autodoc_private_members.py
git checkout 5e6da19f0e44a0ae83944fb6ce18f18f781e1a6e tests/test_ext_autodoc_private_members.py
