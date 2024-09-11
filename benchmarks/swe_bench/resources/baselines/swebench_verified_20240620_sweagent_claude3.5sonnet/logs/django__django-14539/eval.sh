#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 6a5ef557f80a8eb6a758ebe99c8bb477ca47459e
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 6a5ef557f80a8eb6a758ebe99c8bb477ca47459e tests/utils_tests/test_html.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/utils_tests/test_html.py b/tests/utils_tests/test_html.py
--- a/tests/utils_tests/test_html.py
+++ b/tests/utils_tests/test_html.py
@@ -250,6 +250,10 @@ def test_urlize(self):
                 'Search for google.com/?q=! and see.',
                 'Search for <a href="http://google.com/?q=">google.com/?q=</a>! and see.'
             ),
+            (
+                'Search for google.com/?q=1&lt! and see.',
+                'Search for <a href="http://google.com/?q=1%3C">google.com/?q=1&lt</a>! and see.'
+            ),
             (
                 lazystr('Search for google.com/?q=!'),
                 'Search for <a href="http://google.com/?q=">google.com/?q=</a>!'

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 utils_tests.test_html
git checkout 6a5ef557f80a8eb6a758ebe99c8bb477ca47459e tests/utils_tests/test_html.py
