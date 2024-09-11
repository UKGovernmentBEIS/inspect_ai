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
git diff 04ac9b45a34440fa447feb6ae934687aacbfc5f4
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 04ac9b45a34440fa447feb6ae934687aacbfc5f4 tests/delete/tests.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/delete/tests.py b/tests/delete/tests.py
--- a/tests/delete/tests.py
+++ b/tests/delete/tests.py
@@ -582,3 +582,11 @@ def test_fast_delete_empty_no_update_can_self_select(self):
                 User.objects.filter(avatar__desc='missing').delete(),
                 (0, {'delete.User': 0})
             )
+
+    def test_fast_delete_combined_relationships(self):
+        # The cascading fast-delete of SecondReferrer should be combined
+        # in a single DELETE WHERE referrer_id OR unique_field.
+        origin = Origin.objects.create()
+        referer = Referrer.objects.create(origin=origin, unique_field=42)
+        with self.assertNumQueries(2):
+            referer.delete()

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 delete.tests
git checkout 04ac9b45a34440fa447feb6ae934687aacbfc5f4 tests/delete/tests.py
