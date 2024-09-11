#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 39d0fdd9096f7dceccbc8f82e1eda7dd64717a8e
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install .
git checkout 39d0fdd9096f7dceccbc8f82e1eda7dd64717a8e tests/test_requests.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_requests.py b/tests/test_requests.py
--- a/tests/test_requests.py
+++ b/tests/test_requests.py
@@ -81,6 +81,8 @@ def test_entry_points(self):
             (InvalidSchema, 'localhost.localdomain:3128/'),
             (InvalidSchema, '10.122.1.1:3128/'),
             (InvalidURL, 'http://'),
+            (InvalidURL, 'http://*example.com'),
+            (InvalidURL, 'http://.example.com'),
         ))
     def test_invalid_url(self, exception, url):
         with pytest.raises(exception):

EOF_114329324912
pytest -rA tests/test_requests.py
git checkout 39d0fdd9096f7dceccbc8f82e1eda7dd64717a8e tests/test_requests.py
