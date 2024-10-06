import playwright_crawler
from absl.testing import parameterized


class TestPlaywrightCrawler(parameterized.TestCase):
    def setUp(self):
        self._crawler = playwright_crawler.PlaywrightCrawler()

    def test_go_to_page_changes_url(self):
        self.assertEqual(self._crawler.url, "about:blank")
        self._crawler.go_to_page("https://www.example.com")
        self.assertEqual(self._crawler.url, "https://www.example.com/")

    def test_go_to_page_adds_missing_protocol(self):
        self._crawler.go_to_page("www.example.com")
        self.assertEqual(self._crawler.url, "https://www.example.com/")

    def test_nodes_change_on_update(self):
        self._crawler.go_to_page("https://www.example.com")
        self.assertFalse(self._crawler._nodes)
        self._crawler.update()
        self.assertTrue(self._crawler._nodes)

    def test_render_accessibility_tree(self):
        self._crawler.go_to_page("https://www.example.com")
        at_no_update = self._crawler.render(playwright_crawler.CrawlerOutputFormat.AT)
        self.assertEqual(at_no_update, "<empty>")

        self._crawler.update()

        at_update = self._crawler.render(playwright_crawler.CrawlerOutputFormat.AT)
        nodes = at_update.splitlines()
        self.assertEqual(len(nodes), 3)
        print(nodes)
        self.assertTrue(
            nodes[0].startswith(
                '[5] RootWebArea "Example Domain" [focused: True, url: https://www.example.com/]'
            )
        )
        self.assertTrue(
            nodes[1].startswith(
                '  [3] StaticText "This domain is for use in illustrative examples in documents'
            )
        )
        self.assertTrue(
            nodes[2].startswith(
                '  [12] link "More information..." [url: https://www.iana.org/domains/example]'
            )
        )

    def test_click_adjusts_to_scrolling_position(self):
        test_html = """
            <!DOCTYPE html>
            <html lang="en">
            <head>
              <meta charset="UTF-8">
              <title>Scrolling Test Page</title>
              <style>
                body { height: 3000px; }
                .my-button { position: absolute; top: 1500px; }
              </style>
            </head>
            <body>
              <button class="my-button" onclick="changeText(this)">Click Me</button>
              <script>
                function changeText(button) {
                  button.textContent = "Text Changed!";
                }
              </script>
            </body>
            </html>
            """
        self._crawler._page.set_content(test_html)
        self._crawler.update()
        at_before_scroll = self._crawler.render(
            playwright_crawler.CrawlerOutputFormat.AT
        )
        self.assertIn("Scrolling Test Page", at_before_scroll)
        self.assertNotIn("Click Me", at_before_scroll)

        self._crawler.scroll("down")
        self._crawler.update()
        at_after_scroll = self._crawler.render(
            playwright_crawler.CrawlerOutputFormat.AT
        )
        self.assertIn("Click Me", at_after_scroll)

        self._crawler.click("17")
        self._crawler.update()
        at_after_click = self._crawler.render(playwright_crawler.CrawlerOutputFormat.AT)
        self.assertIn("Text Changed!", at_after_click)
