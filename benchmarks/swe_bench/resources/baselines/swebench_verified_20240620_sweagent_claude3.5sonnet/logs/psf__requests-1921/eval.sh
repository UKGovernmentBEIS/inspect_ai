#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 3c88e520da24ae6f736929a750876e7654accc3d
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install .
git checkout 3c88e520da24ae6f736929a750876e7654accc3d test_requests.py
git apply -v - <<'EOF_114329324912'
diff --git a/test_requests.py b/test_requests.py
--- a/test_requests.py
+++ b/test_requests.py
@@ -211,6 +211,14 @@ def test_requests_in_history_are_not_overridden(self):
         req_urls = [r.request.url for r in resp.history]
         assert urls == req_urls
 
+    def test_headers_on_session_with_None_are_not_sent(self):
+        """Do not send headers in Session.headers with None values."""
+        ses = requests.Session()
+        ses.headers['Accept-Encoding'] = None
+        req = requests.Request('GET', 'http://httpbin.org/get')
+        prep = ses.prepare_request(req)
+        assert 'Accept-Encoding' not in prep.headers
+
     def test_user_agent_transfers(self):
 
         heads = {

EOF_114329324912
pytest -rA test_requests.py
git checkout 3c88e520da24ae6f736929a750876e7654accc3d test_requests.py
