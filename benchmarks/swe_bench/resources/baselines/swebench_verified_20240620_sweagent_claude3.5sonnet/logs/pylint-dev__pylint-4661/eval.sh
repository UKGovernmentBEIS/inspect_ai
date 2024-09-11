#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 1d1619ef913b99b06647d2030bddff4800abdf63
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 1d1619ef913b99b06647d2030bddff4800abdf63 tests/lint/unittest_lint.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/lint/unittest_lint.py b/tests/lint/unittest_lint.py
--- a/tests/lint/unittest_lint.py
+++ b/tests/lint/unittest_lint.py
@@ -46,6 +46,7 @@
 from os.path import abspath, basename, dirname, isdir, join, sep
 from shutil import rmtree
 
+import appdirs
 import pytest
 
 from pylint import checkers, config, exceptions, interfaces, lint, testutils
@@ -631,7 +632,7 @@ def test_pylint_home():
     if uhome == "~":
         expected = ".pylint.d"
     else:
-        expected = os.path.join(uhome, ".pylint.d")
+        expected = appdirs.user_cache_dir("pylint")
     assert config.PYLINT_HOME == expected
 
     try:

EOF_114329324912
pytest -rA tests/lint/unittest_lint.py
git checkout 1d1619ef913b99b06647d2030bddff4800abdf63 tests/lint/unittest_lint.py
