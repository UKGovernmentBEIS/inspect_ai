#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff f050a7775dfc9000f55d023d36d925a8d02ccfa8
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test]
git checkout f050a7775dfc9000f55d023d36d925a8d02ccfa8 tests/test_domain_py.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_domain_py.py b/tests/test_domain_py.py
--- a/tests/test_domain_py.py
+++ b/tests/test_domain_py.py
@@ -756,7 +756,7 @@ def test_pymethod_options(app):
 
     # :property:
     assert_node(doctree[1][1][8], addnodes.index,
-                entries=[('single', 'meth5() (Class property)', 'Class.meth5', '', None)])
+                entries=[('single', 'meth5 (Class property)', 'Class.meth5', '', None)])
     assert_node(doctree[1][1][9], ([desc_signature, ([desc_annotation, ("property", desc_sig_space)],
                                                      [desc_name, "meth5"])],
                                    [desc_content, ()]))

EOF_114329324912
tox --current-env -epy39 -v -- tests/test_domain_py.py
git checkout f050a7775dfc9000f55d023d36d925a8d02ccfa8 tests/test_domain_py.py
