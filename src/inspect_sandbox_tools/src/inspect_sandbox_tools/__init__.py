"""
Sandbox container tool code for inspect_ai.

Contains tools for bash, and editor functionality.
"""

from importlib.metadata import version as importlib_version

from inspect_sandbox_tools._util.constants import PKG_NAME

__version__ = importlib_version(PKG_NAME)
__all__ = ["__version__"]
