#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 0b31e024873681e187b574fe1c4afe5e48aeeecf
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 0b31e024873681e187b574fe1c4afe5e48aeeecf tests/template_tests/test_autoreloader.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/template_tests/test_autoreloader.py b/tests/template_tests/test_autoreloader.py
--- a/tests/template_tests/test_autoreloader.py
+++ b/tests/template_tests/test_autoreloader.py
@@ -81,6 +81,17 @@ def test_reset_all_loaders(self, mock_reset):
         autoreload.reset_loaders()
         self.assertEqual(mock_reset.call_count, 2)
 
+    @override_settings(
+        TEMPLATES=[
+            {
+                "DIRS": [""],
+                "BACKEND": "django.template.backends.django.DjangoTemplates",
+            }
+        ]
+    )
+    def test_template_dirs_ignore_empty_path(self):
+        self.assertEqual(autoreload.get_template_directories(), set())
+
     @override_settings(
         TEMPLATES=[
             {

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 template_tests.test_autoreloader
git checkout 0b31e024873681e187b574fe1c4afe5e48aeeecf tests/template_tests/test_autoreloader.py
