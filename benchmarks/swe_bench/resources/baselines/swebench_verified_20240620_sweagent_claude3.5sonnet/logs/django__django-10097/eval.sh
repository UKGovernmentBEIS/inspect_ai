#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONIOENCODING=utf8
export LANGUAGE=en_US:en
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff b9cf764be62e77b4777b3a75ec256f6209a57671
source /opt/miniconda3/bin/activate
conda activate testbed
python setup.py install
git checkout b9cf764be62e77b4777b3a75ec256f6209a57671 tests/validators/invalid_urls.txt tests/validators/valid_urls.txt
git apply -v - <<'EOF_114329324912'
diff --git a/tests/validators/invalid_urls.txt b/tests/validators/invalid_urls.txt
--- a/tests/validators/invalid_urls.txt
+++ b/tests/validators/invalid_urls.txt
@@ -57,3 +57,9 @@ http://example.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.
 http://example.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
 http://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.aaaaaaaaaaaaaaaaaaaaaaaaa
 https://test.[com
+http://foo@bar@example.com
+http://foo/bar@example.com
+http://foo:bar:baz@example.com
+http://foo:bar@baz@example.com
+http://foo:bar/baz@example.com
+http://invalid-.com/?m=foo@example.com
diff --git a/tests/validators/valid_urls.txt b/tests/validators/valid_urls.txt
--- a/tests/validators/valid_urls.txt
+++ b/tests/validators/valid_urls.txt
@@ -48,7 +48,7 @@ http://foo.bar/?q=Test%20URL-encoded%20stuff
 http://مثال.إختبار
 http://例子.测试
 http://उदाहरण.परीक्षा
-http://-.~_!$&'()*+,;=:%40:80%2f::::::@example.com
+http://-.~_!$&'()*+,;=%40:80%2f@example.com
 http://xn--7sbb4ac0ad0be6cf.xn--p1ai
 http://1337.net
 http://a.b-c.de

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1
git checkout b9cf764be62e77b4777b3a75ec256f6209a57671 tests/validators/invalid_urls.txt tests/validators/valid_urls.txt
