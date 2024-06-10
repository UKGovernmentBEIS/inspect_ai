import os
import subprocess
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))

try:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "uninstall", "-y", "inspect_package"]
    )
except subprocess.CalledProcessError:
    pass
