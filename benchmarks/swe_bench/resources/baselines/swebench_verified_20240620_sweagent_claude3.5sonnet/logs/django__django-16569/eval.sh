#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 278881e37619278789942513916acafaa88d26f3
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 278881e37619278789942513916acafaa88d26f3 tests/forms_tests/tests/test_formsets.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/forms_tests/tests/test_formsets.py b/tests/forms_tests/tests/test_formsets.py
--- a/tests/forms_tests/tests/test_formsets.py
+++ b/tests/forms_tests/tests/test_formsets.py
@@ -1480,6 +1480,7 @@ def test_disable_delete_extra_formset_forms(self):
         self.assertIn("DELETE", formset.forms[0].fields)
         self.assertNotIn("DELETE", formset.forms[1].fields)
         self.assertNotIn("DELETE", formset.forms[2].fields)
+        self.assertNotIn("DELETE", formset.empty_form.fields)
 
         formset = ChoiceFormFormset(
             data={

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 forms_tests.tests.test_formsets
git checkout 278881e37619278789942513916acafaa88d26f3 tests/forms_tests/tests/test_formsets.py
