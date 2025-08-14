# Static imports for PyInstaller compatibility
from inspect_tool_support._in_process_tools._text_editor import (
    json_rpc_methods as text_editor_methods,
)
from inspect_tool_support._in_process_tools._version import (
    json_rpc_methods as version_methods,
)
from inspect_tool_support._remote_tools._bash_session import (
    json_rpc_methods as bash_session_methods,
)
from inspect_tool_support._remote_tools._mcp import json_rpc_methods as mcp_methods
from inspect_tool_support._remote_tools._remote_version import (
    json_rpc_methods as remote_version_methods,
)

# from inspect_tool_support._remote_tools._web_browser import (
#     json_rpc_methods as web_browser_methods,
# )

# TODO: The playwright package includes some .sh scripts - e.g. reinstall_chrome_beta_linux.sh
# staticx naïvely treats any executable file as an ELF file. Of course, .sh files
# are not. Unfortunately, there's no trivial way to tell staticx to only process
# true ELF files. The proposed solution is to strip +x from those files' permissions.
# That seems silly. If we're willing to -X them, why include them at all? Some
# suggest implementing a python PyInstall hook to filter them out.

# Static registry of tools with direct module references
# To add a new tool: add an import above and an entry below
_TOOLS = {
    "inspect_tool_support._remote_tools": {
        "bash_session": bash_session_methods,
        "mcp": mcp_methods,
        # "web_browser": web_browser_methods,
        "remote_version": remote_version_methods,
    },
    "inspect_tool_support._in_process_tools": {
        "text_editor": text_editor_methods,
        "version": version_methods,
    },
}


def load_tools(tools_package_name: str) -> set[str]:
    """
    Loads tools from children of the specified package and registers their JSON-RPC methods.

    Note: All JSON-RPC methods are already registered via static imports at module load time.

    Args:
      tools_package_name (str): The name of the package containing the tools child packages.

    Returns:
      set[str]: A set of the names of the tools that were loaded.
    """
    # Return the tool names for the specified package
    return set(_TOOLS.get(tools_package_name, {}).keys())
