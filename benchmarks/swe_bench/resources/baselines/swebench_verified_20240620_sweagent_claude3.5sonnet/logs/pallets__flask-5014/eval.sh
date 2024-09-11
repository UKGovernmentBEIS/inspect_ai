#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 7ee9ceb71e868944a46e1ff00b506772a53a4f1d
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 7ee9ceb71e868944a46e1ff00b506772a53a4f1d tests/test_blueprints.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_blueprints.py b/tests/test_blueprints.py
--- a/tests/test_blueprints.py
+++ b/tests/test_blueprints.py
@@ -256,6 +256,11 @@ def test_dotted_name_not_allowed(app, client):
         flask.Blueprint("app.ui", __name__)
 
 
+def test_empty_name_not_allowed(app, client):
+    with pytest.raises(ValueError):
+        flask.Blueprint("", __name__)
+
+
 def test_dotted_names_from_app(app, client):
     test = flask.Blueprint("test", __name__)
 

EOF_114329324912
pytest -rA tests/test_blueprints.py
git checkout 7ee9ceb71e868944a46e1ff00b506772a53a4f1d tests/test_blueprints.py
