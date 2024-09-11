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
git diff d4df5e1b0b1c643fe0fc521add0236764ec8e92a
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout d4df5e1b0b1c643fe0fc521add0236764ec8e92a tests/template_tests/test_engine.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/template_tests/test_engine.py b/tests/template_tests/test_engine.py
--- a/tests/template_tests/test_engine.py
+++ b/tests/template_tests/test_engine.py
@@ -21,6 +21,13 @@ def test_basic_context(self):
             'obj:test\n',
         )
 
+    def test_autoescape_off(self):
+        engine = Engine(dirs=[TEMPLATE_DIR], autoescape=False)
+        self.assertEqual(
+            engine.render_to_string('test_context.html', {'obj': '<script>'}),
+            'obj:<script>\n',
+        )
+
 
 class GetDefaultTests(SimpleTestCase):
 

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 template_tests.test_engine
git checkout d4df5e1b0b1c643fe0fc521add0236764ec8e92a tests/template_tests/test_engine.py
