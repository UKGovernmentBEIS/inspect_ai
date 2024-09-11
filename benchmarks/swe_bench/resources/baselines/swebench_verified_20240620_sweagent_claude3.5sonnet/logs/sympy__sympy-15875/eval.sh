#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff b506169ad727ee39cb3d60c8b3ff5e315d443d8e
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout b506169ad727ee39cb3d60c8b3ff5e315d443d8e sympy/core/tests/test_arit.py
git apply -v - <<'EOF_114329324912'
diff --git a/sympy/core/tests/test_arit.py b/sympy/core/tests/test_arit.py
--- a/sympy/core/tests/test_arit.py
+++ b/sympy/core/tests/test_arit.py
@@ -1986,10 +1986,15 @@ def test_Add_is_zero():
     x, y = symbols('x y', zero=True)
     assert (x + y).is_zero
 
+    # Issue 15873
+    e = -2*I + (1 + I)**2
+    assert e.is_zero is None
+
 
 def test_issue_14392():
     assert (sin(zoo)**2).as_real_imag() == (nan, nan)
 
+
 def test_divmod():
     assert divmod(x, y) == (x//y, x % y)
     assert divmod(x, 3) == (x//3, x % 3)

EOF_114329324912
PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose sympy/core/tests/test_arit.py
git checkout b506169ad727ee39cb3d60c8b3ff5e315d443d8e sympy/core/tests/test_arit.py
