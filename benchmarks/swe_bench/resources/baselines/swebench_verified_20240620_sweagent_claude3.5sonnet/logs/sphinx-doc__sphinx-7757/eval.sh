#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 212fd67b9f0b4fae6a7c3501fdf1a9a5b2801329
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test]
git checkout 212fd67b9f0b4fae6a7c3501fdf1a9a5b2801329 tests/test_util_inspect.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_util_inspect.py b/tests/test_util_inspect.py
--- a/tests/test_util_inspect.py
+++ b/tests/test_util_inspect.py
@@ -335,10 +335,14 @@ def test_signature_from_str_kwonly_args():
 @pytest.mark.skipif(sys.version_info < (3, 8),
                     reason='python-3.8 or above is required')
 def test_signature_from_str_positionaly_only_args():
-    sig = inspect.signature_from_str('(a, /, b)')
-    assert list(sig.parameters.keys()) == ['a', 'b']
+    sig = inspect.signature_from_str('(a, b=0, /, c=1)')
+    assert list(sig.parameters.keys()) == ['a', 'b', 'c']
     assert sig.parameters['a'].kind == Parameter.POSITIONAL_ONLY
-    assert sig.parameters['b'].kind == Parameter.POSITIONAL_OR_KEYWORD
+    assert sig.parameters['a'].default == Parameter.empty
+    assert sig.parameters['b'].kind == Parameter.POSITIONAL_ONLY
+    assert sig.parameters['b'].default == '0'
+    assert sig.parameters['c'].kind == Parameter.POSITIONAL_OR_KEYWORD
+    assert sig.parameters['c'].default == '1'
 
 
 def test_signature_from_str_invalid():

EOF_114329324912
tox --current-env -epy39 -v -- tests/test_util_inspect.py
git checkout 212fd67b9f0b4fae6a7c3501fdf1a9a5b2801329 tests/test_util_inspect.py
