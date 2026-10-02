import json
import subprocess
import sys
import textwrap

import pytest

WIRE_TYPE_MODULES = [
    "inspect_ai.model._chat_message",
    "inspect_ai._util.content",
    "inspect_ai.tool._tool_call",
    "inspect_ai.tool._tool_info",
    "inspect_ai.tool._tool_choice",
    "inspect_ai.model._model_output",
    "inspect_ai.model._generate_config",
]

# pydantic brings annotated_types and typing_inspection with it.
ALLOWED_THIRD_PARTY = {
    "pydantic",
    "pydantic_core",
    "annotated_types",
    "typing_inspection",
    "typing_extensions",
    "shortuuid",
}

# Replace every inspect_ai package with an empty module that only has
# `__path__`, so no `__init__.py` runs (as if these modules lived in a
# package of their own), then import the wire types and report which
# third-party packages loaded.
PROBE = textwrap.dedent(
    """
    import importlib, importlib.util, json, sys, types
    from pathlib import Path

    before = set(sys.modules)
    root = Path(importlib.util.find_spec("inspect_ai").origin).parent
    for init in root.rglob("__init__.py"):
        name = ".".join(("inspect_ai", *init.parent.relative_to(root).parts))
        stub = types.ModuleType(name)
        stub.__path__ = [str(init.parent)]
        sys.modules[name] = stub

    for module in json.loads(sys.argv[1]):
        importlib.import_module(module)

    loaded = {m.split(".")[0] for m in set(sys.modules) - before if not m.startswith("_")}
    print(json.dumps(sorted(loaded - set(sys.stdlib_module_names) - {"inspect_ai"})))
    """
)


def test_wire_types_import_without_the_rest_of_inspect_ai() -> None:
    result = subprocess.run(
        [sys.executable, "-c", PROBE, json.dumps(WIRE_TYPE_MODULES)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(result.stderr, pytrace=False)
    extra = sorted(set(json.loads(result.stdout)) - ALLOWED_THIRD_PARTY)
    assert not extra, f"unexpected third-party imports: {', '.join(extra)}"
