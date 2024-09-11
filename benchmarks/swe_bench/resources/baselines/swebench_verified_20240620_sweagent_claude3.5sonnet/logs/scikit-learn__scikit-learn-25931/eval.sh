#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff e3d1f9ac39e4bf0f31430e779acc50fb05fe1b64
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -v --no-use-pep517 --no-build-isolation -e .
git checkout e3d1f9ac39e4bf0f31430e779acc50fb05fe1b64 sklearn/ensemble/tests/test_iforest.py
git apply -v - <<'EOF_114329324912'
diff --git a/sklearn/ensemble/tests/test_iforest.py b/sklearn/ensemble/tests/test_iforest.py
--- a/sklearn/ensemble/tests/test_iforest.py
+++ b/sklearn/ensemble/tests/test_iforest.py
@@ -339,3 +339,21 @@ def test_base_estimator_property_deprecated():
     )
     with pytest.warns(FutureWarning, match=warn_msg):
         model.base_estimator_
+
+
+def test_iforest_preserve_feature_names():
+    """Check that feature names are preserved when contamination is not "auto".
+
+    Feature names are required for consistency checks during scoring.
+
+    Non-regression test for Issue #25844
+    """
+    pd = pytest.importorskip("pandas")
+    rng = np.random.RandomState(0)
+
+    X = pd.DataFrame(data=rng.randn(4), columns=["a"])
+    model = IsolationForest(random_state=0, contamination=0.05)
+
+    with warnings.catch_warnings():
+        warnings.simplefilter("error", UserWarning)
+        model.fit(X)

EOF_114329324912
pytest -rA sklearn/ensemble/tests/test_iforest.py
git checkout e3d1f9ac39e4bf0f31430e779acc50fb05fe1b64 sklearn/ensemble/tests/test_iforest.py
