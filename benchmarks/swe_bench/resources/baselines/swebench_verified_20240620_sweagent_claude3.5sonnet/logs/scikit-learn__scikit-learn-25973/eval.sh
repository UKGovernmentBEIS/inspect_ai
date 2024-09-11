#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 10dbc142bd17ccf7bd38eec2ac04b52ce0d1009e
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -v --no-use-pep517 --no-build-isolation -e .
git checkout 10dbc142bd17ccf7bd38eec2ac04b52ce0d1009e sklearn/feature_selection/tests/test_sequential.py
git apply -v - <<'EOF_114329324912'
diff --git a/sklearn/feature_selection/tests/test_sequential.py b/sklearn/feature_selection/tests/test_sequential.py
--- a/sklearn/feature_selection/tests/test_sequential.py
+++ b/sklearn/feature_selection/tests/test_sequential.py
@@ -6,11 +6,12 @@
 from sklearn.preprocessing import StandardScaler
 from sklearn.pipeline import make_pipeline
 from sklearn.feature_selection import SequentialFeatureSelector
-from sklearn.datasets import make_regression, make_blobs
+from sklearn.datasets import make_regression, make_blobs, make_classification
 from sklearn.linear_model import LinearRegression
 from sklearn.ensemble import HistGradientBoostingRegressor
-from sklearn.model_selection import cross_val_score
+from sklearn.model_selection import cross_val_score, LeaveOneGroupOut
 from sklearn.cluster import KMeans
+from sklearn.neighbors import KNeighborsClassifier
 
 
 def test_bad_n_features_to_select():
@@ -314,3 +315,22 @@ def test_backward_neg_tol():
 
     assert 0 < sfs.get_support().sum() < X.shape[1]
     assert new_score < initial_score
+
+
+def test_cv_generator_support():
+    """Check that no exception raised when cv is generator
+
+    non-regression test for #25957
+    """
+    X, y = make_classification(random_state=0)
+
+    groups = np.zeros_like(y, dtype=int)
+    groups[y.size // 2 :] = 1
+
+    cv = LeaveOneGroupOut()
+    splits = cv.split(X, y, groups=groups)
+
+    knc = KNeighborsClassifier(n_neighbors=5)
+
+    sfs = SequentialFeatureSelector(knc, n_features_to_select=5, cv=splits)
+    sfs.fit(X, y)

EOF_114329324912
pytest -rA sklearn/feature_selection/tests/test_sequential.py
git checkout 10dbc142bd17ccf7bd38eec2ac04b52ce0d1009e sklearn/feature_selection/tests/test_sequential.py
