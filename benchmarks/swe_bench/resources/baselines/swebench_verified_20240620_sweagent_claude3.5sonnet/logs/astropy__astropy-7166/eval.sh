#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 26d147868f8a891a6009a25cd6a8576d2e1bd747
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test] --verbose
git checkout 26d147868f8a891a6009a25cd6a8576d2e1bd747 astropy/utils/tests/test_misc.py
git apply -v - <<'EOF_114329324912'
diff --git a/astropy/utils/tests/test_misc.py b/astropy/utils/tests/test_misc.py
--- a/astropy/utils/tests/test_misc.py
+++ b/astropy/utils/tests/test_misc.py
@@ -80,14 +80,26 @@ def __call__(self, *args):
             "FOO"
             pass
 
+        @property
+        def bar(self):
+            "BAR"
+            pass
+
     class Subclass(Base):
         def __call__(self, *args):
             pass
 
+        @property
+        def bar(self):
+            return 42
+
     if Base.__call__.__doc__ is not None:
         # TODO: Maybe if __doc__ is None this test should be skipped instead?
         assert Subclass.__call__.__doc__ == "FOO"
 
+    if Base.bar.__doc__ is not None:
+        assert Subclass.bar.__doc__ == "BAR"
+
 
 def test_set_locale():
     # First, test if the required locales are available

EOF_114329324912
pytest -rA -vv -o console_output_style=classic --tb=no astropy/utils/tests/test_misc.py
git checkout 26d147868f8a891a6009a25cd6a8576d2e1bd747 astropy/utils/tests/test_misc.py
