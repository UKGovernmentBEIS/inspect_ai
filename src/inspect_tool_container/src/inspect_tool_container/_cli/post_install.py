import subprocess
import sys


def install_playwright_dependencies(cmd=None):
    """
    Install Playwright browsers and system dependencies.

    This function is called as a post-install hook and also available
    as a standalone command.

    Args:
        cmd: Used by setuptools for the entry point. Not used in the function.
    """
    try:
        print("\n=== Installing Playwright dependencies ===")
        print("Installing Playwright browsers...")
        subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)

        print("\nInstalling Playwright system dependencies...")
        subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True)
        print("=== Playwright setup completed successfully ===\n")
        return True
    except Exception as e:
        print(f"\nError during Playwright setup: {e}", file=sys.stderr)
        print(
            "You may need to run 'playwright install' and 'playwright install-deps' manually after installation"
        )
        return False


def main():
    """Main entry point for the script when run as a command."""
    success = install_playwright_dependencies()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
