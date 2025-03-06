"""
Multi-tool package for inspect_ai.

Contains tools for web browser, bash, and editor functionality.
"""

__version__ = "0.1.0"

# Ensure package modules are accessible as inspect_multi_tool.* 
# This makes imports work correctly when installed with pyproject.toml
from . import _constants
from . import _load_tools
from . import _in_process_tools
from . import _remote_tools
from . import _util
from . import back_compat
