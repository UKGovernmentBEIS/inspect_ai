#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff cffd4e0f86fefd4802349a9f9b19ed70934ea354
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout cffd4e0f86fefd4802349a9f9b19ed70934ea354 sympy/core/tests/test_basic.py
git apply -v - <<'EOF_114329324912'
diff --git a/sympy/core/tests/test_basic.py b/sympy/core/tests/test_basic.py
--- a/sympy/core/tests/test_basic.py
+++ b/sympy/core/tests/test_basic.py
@@ -34,6 +34,12 @@ def test_structure():
     assert bool(b1)
 
 
+def test_immutable():
+    assert not hasattr(b1, '__dict__')
+    with raises(AttributeError):
+        b1.x = 1
+
+
 def test_equality():
     instances = [b1, b2, b3, b21, Basic(b1, b1, b1), Basic]
     for i, b_i in enumerate(instances):

EOF_114329324912
PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose sympy/core/tests/test_basic.py
git checkout cffd4e0f86fefd4802349a9f9b19ed70934ea354 sympy/core/tests/test_basic.py
