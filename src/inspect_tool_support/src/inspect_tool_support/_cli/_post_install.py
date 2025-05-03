import subprocess
import sys


def post_install(no_web_browser: bool | None) -> None:
    if not (no_web_browser or False):
        _install_playwright()


def _install_playwright() -> None:
    # We need to be very careful about using the same Python interpreter that
    # we've been launched with. This is because the Playwright package is
    # installed in the same venv as this application.
    the_proper_python = sys.executable

    subprocess.run(
        [the_proper_python, "-m", "playwright", "install", "--with-deps", "chromium"],
        check=True,
    )
    print("Successfully ran 'playwright install'")
    subprocess.run([the_proper_python, "-m", "playwright", "install-deps"], check=True)
    print("Successfully ran 'playwright install-deps'")
