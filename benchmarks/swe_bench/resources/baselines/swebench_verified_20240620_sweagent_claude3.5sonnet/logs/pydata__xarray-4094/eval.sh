#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff a64cf2d5476e7bbda099b34c40b7be1880dbd39a
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout a64cf2d5476e7bbda099b34c40b7be1880dbd39a xarray/tests/test_dataset.py
git apply -v - <<'EOF_114329324912'
diff --git a/xarray/tests/test_dataset.py b/xarray/tests/test_dataset.py
--- a/xarray/tests/test_dataset.py
+++ b/xarray/tests/test_dataset.py
@@ -3031,6 +3031,14 @@ def test_to_stacked_array_dtype_dims(self):
         assert y.dims == ("x", "features")
 
     def test_to_stacked_array_to_unstacked_dataset(self):
+
+        # single dimension: regression test for GH4049
+        arr = xr.DataArray(np.arange(3), coords=[("x", [0, 1, 2])])
+        data = xr.Dataset({"a": arr, "b": arr})
+        stacked = data.to_stacked_array("y", sample_dims=["x"])
+        unstacked = stacked.to_unstacked_dataset("y")
+        assert_identical(unstacked, data)
+
         # make a two dimensional dataset
         a, b = create_test_stacked_array()
         D = xr.Dataset({"a": a, "b": b})

EOF_114329324912
pytest -rA xarray/tests/test_dataset.py
git checkout a64cf2d5476e7bbda099b34c40b7be1880dbd39a xarray/tests/test_dataset.py
