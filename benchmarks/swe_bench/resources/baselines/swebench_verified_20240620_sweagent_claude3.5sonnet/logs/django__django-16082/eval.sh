#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff bf47c719719d0e190a99fa2e7f959d5bbb7caf8a
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout bf47c719719d0e190a99fa2e7f959d5bbb7caf8a tests/expressions/tests.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/expressions/tests.py b/tests/expressions/tests.py
--- a/tests/expressions/tests.py
+++ b/tests/expressions/tests.py
@@ -2416,7 +2416,13 @@ def test_resolve_output_field_number(self):
             (IntegerField, FloatField, FloatField),
             (FloatField, IntegerField, FloatField),
         ]
-        connectors = [Combinable.ADD, Combinable.SUB, Combinable.MUL, Combinable.DIV]
+        connectors = [
+            Combinable.ADD,
+            Combinable.SUB,
+            Combinable.MUL,
+            Combinable.DIV,
+            Combinable.MOD,
+        ]
         for lhs, rhs, combined in tests:
             for connector in connectors:
                 with self.subTest(

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 expressions.tests
git checkout bf47c719719d0e190a99fa2e7f959d5bbb7caf8a tests/expressions/tests.py
