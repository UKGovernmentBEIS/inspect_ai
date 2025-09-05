#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# When running as a PyInstaller onefile binary, all bundled shared libs are extracted
# under sys._MEIPASS. Ensure the dynamic linker can find them by prepending that
# lib directory to LD_LIBRARY_PATH before launching Chromium.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    meipass_lib = Path(getattr(sys, "_MEIPASS")) / "lib"
    existing_ld = os.environ.get("LD_LIBRARY_PATH", "")
    new_ld = f"{meipass_lib}:{existing_ld}" if existing_ld else str(meipass_lib)
    os.environ["LD_LIBRARY_PATH"] = new_ld
    print(f"LD_LIBRARY_PATH set to {os.environ['LD_LIBRARY_PATH']}")
    # Hint Playwright to use packaged browsers and skip host validation inside minimal containers
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    os.environ.setdefault("PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS", "1")


def main():
    try:
        os.environ["DEBUG"] = "pw:api,pw:browser*"
        # os.environ['PWDEBUG'] = '1'  # This will slow down execution but provide more details

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            page = browser.new_page()
            page.goto("https://playwright.dev/")
            h2_text = page.locator("h1").first.text_content()
            print(f"First H2: {h2_text}")
            browser.close()
    except Exception as ex:
        print(f"caught {ex}")
        raise


if __name__ == "__main__":
    main()

# pip install playwright
# NODE_OPTIONS='' PLAYWRIGHT_BROWSERS_PATH=0  playwright install chromium
# NODE_OPTIONS='' playwright install-deps
