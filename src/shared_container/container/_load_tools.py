import importlib
import os


def load_tools(subdir_name: str) -> set[str]:
    """
    Loads tools from a specified subdirectory and registers their JSON-RPC methods.

    Args:
      subdir_name (str): The name of the subdirectory containing the tools.

    Returns:
      set[str]: A set of the names of the tools that were loaded.
    """
    result: set[str] = set()
    tools_dir = os.path.join(os.path.dirname(__file__), subdir_name)
    package_prefix = subdir_name.replace(os.sep, ".")
    for entry in os.listdir(tools_dir):
        entry_path = os.path.join(tools_dir, entry)
        if os.path.isdir(entry_path):
            result.add(entry.lstrip("_"))
            importlib.import_module(f"{package_prefix}.{entry}.json_rpc_methods")
    return result
