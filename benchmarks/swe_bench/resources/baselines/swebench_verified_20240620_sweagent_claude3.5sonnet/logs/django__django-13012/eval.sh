#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen
export LANG=en_US.UTF-8
export LANGUAGE=en_US:en
export LC_ALL=en_US.UTF-8
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 22a59c01c00cf9fbefaee0e8e67fab82bbaf1fd2
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 22a59c01c00cf9fbefaee0e8e67fab82bbaf1fd2 tests/expressions/tests.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/expressions/tests.py b/tests/expressions/tests.py
--- a/tests/expressions/tests.py
+++ b/tests/expressions/tests.py
@@ -1828,3 +1828,13 @@ def test_reversed_and(self):
     def test_reversed_or(self):
         with self.assertRaisesMessage(NotImplementedError, self.bitwise_msg):
             object() | Combinable()
+
+
+class ExpressionWrapperTests(SimpleTestCase):
+    def test_empty_group_by(self):
+        expr = ExpressionWrapper(Value(3), output_field=IntegerField())
+        self.assertEqual(expr.get_group_by_cols(alias=None), [])
+
+    def test_non_empty_group_by(self):
+        expr = ExpressionWrapper(Lower(Value('f')), output_field=IntegerField())
+        self.assertEqual(expr.get_group_by_cols(alias=None), [expr.expression])

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 expressions.tests
git checkout 22a59c01c00cf9fbefaee0e8e67fab82bbaf1fd2 tests/expressions/tests.py
