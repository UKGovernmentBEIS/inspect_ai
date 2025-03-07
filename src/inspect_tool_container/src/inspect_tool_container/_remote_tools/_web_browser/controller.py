import threading
from typing import Awaitable, Callable, Literal

from inspect_tool_container._remote_tools._web_browser.constants import (
    DEFAULT_SESSION_NAME,
)
from inspect_tool_container._remote_tools._web_browser.playwright_browser import (
    PlaywrightBrowser,
)
from inspect_tool_container._remote_tools._web_browser.playwright_crawler import (
    PlaywrightCrawler,
)
from inspect_tool_container._remote_tools._web_browser.playwright_page_crawler import (
    PageCrawler,
)
from inspect_tool_container._remote_tools._web_browser.scale_factor import (
    get_screen_scale_factor,
)
from inspect_tool_container._remote_tools._web_browser.tool_types import CrawlerResult


class Controller:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._browser: PlaywrightBrowser | None = None
        self._sessions: dict[str, PlaywrightCrawler] = {}

    async def new_session(self, headful: bool) -> str:
        with self._lock:
            if not self._browser:
                self._browser = await PlaywrightBrowser.create(headless=not headful)
            current_count = len(self._sessions)
            name = (
                DEFAULT_SESSION_NAME
                if current_count == 0
                else f"{DEFAULT_SESSION_NAME}_{current_count}"
            )
            crawler = await PlaywrightCrawler.create(
                await self._browser.get_new_context(),
                device_scale_factor=get_screen_scale_factor() if headful else 1,
            )
            self._sessions[name] = crawler
            return name

    async def go_to_url(self, session_name: str, url: str) -> CrawlerResult:
        async def handler(page: PageCrawler) -> None:
            await page.go_to_url(url)

        return await self._execute_crawler_command(session_name, handler)

    async def click(self, session_name: str, element_id: int) -> CrawlerResult:
        async def handler(page: PageCrawler) -> None:
            await page.click(element_id)

        return await self._execute_crawler_command(session_name, handler)

    async def scroll(
        self, session_name: str, direction: Literal["up", "down"]
    ) -> CrawlerResult:
        async def handler(page: PageCrawler) -> None:
            await page.scroll(direction)

        return await self._execute_crawler_command(session_name, handler)

    async def forward(self, session_name: str) -> CrawlerResult:
        async def handler(page: PageCrawler) -> None:
            await page.forward()

        return await self._execute_crawler_command(session_name, handler)

    async def back(self, session_name: str) -> CrawlerResult:
        async def handler(page: PageCrawler) -> None:
            await page.back()

        return await self._execute_crawler_command(session_name, handler)

    async def refresh(self, session_name: str) -> CrawlerResult:
        async def handler(page: PageCrawler) -> None:
            await page.refresh()

        return await self._execute_crawler_command(session_name, handler)

    async def type_text(
        self, session_name: str, element_id: int, text: str
    ) -> CrawlerResult:
        async def handler(page: PageCrawler) -> None:
            await page.type(element_id, text)

        return await self._execute_crawler_command(session_name, handler)

    async def type_submit(
        self, session_name: str, element_id: int, text: str
    ) -> CrawlerResult:
        async def handler(page: PageCrawler) -> None:
            await page.clear(element_id)
            await page.type(element_id, text + "\n")

        return await self._execute_crawler_command(session_name, handler)

    async def _execute_crawler_command(
        self, session_name: str, handler: Callable[[PageCrawler], Awaitable[None]]
    ) -> CrawlerResult:
        if not self._sessions:
            await self.new_session(False)

        try:
            crawler = self._sessions[session_name]

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
