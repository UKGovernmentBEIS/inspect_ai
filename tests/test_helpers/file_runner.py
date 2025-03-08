import subprocess
import sys
from pathlib import Path


def run_tests_by_file():
    args = sys.argv[1:]
    TESTS_DIR = Path(__file__).parent.parent
    test_files = TESTS_DIR.glob("**/test_*.py")

    for test_file in test_files:
        pytest_command = ["pytest", test_file.as_posix()] + args
        result = subprocess.run(pytest_command)
        if result.returncode != 0:
            sys.exit(result.returncode)

    print("All tests passed.")


if __name__ == "__main__":
    run_tests_by_file()
