from importlib.metadata import version


def pip_dependency_error(feature: str, dependencies: list[str]) -> Exception:
    return ModuleNotFoundError(
        f"ERROR: {feature} requires optional dependencies. "
        f"Install with:\n\npip install {' '.join(dependencies)}\n"
    )


def module_version_error(
    feature: str, package: str, required_version: str
) -> Exception:
    return ModuleNotFoundError(
        f"ERROR: {feature} requires at least version {required_version} of package {package} "
        f"(you have version {version(package)} installed).\n\n"
        f"Upgrade with:\n\npip install --upgrade {package}\n"
    )


def exception_message(ex: BaseException) -> str:
    return getattr(ex, "message", repr(ex))
