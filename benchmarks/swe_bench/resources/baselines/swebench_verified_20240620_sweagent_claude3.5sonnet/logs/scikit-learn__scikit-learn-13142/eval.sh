#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 1c8668b0a021832386470ddf740d834e02c66f69
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -v --no-use-pep517 --no-build-isolation -e .
git checkout 1c8668b0a021832386470ddf740d834e02c66f69 sklearn/mixture/tests/test_bayesian_mixture.py sklearn/mixture/tests/test_gaussian_mixture.py
git apply -v - <<'EOF_114329324912'
diff --git a/sklearn/mixture/tests/test_bayesian_mixture.py b/sklearn/mixture/tests/test_bayesian_mixture.py
--- a/sklearn/mixture/tests/test_bayesian_mixture.py
+++ b/sklearn/mixture/tests/test_bayesian_mixture.py
@@ -451,6 +451,15 @@ def test_bayesian_mixture_fit_predict(seed, max_iter, tol):
         assert_array_equal(Y_pred1, Y_pred2)
 
 
+def test_bayesian_mixture_fit_predict_n_init():
+    # Check that fit_predict is equivalent to fit.predict, when n_init > 1
+    X = np.random.RandomState(0).randn(1000, 5)
+    gm = BayesianGaussianMixture(n_components=5, n_init=10, random_state=0)
+    y_pred1 = gm.fit_predict(X)
+    y_pred2 = gm.predict(X)
+    assert_array_equal(y_pred1, y_pred2)
+
+
 def test_bayesian_mixture_predict_predict_proba():
     # this is the same test as test_gaussian_mixture_predict_predict_proba()
     rng = np.random.RandomState(0)
diff --git a/sklearn/mixture/tests/test_gaussian_mixture.py b/sklearn/mixture/tests/test_gaussian_mixture.py
--- a/sklearn/mixture/tests/test_gaussian_mixture.py
+++ b/sklearn/mixture/tests/test_gaussian_mixture.py
@@ -598,6 +598,15 @@ def test_gaussian_mixture_fit_predict(seed, max_iter, tol):
         assert_greater(adjusted_rand_score(Y, Y_pred2), .95)
 
 
+def test_gaussian_mixture_fit_predict_n_init():
+    # Check that fit_predict is equivalent to fit.predict, when n_init > 1
+    X = np.random.RandomState(0).randn(1000, 5)
+    gm = GaussianMixture(n_components=5, n_init=5, random_state=0)
+    y_pred1 = gm.fit_predict(X)
+    y_pred2 = gm.predict(X)
+    assert_array_equal(y_pred1, y_pred2)
+
+
 def test_gaussian_mixture_fit():
     # recover the ground truth
     rng = np.random.RandomState(0)

EOF_114329324912
pytest -rA sklearn/mixture/tests/test_bayesian_mixture.py sklearn/mixture/tests/test_gaussian_mixture.py
git checkout 1c8668b0a021832386470ddf740d834e02c66f69 sklearn/mixture/tests/test_bayesian_mixture.py sklearn/mixture/tests/test_gaussian_mixture.py
