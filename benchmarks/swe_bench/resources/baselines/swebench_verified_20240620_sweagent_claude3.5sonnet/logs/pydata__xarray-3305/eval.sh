#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 69c7e01e5167a3137c285cb50d1978252bb8bcbf
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 69c7e01e5167a3137c285cb50d1978252bb8bcbf xarray/tests/test_dataarray.py
git apply -v - <<'EOF_114329324912'
diff --git a/xarray/tests/test_dataarray.py b/xarray/tests/test_dataarray.py
--- a/xarray/tests/test_dataarray.py
+++ b/xarray/tests/test_dataarray.py
@@ -2298,17 +2298,17 @@ def test_reduce_out(self):
         with pytest.raises(TypeError):
             orig.mean(out=np.ones(orig.shape))
 
-    # skip due to bug in older versions of numpy.nanpercentile
     def test_quantile(self):
         for q in [0.25, [0.50], [0.25, 0.75]]:
             for axis, dim in zip(
                 [None, 0, [0], [0, 1]], [None, "x", ["x"], ["x", "y"]]
             ):
-                actual = self.dv.quantile(q, dim=dim)
+                actual = DataArray(self.va).quantile(q, dim=dim, keep_attrs=True)
                 expected = np.nanpercentile(
                     self.dv.values, np.array(q) * 100, axis=axis
                 )
                 np.testing.assert_allclose(actual.values, expected)
+                assert actual.attrs == self.attrs
 
     def test_reduce_keep_attrs(self):
         # Test dropped attrs

EOF_114329324912
pytest -rA xarray/tests/test_dataarray.py
git checkout 69c7e01e5167a3137c285cb50d1978252bb8bcbf xarray/tests/test_dataarray.py
