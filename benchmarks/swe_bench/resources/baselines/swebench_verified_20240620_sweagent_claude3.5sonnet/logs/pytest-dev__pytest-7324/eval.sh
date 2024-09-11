#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 19ad5889353c7f5f2b65cc2acd346b7a9e95dfcd
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 19ad5889353c7f5f2b65cc2acd346b7a9e95dfcd testing/test_mark_expression.py
git apply -v - <<'EOF_114329324912'
diff --git a/testing/test_mark_expression.py b/testing/test_mark_expression.py
--- a/testing/test_mark_expression.py
+++ b/testing/test_mark_expression.py
@@ -130,6 +130,7 @@ def test_syntax_errors(expr: str, column: int, message: str) -> None:
         "123.232",
         "True",
         "False",
+        "None",
         "if",
         "else",
         "while",

EOF_114329324912
pytest -rA testing/test_mark_expression.py
git checkout 19ad5889353c7f5f2b65cc2acd346b7a9e95dfcd testing/test_mark_expression.py
