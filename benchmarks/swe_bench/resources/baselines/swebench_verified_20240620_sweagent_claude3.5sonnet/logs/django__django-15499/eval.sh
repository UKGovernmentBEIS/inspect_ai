#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff d90e34c61b27fba2527834806639eebbcfab9631
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout d90e34c61b27fba2527834806639eebbcfab9631 tests/migrations/test_optimizer.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/migrations/test_optimizer.py b/tests/migrations/test_optimizer.py
--- a/tests/migrations/test_optimizer.py
+++ b/tests/migrations/test_optimizer.py
@@ -129,6 +129,30 @@ def test_create_alter_model_options(self):
             ],
         )
 
+    def test_create_alter_model_managers(self):
+        self.assertOptimizesTo(
+            [
+                migrations.CreateModel("Foo", fields=[]),
+                migrations.AlterModelManagers(
+                    name="Foo",
+                    managers=[
+                        ("objects", models.Manager()),
+                        ("things", models.Manager()),
+                    ],
+                ),
+            ],
+            [
+                migrations.CreateModel(
+                    "Foo",
+                    fields=[],
+                    managers=[
+                        ("objects", models.Manager()),
+                        ("things", models.Manager()),
+                    ],
+                ),
+            ],
+        )
+
     def test_create_model_and_remove_model_options(self):
         self.assertOptimizesTo(
             [

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 migrations.test_optimizer
git checkout d90e34c61b27fba2527834806639eebbcfab9631 tests/migrations/test_optimizer.py
