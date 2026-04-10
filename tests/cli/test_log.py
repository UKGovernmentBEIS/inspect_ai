import pytest

from inspect_ai._cli.log import _TS_MONO_APP, view_type_resource

_submodule_missing = not (_TS_MONO_APP / "src").exists()


@pytest.mark.skipif(_submodule_missing, reason="ts-mono submodule not initialized")
def test_view_type_resource():
    ts_types = view_type_resource("generated.ts")
    assert isinstance(ts_types, str)
    assert "auto-generated" in ts_types
