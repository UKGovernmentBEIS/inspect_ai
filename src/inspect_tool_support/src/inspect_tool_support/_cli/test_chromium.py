#!/usr/bin/env python3
import os
import sys
import traceback
from pathlib import Path

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    meipass_lib = Path(sys._MEIPASS) / "lib"
    existing_ld = os.environ.get("LD_LIBRARY_PATH", "")
    new_ld = f"{meipass_lib}:{existing_ld}" if existing_ld else str(meipass_lib)
    os.environ["LD_LIBRARY_PATH"] = new_ld
    print(f"LD_LIBRARY_PATH set to {os.environ['LD_LIBRARY_PATH']}")
    # Hint Playwright to use packaged browsers and skip host validation inside minimal containers
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    os.environ.setdefault("PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS", "1")
    os.environ["DEBUG"] = (
        "pw:api,pw:browser,pw:channel,pw:driver,pw:page,pw:network,pw:proxy,pw:fetch"
    )


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: Playwright not installed.")
    sys.exit(1)


def test_chromium():
    with sync_playwright() as p:
        browser_args = [
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            # "--enable-logging",
            "--v=1",
            "--log-level=0",
            "--enable-crash-reporter",
            "--crash-dumps-dir=/tmp/chromium-crashes",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=TranslateUI",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
            "--remote-debugging-port=9222",
            "--disable-web-fonts",
            "--disable-font-subpixel-positioning",
            "--force-device-scale-factor=1",
        ]

        browser = p.chromium.launch(headless=True, args=browser_args)

        page = browser.new_page()
        page.on("pageerror", lambda error: print(f"PAGE ERROR: {error}"))
        page.on("crash", lambda: print("PAGE CRASHED!"))

        try:
            page.goto("https://boston.com", timeout=30000)  # Get page title
            print(
                "✅ Success"
                if page.title()
                == "Boston.com: Local breaking news, sports, weather, and things to do"
                else "❌ FAILURE"
            )

        except Exception as nav_error:
            print(
                f"Page.goto: ({type(nav_error).__name__}) {nav_error}\n{traceback.format_exc()}"
            )

        browser.close()

    return True


def main():
    """Main function to run the test."""
    # Run the async test
    # success = asyncio.run(test_chromium_navigation())

    success = test_chromium_navigation()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
