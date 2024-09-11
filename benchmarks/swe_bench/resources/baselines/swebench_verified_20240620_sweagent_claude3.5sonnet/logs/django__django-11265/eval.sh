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
git diff 21aa2a5e785eef1f47beb1c3760fdd7d8915ae09
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 21aa2a5e785eef1f47beb1c3760fdd7d8915ae09 tests/filtered_relation/tests.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/filtered_relation/tests.py b/tests/filtered_relation/tests.py
--- a/tests/filtered_relation/tests.py
+++ b/tests/filtered_relation/tests.py
@@ -98,6 +98,14 @@ def test_with_join(self):
             [self.author1]
         )
 
+    def test_with_exclude(self):
+        self.assertSequenceEqual(
+            Author.objects.annotate(
+                book_alice=FilteredRelation('book', condition=Q(book__title__iexact='poem by alice')),
+            ).exclude(book_alice__isnull=False),
+            [self.author2],
+        )
+
     def test_with_join_and_complex_condition(self):
         self.assertSequenceEqual(
             Author.objects.annotate(

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 filtered_relation.tests
git checkout 21aa2a5e785eef1f47beb1c3760fdd7d8915ae09 tests/filtered_relation/tests.py
