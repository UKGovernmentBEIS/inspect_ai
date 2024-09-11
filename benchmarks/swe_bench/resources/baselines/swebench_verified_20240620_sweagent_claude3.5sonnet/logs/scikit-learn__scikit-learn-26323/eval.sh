#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 586f4318ffcdfbd9a1093f35ad43e81983740b66
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -v --no-use-pep517 --no-build-isolation -e .
git checkout 586f4318ffcdfbd9a1093f35ad43e81983740b66 sklearn/compose/tests/test_column_transformer.py
git apply -v - <<'EOF_114329324912'
diff --git a/sklearn/compose/tests/test_column_transformer.py b/sklearn/compose/tests/test_column_transformer.py
--- a/sklearn/compose/tests/test_column_transformer.py
+++ b/sklearn/compose/tests/test_column_transformer.py
@@ -22,6 +22,7 @@
 from sklearn.exceptions import NotFittedError
 from sklearn.preprocessing import FunctionTransformer
 from sklearn.preprocessing import StandardScaler, Normalizer, OneHotEncoder
+from sklearn.feature_selection import VarianceThreshold
 
 
 class Trans(TransformerMixin, BaseEstimator):
@@ -2185,3 +2186,27 @@ def test_raise_error_if_index_not_aligned():
     )
     with pytest.raises(ValueError, match=msg):
         ct.fit_transform(X)
+
+
+def test_remainder_set_output():
+    """Check that the output is set for the remainder.
+
+    Non-regression test for #26306.
+    """
+
+    pd = pytest.importorskip("pandas")
+    df = pd.DataFrame({"a": [True, False, True], "b": [1, 2, 3]})
+
+    ct = make_column_transformer(
+        (VarianceThreshold(), make_column_selector(dtype_include=bool)),
+        remainder=VarianceThreshold(),
+        verbose_feature_names_out=False,
+    )
+    ct.set_output(transform="pandas")
+
+    out = ct.fit_transform(df)
+    pd.testing.assert_frame_equal(out, df)
+
+    ct.set_output(transform="default")
+    out = ct.fit_transform(df)
+    assert isinstance(out, np.ndarray)

EOF_114329324912
pytest -rA sklearn/compose/tests/test_column_transformer.py
git checkout 586f4318ffcdfbd9a1093f35ad43e81983740b66 sklearn/compose/tests/test_column_transformer.py
