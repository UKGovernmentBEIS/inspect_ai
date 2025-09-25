import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest

from inspect_ai.log import read_eval_log, write_eval_log
from inspect_ai.scorer._metric import ProvenanceData, ScoreEdit


@pytest.fixture
def original_log():
    """Fixture to provide a starting log file."""
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    log = read_eval_log(log_file)
    log.location = None
    # Return a deep copy to avoid test pollution
    import copy

    return copy.deepcopy(log)


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
        new_log_path = temp_dir / f"new_log.{format}"
        write_eval_log(original_log, new_log_path, format=format)

        # Read the new log file
        new_log = read_eval_log(new_log_path, format=format)
        new_log.location = None

        # Compare the logs
        assert original_log.model_dump_json() == new_log.model_dump_json(), (
            f"Round-trip failed for {format} format"
        )


def test_eval_format_round_trip_overwrite(original_log, temp_dir):
    format = "eval"

    # Write it to a new file in the current format
    new_log_path = (temp_dir / f"new_log.{format}").as_posix()
    write_eval_log(original_log, new_log_path, format=format)

    # make a copy of the log file for later comparison
    copy_log_path = (temp_dir / f"new_log_copy.{format}").as_posix()
    shutil.copy(new_log_path, copy_log_path)

    # Overwrite the file
    write_eval_log(original_log, new_log_path, format=format)

    # ensure the zip file matches the original after overwriting
    assert compare_zip_contents(new_log_path, copy_log_path), (
        "EVAL zip file contents changed after rewriting file"
    )


def test_log_format_round_trip_cross(original_log, temp_dir):
    """Test round-trip consistency across formats."""
    # Write it to EVAL format
    eval_log_path = temp_dir / "cross_format.eval"
    write_eval_log(original_log, eval_log_path, format="eval")

    # Read the EVAL log
    eval_log = read_eval_log(eval_log_path, format="eval")
    eval_log.location = None

    # Write it back to JSON
    new_json_log_path = (temp_dir / "cross_format.json").as_posix()
    write_eval_log(eval_log, new_json_log_path, format="json")

    # Read the new JSON log
    new_json_log = read_eval_log(new_json_log_path, format="json")
    new_json_log.location = None

    # Compare the logs
    assert original_log.model_dump_json() == new_json_log.model_dump_json(), (
        "Cross-format round-trip failed"
    )


def test_log_format_equality(original_log, temp_dir):
    """Test that identical log files are created for both formats."""
    # Write it to both formats
    json_log_path = (temp_dir / "test_equality.json").as_posix()
    eval_log_path = (temp_dir / "test_equality.eval").as_posix()

    write_eval_log(original_log, json_log_path, format="json")
    write_eval_log(original_log, eval_log_path, format="eval")

    # Read both logs back
    json_log = read_eval_log(json_log_path, format="json")
    json_log.location = None
    eval_log = read_eval_log(eval_log_path, format="eval")
    eval_log.location = None

    # Compare the logs
    assert json_log.model_dump_json() == eval_log.model_dump_json(), (
        "Logs in different formats are not identical"
    )


def test_log_format_detection(original_log, temp_dir):
    """Test that auto format detection works correctly."""
    # Write it to both formats
    json_log_path = temp_dir / "auto_test.json"
    eval_log_path = temp_dir / "auto_test.eval"

    write_eval_log(original_log, json_log_path, format="auto")
    write_eval_log(original_log, eval_log_path, format="auto")

    # Read both logs back using auto format
    json_log = read_eval_log(json_log_path, format="auto")
    json_log.location = None
    eval_log = read_eval_log(eval_log_path, format="auto")
    eval_log.location = None

    # Compare the logs
    assert json_log.model_dump_json() == eval_log.model_dump_json(), (
        "Auto format detection failed"
    )


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
    assert compare_zip_contents(eval_log_path, new_eval_log_path), (
        "EVAL zip file contents changed after round trip"
    )


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
    new_json_log.location = None

    # Compare the original and new JSON logs
    assert original_log.model_dump_json() == new_json_log.model_dump_json(), (
        "JSON content changed after roundtrip through EVAL format"
    )


@pytest.mark.parametrize("format", ["json", "eval"])
def test_score_editing_round_trip(original_log, temp_dir, format):
    """Test that logs with edited scores survive round-trip."""
    # First, add some score edits to the log
    if original_log.samples and len(original_log.samples) > 0:
        sample = original_log.samples[0]
        if sample.scores:
            score_name = list(sample.scores.keys())[0]
            score = sample.scores[score_name]

            provenance = ProvenanceData(author="test_user", reason="Test edit")
            edit = ScoreEdit(value="edited_value", provenance=provenance)
            score.history.append(edit)

    log_path = temp_dir / f"edited_log.{format}"
    write_eval_log(original_log, log_path, format=format)

    new_log = read_eval_log(log_path, format=format)
    new_log.location = None

    # Check that the edit survived
    if new_log.samples and len(new_log.samples) > 0:
        new_sample = new_log.samples[0]
        if new_sample.scores:
            new_score_name = list(new_sample.scores.keys())[0]
            new_score = new_sample.scores[new_score_name]

            assert len(new_score.history) > 1
            assert new_score.value == "edited_value"

            edit_with_provenance = next(
                (h for h in new_score.history if h.provenance is not None), None
            )

            assert edit_with_provenance is not None
            assert edit_with_provenance.provenance.author == "test_user"


@pytest.mark.parametrize("format", ["json", "eval"])
def test_mixed_scores_round_trip(original_log, temp_dir, format):
    """Test logs with both legacy and edited scores."""
    # Add edits to some scores but not others
    if original_log.samples and len(original_log.samples) > 1:
        sample1 = original_log.samples[0]
        if sample1.scores:
            score = next(sample1.scores.values())
            edit = ScoreEdit(value="edited")
            score.history.append(edit)

    log_path = temp_dir / f"mixed_log.{format}"
    write_eval_log(original_log, log_path, format=format)

    new_log = read_eval_log(log_path, format=format)
    new_log.location = None

    assert original_log.model_dump_json() == new_log.model_dump_json()


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
