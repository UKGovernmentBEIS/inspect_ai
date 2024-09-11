#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff fbe850106b2e4b85f838219cb9e1df95fba6c164
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout fbe850106b2e4b85f838219cb9e1df95fba6c164 tests/responses/test_fileresponse.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/responses/test_fileresponse.py b/tests/responses/test_fileresponse.py
--- a/tests/responses/test_fileresponse.py
+++ b/tests/responses/test_fileresponse.py
@@ -253,8 +253,10 @@ def test_compressed_response(self):
         """
         test_tuples = (
             (".tar.gz", "application/gzip"),
+            (".tar.br", "application/x-brotli"),
             (".tar.bz2", "application/x-bzip"),
             (".tar.xz", "application/x-xz"),
+            (".tar.Z", "application/x-compress"),
         )
         for extension, mimetype in test_tuples:
             with self.subTest(ext=extension):

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 responses.test_fileresponse
git checkout fbe850106b2e4b85f838219cb9e1df95fba6c164 tests/responses/test_fileresponse.py
