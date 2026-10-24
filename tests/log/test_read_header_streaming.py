import io
from pathlib import Path
from typing import Any

import pytest

from inspect_ai.log import read_eval_log, write_eval_log
from inspect_ai.log._recorders import json as json_recorder
from inspect_ai.log._recorders.json import _scan_header_keys
from inspect_ai.util._early_stopping import EarlyStoppingSummary


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


def test_json_header_only_reads_floats_as_float(tmp_path: Path) -> None:
    """Floats in untyped header fields must not come back as ``Decimal``.

    A ``Decimal`` is written back as a JSON string by anything that rewrites
    the header, and fails validation in ``JsonValue`` fields.
    """
    log = read_eval_log("tests/log/test_eval_log/log_formats.json")
    log.eval.metadata = {"run": 0.25}
    assert log.results
    log.results.early_stopping = EarlyStoppingSummary(
        manager="test", early_stops=[], metadata={"confidence": 0.95}
    )
    log_file = (tmp_path / "log.json").as_posix()
    write_eval_log(log, log_file)

    header = read_eval_log(log_file, header_only=True)

    assert header.eval.metadata == {"run": 0.25}
    assert type(header.eval.metadata["run"]) is float
    assert header.results and header.results.early_stopping
    assert header.results.early_stopping.metadata == {"confidence": 0.95}


@pytest.mark.parametrize(
    "literal,expected",
    [("18446744073709551615", 2**64 - 1), ("1e309", float("inf"))],
)
def test_json_header_only_streams_numbers_ijson_overflows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, literal: str, expected: Any
) -> None:
    """Numbers beyond int64 or a double are read without parsing the samples.

    Python never writes ``1e309`` (it writes ``Infinity``), but it is valid JSON.
    """
    log = read_eval_log("tests/log/test_eval_log/log_formats.json")
    log.eval.metadata = {"big": 0, "nested": {"x": 0.25, "xs": [0.5]}}
    log_file = tmp_path / "log.json"
    write_eval_log(log, log_file.as_posix())
    log_file.write_text(
        log_file.read_text().replace('"big": 0', f'"big": {literal}', 1)
    )

    def full_parse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("header-only read parsed the whole log")

    monkeypatch.setattr(json_recorder, "_parse_json_log", full_parse)
    header = read_eval_log(log_file.as_posix(), header_only=True)

    assert header.samples is None
    nested = {"x": 0.25, "xs": [0.5]}
    assert header.eval.metadata == {"big": expected, "nested": nested}
    assert type(header.eval.metadata["nested"]["x"]) is float
    assert type(header.eval.metadata["nested"]["xs"][0]) is float
