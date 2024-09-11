#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff a7141cd90019b62688d507ae056298507678c058
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test] --verbose
git checkout a7141cd90019b62688d507ae056298507678c058 astropy/utils/tests/test_introspection.py
git apply -v - <<'EOF_114329324912'
diff --git a/astropy/utils/tests/test_introspection.py b/astropy/utils/tests/test_introspection.py
--- a/astropy/utils/tests/test_introspection.py
+++ b/astropy/utils/tests/test_introspection.py
@@ -67,7 +67,7 @@ def test_minversion():
     from types import ModuleType
     test_module = ModuleType(str("test_module"))
     test_module.__version__ = '0.12.2'
-    good_versions = ['0.12', '0.12.1', '0.12.0.dev']
+    good_versions = ['0.12', '0.12.1', '0.12.0.dev', '0.12dev']
     bad_versions = ['1', '1.2rc1']
     for version in good_versions:
         assert minversion(test_module, version)

EOF_114329324912
pytest -rA -vv -o console_output_style=classic --tb=no astropy/utils/tests/test_introspection.py
git checkout a7141cd90019b62688d507ae056298507678c058 astropy/utils/tests/test_introspection.py
