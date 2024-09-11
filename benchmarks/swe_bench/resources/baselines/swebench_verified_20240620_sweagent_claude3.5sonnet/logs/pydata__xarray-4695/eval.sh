#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 51ef2a66c4e0896eab7d2b03e3dfb3963e338e3c
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 51ef2a66c4e0896eab7d2b03e3dfb3963e338e3c xarray/tests/test_dataarray.py
git apply -v - <<'EOF_114329324912'
diff --git a/xarray/tests/test_dataarray.py b/xarray/tests/test_dataarray.py
--- a/xarray/tests/test_dataarray.py
+++ b/xarray/tests/test_dataarray.py
@@ -1170,6 +1170,16 @@ def test_loc_single_boolean(self):
         assert data.loc[True] == 0
         assert data.loc[False] == 1
 
+    def test_loc_dim_name_collision_with_sel_params(self):
+        da = xr.DataArray(
+            [[0, 0], [1, 1]],
+            dims=["dim1", "method"],
+            coords={"dim1": ["x", "y"], "method": ["a", "b"]},
+        )
+        np.testing.assert_array_equal(
+            da.loc[dict(dim1=["x", "y"], method=["a"])], [[0], [1]]
+        )
+
     def test_selection_multiindex(self):
         mindex = pd.MultiIndex.from_product(
             [["a", "b"], [1, 2], [-1, -2]], names=("one", "two", "three")

EOF_114329324912
pytest -rA xarray/tests/test_dataarray.py
git checkout 51ef2a66c4e0896eab7d2b03e3dfb3963e338e3c xarray/tests/test_dataarray.py
