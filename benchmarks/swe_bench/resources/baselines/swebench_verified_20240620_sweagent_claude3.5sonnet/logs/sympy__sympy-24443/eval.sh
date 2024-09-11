#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 809c53c077485ca48a206cee78340389cb83b7f1
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 809c53c077485ca48a206cee78340389cb83b7f1 sympy/combinatorics/tests/test_homomorphisms.py
git apply -v - <<'EOF_114329324912'
diff --git a/sympy/combinatorics/tests/test_homomorphisms.py b/sympy/combinatorics/tests/test_homomorphisms.py
--- a/sympy/combinatorics/tests/test_homomorphisms.py
+++ b/sympy/combinatorics/tests/test_homomorphisms.py
@@ -57,6 +57,11 @@ def test_homomorphism():
     assert T.codomain == D
     assert T(a*b) == p
 
+    D3 = DihedralGroup(3)
+    T = homomorphism(D3, D3, D3.generators, D3.generators)
+    assert T.is_isomorphism()
+
+
 def test_isomorphisms():
 
     F, a, b = free_group("a, b")

EOF_114329324912
PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose sympy/combinatorics/tests/test_homomorphisms.py
git checkout 809c53c077485ca48a206cee78340389cb83b7f1 sympy/combinatorics/tests/test_homomorphisms.py
