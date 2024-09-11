#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 3cedd79e6c121910220f8e6df77c54a0b344ea94
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test] --verbose
git checkout 3cedd79e6c121910220f8e6df77c54a0b344ea94 astropy/units/tests/test_units.py
git apply -v - <<'EOF_114329324912'
diff --git a/astropy/units/tests/test_units.py b/astropy/units/tests/test_units.py
--- a/astropy/units/tests/test_units.py
+++ b/astropy/units/tests/test_units.py
@@ -185,6 +185,13 @@ def test_unknown_unit3():
     assert unit != unit3
     assert not unit.is_equivalent(unit3)
 
+    # Also test basic (in)equalities.
+    assert unit == "FOO"
+    assert unit != u.m
+    # next two from gh-7603.
+    assert unit != None  # noqa
+    assert unit not in (None, u.m)
+
     with pytest.raises(ValueError):
         unit._get_converter(unit3)
 

EOF_114329324912
pytest -rA -vv -o console_output_style=classic --tb=no astropy/units/tests/test_units.py
git checkout 3cedd79e6c121910220f8e6df77c54a0b344ea94 astropy/units/tests/test_units.py
