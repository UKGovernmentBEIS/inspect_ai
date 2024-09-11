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
git diff 437196da9a386bd4cc62b0ce3f2de4aba468613d
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 437196da9a386bd4cc62b0ce3f2de4aba468613d tests/delete/tests.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/delete/tests.py b/tests/delete/tests.py
--- a/tests/delete/tests.py
+++ b/tests/delete/tests.py
@@ -605,6 +605,12 @@ def receiver(instance, **kwargs):
 
 
 class FastDeleteTests(TestCase):
+    def test_fast_delete_all(self):
+        with self.assertNumQueries(1) as ctx:
+            User.objects.all().delete()
+        sql = ctx.captured_queries[0]['sql']
+        # No subqueries is used when performing a full delete.
+        self.assertNotIn('SELECT', sql)
 
     def test_fast_delete_fk(self):
         u = User.objects.create(

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 delete.tests
git checkout 437196da9a386bd4cc62b0ce3f2de4aba468613d tests/delete/tests.py
