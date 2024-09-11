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
git diff eb16c7260e573ec513d84cb586d96bdf508f3173
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout eb16c7260e573ec513d84cb586d96bdf508f3173 tests/user_commands/tests.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/user_commands/tests.py b/tests/user_commands/tests.py
--- a/tests/user_commands/tests.py
+++ b/tests/user_commands/tests.py
@@ -253,6 +253,16 @@ def test_disallowed_abbreviated_options(self):
         self.assertNoOutput(err)
         self.assertEqual(out.strip(), 'Set foo')
 
+    def test_skip_checks(self):
+        self.write_settings('settings.py', apps=['django.contrib.staticfiles', 'user_commands'], sdict={
+            # (staticfiles.E001) The STATICFILES_DIRS setting is not a tuple or
+            # list.
+            'STATICFILES_DIRS': '"foo"',
+        })
+        out, err = self.run_manage(['set_option', '--skip-checks', '--set', 'foo'])
+        self.assertNoOutput(err)
+        self.assertEqual(out.strip(), 'Set foo')
+
 
 class UtilsTests(SimpleTestCase):
 

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 user_commands.tests
git checkout eb16c7260e573ec513d84cb586d96bdf508f3173 tests/user_commands/tests.py
