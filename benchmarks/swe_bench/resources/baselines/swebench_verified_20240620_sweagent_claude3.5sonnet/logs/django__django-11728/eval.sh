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
git diff 05457817647368be4b019314fcc655445a5b4c0c
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 05457817647368be4b019314fcc655445a5b4c0c tests/admin_docs/test_views.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/admin_docs/test_views.py b/tests/admin_docs/test_views.py
--- a/tests/admin_docs/test_views.py
+++ b/tests/admin_docs/test_views.py
@@ -348,9 +348,13 @@ def test_simplify_regex(self):
             (r'^a', '/a'),
             (r'^(?P<a>\w+)/b/(?P<c>\w+)/$', '/<a>/b/<c>/'),
             (r'^(?P<a>\w+)/b/(?P<c>\w+)$', '/<a>/b/<c>'),
+            (r'^(?P<a>\w+)/b/(?P<c>\w+)', '/<a>/b/<c>'),
             (r'^(?P<a>\w+)/b/(\w+)$', '/<a>/b/<var>'),
+            (r'^(?P<a>\w+)/b/(\w+)', '/<a>/b/<var>'),
             (r'^(?P<a>\w+)/b/((x|y)\w+)$', '/<a>/b/<var>'),
+            (r'^(?P<a>\w+)/b/((x|y)\w+)', '/<a>/b/<var>'),
             (r'^(?P<a>(x|y))/b/(?P<c>\w+)$', '/<a>/b/<c>'),
+            (r'^(?P<a>(x|y))/b/(?P<c>\w+)', '/<a>/b/<c>'),
             (r'^(?P<a>(x|y))/b/(?P<c>\w+)ab', '/<a>/b/<c>ab'),
             (r'^(?P<a>(x|y)(\(|\)))/b/(?P<c>\w+)ab', '/<a>/b/<c>ab'),
             (r'^a/?$', '/a/'),

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 admin_docs.test_views
git checkout 05457817647368be4b019314fcc655445a5b4c0c tests/admin_docs/test_views.py
