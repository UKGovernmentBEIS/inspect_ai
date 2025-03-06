import os
from setuptools import setup, find_namespace_packages

# Define dependencies directly
requirements = [
    "aiohttp",
    "jsonrpcserver",
    "pydantic",
    "tomli",
    "playwright",  # For web browser functionality
]

setup(
    name="inspect-multi-tool",
    version="0.1.0",
    description="Multi-tool container for inspect_ai",
    package_dir={
        'inspect_multi_tool': '.',
        'inspect_multi_tool._in_process_tools': '_in_process_tools',
        'inspect_multi_tool._remote_tools': '_remote_tools',
        'inspect_multi_tool._util': '_util',
        'inspect_multi_tool.back_compat': 'back_compat',
    },
    packages=find_namespace_packages(include=['inspect_multi_tool', 'inspect_multi_tool.*']),
    install_requires=requirements,
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "multi-tool=inspect_multi_tool.multi_tool_v1:main",
            "multi-tool-server=inspect_multi_tool.server:main",
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