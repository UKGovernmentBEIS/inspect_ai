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

    # Handle different import contexts
    if __package__ is None or __package__ == "":
        # Direct development execution
        tools_dir = os.path.join(os.path.dirname(__file__), subdir_name)
        package_prefix = subdir_name
    else:
        # Installed package context
        tools_dir = os.path.join(os.path.dirname(__file__), subdir_name)
        package_prefix = f"{__package__}.{subdir_name}"

    # Always keep the subdirectory name with its leading underscore
    for entry in os.listdir(tools_dir):
        entry_path = os.path.join(tools_dir, entry)
        if os.path.isdir(entry_path):
            # Strip leading underscore for the tool name
            tool_name = entry.lstrip("_")
            result.add(tool_name)
            # But keep original directory name for import
            try:
                importlib.import_module(f"{package_prefix}.{entry}.json_rpc_methods")
            except ImportError as e:
                print(f"Error importing {package_prefix}.{entry}.json_rpc_methods: {e}")
                # Fallback to direct import if package import fails
                if __package__:
                    try:
                        importlib.import_module(
                            f"{subdir_name}.{entry}.json_rpc_methods"
                        )
                    except ImportError:
                        raise

    return result
