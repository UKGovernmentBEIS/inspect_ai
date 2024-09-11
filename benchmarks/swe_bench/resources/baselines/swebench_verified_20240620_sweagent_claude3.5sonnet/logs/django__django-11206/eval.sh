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
git diff 571ab44e8a8936014c22e7eebe4948d9611fd7ce
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 571ab44e8a8936014c22e7eebe4948d9611fd7ce tests/utils_tests/test_numberformat.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/utils_tests/test_numberformat.py b/tests/utils_tests/test_numberformat.py
--- a/tests/utils_tests/test_numberformat.py
+++ b/tests/utils_tests/test_numberformat.py
@@ -94,7 +94,7 @@ def test_decimal_numbers(self):
             ('1e-10', 8, '0.00000000'),
             ('1e-11', 8, '0.00000000'),
             ('1' + ('0' * 300), 3, '1.000e+300'),
-            ('0.{}1234'.format('0' * 299), 3, '1.234e-300'),
+            ('0.{}1234'.format('0' * 299), 3, '0.000'),
         ]
         for value, decimal_pos, expected_value in tests:
             with self.subTest(value=value):

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 utils_tests.test_numberformat
git checkout 571ab44e8a8936014c22e7eebe4948d9611fd7ce tests/utils_tests/test_numberformat.py
