import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest

from inspect_ai.log import read_eval_log, write_eval_log
from inspect_ai.log._edit import ProvenanceData, TagsEdit, edit_eval_log
from inspect_ai.scorer._metric import ScoreEdit


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
        assert original_log.model_dump() == new_log.model_dump(), (
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
    assert original_log.model_dump() == new_json_log.model_dump(), (
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
    assert json_log.model_dump() == eval_log.model_dump(), (
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
    assert json_log.model_dump() == eval_log.model_dump(), (
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
    assert original_log.model_dump() == new_json_log.model_dump(), (
        "JSON content changed after roundtrip through EVAL format"
    )


@pytest.mark.parametrize("format", ["json", "eval"])
def test_score_editing_round_trip(original_log, temp_dir, format):
    """Test that logs with edited scores survive round-trip."""
    from inspect_ai.log._score import edit_score

    if original_log.samples and len(original_log.samples) > 0:
        sample = original_log.samples[0]
        if sample.scores:
            score_name = list(sample.scores.keys())[0]
            provenance = ProvenanceData(author="test_user", reason="Test edit")
            edit = ScoreEdit(value="edited_value", provenance=provenance)
            edit_score(
                original_log, sample.id, score_name, edit, recompute_metrics=False
            )

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

            assert new_score.value == "edited_value"
            assert len(new_score.history) == 2  # original + edit
            assert new_score.history[0].provenance is None  # original has no provenance
            assert new_score.history[1].provenance.author == "test_user"


def test_write_header_only_preserves_samples(original_log, temp_dir):
    """Test that header_only write appends the header without losing samples."""
    eval_log_path = (temp_dir / "test.eval").as_posix()

    # Write the full log (with samples)
    write_eval_log(original_log, eval_log_path, format="eval")

    # Read just the header, add a tag, and write header_only
    header = read_eval_log(eval_log_path, header_only=True)
    header = edit_eval_log(
        header,
        [TagsEdit(tags_add=["new_tag"])],
        ProvenanceData(author="test", reason="test header_only"),
    )
    write_eval_log(header, eval_log_path, format="eval", header_only=True)

    # Read back the full log and verify header was updated
    restored = read_eval_log(eval_log_path)
    assert "new_tag" in restored.tags
    assert restored.log_updates is not None
    assert len(restored.log_updates) == 1
    assert restored.log_updates[0].provenance.author == "test"

    # Verify samples are still intact
    assert restored.samples is not None
    assert len(restored.samples) == len(original_log.samples)
    for orig, rest in zip(original_log.samples, restored.samples):
        assert orig.id == rest.id
        assert orig.epoch == rest.epoch


def test_write_header_only_with_file_uri(original_log, temp_dir):
    """Test that header_only write works when location is a file:/// URI."""
    eval_log_path = (temp_dir / "test.eval").as_posix()

    # Write the full log
    write_eval_log(original_log, eval_log_path, format="eval")

    # Read the log — this sets log.location to a file:/// URI
    header = read_eval_log(eval_log_path, header_only=True)
    file_uri = f"file://{eval_log_path}"
    header.location = file_uri

    # Edit and write header_only using the file:/// URI as location
    header = edit_eval_log(
        header,
        [TagsEdit(tags_add=["uri_tag"])],
        ProvenanceData(author="test", reason="test file URI"),
    )
    write_eval_log(header, header.location, format="eval", header_only=True)

    # Verify the update and samples survived
    restored = read_eval_log(eval_log_path)
    assert "uri_tag" in restored.tags
    assert restored.samples is not None
    assert len(restored.samples) == len(original_log.samples)


def test_write_json_header_only_no_samples(original_log, temp_dir):
    """Writing a JSON log whose EvalLog carries only a header must succeed.

    Build a header-only EvalLog (samples=None) and write it as JSON, then
    read it back. The on-disk file must be parseable and round-trip with
    samples still None — no spurious empty list, no exception on write.
    """
    header_only_log = original_log.model_copy(update={"samples": None})

    json_log_path = (temp_dir / "header_only_fresh.json").as_posix()
    write_eval_log(header_only_log, json_log_path, format="json")

    restored = read_eval_log(json_log_path, format="json")
    assert restored.samples is None
    assert restored.eval.task == original_log.eval.task
    assert restored.status == original_log.status


def test_write_json_header_only_to_new_file_drops_samples(original_log, temp_dir):
    """A header_only write to a new JSON file must not persist in-memory samples.

    If the caller passes `header_only=True`, the resulting file should contain
    only the header — sample data carried on the in-memory EvalLog must be
    dropped, not serialized. Today JSONRecorder.write_log ignores `header_only`
    and writes the full object, so the new file would contain every sample.
    """
    assert original_log.samples is not None and len(original_log.samples) > 0

    json_log_path = (temp_dir / "json_header_only_new.json").as_posix()
    write_eval_log(original_log, json_log_path, format="json", header_only=True)

    restored = read_eval_log(json_log_path, format="json")
    assert restored.samples is None, (
        "header_only write to a new JSON file wrote samples to disk"
    )
    # Sanity: the rest of the header is still there.
    assert restored.eval.task == original_log.eval.task
    assert restored.status == original_log.status


def test_write_json_header_only_preserves_samples(original_log, temp_dir):
    """JSON regression: header_only write must not erase existing samples.

    Reproduces the destructive chain reported on PR #4014:
      1. Write a full JSON log with samples.
      2. Read it with header_only=True (samples becomes None on the in-memory log).
      3. Write that header-only log back with header_only=True.
      4. Re-read the file in full.

    The samples on disk must be untouched. Today JSONRecorder.write_log ignores
    `header_only` and serializes the (sample-less) in-memory object, erasing
    the samples on disk.
    """
    json_log_path = (temp_dir / "json_header_only.json").as_posix()

    write_eval_log(original_log, json_log_path, format="json")
    assert original_log.samples is not None and len(original_log.samples) > 0
    original_sample_count = len(original_log.samples)

    header = read_eval_log(json_log_path, header_only=True, format="json")
    assert header.samples is None

    header = edit_eval_log(
        header,
        [TagsEdit(tags_add=["json_header_only_tag"])],
        ProvenanceData(author="test", reason="test json header_only"),
    )
    write_eval_log(header, json_log_path, format="json", header_only=True)

    restored = read_eval_log(json_log_path, format="json")
    assert "json_header_only_tag" in restored.tags
    assert restored.samples is not None, "header_only write erased samples on disk"
    assert len(restored.samples) == original_sample_count
    for orig, rest in zip(original_log.samples, restored.samples):
        assert orig.id == rest.id
        assert orig.epoch == rest.epoch


@pytest.mark.parametrize("format", ["json", "eval"])
def test_write_header_only_ignores_in_memory_sample_changes(
    original_log, temp_dir, format
):
    """header_only writes must use on-disk samples, not the in-memory log's.

    Contract guard for the JSON read-modify-write fix and the .eval in-place
    header swap: if a caller mutates `log.samples` in memory before a
    header_only write, those mutations must NOT leak to disk. Only a
    subsequent header_only=False write should persist sample changes.

    The risk is a "helpful" fix that grabs samples off the in-memory object
    when they're present (instead of from disk), silently honoring caller
    mutations that the header_only contract says to discard.
    """
    assert original_log.samples is not None and len(original_log.samples) > 0
    original_input = original_log.samples[0].input

    log_path = (temp_dir / f"in_memory_mutation.{format}").as_posix()
    write_eval_log(original_log, log_path, format=format)

    # Read back as a full log (so samples are loaded), then mutate both the
    # header (via edit_eval_log) and the in-memory samples.
    log = read_eval_log(log_path, format=format)
    log = edit_eval_log(
        log,
        [TagsEdit(tags_add=["mutation_tag"])],
        ProvenanceData(author="test", reason="mutation guard"),
    )
    sentinel = "MUTATED IN MEMORY — must not reach disk on header_only write"
    log.samples[0].input = sentinel

    # header_only write: header lands on disk, sample mutation does NOT.
    write_eval_log(log, log_path, format=format, header_only=True)

    after_header_only = read_eval_log(log_path, format=format)
    assert "mutation_tag" in after_header_only.tags
    assert after_header_only.samples is not None
    assert len(after_header_only.samples) == len(original_log.samples)
    assert after_header_only.samples[0].input == original_input, (
        "header_only write leaked in-memory sample mutation to disk"
    )

    # full write of the same in-memory log: sample mutation now lands.
    write_eval_log(log, log_path, format=format, header_only=False)

    after_full = read_eval_log(log_path, format=format)
    assert "mutation_tag" in after_full.tags
    assert after_full.samples is not None
    assert after_full.samples[0].input == sentinel


def test_write_s3_eval_header_only_ignores_in_memory_sample_changes(
    original_log, mock_s3
):
    """Same in-memory-mutation guard as the local-format test, but on S3 .eval.

    The S3 fix (download → in-place header swap → upload) must read samples
    from the downloaded copy, not from the in-memory log handed in.
    """
    assert original_log.samples is not None and len(original_log.samples) > 0
    original_input = original_log.samples[0].input

    log_path = "s3://test-bucket/s3_in_memory_mutation.eval"
    write_eval_log(original_log, log_path, format="eval")

    log = read_eval_log(log_path, format="eval")
    log = edit_eval_log(
        log,
        [TagsEdit(tags_add=["s3_mutation_tag"])],
        ProvenanceData(author="test", reason="s3 mutation guard"),
    )
    sentinel = "MUTATED IN MEMORY (S3) — must not reach disk on header_only write"
    log.samples[0].input = sentinel

    write_eval_log(
        log, log_path, format="eval", header_only=True, if_match_etag=log.etag
    )

    after_header_only = read_eval_log(log_path, format="eval")
    assert "s3_mutation_tag" in after_header_only.tags
    assert after_header_only.samples is not None
    assert len(after_header_only.samples) == len(original_log.samples)
    assert after_header_only.samples[0].input == original_input, (
        "S3 header_only write leaked in-memory sample mutation to disk"
    )

    # full write should persist the in-memory sample mutation.
    write_eval_log(
        log,
        log_path,
        format="eval",
        header_only=False,
        if_match_etag=after_header_only.etag,
    )

    after_full = read_eval_log(log_path, format="eval")
    assert "s3_mutation_tag" in after_full.tags
    assert after_full.samples is not None
    assert after_full.samples[0].input == sentinel


def test_write_s3_eval_header_only_compacts_zip(original_log, mock_s3):
    """S3 header_only write must compact the .eval zip, not leave dead bytes.

    The local in-place trick uses `ZipFile(..., "a")` which removes the old
    `header.json` from the central directory but leaves its compressed bytes
    in the file. That's a tolerable size leak locally. On S3 we re-upload
    the whole object on every edit, so dead bytes accumulate across the
    network — the rewrite there should produce a compact zip with no
    orphan data.

    The test compares the post-edit file size to a baseline written from
    scratch with the same final state. They should match within a small
    tolerance (zip timestamps / entry ordering).
    """
    from inspect_ai._util.file import filesystem

    edits = [TagsEdit(tags_add=["compact_tag"])]
    provenance = ProvenanceData(author="test", reason="compaction test")

    # Baseline: write the final log state directly.
    baseline_path = "s3://test-bucket/compact_baseline.eval"
    baseline_log = edit_eval_log(original_log, edits, provenance)
    write_eval_log(baseline_log, baseline_path, format="eval")
    fs = filesystem(baseline_path)
    baseline_size = fs.info(baseline_path).size

    # Test: write original, header_only-swap to the same final state.
    test_path = "s3://test-bucket/compact_test.eval"
    write_eval_log(original_log, test_path, format="eval")
    header = read_eval_log(test_path, header_only=True, format="eval")
    header = edit_eval_log(header, edits, provenance)
    write_eval_log(
        header, test_path, format="eval", header_only=True, if_match_etag=header.etag
    )
    test_size = fs.info(test_path).size

    # Allow a small tolerance for zip metadata jitter; the test fixture's
    # header is ~1.5KB compressed, so any dead-header leak will easily
    # exceed this threshold.
    growth = test_size - baseline_size
    assert growth < 256, (
        f"after header_only edit on S3, file is {growth} bytes larger "
        f"than the from-scratch baseline ({test_size} vs {baseline_size}) "
        f"— old header.json bytes are likely retained as dead data"
    )


def test_write_s3_eval_header_only_preserves_samples(original_log, mock_s3):
    """S3 .eval regression: header_only write must not erase existing samples.

    Same destructive chain as the JSON case, but on S3 with an `If-Match`
    ETag. The S3 conditional write path in EvalRecorder ignores `header_only`
    and rewrites the object from the in-memory header-only EvalLog, writing
    `log.samples or []` (= zero samples) into the new object.
    """
    log_path = "s3://test-bucket/s3_eval_header_only.eval"

    write_eval_log(original_log, log_path, format="eval")
    assert original_log.samples is not None and len(original_log.samples) > 0
    original_sample_count = len(original_log.samples)

    header = read_eval_log(log_path, header_only=True, format="eval")
    assert header.samples is None
    assert header.etag is not None, (
        "S3 header_only read should return an ETag for conditional write"
    )

    header = edit_eval_log(
        header,
        [TagsEdit(tags_add=["s3_header_only_tag"])],
        ProvenanceData(author="test", reason="test s3 eval header_only"),
    )
    write_eval_log(
        header,
        log_path,
        format="eval",
        header_only=True,
        if_match_etag=header.etag,
    )

    restored = read_eval_log(log_path, format="eval")
    assert "s3_header_only_tag" in restored.tags
    assert restored.samples is not None, "header_only S3 write erased samples on disk"
    assert len(restored.samples) == original_sample_count
    for orig, rest in zip(original_log.samples, restored.samples):
        assert orig.id == rest.id
        assert orig.epoch == rest.epoch


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
