import importlib.util
import inspect
import json
import site
import sys
from functools import lru_cache
from importlib.metadata import Distribution, PackageNotFoundError
from typing import Any


def get_installed_package_name(obj: Any) -> str | None:
    # special handling for built-in functions
    if inspect.isbuiltin(obj):
        # try to get the module name
        if getattr(obj, "__module__") is not None:
            module_name = obj.__module__
            if module_name:
                return module_name.split(".")[0]

        # try to get the class that defines this method
        if hasattr(obj, "__objclass__"):
            cls = obj.__objclass__
        elif hasattr(obj, "__self__"):
            cls = type(obj.__self__)
        else:
            return None

        for base_cls in inspect.getmro(cls):
            module = inspect.getmodule(base_cls)
            if module:
                return module.__name__.split(".")[0]

    # get the module of the object
    module = inspect.getmodule(obj)
    if module is None:
        return None

    # find the origin (install path) for the module
    module_name = module.__name__
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception:
        return None
    if spec is None or spec.origin is None:
        return None

    # check if this is a package (either in library or installed editable)
    package_name = module_name.split(".")[0]
    if package_path_is_in_site_packages(spec.origin):
        return package_name
    if package_is_installed_editable(package_name):
        return package_name
    else:
        return None


@lru_cache(maxsize=None)
def package_path_is_in_site_packages(path: str) -> bool:
    path = path.lower()
    return (
        any(path.startswith(p.lower()) for p in site.getsitepackages())
        or path.startswith(site.getusersitepackages().lower())
        or any(
            "site-packages" in p.lower() and path.startswith(p.lower())
            for p in sys.path
        )
    )


@lru_cache(maxsize=None)
def package_is_installed_editable(package: str) -> bool:
    # get the distribution
    try:
        distribution = Distribution.from_name(package)
    except (ValueError, PackageNotFoundError):
        return False

    # read the direct_url json
    direct_url_json = distribution.read_text("direct_url.json")
    if not direct_url_json:
        return False

    # parse the json
    try:
        direct_url = json.loads(direct_url_json)
        if not isinstance(direct_url, dict):
            return False
    except json.JSONDecodeError:
        return False

    # read the editable property
    return direct_url.get("dir_info", {}).get("editable", False) is not False
