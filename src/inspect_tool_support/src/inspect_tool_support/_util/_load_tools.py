import importlib
import pkgutil


def load_tools(tools_package_name: str) -> set[str]:
    """
    Loads tools from children of the specified package and registers their JSON-RPC methods.

    Args:
      tools_package_name (str): The name of the package containing the tools child packages.

    Returns:
      set[str]: A set of the names of the tools that were loaded.
    """
    tools_package_path = importlib.import_module(tools_package_name).__path__[0]
    package_infos = (
        module for module in pkgutil.iter_modules([tools_package_path]) if module.ispkg
    )

    result: set[str] = set()
    for package_info in package_infos:
        importlib.import_module(
            f"{tools_package_name}.{package_info.name}.json_rpc_methods"
        )
        result.add(package_info.name.lstrip("_"))

    return result
