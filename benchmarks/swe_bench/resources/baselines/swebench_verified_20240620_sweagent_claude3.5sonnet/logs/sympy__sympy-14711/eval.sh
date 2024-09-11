#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff c6753448b5c34f95e250105d76709fe4d349ca1f
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout c6753448b5c34f95e250105d76709fe4d349ca1f sympy/physics/vector/tests/test_vector.py
git apply -v - <<'EOF_114329324912'
diff --git a/sympy/physics/vector/tests/test_vector.py b/sympy/physics/vector/tests/test_vector.py
--- a/sympy/physics/vector/tests/test_vector.py
+++ b/sympy/physics/vector/tests/test_vector.py
@@ -13,6 +13,8 @@ def test_Vector():
     assert A.y != A.z
     assert A.z != A.x
 
+    assert A.x + 0 == A.x
+
     v1 = x*A.x + y*A.y + z*A.z
     v2 = x**2*A.x + y**2*A.y + z**2*A.z
     v3 = v1 + v2

EOF_114329324912
PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose sympy/physics/vector/tests/test_vector.py
git checkout c6753448b5c34f95e250105d76709fe4d349ca1f sympy/physics/vector/tests/test_vector.py
