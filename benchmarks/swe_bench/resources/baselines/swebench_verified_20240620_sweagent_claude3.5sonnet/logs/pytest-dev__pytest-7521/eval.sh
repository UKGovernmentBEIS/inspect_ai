#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 41d211c24a6781843b174379d6d6538f5c17adb9
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 41d211c24a6781843b174379d6d6538f5c17adb9 testing/test_capture.py
git apply -v - <<'EOF_114329324912'
diff --git a/testing/test_capture.py b/testing/test_capture.py
--- a/testing/test_capture.py
+++ b/testing/test_capture.py
@@ -514,6 +514,12 @@ def test_hello(capfd):
         )
         reprec.assertoutcome(passed=1)
 
+    @pytest.mark.parametrize("nl", ("\n", "\r\n", "\r"))
+    def test_cafd_preserves_newlines(self, capfd, nl):
+        print("test", end=nl)
+        out, err = capfd.readouterr()
+        assert out.endswith(nl)
+
     def test_capfdbinary(self, testdir):
         reprec = testdir.inline_runsource(
             """\

EOF_114329324912
pytest -rA testing/test_capture.py
git checkout 41d211c24a6781843b174379d6d6538f5c17adb9 testing/test_capture.py
