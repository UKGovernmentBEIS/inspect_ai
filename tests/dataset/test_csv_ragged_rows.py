"""A CSV row whose field count differs from the header is malformed.

It used to reach the empty-row filter and die there on AttributeError, naming
neither the file nor the row. These check that it now says what is wrong, where.
"""

from pathlib import Path

import pytest

from inspect_ai.dataset import csv_dataset


def write_csv(tmp_path: Path, body: str) -> str:
    path = tmp_path / "data.csv"
    path.write_text(body, newline="")
    return str(path)


def test_short_blank_row_names_the_row(tmp_path: Path) -> None:
    # the case from the report: 2 fields under a 3 column header
    csv_file = write_csv(tmp_path, "input,target,id\n2+2,4,q1\n,\n3+3,6,q2\n")

    with pytest.raises(ValueError) as info:
        csv_dataset(csv_file)

    message = str(info.value)
    assert "row 3" in message
    assert "2 fields, the header has 3" in message
    assert "id" in message


def test_long_row_names_the_row(tmp_path: Path) -> None:
    csv_file = write_csv(tmp_path, "input,target\n2+2,4\n,,extra\n")

    with pytest.raises(ValueError) as info:
        csv_dataset(csv_file)

    message = str(info.value)
    assert "row 3" in message
    assert "3 fields, the header has 2" in message
    assert "extra" in message


def test_short_row_with_content_is_not_silently_truncated(tmp_path: Path) -> None:
    # this one used to load, dropping the missing column as None
    csv_file = write_csv(tmp_path, "input,target,id\n2+2,4\n")

    with pytest.raises(ValueError, match="No value for: id"):
        csv_dataset(csv_file)


def test_long_row_with_content_is_not_silently_absorbed(tmp_path: Path) -> None:
    # this one used to load too, with the extras swallowed by the restkey
    csv_file = write_csv(tmp_path, "input,target\n2+2,4\n3+3,6,extra\n")

    with pytest.raises(ValueError, match="Unexpected values"):
        csv_dataset(csv_file)


def test_singular_field_count_reads_correctly(tmp_path: Path) -> None:
    csv_file = write_csv(tmp_path, "a,b,c,d\n1,2,3,4\nz\n")

    with pytest.raises(ValueError, match="has 1 field, the header has 4"):
        csv_dataset(csv_file)


def test_row_number_accounts_for_explicit_fieldnames(tmp_path: Path) -> None:
    # with fieldnames given there is no header line, so data starts at row 1
    csv_file = write_csv(tmp_path, "2+2,4,q1\n,\n")

    with pytest.raises(ValueError) as info:
        csv_dataset(csv_file, fieldnames=["input", "target", "id"])

    assert "row 2" in str(info.value)


def test_well_formed_blank_row_is_still_skipped(tmp_path: Path) -> None:
    # all columns present and blank: the filter's actual job, must not raise
    csv_file = write_csv(tmp_path, "input,target\n2+2,4\n,\n3+3,6\n")

    dataset = csv_dataset(csv_file)

    assert len(dataset) == 2
    assert [sample.input for sample in dataset] == ["2+2", "3+3"]


def test_well_formed_file_is_unaffected(tmp_path: Path) -> None:
    csv_file = write_csv(tmp_path, "input,target\n2+2,4\n3+3,6\n")

    dataset = csv_dataset(csv_file)

    assert len(dataset) == 2
