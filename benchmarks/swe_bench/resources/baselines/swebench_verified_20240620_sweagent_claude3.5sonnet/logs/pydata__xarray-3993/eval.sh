#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 8cc34cb412ba89ebca12fc84f76a9e452628f1bc
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 8cc34cb412ba89ebca12fc84f76a9e452628f1bc xarray/tests/test_dataset.py xarray/tests/test_units.py
git apply -v - <<'EOF_114329324912'
diff --git a/xarray/tests/test_dataset.py b/xarray/tests/test_dataset.py
--- a/xarray/tests/test_dataset.py
+++ b/xarray/tests/test_dataset.py
@@ -6603,6 +6603,9 @@ def test_integrate(dask):
     with pytest.raises(ValueError):
         da.integrate("x2d")
 
+    with pytest.warns(FutureWarning):
+        da.integrate(dim="x")
+
 
 @pytest.mark.parametrize("dask", [True, False])
 @pytest.mark.parametrize("which_datetime", ["np", "cftime"])
diff --git a/xarray/tests/test_units.py b/xarray/tests/test_units.py
--- a/xarray/tests/test_units.py
+++ b/xarray/tests/test_units.py
@@ -3681,7 +3681,7 @@ def test_stacking_reordering(self, func, dtype):
         (
             method("diff", dim="x"),
             method("differentiate", coord="x"),
-            method("integrate", dim="x"),
+            method("integrate", coord="x"),
             method("quantile", q=[0.25, 0.75]),
             method("reduce", func=np.sum, dim="x"),
             pytest.param(lambda x: x.dot(x), id="method_dot"),

EOF_114329324912
pytest -rA xarray/tests/test_dataset.py xarray/tests/test_units.py
git checkout 8cc34cb412ba89ebca12fc84f76a9e452628f1bc xarray/tests/test_dataset.py xarray/tests/test_units.py
