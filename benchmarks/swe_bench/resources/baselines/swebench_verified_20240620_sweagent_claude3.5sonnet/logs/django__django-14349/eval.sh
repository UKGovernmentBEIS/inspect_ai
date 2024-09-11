#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff a708f39ce67af174df90c5b5e50ad1976cec7cb8
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout a708f39ce67af174df90c5b5e50ad1976cec7cb8 tests/validators/tests.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/validators/tests.py b/tests/validators/tests.py
--- a/tests/validators/tests.py
+++ b/tests/validators/tests.py
@@ -226,9 +226,15 @@
     (URLValidator(), None, ValidationError),
     (URLValidator(), 56, ValidationError),
     (URLValidator(), 'no_scheme', ValidationError),
-    # Trailing newlines not accepted
+    # Newlines and tabs are not accepted.
     (URLValidator(), 'http://www.djangoproject.com/\n', ValidationError),
     (URLValidator(), 'http://[::ffff:192.9.5.5]\n', ValidationError),
+    (URLValidator(), 'http://www.djangoproject.com/\r', ValidationError),
+    (URLValidator(), 'http://[::ffff:192.9.5.5]\r', ValidationError),
+    (URLValidator(), 'http://www.django\rproject.com/', ValidationError),
+    (URLValidator(), 'http://[::\rffff:192.9.5.5]', ValidationError),
+    (URLValidator(), 'http://\twww.djangoproject.com/', ValidationError),
+    (URLValidator(), 'http://\t[::ffff:192.9.5.5]', ValidationError),
     # Trailing junk does not take forever to reject
     (URLValidator(), 'http://www.asdasdasdasdsadfm.com.br ', ValidationError),
     (URLValidator(), 'http://www.asdasdasdasdsadfm.com.br z', ValidationError),

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 validators.tests
git checkout a708f39ce67af174df90c5b5e50ad1976cec7cb8 tests/validators/tests.py
