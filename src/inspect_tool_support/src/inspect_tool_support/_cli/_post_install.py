import subprocess


def post_install(no_web_browser: bool | None) -> None:
    if not (no_web_browser or False):
        _install_playwright()


def _install_playwright() -> None:
    subprocess.run(["playwright", "install", "--with-deps", "chromium"], check=True)
    print("Successfully ran 'playwright install'")
    subprocess.run(["playwright", "install-deps"], check=True)
    print("Successfully ran 'playwright install-deps'")
