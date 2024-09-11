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
git diff e6588aa4e793b7f56f4cadbfa155b581e0efc59a
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout e6588aa4e793b7f56f4cadbfa155b581e0efc59a tests/model_forms/tests.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/model_forms/tests.py b/tests/model_forms/tests.py
--- a/tests/model_forms/tests.py
+++ b/tests/model_forms/tests.py
@@ -1814,6 +1814,10 @@ class Meta:
 
         bw = BetterWriter.objects.create(name='Joe Better', score=10)
         self.assertEqual(sorted(model_to_dict(bw)), ['id', 'name', 'score', 'writer_ptr'])
+        self.assertEqual(sorted(model_to_dict(bw, fields=[])), [])
+        self.assertEqual(sorted(model_to_dict(bw, fields=['id', 'name'])), ['id', 'name'])
+        self.assertEqual(sorted(model_to_dict(bw, exclude=[])), ['id', 'name', 'score', 'writer_ptr'])
+        self.assertEqual(sorted(model_to_dict(bw, exclude=['id', 'name'])), ['score', 'writer_ptr'])
 
         form = BetterWriterForm({'name': 'Some Name', 'score': 12})
         self.assertTrue(form.is_valid())

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 model_forms.tests
git checkout e6588aa4e793b7f56f4cadbfa155b581e0efc59a tests/model_forms/tests.py
