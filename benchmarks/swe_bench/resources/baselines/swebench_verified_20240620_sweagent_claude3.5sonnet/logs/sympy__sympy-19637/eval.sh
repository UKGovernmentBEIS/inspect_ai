#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 63f8f465d48559fecb4e4bf3c48b75bf15a3e0ef
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 63f8f465d48559fecb4e4bf3c48b75bf15a3e0ef sympy/core/tests/test_sympify.py
git apply -v - <<'EOF_114329324912'
diff --git a/sympy/core/tests/test_sympify.py b/sympy/core/tests/test_sympify.py
--- a/sympy/core/tests/test_sympify.py
+++ b/sympy/core/tests/test_sympify.py
@@ -512,6 +512,7 @@ def test_kernS():
     assert kernS('(1-2.*(1-y)*x)') == 1 - 2.*x*(1 - y)
     one = kernS('x - (x - 1)')
     assert one != 1 and one.expand() == 1
+    assert kernS("(2*x)/(x-1)") == 2*x/(x-1)
 
 
 def test_issue_6540_6552():

EOF_114329324912
PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose sympy/core/tests/test_sympify.py
git checkout 63f8f465d48559fecb4e4bf3c48b75bf15a3e0ef sympy/core/tests/test_sympify.py
