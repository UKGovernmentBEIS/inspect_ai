from playwright.async_api import async_playwright


async def exec_playwright_test() -> str:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            page = await browser.new_page()
            await page.goto("https://playwright.dev/")
            h2_text = await page.locator("h1").first.text_content()
            await browser.close()
            return h2_text or "result was None"
    except Exception as ex:
        print(f"_exec_playwright_test caught {ex}")
        raise
