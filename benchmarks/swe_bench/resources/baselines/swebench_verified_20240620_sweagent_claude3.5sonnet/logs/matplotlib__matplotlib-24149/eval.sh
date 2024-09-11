#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff af39f1edffcd828f05cfdd04f2e59506bb4a27bc
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout af39f1edffcd828f05cfdd04f2e59506bb4a27bc lib/matplotlib/tests/test_axes.py
git apply -v - <<'EOF_114329324912'
diff --git a/lib/matplotlib/tests/test_axes.py b/lib/matplotlib/tests/test_axes.py
--- a/lib/matplotlib/tests/test_axes.py
+++ b/lib/matplotlib/tests/test_axes.py
@@ -8195,3 +8195,16 @@ def test_bar_leading_nan():
         for b in rest:
             assert np.isfinite(b.xy).all()
             assert np.isfinite(b.get_width())
+
+
+@check_figures_equal(extensions=["png"])
+def test_bar_all_nan(fig_test, fig_ref):
+    mpl.style.use("mpl20")
+    ax_test = fig_test.subplots()
+    ax_ref = fig_ref.subplots()
+
+    ax_test.bar([np.nan], [np.nan])
+    ax_test.bar([1], [1])
+
+    ax_ref.bar([1], [1]).remove()
+    ax_ref.bar([1], [1])

EOF_114329324912
pytest -rA lib/matplotlib/tests/test_axes.py
git checkout af39f1edffcd828f05cfdd04f2e59506bb4a27bc lib/matplotlib/tests/test_axes.py
