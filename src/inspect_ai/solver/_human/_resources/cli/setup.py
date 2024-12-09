from setuptools import setup

setup(
    name="human_cli",
    version="0.1.0",
    py_modules=["commands"],
    entry_points={
        "console_scripts": [
            "start=commands:start",
        ],
    },
)
