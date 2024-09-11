#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 770d3e6a4ce8e0a91a9e27156036c1985e74d4a3
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 770d3e6a4ce8e0a91a9e27156036c1985e74d4a3 tests/expressions/tests.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/expressions/tests.py b/tests/expressions/tests.py
--- a/tests/expressions/tests.py
+++ b/tests/expressions/tests.py
@@ -1905,6 +1905,13 @@ def test_optimizations(self):
         )
         self.assertNotIn('ORDER BY', captured_sql)
 
+    def test_negated_empty_exists(self):
+        manager = Manager.objects.create()
+        qs = Manager.objects.filter(
+            ~Exists(Manager.objects.none()) & Q(pk=manager.pk)
+        )
+        self.assertSequenceEqual(qs, [manager])
+
 
 class FieldTransformTests(TestCase):
 

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 expressions.tests
git checkout 770d3e6a4ce8e0a91a9e27156036c1985e74d4a3 tests/expressions/tests.py
