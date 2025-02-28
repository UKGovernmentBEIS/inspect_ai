"""A crawler implementation using Playwright.

Largely based on  https://github.com/web-arena-x/webarena
"""

from __future__ import annotations

from asyncio.futures import Future

from playwright.async_api import BrowserContext, Page

from inspect_tool_support._remote_tools._web_browser.playwright_page_crawler import (
    PageCrawler,
)


class PlaywrightCrawler:
    @classmethod
    async def create(
        cls, browser_context: BrowserContext, device_scale_factor: float | None = None
    ) -> PlaywrightCrawler:
        page_crawler = await PageCrawler.create(
            await browser_context.new_page(), device_scale_factor
        )

        return PlaywrightCrawler(browser_context, page_crawler, device_scale_factor)

    def __init__(
        self,
        browser_context: BrowserContext,
        page_crawler: PageCrawler,
        device_scale_factor: float | None,
    ):
        self._device_scale_factor = device_scale_factor
        self._page_future = Future[PageCrawler]()
        self._page_future.set_result(page_crawler)
        browser_context.on("page", self._on_page)

    @property
    async def current_page(self) -> PageCrawler:
        return await self._page_future

    async def _on_page(self, new_page: Page) -> None:
        # we know we're switching pages, but it will take time to get the new page crawler, so
        # reset the future to force new callers to wait.
        # TODO: A race remains in the case that we get multiple on_pages before the first one sets the result
        self._page_future = Future()
        self._page_future.set_result(
            await PageCrawler.create(new_page, self._device_scale_factor)
        )
