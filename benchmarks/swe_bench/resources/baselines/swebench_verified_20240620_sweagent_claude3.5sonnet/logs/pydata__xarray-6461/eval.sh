#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 851dadeb0338403e5021c3fbe80cbc9127ee672d
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 851dadeb0338403e5021c3fbe80cbc9127ee672d xarray/tests/test_computation.py
git apply -v - <<'EOF_114329324912'
diff --git a/xarray/tests/test_computation.py b/xarray/tests/test_computation.py
--- a/xarray/tests/test_computation.py
+++ b/xarray/tests/test_computation.py
@@ -1928,6 +1928,10 @@ def test_where_attrs() -> None:
     expected = xr.DataArray([1, 0], dims="x", attrs={"attr": "x"})
     assert_identical(expected, actual)
 
+    # ensure keep_attrs can handle scalar values
+    actual = xr.where(cond, 1, 0, keep_attrs=True)
+    assert actual.attrs == {}
+
 
 @pytest.mark.parametrize("use_dask", [True, False])
 @pytest.mark.parametrize("use_datetime", [True, False])

EOF_114329324912
pytest -rA xarray/tests/test_computation.py
git checkout 851dadeb0338403e5021c3fbe80cbc9127ee672d xarray/tests/test_computation.py
