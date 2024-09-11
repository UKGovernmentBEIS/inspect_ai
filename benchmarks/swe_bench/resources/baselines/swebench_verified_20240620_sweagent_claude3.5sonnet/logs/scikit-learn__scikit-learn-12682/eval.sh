#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff d360ffa7c5896a91ae498b3fb9cf464464ce8f34
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -v --no-use-pep517 --no-build-isolation -e .
git checkout d360ffa7c5896a91ae498b3fb9cf464464ce8f34 sklearn/decomposition/tests/test_dict_learning.py
git apply -v - <<'EOF_114329324912'
diff --git a/sklearn/decomposition/tests/test_dict_learning.py b/sklearn/decomposition/tests/test_dict_learning.py
--- a/sklearn/decomposition/tests/test_dict_learning.py
+++ b/sklearn/decomposition/tests/test_dict_learning.py
@@ -57,6 +57,54 @@ def test_dict_learning_overcomplete():
     assert dico.components_.shape == (n_components, n_features)
 
 
+def test_max_iter():
+    def ricker_function(resolution, center, width):
+        """Discrete sub-sampled Ricker (Mexican hat) wavelet"""
+        x = np.linspace(0, resolution - 1, resolution)
+        x = ((2 / (np.sqrt(3 * width) * np.pi ** .25))
+             * (1 - (x - center) ** 2 / width ** 2)
+             * np.exp(-(x - center) ** 2 / (2 * width ** 2)))
+        return x
+
+    def ricker_matrix(width, resolution, n_components):
+        """Dictionary of Ricker (Mexican hat) wavelets"""
+        centers = np.linspace(0, resolution - 1, n_components)
+        D = np.empty((n_components, resolution))
+        for i, center in enumerate(centers):
+            D[i] = ricker_function(resolution, center, width)
+        D /= np.sqrt(np.sum(D ** 2, axis=1))[:, np.newaxis]
+        return D
+
+    transform_algorithm = 'lasso_cd'
+    resolution = 1024
+    subsampling = 3  # subsampling factor
+    n_components = resolution // subsampling
+
+    # Compute a wavelet dictionary
+    D_multi = np.r_[tuple(ricker_matrix(width=w, resolution=resolution,
+                          n_components=n_components // 5)
+                          for w in (10, 50, 100, 500, 1000))]
+
+    X = np.linspace(0, resolution - 1, resolution)
+    first_quarter = X < resolution / 4
+    X[first_quarter] = 3.
+    X[np.logical_not(first_quarter)] = -1.
+    X = X.reshape(1, -1)
+
+    # check that the underlying model fails to converge
+    with pytest.warns(ConvergenceWarning):
+        model = SparseCoder(D_multi, transform_algorithm=transform_algorithm,
+                            transform_max_iter=1)
+        model.fit_transform(X)
+
+    # check that the underlying model converges w/o warnings
+    with pytest.warns(None) as record:
+        model = SparseCoder(D_multi, transform_algorithm=transform_algorithm,
+                            transform_max_iter=2000)
+        model.fit_transform(X)
+    assert not record.list
+
+
 def test_dict_learning_lars_positive_parameter():
     n_components = 5
     alpha = 1

EOF_114329324912
pytest -rA sklearn/decomposition/tests/test_dict_learning.py
git checkout d360ffa7c5896a91ae498b3fb9cf464464ce8f34 sklearn/decomposition/tests/test_dict_learning.py
