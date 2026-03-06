from inspect_ai._util.error import pip_dependency_error


def verify_fastapi_prerequisites() -> None:
    # ensure we have all of the optional packages we need
    required_packages: list[str] = []
    try:
        import fastapi  # noqa: F401
    except ImportError:
        required_packages.append("fastapi")
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        required_packages.append("uvicorn")

    if len(required_packages) > 0:
        raise pip_dependency_error("inspect_ai._view.fastapi_server", required_packages)
