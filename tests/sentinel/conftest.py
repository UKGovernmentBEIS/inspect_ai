import sys
from collections.abc import Iterator

import pytest
from test_helpers import fake_sentinel as fake

import inspect_ai._sentinel


@pytest.fixture
def fake_sentinel(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Install `test_helpers.fake_sentinel` as `inspect_sentinel` for the test."""
    monkeypatch.setitem(sys.modules, "inspect_sentinel", fake)
    monkeypatch.setitem(sys.modules, "inspect_sentinel._integration", fake)
    yield
    # _dispatch binds the fake's names when it is imported, so forget it: a
    # later import meets the block on inspect_sentinel again
    sys.modules.pop("inspect_ai._sentinel._dispatch", None)
    vars(inspect_ai._sentinel).pop("_dispatch", None)
