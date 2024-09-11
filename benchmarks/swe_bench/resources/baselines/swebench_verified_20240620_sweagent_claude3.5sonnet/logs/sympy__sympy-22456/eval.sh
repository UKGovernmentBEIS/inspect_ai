#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff a3475b3f9ac662cd425157dd3bdb93ad7111c090
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout a3475b3f9ac662cd425157dd3bdb93ad7111c090 sympy/codegen/tests/test_ast.py
git apply -v - <<'EOF_114329324912'
diff --git a/sympy/codegen/tests/test_ast.py b/sympy/codegen/tests/test_ast.py
--- a/sympy/codegen/tests/test_ast.py
+++ b/sympy/codegen/tests/test_ast.py
@@ -267,6 +267,7 @@ def test_String():
     assert st == String('foobar')
     assert st.text == 'foobar'
     assert st.func(**st.kwargs()) == st
+    assert st.func(*st.args) == st
 
 
     class Signifier(String):

EOF_114329324912
PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose sympy/codegen/tests/test_ast.py
git checkout a3475b3f9ac662cd425157dd3bdb93ad7111c090 sympy/codegen/tests/test_ast.py
