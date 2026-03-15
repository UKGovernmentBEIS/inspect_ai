from inspect_ai._util.url import location_query_param, location_without_query


def test_location_without_query_with_params():
    location = "s3://bucket/file.eval?versionId=abc123"
    assert location_without_query(location) == "s3://bucket/file.eval"


def test_location_without_query_without_params():
    location = "s3://bucket/file.eval"
    assert location_without_query(location) == "s3://bucket/file.eval"


def test_location_query_param_found():
    location = "s3://bucket/file.eval?versionId=abc123"
    assert location_query_param(location, "versionId") == "abc123"


def test_location_query_param_not_found():
    location = "s3://bucket/file.eval"
    assert location_query_param(location, "versionId") is None
