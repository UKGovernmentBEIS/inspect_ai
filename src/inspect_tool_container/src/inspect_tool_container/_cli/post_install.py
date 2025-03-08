import subprocess
import sys

if __name__ == "__main__":
    print("\n=== Installing Playwright browsers ===")
    subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)
    print("\n=== Installing Playwright dependencies ===")
    subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True)
    print("=== Playwright setup completed successfully ===\n")
