#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff f7eea978097085a6781a0e92fc14ba7712a52d75
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -v --no-use-pep517 --no-build-isolation -e .
git checkout f7eea978097085a6781a0e92fc14ba7712a52d75 sklearn/impute/tests/test_impute.py
git apply -v - <<'EOF_114329324912'
diff --git a/sklearn/impute/tests/test_impute.py b/sklearn/impute/tests/test_impute.py
--- a/sklearn/impute/tests/test_impute.py
+++ b/sklearn/impute/tests/test_impute.py
@@ -1524,6 +1524,21 @@ def test_iterative_imputer_keep_empty_features(initial_strategy):
     assert_allclose(X_imputed[:, 1], 0)
 
 
+def test_iterative_imputer_constant_fill_value():
+    """Check that we propagate properly the parameter `fill_value`."""
+    X = np.array([[-1, 2, 3, -1], [4, -1, 5, -1], [6, 7, -1, -1], [8, 9, 0, -1]])
+
+    fill_value = 100
+    imputer = IterativeImputer(
+        missing_values=-1,
+        initial_strategy="constant",
+        fill_value=fill_value,
+        max_iter=0,
+    )
+    imputer.fit_transform(X)
+    assert_array_equal(imputer.initial_imputer_.statistics_, fill_value)
+
+
 @pytest.mark.parametrize("keep_empty_features", [True, False])
 def test_knn_imputer_keep_empty_features(keep_empty_features):
     """Check the behaviour of `keep_empty_features` for `KNNImputer`."""

EOF_114329324912
pytest -rA sklearn/impute/tests/test_impute.py
git checkout f7eea978097085a6781a0e92fc14ba7712a52d75 sklearn/impute/tests/test_impute.py
