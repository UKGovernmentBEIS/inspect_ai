#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff b4777fdcef467b7132c055f8ac2c9a5059e6a145
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout b4777fdcef467b7132c055f8ac2c9a5059e6a145 sympy/printing/tests/test_str.py
git apply -v - <<'EOF_114329324912'
diff --git a/sympy/printing/tests/test_str.py b/sympy/printing/tests/test_str.py
--- a/sympy/printing/tests/test_str.py
+++ b/sympy/printing/tests/test_str.py
@@ -252,6 +252,8 @@ def test_Mul():
     # For issue 14160
     assert str(Mul(-2, x, Pow(Mul(y,y,evaluate=False), -1, evaluate=False),
                                                 evaluate=False)) == '-2*x/(y*y)'
+    # issue 21537
+    assert str(Mul(x, Pow(1/y, -1, evaluate=False), evaluate=False)) == 'x/(1/y)'
 
 
     class CustomClass1(Expr):

EOF_114329324912
PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose sympy/printing/tests/test_str.py
git checkout b4777fdcef467b7132c055f8ac2c9a5059e6a145 sympy/printing/tests/test_str.py
