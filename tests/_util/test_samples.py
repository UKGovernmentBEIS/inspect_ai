import pytest

from inspect_ai._util.samples import parse_samples_limit


def test_parse_samples_limit_single():
    assert parse_samples_limit("10") == 10


def test_parse_samples_limit_range():
    assert parse_samples_limit("5-10") == (4, 10)


def test_parse_samples_limit_none():
    assert parse_samples_limit(None) is None


def test_parse_samples_limit_rejects_extra_dash():
    # "5-10-15" used to silently drop the trailing "15" and return (4, 10).
    with pytest.raises(ValueError, match="Invalid sample limit"):
        parse_samples_limit("5-10-15")
