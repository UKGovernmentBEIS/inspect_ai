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
git diff bb64b99b78a579cb2f6178011a4cf9366e634438
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout bb64b99b78a579cb2f6178011a4cf9366e634438 tests/migrations/test_optimizer.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/migrations/test_optimizer.py b/tests/migrations/test_optimizer.py
--- a/tests/migrations/test_optimizer.py
+++ b/tests/migrations/test_optimizer.py
@@ -119,6 +119,42 @@ def test_create_alter_model_options(self):
             ]
         )
 
+    def test_create_model_and_remove_model_options(self):
+        self.assertOptimizesTo(
+            [
+                migrations.CreateModel(
+                    'MyModel',
+                    fields=[],
+                    options={'verbose_name': 'My Model'},
+                ),
+                migrations.AlterModelOptions('MyModel', options={}),
+            ],
+            [migrations.CreateModel('MyModel', fields=[])],
+        )
+        self.assertOptimizesTo(
+            [
+                migrations.CreateModel(
+                    'MyModel',
+                    fields=[],
+                    options={
+                        'verbose_name': 'My Model',
+                        'verbose_name_plural': 'My Model plural',
+                    },
+                ),
+                migrations.AlterModelOptions(
+                    'MyModel',
+                    options={'verbose_name': 'My Model'},
+                ),
+            ],
+            [
+                migrations.CreateModel(
+                    'MyModel',
+                    fields=[],
+                    options={'verbose_name': 'My Model'},
+                ),
+            ],
+        )
+
     def _test_create_alter_foo_delete_model(self, alter_foo):
         """
         CreateModel, AlterModelTable, AlterUniqueTogether/AlterIndexTogether/

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 migrations.test_optimizer
git checkout bb64b99b78a579cb2f6178011a4cf9366e634438 tests/migrations/test_optimizer.py
