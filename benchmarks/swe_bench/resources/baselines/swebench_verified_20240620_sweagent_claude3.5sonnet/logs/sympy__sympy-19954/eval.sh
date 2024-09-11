#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 6f54459aa0248bf1467ad12ee6333d8bc924a642
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 6f54459aa0248bf1467ad12ee6333d8bc924a642 sympy/combinatorics/tests/test_perm_groups.py
git apply -v - <<'EOF_114329324912'
diff --git a/sympy/combinatorics/tests/test_perm_groups.py b/sympy/combinatorics/tests/test_perm_groups.py
--- a/sympy/combinatorics/tests/test_perm_groups.py
+++ b/sympy/combinatorics/tests/test_perm_groups.py
@@ -905,6 +905,14 @@ def test_sylow_subgroup():
     assert G.order() % S.order() == 0
     assert G.order()/S.order() % 2 > 0
 
+    G = DihedralGroup(18)
+    S = G.sylow_subgroup(p=2)
+    assert S.order() == 4
+
+    G = DihedralGroup(50)
+    S = G.sylow_subgroup(p=2)
+    assert S.order() == 4
+
 
 @slow
 def test_presentation():

EOF_114329324912
PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose sympy/combinatorics/tests/test_perm_groups.py
git checkout 6f54459aa0248bf1467ad12ee6333d8bc924a642 sympy/combinatorics/tests/test_perm_groups.py
