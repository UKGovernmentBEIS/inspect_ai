#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 50d8a102f0735da8e165a0369bbb994c7d0592a6
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 50d8a102f0735da8e165a0369bbb994c7d0592a6 sympy/sets/tests/test_sets.py
git apply -v - <<'EOF_114329324912'
diff --git a/sympy/sets/tests/test_sets.py b/sympy/sets/tests/test_sets.py
--- a/sympy/sets/tests/test_sets.py
+++ b/sympy/sets/tests/test_sets.py
@@ -187,6 +187,10 @@ def test_Complement():
 
     assert S.Reals - Union(S.Naturals, FiniteSet(pi)) == \
             Intersection(S.Reals - S.Naturals, S.Reals - FiniteSet(pi))
+    # isssue 12712
+    assert Complement(FiniteSet(x, y, 2), Interval(-10, 10)) == \
+            Complement(FiniteSet(x, y), Interval(-10, 10))
+
 
 def test_complement():
     assert Interval(0, 1).complement(S.Reals) == \

EOF_114329324912
PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose sympy/sets/tests/test_sets.py
git checkout 50d8a102f0735da8e165a0369bbb994c7d0592a6 sympy/sets/tests/test_sets.py
