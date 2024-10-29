import json
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

from inspect_ai.log import read_eval_log, write_eval_log


@pytest.fixture
def original_log():
    """Fixture to provide a starting log file."""
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    return read_eval_log(log_file)


@pytest.fixture
def temp_dir():
    """Fixture to create a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


def test_log_format_round_trip_single(original_log, temp_dir):
    """Test round-trip consistency within the same format."""
    formats = ["json", "eval"]

    for format in formats:
        # Write it to a new file in the current format
        new_log_path = (temp_dir / f"new_log.{format}").as_posix()
        write_eval_log(original_log, new_log_path, format=format)

        # Read the new log file
        new_log = read_eval_log(new_log_path, format=format)

        # Compare the logs
        assert original_log == new_log, f"Round-trip failed for {format} format"


def test_log_format_round_trip_cross(original_log, temp_dir):
    """Test round-trip consistency across formats."""
    # Write it to EVAL format
    eval_log_path = (temp_dir / "cross_format.eval").as_posix()
    write_eval_log(original_log, eval_log_path, format="eval")

    # Read the EVAL log
    eval_log = read_eval_log(eval_log_path, format="eval")

    # Write it back to JSON
    new_json_log_path = (temp_dir / "cross_format.json").as_posix()
    write_eval_log(eval_log, new_json_log_path, format="json")

    # Read the new JSON log
    new_json_log = read_eval_log(new_json_log_path, format="json")

    # Compare the logs
    assert original_log == new_json_log, "Cross-format round-trip failed"


def test_log_format_equality(original_log, temp_dir):
    """Test that identical log files are created for both formats."""
    # Write it to both formats
    json_log_path = (temp_dir / "test_equality.json").as_posix()
    eval_log_path = (temp_dir / "test_equality.eval").as_posix()

    write_eval_log(original_log, json_log_path, format="json")
    write_eval_log(original_log, eval_log_path, format="eval")

    # Read both logs back
    json_log = read_eval_log(json_log_path, format="json")
    eval_log = read_eval_log(eval_log_path, format="eval")

    # Compare the logs
    assert json_log == eval_log, "Logs in different formats are not identical"


def test_log_format_detection(original_log, temp_dir):
    """Test that auto format detection works correctly."""
    # Write it to both formats
    json_log_path = (temp_dir / "auto_test.json").as_posix()
    eval_log_path = (temp_dir / "auto_test.eval").as_posix()

    write_eval_log(original_log, json_log_path, format="auto")
    write_eval_log(original_log, eval_log_path, format="auto")

    # Read both logs back using auto format
    json_log = read_eval_log(json_log_path, format="auto")
    eval_log = read_eval_log(eval_log_path, format="auto")

    # Compare the logs
    assert json_log == eval_log, "Auto format detection failed"


def test_log_format_eval_zip_structure(original_log, temp_dir):
    """Test that the .eval zip file structure is preserved across round trips."""
    # Write it to EVAL format
    eval_log_path = (temp_dir / "test.eval").as_posix()
    write_eval_log(original_log, eval_log_path, format="eval")

    # Read the EVAL log and write it back to a new EVAL file
    eval_log = read_eval_log(eval_log_path, format="eval")
    new_eval_log_path = (temp_dir / "test_new.eval").as_posix()
    write_eval_log(eval_log, new_eval_log_path, format="eval")

    # Compare the two EVAL files
    assert compare_zip_contents(
        eval_log_path, new_eval_log_path
    ), "EVAL zip file contents changed after round trip"


def test_log_format_eval_zip_json_integrity(original_log, temp_dir):
    """Test that JSON files within the .eval zip remain intact and parseable."""
    # Write it to EVAL format
    eval_log_path = (temp_dir / "test.eval").as_posix()
    write_eval_log(original_log, eval_log_path, format="eval")

    with zipfile.ZipFile(eval_log_path, "r") as zip_file:
        for file_name in zip_file.namelist():
            if file_name.endswith(".json"):
                with zip_file.open(file_name) as json_file:
                    content = json_file.read().decode("utf-8")
                    try:
                        json.loads(content)
                    except json.JSONDecodeError:
                        pytest.fail(f"Invalid JSON in {file_name} within EVAL zip")


def test_log_format_eval_zip_roundtrip(original_log, temp_dir):
    """Test that JSON content is preserved when roundtripping through EVAL format."""
    # Write it to EVAL format
    eval_log_path = (temp_dir / "test.eval").as_posix()
    write_eval_log(original_log, eval_log_path, format="eval")

    # Read the EVAL log and write it back to JSON
    eval_log = read_eval_log(eval_log_path, format="eval")
    new_json_log_path = (temp_dir / "test_new.json").as_posix()
    write_eval_log(eval_log, new_json_log_path, format="json")

    # Read the new JSON log
    new_json_log = read_eval_log(new_json_log_path, format="json")

    # Compare the original and new JSON logs
    assert (
        original_log == new_json_log
    ), "JSON content changed after roundtrip through EVAL format"


def compare_zip_contents(zip_file1: Path, zip_file2: Path) -> bool:
    """Compare the contents of two zip files."""
    with (
        zipfile.ZipFile(zip_file1, "r") as zip1,
        zipfile.ZipFile(zip_file2, "r") as zip2,
    ):
        if zip1.namelist() != zip2.namelist():
            return False

        for file_name in zip1.namelist():
            with zip1.open(file_name) as file1, zip2.open(file_name) as file2:
                if file1.read() != file2.read():
                    return False

    return True
