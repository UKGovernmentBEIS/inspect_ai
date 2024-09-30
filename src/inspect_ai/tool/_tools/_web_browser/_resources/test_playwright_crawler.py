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
