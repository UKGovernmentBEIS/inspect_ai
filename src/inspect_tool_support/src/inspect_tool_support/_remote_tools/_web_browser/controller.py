from typing import Awaitable, Callable, Literal

from inspect_tool_support._remote_tools._web_browser.constants import (
    DEFAULT_SESSION_NAME,
)
from inspect_tool_support._remote_tools._web_browser.playwright_browser import (
    PlaywrightBrowser,
)
from inspect_tool_support._remote_tools._web_browser.playwright_crawler import (
    PlaywrightCrawler,
)
from inspect_tool_support._remote_tools._web_browser.playwright_page_crawler import (
    PageCrawler,
)
from inspect_tool_support._remote_tools._web_browser.scale_factor import (
    get_screen_scale_factor,
)
from inspect_tool_support._remote_tools._web_browser.tool_types import CrawlerResult
from inspect_tool_support._util.session_controller import SessionController


class WebBrowserSessionController(SessionController[PlaywrightCrawler]):
    """WebBrowserSessionController provides support for isolated inspect subtask sessions."""

    def __init__(self) -> None:
        super().__init__()
        self._browser: PlaywrightBrowser | None = None

    async def new_session(self, headful: bool) -> str:
        async def factory() -> PlaywrightCrawler:
            if not self._browser:
                self._browser = await PlaywrightBrowser.create(headless=not headful)
            return await PlaywrightCrawler.create(
                await self._browser.get_new_context(),
                device_scale_factor=get_screen_scale_factor() if headful else 1,
            )

        return await self.create_new_session(DEFAULT_SESSION_NAME, factory)

    async def go_to_url(self, session_name: str, url: str) -> CrawlerResult:
        return await self._execute_crawler_command(
            session_name, lambda page: page.go_to_url(url)
        )

    async def click(self, session_name: str, element_id: int) -> CrawlerResult:
        return await self._execute_crawler_command(
            session_name, lambda page: page.click(element_id)
        )

    async def scroll(
        self, session_name: str, direction: Literal["up", "down"]
    ) -> CrawlerResult:
        return await self._execute_crawler_command(
            session_name, lambda page: page.scroll(direction)
        )

    async def forward(self, session_name: str) -> CrawlerResult:
        return await self._execute_crawler_command(
            session_name, lambda page: page.forward()
        )

    async def back(self, session_name: str) -> CrawlerResult:
        return await self._execute_crawler_command(
            session_name, lambda page: page.back()
        )

    async def refresh(self, session_name: str) -> CrawlerResult:
        return await self._execute_crawler_command(
            session_name, lambda page: page.refresh()
        )

    async def type_text(
        self, session_name: str, element_id: int, text: str
    ) -> CrawlerResult:
        return await self._execute_crawler_command(
            session_name, lambda page: page.type(element_id, text)
        )

    async def type_submit(
        self, session_name: str, element_id: int, text: str
    ) -> CrawlerResult:
        return await self._execute_crawler_command(
            session_name, lambda page: page.submit(element_id, text)
        )

    async def _execute_crawler_command(
        self, session_name: str, handler: Callable[[PageCrawler], Awaitable[None]]
    ) -> CrawlerResult:
        try:
            crawler = self.session_for_name(session_name)

            await handler(await crawler.current_page)

            # Make sure to go back and sample .current_page after calling the handler
            # since the page may have changed
            await (await crawler.current_page).update()

            # If there's a cookies message click to sort it out.
            await (await crawler.current_page).auto_click_cookies()

            return CrawlerResult(
                web_url=(await crawler.current_page).url.split("?")[0],
                main_content=(await crawler.current_page).render_main_content(),
                web_at=(await crawler.current_page).render_at(),
                error=None,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            return CrawlerResult(
                web_url=(await crawler.current_page).url.split("?")[0],
                web_at="encountered error",
                error=str(e),
            )
