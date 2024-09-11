#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 0eb3e9bd754e4c9fac8b616b705178727fc8031e
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 0eb3e9bd754e4c9fac8b616b705178727fc8031e tests/migrations/test_writer.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/migrations/test_writer.py b/tests/migrations/test_writer.py
--- a/tests/migrations/test_writer.py
+++ b/tests/migrations/test_writer.py
@@ -7,6 +7,7 @@
 import pathlib
 import re
 import sys
+import time
 import uuid
 import zoneinfo
 from types import NoneType
@@ -912,13 +913,18 @@ def test_sorted_imports(self):
                             ),
                         ),
                     ),
+                    migrations.AddField(
+                        "mymodel",
+                        "myfield2",
+                        models.FloatField(default=time.time),
+                    ),
                 ]
             },
         )
         writer = MigrationWriter(migration)
         output = writer.as_string()
         self.assertIn(
-            "import datetime\nfrom django.db import migrations, models\n",
+            "import datetime\nimport time\nfrom django.db import migrations, models\n",
             output,
         )
 

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 migrations.test_writer
git checkout 0eb3e9bd754e4c9fac8b616b705178727fc8031e tests/migrations/test_writer.py
