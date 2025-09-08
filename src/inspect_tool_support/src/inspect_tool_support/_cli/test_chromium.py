#!/usr/bin/env python3
import os
import sys
import traceback
from pathlib import Path

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    meipass = Path(sys._MEIPASS)

    # NEW: Configure fontconfig paths
    bundled_fonts_conf = meipass / "etc" / "fonts" / "fonts.conf"

    if bundled_fonts_conf.exists():
        # Point to bundled fontconfig
        os.environ["FONTCONFIG_FILE"] = str(bundled_fonts_conf)
        os.environ["FONTCONFIG_PATH"] = str(bundled_fonts_conf.parent)

        # Create writable cache directory
        fc_cache = Path("/tmp") / f"fontconfig-{os.getpid()}"
        fc_cache.mkdir(exist_ok=True)
        os.environ["FC_CACHE"] = str(fc_cache)
    else:
        print("BUNDLED FONT CONFIG dir not found")

    meipass_lib = meipass / "lib"
    existing_ld = os.environ.get("LD_LIBRARY_PATH", "")
    new_ld = f"{meipass_lib}:{existing_ld}" if existing_ld else str(meipass_lib)
    os.environ["LD_LIBRARY_PATH"] = new_ld
    print(f"LD_LIBRARY_PATH set to {os.environ['LD_LIBRARY_PATH']}")
    print(f"FONT_CONFIG_PATH set to {os.environ['FONTCONFIG_PATH']}")
    print(f"FONT_CONFIG_FILE set to {os.environ['FONTCONFIG_FILE']}")

    # Hint Playwright to use packaged browsers and skip host validation inside minimal containers
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    # os.environ.setdefault("PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS", "1")
    os.environ["DEBUG"] = "pw:*"
    os.environ["PLAYWRIGHT_DEBUG"] = "pw:*"
    os.environ["CHROME_LOG_FILE"] = "/tmp/pyinstaller_chrome_debug.log"


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: Playwright not installed.")
    sys.exit(1)


critical_disables = [
    # Font-related (likely main culprit)
    "FontSystemFallbackNotoCjk",
    "FontAccess",
    "WebFontsCacheAwareTimeoutAdaption",
    "RenderBlockingFonts",
    # Memory management
    "OptimizationGuideModelDownloading",
    "OptimizationHintsFetching",
    "OptimizationTargetPrediction",
    "OptimizationHints",
    # Background processing
    "BackgroundFetch",
    "ServiceWorkerAutoPreload",
    "BackgroundResourceFetch",
    # GPU/Rendering
    "VizDisplayCompositor",
    "CompositeBGColorAnimation",
    "TranslateUI",
    "WebUSB",
    "WebBluetooth",
    "FencedFrames",  # Experimental frames
    "SharedArrayBuffer",  # Shared memory
    "WebAssemblyLazyCompilation",  # WASM features
    "VizDisplayCompositor",  # Display compositor
    "CompositeBGColorAnimation",  # Background animations
    "CompositeBoxShadowAnimation",  # Shadow animations
    "Canvas2dGPUTransfer",  # GPU canvas
    "CanvasHDR",  # HDR canvas
    "BackgroundFetch",  # Background resource usage
    "BackgroundResourceFetch",  # More background activity
    "ServiceWorkerAutoPreload",  # Service worker preloading
    "PrefetchPrivacyChanges",  # Prefetch behavior
    "MemorySaverModeRenderTuning",  # Memory tuning
    "PrivateNetworkAccessForWorkers",  # Network access checks
    "PrivateNetworkAccessSendPreflights",  # CORS preflights
    "BlockInsecurePrivateNetworkRequests",  # Security blocks
    "CorsRFC1918",  # CORS restrictions
    "InterestFeedContentSuggestions",  # NTP suggestions
    "Translate",  # Translation popups
    "GlobalMediaControls",  # Media controls
    "TabSearch",  # Tab search UI
    "LensStandalone,LensRegionSearch",  # Google Lens features
]


def test_chromium():
    with sync_playwright() as p:
        browser_args = [
            f"--disable-features={','.join(critical_disables)}",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--enable-logging",
            "--v=1",
            "--log-level=1",
            "--enable-crash-reporter",
            "--crash-dumps-dir=/tmp/chromium-crashes",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            # "--disable-web-security",
            # "--remote-debugging-port=9222",
            "--disable-web-fonts",
            "--disable-remote-fonts",
            "--disable-font-subpixel-positioning",
            "--force-device-scale-factor=1",
            "--crash-dumps-dir=/tmp/chromium-crashes",
            "--log-net-log=/tmp/net-export.json",
            "--disable-dev-shm-usage",
            # Disable SPDY and QUIC protocols:
            "--disable-http2",
            "--disable-quic",
            # Disable histogram logging:
            "--disable-background-timer-throttling",
            "--disable-blink-features=AutomationControlled",
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

    success = test_chromium()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
