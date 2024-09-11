#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen
export LANG=en_US.UTF-8
export LANGUAGE=en_US:en
export LC_ALL=en_US.UTF-8
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git diff 28d5262fa3315690395f04e3619ed554dbaf725b
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .
git checkout 28d5262fa3315690395f04e3619ed554dbaf725b tests/admin_docs/test_views.py tests/auth_tests/test_forms.py tests/forms_tests/tests/test_forms.py tests/forms_tests/widget_tests/base.py tests/forms_tests/widget_tests/test_clearablefileinput.py tests/model_forms/tests.py tests/template_tests/filter_tests/test_addslashes.py tests/template_tests/filter_tests/test_make_list.py tests/template_tests/filter_tests/test_title.py tests/template_tests/filter_tests/test_urlize.py tests/template_tests/syntax_tests/test_url.py tests/utils_tests/test_html.py tests/view_tests/tests/test_csrf.py tests/view_tests/tests/test_debug.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/admin_docs/test_views.py b/tests/admin_docs/test_views.py
--- a/tests/admin_docs/test_views.py
+++ b/tests/admin_docs/test_views.py
@@ -199,7 +199,7 @@ def test_methods_with_arguments_display_arguments_default_value(self):
         """
         Methods with keyword arguments should have their arguments displayed.
         """
-        self.assertContains(self.response, "<td>suffix=&#39;ltd&#39;</td>")
+        self.assertContains(self.response, '<td>suffix=&#x27;ltd&#x27;</td>')
 
     def test_methods_with_multiple_arguments_display_arguments(self):
         """
diff --git a/tests/auth_tests/test_forms.py b/tests/auth_tests/test_forms.py
--- a/tests/auth_tests/test_forms.py
+++ b/tests/auth_tests/test_forms.py
@@ -236,7 +236,7 @@ def test_password_help_text(self):
         form = UserCreationForm()
         self.assertEqual(
             form.fields['password1'].help_text,
-            '<ul><li>Your password can&#39;t be too similar to your other personal information.</li></ul>'
+            '<ul><li>Your password can&#x27;t be too similar to your other personal information.</li></ul>'
         )
 
     @override_settings(AUTH_PASSWORD_VALIDATORS=[
diff --git a/tests/forms_tests/tests/test_forms.py b/tests/forms_tests/tests/test_forms.py
--- a/tests/forms_tests/tests/test_forms.py
+++ b/tests/forms_tests/tests/test_forms.py
@@ -995,7 +995,7 @@ def clean_special_safe_name(self):
         self.assertHTMLEqual(
             f.as_table(),
             """<tr><th>&lt;em&gt;Special&lt;/em&gt; Field:</th><td>
-<ul class="errorlist"><li>Something&#39;s wrong with &#39;Nothing to escape&#39;</li></ul>
+<ul class="errorlist"><li>Something&#x27;s wrong with &#x27;Nothing to escape&#x27;</li></ul>
 <input type="text" name="special_name" value="Nothing to escape" required></td></tr>
 <tr><th><em>Special</em> Field:</th><td>
 <ul class="errorlist"><li>'<b>Nothing to escape</b>' is a safe string</li></ul>
@@ -1008,10 +1008,10 @@ def clean_special_safe_name(self):
         self.assertHTMLEqual(
             f.as_table(),
             """<tr><th>&lt;em&gt;Special&lt;/em&gt; Field:</th><td>
-<ul class="errorlist"><li>Something&#39;s wrong with &#39;Should escape &lt; &amp; &gt; and
-&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;&#39;</li></ul>
+<ul class="errorlist"><li>Something&#x27;s wrong with &#x27;Should escape &lt; &amp; &gt; and
+&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;&#x27;</li></ul>
 <input type="text" name="special_name"
-value="Should escape &lt; &amp; &gt; and &lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" required></td></tr>
+value="Should escape &lt; &amp; &gt; and &lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" required></td></tr>
 <tr><th><em>Special</em> Field:</th><td>
 <ul class="errorlist"><li>'<b><i>Do not escape</i></b>' is a safe string</li></ul>
 <input type="text" name="special_safe_name" value="&lt;i&gt;Do not escape&lt;/i&gt;" required></td></tr>"""
@@ -2632,7 +2632,7 @@ def clean(self):
             t.render(Context({'form': UserRegistration(auto_id=False)})),
             """<form>
 <p>Username: <input type="text" name="username" maxlength="10" required><br>
-Good luck picking a username that doesn&#39;t already exist.</p>
+Good luck picking a username that doesn&#x27;t already exist.</p>
 <p>Password1: <input type="password" name="password1" required></p>
 <p>Password2: <input type="password" name="password2" required></p>
 <input type="submit" required>
diff --git a/tests/forms_tests/widget_tests/base.py b/tests/forms_tests/widget_tests/base.py
--- a/tests/forms_tests/widget_tests/base.py
+++ b/tests/forms_tests/widget_tests/base.py
@@ -22,7 +22,10 @@ def check_html(self, widget, name, value, html='', attrs=None, strict=False, **k
         if self.jinja2_renderer:
             output = widget.render(name, value, attrs=attrs, renderer=self.jinja2_renderer, **kwargs)
             # Django escapes quotes with '&quot;' while Jinja2 uses '&#34;'.
-            assertEqual(output.replace('&#34;', '&quot;'), html)
+            output = output.replace('&#34;', '&quot;')
+            # Django escapes single quotes with '&#x27;' while Jinja2 uses '&#39;'.
+            output = output.replace('&#39;', '&#x27;')
+            assertEqual(output, html)
 
         output = widget.render(name, value, attrs=attrs, renderer=self.django_renderer, **kwargs)
         assertEqual(output, html)
diff --git a/tests/forms_tests/widget_tests/test_clearablefileinput.py b/tests/forms_tests/widget_tests/test_clearablefileinput.py
--- a/tests/forms_tests/widget_tests/test_clearablefileinput.py
+++ b/tests/forms_tests/widget_tests/test_clearablefileinput.py
@@ -46,7 +46,7 @@ def __str__(self):
         self.check_html(ClearableFileInput(), 'my<div>file', StrangeFieldFile(), html=(
             """
             Currently: <a href="something?chapter=1&amp;sect=2&amp;copy=3&amp;lang=en">
-            something&lt;div onclick=&quot;alert(&#39;oops&#39;)&quot;&gt;.jpg</a>
+            something&lt;div onclick=&quot;alert(&#x27;oops&#x27;)&quot;&gt;.jpg</a>
             <input type="checkbox" name="my&lt;div&gt;file-clear" id="my&lt;div&gt;file-clear_id">
             <label for="my&lt;div&gt;file-clear_id">Clear</label><br>
             Change: <input type="file" name="my&lt;div&gt;file">
diff --git a/tests/model_forms/tests.py b/tests/model_forms/tests.py
--- a/tests/model_forms/tests.py
+++ b/tests/model_forms/tests.py
@@ -1197,7 +1197,7 @@ def test_initial_values(self):
 <li>Article: <textarea rows="10" cols="40" name="article" required></textarea></li>
 <li>Categories: <select multiple name="categories">
 <option value="%s" selected>Entertainment</option>
-<option value="%s" selected>It&#39;s a test</option>
+<option value="%s" selected>It&#x27;s a test</option>
 <option value="%s">Third test</option>
 </select></li>
 <li>Status: <select name="status">
@@ -1239,7 +1239,7 @@ def test_initial_values(self):
 <li>Article: <textarea rows="10" cols="40" name="article" required>Hello.</textarea></li>
 <li>Categories: <select multiple name="categories">
 <option value="%s">Entertainment</option>
-<option value="%s">It&#39;s a test</option>
+<option value="%s">It&#x27;s a test</option>
 <option value="%s">Third test</option>
 </select></li>
 <li>Status: <select name="status">
@@ -1290,7 +1290,7 @@ def formfield_for_dbfield(db_field, **kwargs):
 <li><label for="id_categories">Categories:</label>
 <select multiple name="categories" id="id_categories">
 <option value="%d" selected>Entertainment</option>
-<option value="%d" selected>It&39;s a test</option>
+<option value="%d" selected>It&#x27;s a test</option>
 <option value="%d">Third test</option>
 </select></li>"""
             % (self.c1.pk, self.c2.pk, self.c3.pk))
@@ -1361,7 +1361,7 @@ def test_multi_fields(self):
 <tr><th>Article:</th><td><textarea rows="10" cols="40" name="article" required></textarea></td></tr>
 <tr><th>Categories:</th><td><select multiple name="categories">
 <option value="%s">Entertainment</option>
-<option value="%s">It&#39;s a test</option>
+<option value="%s">It&#x27;s a test</option>
 <option value="%s">Third test</option>
 </select></td></tr>
 <tr><th>Status:</th><td><select name="status">
@@ -1391,7 +1391,7 @@ def test_multi_fields(self):
 <li>Article: <textarea rows="10" cols="40" name="article" required>Hello.</textarea></li>
 <li>Categories: <select multiple name="categories">
 <option value="%s" selected>Entertainment</option>
-<option value="%s">It&#39;s a test</option>
+<option value="%s">It&#x27;s a test</option>
 <option value="%s">Third test</option>
 </select></li>
 <li>Status: <select name="status">
@@ -1535,7 +1535,7 @@ def test_runtime_choicefield_populated(self):
 <li>Article: <textarea rows="10" cols="40" name="article" required></textarea></li>
 <li>Categories: <select multiple name="categories">
 <option value="%s">Entertainment</option>
-<option value="%s">It&#39;s a test</option>
+<option value="%s">It&#x27;s a test</option>
 <option value="%s">Third test</option>
 </select> </li>
 <li>Status: <select name="status">
@@ -1561,7 +1561,7 @@ def test_runtime_choicefield_populated(self):
 <li>Article: <textarea rows="10" cols="40" name="article" required></textarea></li>
 <li>Categories: <select multiple name="categories">
 <option value="%s">Entertainment</option>
-<option value="%s">It&#39;s a test</option>
+<option value="%s">It&#x27;s a test</option>
 <option value="%s">Third test</option>
 <option value="%s">Fourth</option>
 </select></li>
diff --git a/tests/template_tests/filter_tests/test_addslashes.py b/tests/template_tests/filter_tests/test_addslashes.py
--- a/tests/template_tests/filter_tests/test_addslashes.py
+++ b/tests/template_tests/filter_tests/test_addslashes.py
@@ -15,7 +15,7 @@ def test_addslashes01(self):
     @setup({'addslashes02': '{{ a|addslashes }} {{ b|addslashes }}'})
     def test_addslashes02(self):
         output = self.engine.render_to_string('addslashes02', {"a": "<a>'", "b": mark_safe("<a>'")})
-        self.assertEqual(output, r"&lt;a&gt;\&#39; <a>\'")
+        self.assertEqual(output, r"&lt;a&gt;\&#x27; <a>\'")
 
 
 class FunctionTests(SimpleTestCase):
diff --git a/tests/template_tests/filter_tests/test_make_list.py b/tests/template_tests/filter_tests/test_make_list.py
--- a/tests/template_tests/filter_tests/test_make_list.py
+++ b/tests/template_tests/filter_tests/test_make_list.py
@@ -19,7 +19,7 @@ def test_make_list01(self):
     @setup({'make_list02': '{{ a|make_list }}'})
     def test_make_list02(self):
         output = self.engine.render_to_string('make_list02', {"a": mark_safe("&")})
-        self.assertEqual(output, "[&#39;&amp;&#39;]")
+        self.assertEqual(output, '[&#x27;&amp;&#x27;]')
 
     @setup({'make_list03': '{% autoescape off %}{{ a|make_list|stringformat:"s"|safe }}{% endautoescape %}'})
     def test_make_list03(self):
diff --git a/tests/template_tests/filter_tests/test_title.py b/tests/template_tests/filter_tests/test_title.py
--- a/tests/template_tests/filter_tests/test_title.py
+++ b/tests/template_tests/filter_tests/test_title.py
@@ -9,7 +9,7 @@ class TitleTests(SimpleTestCase):
     @setup({'title1': '{{ a|title }}'})
     def test_title1(self):
         output = self.engine.render_to_string('title1', {'a': 'JOE\'S CRAB SHACK'})
-        self.assertEqual(output, 'Joe&#39;s Crab Shack')
+        self.assertEqual(output, 'Joe&#x27;s Crab Shack')
 
     @setup({'title2': '{{ a|title }}'})
     def test_title2(self):
diff --git a/tests/template_tests/filter_tests/test_urlize.py b/tests/template_tests/filter_tests/test_urlize.py
--- a/tests/template_tests/filter_tests/test_urlize.py
+++ b/tests/template_tests/filter_tests/test_urlize.py
@@ -52,7 +52,7 @@ def test_urlize05(self):
     @setup({'urlize06': '{{ a|urlize }}'})
     def test_urlize06(self):
         output = self.engine.render_to_string('urlize06', {'a': "<script>alert('foo')</script>"})
-        self.assertEqual(output, '&lt;script&gt;alert(&#39;foo&#39;)&lt;/script&gt;')
+        self.assertEqual(output, '&lt;script&gt;alert(&#x27;foo&#x27;)&lt;/script&gt;')
 
     # mailto: testing for urlize
     @setup({'urlize07': '{{ a|urlize }}'})
@@ -113,7 +113,7 @@ def test_url_split_chars(self):
         )
         self.assertEqual(
             urlize('www.server.com\'abc'),
-            '<a href="http://www.server.com" rel="nofollow">www.server.com</a>&#39;abc',
+            '<a href="http://www.server.com" rel="nofollow">www.server.com</a>&#x27;abc',
         )
         self.assertEqual(
             urlize('www.server.com<abc'),
@@ -284,7 +284,7 @@ def test_wrapping_characters(self):
             ('<>', ('&lt;', '&gt;')),
             ('[]', ('[', ']')),
             ('""', ('&quot;', '&quot;')),
-            ("''", ('&#39;', '&#39;')),
+            ("''", ('&#x27;', '&#x27;')),
         )
         for wrapping_in, (start_out, end_out) in wrapping_chars:
             with self.subTest(wrapping_in=wrapping_in):
diff --git a/tests/template_tests/syntax_tests/test_url.py b/tests/template_tests/syntax_tests/test_url.py
--- a/tests/template_tests/syntax_tests/test_url.py
+++ b/tests/template_tests/syntax_tests/test_url.py
@@ -78,7 +78,7 @@ def test_url11(self):
     @setup({'url12': '{% url "client_action" id=client.id action="!$&\'()*+,;=~:@," %}'})
     def test_url12(self):
         output = self.engine.render_to_string('url12', {'client': {'id': 1}})
-        self.assertEqual(output, '/client/1/!$&amp;&#39;()*+,;=~:@,/')
+        self.assertEqual(output, '/client/1/!$&amp;&#x27;()*+,;=~:@,/')
 
     @setup({'url13': '{% url "client_action" id=client.id action=arg|join:"-" %}'})
     def test_url13(self):
diff --git a/tests/utils_tests/test_html.py b/tests/utils_tests/test_html.py
--- a/tests/utils_tests/test_html.py
+++ b/tests/utils_tests/test_html.py
@@ -27,7 +27,7 @@ def test_escape(self):
             ('<', '&lt;'),
             ('>', '&gt;'),
             ('"', '&quot;'),
-            ("'", '&#39;'),
+            ("'", '&#x27;'),
         )
         # Substitution patterns for testing the above items.
         patterns = ("%s", "asdf%sfdsa", "%s1", "1%sb")
@@ -70,6 +70,8 @@ def test_strip_tags(self):
         items = (
             ('<p>See: &#39;&eacute; is an apostrophe followed by e acute</p>',
              'See: &#39;&eacute; is an apostrophe followed by e acute'),
+            ('<p>See: &#x27;&eacute; is an apostrophe followed by e acute</p>',
+             'See: &#x27;&eacute; is an apostrophe followed by e acute'),
             ('<adf>a', 'a'),
             ('</adf>a', 'a'),
             ('<asdf><asdf>e', 'e'),
diff --git a/tests/view_tests/tests/test_csrf.py b/tests/view_tests/tests/test_csrf.py
--- a/tests/view_tests/tests/test_csrf.py
+++ b/tests/view_tests/tests/test_csrf.py
@@ -44,22 +44,22 @@ def test_no_referer(self):
         self.assertContains(
             response,
             'You are seeing this message because this HTTPS site requires a '
-            '&#39;Referer header&#39; to be sent by your Web browser, but '
+            '&#x27;Referer header&#x27; to be sent by your Web browser, but '
             'none was sent.',
             status_code=403,
         )
         self.assertContains(
             response,
-            'If you have configured your browser to disable &#39;Referer&#39; '
+            'If you have configured your browser to disable &#x27;Referer&#x27; '
             'headers, please re-enable them, at least for this site, or for '
-            'HTTPS connections, or for &#39;same-origin&#39; requests.',
+            'HTTPS connections, or for &#x27;same-origin&#x27; requests.',
             status_code=403,
         )
         self.assertContains(
             response,
             'If you are using the &lt;meta name=&quot;referrer&quot; '
             'content=&quot;no-referrer&quot;&gt; tag or including the '
-            '&#39;Referrer-Policy: no-referrer&#39; header, please remove them.',
+            '&#x27;Referrer-Policy: no-referrer&#x27; header, please remove them.',
             status_code=403,
         )
 
diff --git a/tests/view_tests/tests/test_debug.py b/tests/view_tests/tests/test_debug.py
--- a/tests/view_tests/tests/test_debug.py
+++ b/tests/view_tests/tests/test_debug.py
@@ -304,7 +304,7 @@ def test_request_and_exception(self):
         reporter = ExceptionReporter(request, exc_type, exc_value, tb)
         html = reporter.get_traceback_html()
         self.assertInHTML('<h1>ValueError at /test_view/</h1>', html)
-        self.assertIn('<pre class="exception_value">Can&#39;t find my keys</pre>', html)
+        self.assertIn('<pre class="exception_value">Can&#x27;t find my keys</pre>', html)
         self.assertIn('<th>Request Method:</th>', html)
         self.assertIn('<th>Request URL:</th>', html)
         self.assertIn('<h3 id="user-info">USER</h3>', html)
@@ -325,7 +325,7 @@ def test_no_request(self):
         reporter = ExceptionReporter(None, exc_type, exc_value, tb)
         html = reporter.get_traceback_html()
         self.assertInHTML('<h1>ValueError</h1>', html)
-        self.assertIn('<pre class="exception_value">Can&#39;t find my keys</pre>', html)
+        self.assertIn('<pre class="exception_value">Can&#x27;t find my keys</pre>', html)
         self.assertNotIn('<th>Request Method:</th>', html)
         self.assertNotIn('<th>Request URL:</th>', html)
         self.assertNotIn('<h3 id="user-info">USER</h3>', html)
@@ -463,7 +463,7 @@ def test_request_and_message(self):
         reporter = ExceptionReporter(request, None, "I'm a little teapot", None)
         html = reporter.get_traceback_html()
         self.assertInHTML('<h1>Report at /test_view/</h1>', html)
-        self.assertIn('<pre class="exception_value">I&#39;m a little teapot</pre>', html)
+        self.assertIn('<pre class="exception_value">I&#x27;m a little teapot</pre>', html)
         self.assertIn('<th>Request Method:</th>', html)
         self.assertIn('<th>Request URL:</th>', html)
         self.assertNotIn('<th>Exception Type:</th>', html)
@@ -476,7 +476,7 @@ def test_message_only(self):
         reporter = ExceptionReporter(None, None, "I'm a little teapot", None)
         html = reporter.get_traceback_html()
         self.assertInHTML('<h1>Report</h1>', html)
-        self.assertIn('<pre class="exception_value">I&#39;m a little teapot</pre>', html)
+        self.assertIn('<pre class="exception_value">I&#x27;m a little teapot</pre>', html)
         self.assertNotIn('<th>Request Method:</th>', html)
         self.assertNotIn('<th>Request URL:</th>', html)
         self.assertNotIn('<th>Exception Type:</th>', html)
@@ -508,7 +508,7 @@ def test_local_variable_escaping(self):
         except Exception:
             exc_type, exc_value, tb = sys.exc_info()
         html = ExceptionReporter(None, exc_type, exc_value, tb).get_traceback_html()
-        self.assertIn('<td class="code"><pre>&#39;&lt;p&gt;Local variable&lt;/p&gt;&#39;</pre></td>', html)
+        self.assertIn('<td class="code"><pre>&#x27;&lt;p&gt;Local variable&lt;/p&gt;&#x27;</pre></td>', html)
 
     def test_unprintable_values_handling(self):
         "Unprintable values should not make the output generation choke."
@@ -607,7 +607,7 @@ def test_request_with_items_key(self):
         An exception report can be generated for requests with 'items' in
         request GET, POST, FILES, or COOKIES QueryDicts.
         """
-        value = '<td>items</td><td class="code"><pre>&#39;Oops&#39;</pre></td>'
+        value = '<td>items</td><td class="code"><pre>&#x27;Oops&#x27;</pre></td>'
         # GET
         request = self.rf.get('/test_view/?items=Oops')
         reporter = ExceptionReporter(request, None, None, None)
@@ -634,7 +634,7 @@ def test_request_with_items_key(self):
         request = rf.get('/test_view/')
         reporter = ExceptionReporter(request, None, None, None)
         html = reporter.get_traceback_html()
-        self.assertInHTML('<td>items</td><td class="code"><pre>&#39;Oops&#39;</pre></td>', html)
+        self.assertInHTML('<td>items</td><td class="code"><pre>&#x27;Oops&#x27;</pre></td>', html)
 
     def test_exception_fetching_user(self):
         """

EOF_114329324912
./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 admin_docs.test_views auth_tests.test_forms forms_tests.tests.test_forms forms_tests.widget_tests.base forms_tests.widget_tests.test_clearablefileinput model_forms.tests template_tests.filter_tests.test_addslashes template_tests.filter_tests.test_make_list template_tests.filter_tests.test_title template_tests.filter_tests.test_urlize template_tests.syntax_tests.test_url utils_tests.test_html view_tests.tests.test_csrf view_tests.tests.test_debug
git checkout 28d5262fa3315690395f04e3619ed554dbaf725b tests/admin_docs/test_views.py tests/auth_tests/test_forms.py tests/forms_tests/tests/test_forms.py tests/forms_tests/widget_tests/base.py tests/forms_tests/widget_tests/test_clearablefileinput.py tests/model_forms/tests.py tests/template_tests/filter_tests/test_addslashes.py tests/template_tests/filter_tests/test_make_list.py tests/template_tests/filter_tests/test_title.py tests/template_tests/filter_tests/test_urlize.py tests/template_tests/syntax_tests/test_url.py tests/utils_tests/test_html.py tests/view_tests/tests/test_csrf.py tests/view_tests/tests/test_debug.py
