#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 1ba83c47ce7b177efe90d5f51f7760680f72eda0
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install .
git checkout 1ba83c47ce7b177efe90d5f51f7760680f72eda0 test_requests.py
git apply -v - <<'EOF_114329324912'
diff --git a/test_requests.py b/test_requests.py
--- a/test_requests.py
+++ b/test_requests.py
@@ -433,6 +433,11 @@ def test_unicode_multipart_post_fieldnames(self):
         prep = r.prepare()
         assert b'name="stuff"' in prep.body
         assert b'name="b\'stuff\'"' not in prep.body
+    
+    def test_unicode_method_name(self):
+        files = {'file': open('test_requests.py', 'rb')}
+        r = requests.request(method=u'POST', url=httpbin('post'), files=files)
+        assert r.status_code == 200
 
     def test_custom_content_type(self):
         r = requests.post(httpbin('post'),

EOF_114329324912
pytest -rA test_requests.py
git checkout 1ba83c47ce7b177efe90d5f51f7760680f72eda0 test_requests.py
