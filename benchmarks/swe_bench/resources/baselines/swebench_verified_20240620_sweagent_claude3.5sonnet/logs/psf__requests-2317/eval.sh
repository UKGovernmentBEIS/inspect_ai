#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 091991be0da19de9108dbe5e3752917fea3d7fdc
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install .
git checkout 091991be0da19de9108dbe5e3752917fea3d7fdc test_requests.py
git apply -v - <<'EOF_114329324912'
diff --git a/test_requests.py b/test_requests.py
--- a/test_requests.py
+++ b/test_requests.py
@@ -1389,6 +1389,11 @@ def test_total_timeout_connect(self):
         except ConnectTimeout:
             pass
 
+    def test_encoded_methods(self):
+        """See: https://github.com/kennethreitz/requests/issues/2316"""
+        r = requests.request(b'GET', httpbin('get'))
+        assert r.ok
+
 
 SendCall = collections.namedtuple('SendCall', ('args', 'kwargs'))
 

EOF_114329324912
pytest -rA test_requests.py
git checkout 091991be0da19de9108dbe5e3752917fea3d7fdc test_requests.py
