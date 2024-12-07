from unittest.mock import MagicMock, call, patch

import web_environment
from absl.testing import parameterized
from playwright_crawler import CrawlerOutputFormat


class TestWebEnvironment(parameterized.TestCase):
    @patch("playwright_crawler.PlaywrightCrawler")
    def setUp(self, MockCrawler):
        self._mock_crawler = MagicMock()
        MockCrawler.return_value = self._mock_crawler
        self._mock_browser_context = MagicMock()
        self._web_env = web_environment.WebEnvironment(self._mock_browser_context)

    def test_step_go_to_command(self):
        self._web_env.step("web_go https://en.wikipedia.org/wiki/Sun ignored_param")
        self._mock_crawler.go_to_page.assert_called_once_with(
            "https://en.wikipedia.org/wiki/Sun"
        )

    def test_step_click_command(self):
        self._web_env.step("web_click 1111 ignored_param")
        # click() might be also called later but we only check the first call
        self.assertEqual(self._mock_crawler.mock_calls[0], call.click("1111"))

    def test_step_scroll_command(self):
        self._web_env.step("web_scroll up ignored_param")
        self._mock_crawler.scroll.assert_called_once_with("up")

    def test_step_forward_command(self):
        self._web_env.step("web_forward ignored_param")
        self._mock_crawler.forward.assert_called_once_with()

    def test_step_back_command(self):
        self._web_env.step("web_back ignored_param")
        self._mock_crawler.back.assert_called_once_with()

    def test_step_refresh_command(self):
        self._web_env.step("web_refresh ignored_param")
        self._mock_crawler.refresh.assert_called_once_with()

    def test_step_type_command(self):
        self._web_env.step("web_type some_element_id text to type into element")
        self._mock_crawler.type.assert_called_once_with(
            "some_element_id", "text to type into element"
        )

    def test_step_type_submit_command(self):
        self._web_env.step("web_type_submit some_element_id text to type into element")
        self._mock_crawler.clear.assert_called_once()
        self._mock_crawler.type.assert_called_once_with(
            "some_element_id", "text to type into element\n"
        )

    @parameterized.parameters(
        ("web_go"),
        ("web_click"),
        ("web_scroll"),
        ("web_type"),
        ("web_type_submit"),
        ("some_random_command"),
    )
    def test_step_invalid_command(self, command):
        self._web_env.step(command)
        self.assertEqual(self._web_env._last_error, f'\n\nInvalid command: "{command}"')

    def test_get_observations_returns_only_required_observations(self):
        obs = self._web_env.get_observations(["web_at"])
        self.assertTrue(set(obs.keys()) == set(["web_at"]))
        self._mock_crawler.render.assert_called_once_with(CrawlerOutputFormat.AT)
