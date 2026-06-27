import io

from inspect_ai.log._recorders.json import _scan_header_keys


def test_scan_header_keys_stops_at_last_header_field_not_samples():
    """Pass 1 must report the last *header* field, never `samples` itself.

    ijson emits the top-level `samples` key as a `map_key` event *before* its
    `start_array` event, so the scan loop records `last_header_field = "samples"`
    before it breaks. Pass 2 then can't stop until it has materialized the entire
    `samples` array. For this payload the last header field is `status`.
    """
    payload = b'{"version": 2, "status": "success", "samples": [{"id": 1}]}'

    version, last_header_field = _scan_header_keys(io.BytesIO(payload))

    assert version == 2
    assert last_header_field == "status"
