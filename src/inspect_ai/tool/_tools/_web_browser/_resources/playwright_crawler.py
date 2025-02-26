"""A crawler implementation using Playwright.

Largely based on  https://github.com/web-arena-x/webarena
"""

from __future__ import annotations

from playwright.async_api import BrowserContext, Page

from playwright_page_crawler import PageCrawler


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
        self._page_crawler = page_crawler
        browser_context.on("page", self._on_page)

    @property
    def current_page(self) -> PageCrawler:
        return self._page_crawler

    async def _on_page(self, new_page: Page):
        self._page_crawler = await PageCrawler.create(
            new_page, self._device_scale_factor
        )
