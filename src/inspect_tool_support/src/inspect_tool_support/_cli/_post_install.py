import platform
import subprocess


def post_install(no_web_browser: bool | None) -> None:
    if not (no_web_browser or False):
        _install_playwright()


def _install_playwright() -> None:
    subprocess.run(["playwright", "install", "--with-deps", "chromium"], check=True)
    print("Successfully ran 'playwright install'")
    subprocess.run(["playwright", "install-deps"], check=True)
    print("Successfully ran 'playwright install-deps'")


def _is_kali_linux():
    try:
        os_info = platform.freedesktop_os_release()
        return (
            "kali" in os_info.get("ID", "").lower()
            or "kali" in os_info.get("NAME", "").lower()
        )
    except AttributeError:
        return False
