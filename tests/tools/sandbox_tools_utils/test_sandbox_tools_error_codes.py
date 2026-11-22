import importlib.util
from pathlib import Path

from inspect_ai.tool._sandbox_tools_utils._error_mapper import ServerErrorCode

REPO = Path(__file__).parents[3]
GUEST_COMMON_TYPES = (
    REPO
    / "src"
    / "inspect_sandbox_tools"
    / "src"
    / "inspect_sandbox_tools"
    / "_util"
    / "common_types.py"
)


def test_host_and_tools_server_define_the_same_error_codes() -> None:
    # The injected package is not installed in the host environment, so load
    # its module from source; it imports only the standard library.
    spec = importlib.util.spec_from_file_location(
        "guest_common_types", GUEST_COMMON_TYPES
    )
    assert spec is not None and spec.loader is not None
    guest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guest)

    assert {code.name: code.value for code in guest.ServerErrorCode} == {
        code.name: code.value for code in ServerErrorCode
    }
