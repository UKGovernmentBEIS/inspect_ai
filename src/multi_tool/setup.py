import os
from setuptools import setup, find_namespace_packages

# Read requirements from container/pyproject.toml if it exists
requirements = []
try:
    import tomli
    with open(os.path.join("container", "pyproject.toml"), "rb") as f:
        pyproject = tomli.load(f)
        requirements = pyproject.get("project", {}).get("dependencies", [])
except (ImportError, FileNotFoundError):
    pass

setup(
    name="inspect-multi-tool",
    version="0.1.0",
    description="Multi-tool container for inspect_ai",
    package_dir={
        'inspect_multi_tool': '.',
        'inspect_multi_tool.container': 'container',
        'inspect_multi_tool.container._in_process_tools': 'container/_in_process_tools',
        'inspect_multi_tool.container._remote_tools': 'container/_remote_tools',
        'inspect_multi_tool.container._util': 'container/_util',
        'inspect_multi_tool.web_browser_back_compat': 'web_browser_back_compat',
    },
    packages=find_namespace_packages(include=['inspect_multi_tool', 'inspect_multi_tool.*']),
    install_requires=requirements + [
        "aiohttp",
        "jsonrpcserver",
    ],
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "multi-tool=inspect_multi_tool.container.multi_tool_v1:main",
            "multi-tool-server=inspect_multi_tool.container.server:main",
        ],
    },
    data_files=[
        # These directories will be created by the install_script.py
    ],
    scripts=['install_script.py', 'install_service.py'],
    include_package_data=True,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
)