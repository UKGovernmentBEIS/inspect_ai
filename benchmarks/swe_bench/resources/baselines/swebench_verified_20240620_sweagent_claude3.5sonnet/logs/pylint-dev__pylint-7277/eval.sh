#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 684a1d6aa0a6791e20078bc524f97c8906332390
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 684a1d6aa0a6791e20078bc524f97c8906332390 tests/test_self.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_self.py b/tests/test_self.py
--- a/tests/test_self.py
+++ b/tests/test_self.py
@@ -759,6 +759,24 @@ def test_modify_sys_path() -> None:
                 modify_sys_path()
             assert sys.path == paths[1:]
 
+            paths = ["", *default_paths]
+            sys.path = copy(paths)
+            with _test_environ_pythonpath():
+                modify_sys_path()
+            assert sys.path == paths[1:]
+
+            paths = [".", *default_paths]
+            sys.path = copy(paths)
+            with _test_environ_pythonpath():
+                modify_sys_path()
+            assert sys.path == paths[1:]
+
+            paths = ["/do_not_remove", *default_paths]
+            sys.path = copy(paths)
+            with _test_environ_pythonpath():
+                modify_sys_path()
+            assert sys.path == paths
+
             paths = [cwd, cwd, *default_paths]
             sys.path = copy(paths)
             with _test_environ_pythonpath("."):

EOF_114329324912
pytest -rA tests/test_self.py
git checkout 684a1d6aa0a6791e20078bc524f97c8906332390 tests/test_self.py
