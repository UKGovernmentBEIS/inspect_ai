#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff c50643a49811e9fe2f4851adff4313ad46f7325e
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout c50643a49811e9fe2f4851adff4313ad46f7325e sympy/crypto/tests/test_crypto.py
git apply -v - <<'EOF_114329324912'
diff --git a/sympy/crypto/tests/test_crypto.py b/sympy/crypto/tests/test_crypto.py
--- a/sympy/crypto/tests/test_crypto.py
+++ b/sympy/crypto/tests/test_crypto.py
@@ -247,6 +247,8 @@ def test_encode_morse():
     assert encode_morse(' ', sep='`') == '``'
     assert encode_morse(' ', sep='``') == '````'
     assert encode_morse('!@#$%^&*()_+') == '-.-.--|.--.-.|...-..-|-.--.|-.--.-|..--.-|.-.-.'
+    assert encode_morse('12345') == '.----|..---|...--|....-|.....'
+    assert encode_morse('67890') == '-....|--...|---..|----.|-----'
 
 
 def test_decode_morse():

EOF_114329324912
PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose sympy/crypto/tests/test_crypto.py
git checkout c50643a49811e9fe2f4851adff4313ad46f7325e sympy/crypto/tests/test_crypto.py
