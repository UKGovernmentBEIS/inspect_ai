import logging
from os import getenv

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright


class PlaywrightBrowser:
    """Stores the browser and creates new contexts."""

    WIDTH = 1280
    HEIGHT = 1080
    _playwright: Playwright | None = None

    @classmethod
    async def create(cls, headless: bool | None = None) -> "PlaywrightBrowser":
        if PlaywrightBrowser._playwright is None:
            PlaywrightBrowser._playwright = await async_playwright().start()

        headless = True if headless is None else headless
        logging.info(
            "Starting chromium in %s mode.", "headless" if headless else "headful"
        )

        return PlaywrightBrowser(
            await PlaywrightBrowser._playwright.chromium.launch(
                headless=headless,
                # Required for Gmail signup see
                # https://stackoverflow.com/questions/65139098/how-to-login-to-google-account-with-playwright
                args=["--disable-blink-features=AutomationControlled"],
            )
        )

    def __init__(self, browser: Browser) -> None:
        self._browser = browser

    async def get_new_context(self) -> BrowserContext:
        return await self._browser.new_context(
            geolocation={"longitude": -0.12, "latitude": 51},
            locale="en-GB",
            permissions=["geolocation"],
            timezone_id="Europe/London",
            viewport={"width": self.WIDTH, "height": self.HEIGHT},
            ignore_https_errors=getenv("IGNORE_HTTPS_ERRORS", "") != "",
        )

    async def close(self) -> None:
        await self._browser.close()
        if PlaywrightBrowser._playwright is not None:
            await PlaywrightBrowser._playwright.stop()
            PlaywrightBrowser._playwright = None
