import json
import zipfile

import pytest

from inspect_ai.log import read_eval_log, write_eval_log
from inspect_ai.log._edit import (
    MetadataEdit,
    ProvenanceData,
    TagsEdit,
    edit_eval_log,
)
from inspect_ai.log._log import EvalConfig, EvalDataset, EvalLog, EvalSpec


def _make_log(
    tags: list[str] | None = None,
    metadata: dict | None = None,
) -> EvalLog:
    return EvalLog(
        version=2,
        eval=EvalSpec(
            eval_id="test_eval",
            run_id="test_run",
            created="2025-01-01T00:00:00Z",
            task="test_task",
            task_id="test_task_id",
            dataset=EvalDataset(),
            model="test_model",
            config=EvalConfig(),
            tags=tags,
            metadata=metadata,
        ),
    )


def _provenance(**kwargs: str) -> ProvenanceData:
    return ProvenanceData(
        author=kwargs.get("author", "test"), reason=kwargs.get("reason")
    )


class TestReadAPI:
    """Test that tags/metadata properties work correctly."""

    def test_no_updates_returns_eval_values(self) -> None:
        log = _make_log(tags=["a", "b"], metadata={"key": "val"})
        assert log.tags == ["a", "b"]
        assert log.metadata == {"key": "val"}

    def test_no_tags_or_metadata_returns_empty(self) -> None:
        log = _make_log()
        assert log.tags == []
        assert log.metadata == {}

    def test_tags_are_sorted(self) -> None:
        log = _make_log(tags=["c", "a", "b"])
        assert log.tags == ["a", "b", "c"]


class TestTagsEdit:
    """Test tag editing."""

    def test_add_tags(self) -> None:
        log = _make_log(tags=["a"])
        log = edit_eval_log(log, [TagsEdit(tags_add=["b", "c"])], _provenance())
        assert log.tags == ["a", "b", "c"]

    def test_remove_tags(self) -> None:
        log = _make_log(tags=["a", "b", "c"])
        log = edit_eval_log(log, [TagsEdit(tags_remove=["b"])], _provenance())
        assert log.tags == ["a", "c"]

    def test_add_and_remove_tags(self) -> None:
        log = _make_log(tags=["a", "b"])
        log = edit_eval_log(
            log,
            [TagsEdit(tags_add=["c"], tags_remove=["a"])],
            _provenance(),
        )
        assert log.tags == ["b", "c"]

    def test_add_existing_tag_is_noop(self) -> None:
        log = _make_log(tags=["a"])
        log = edit_eval_log(log, [TagsEdit(tags_add=["a"])], _provenance())
        assert log.tags == ["a"]
        assert log.log_updates is None

    def test_remove_nonexistent_tag_is_noop(self) -> None:
        log = _make_log(tags=["a"])
        log = edit_eval_log(log, [TagsEdit(tags_remove=["z"])], _provenance())
        assert log.tags == ["a"]
        assert log.log_updates is None

    def test_readd_previously_removed_tag(self) -> None:
        log = _make_log(tags=["a", "b"])
        log = edit_eval_log(log, [TagsEdit(tags_remove=["a"])], _provenance())
        log = edit_eval_log(log, [TagsEdit(tags_add=["a"])], _provenance())
        assert log.tags == ["a", "b"]
        assert len(log.log_updates or []) == 2

    def test_empty_tag_raises(self) -> None:
        log = _make_log()
        with pytest.raises(ValueError, match="non-empty"):
            edit_eval_log(log, [TagsEdit(tags_add=[""])], _provenance())

    def test_whitespace_tag_raises(self) -> None:
        log = _make_log()
        with pytest.raises(ValueError, match="non-empty"):
            edit_eval_log(log, [TagsEdit(tags_add=["  "])], _provenance())


class TestMetadataEdit:
    """Test metadata editing."""

    def test_set_metadata(self) -> None:
        log = _make_log(metadata={"a": 1})
        log = edit_eval_log(log, [MetadataEdit(metadata_set={"b": 2})], _provenance())
        assert log.metadata == {"a": 1, "b": 2}

    def test_overwrite_metadata(self) -> None:
        log = _make_log(metadata={"a": 1})
        log = edit_eval_log(log, [MetadataEdit(metadata_set={"a": 99})], _provenance())
        assert log.metadata == {"a": 99}

    def test_remove_metadata(self) -> None:
        log = _make_log(metadata={"a": 1, "b": 2})
        log = edit_eval_log(log, [MetadataEdit(metadata_remove=["a"])], _provenance())
        assert log.metadata == {"b": 2}

    def test_set_existing_value_is_noop(self) -> None:
        log = _make_log(metadata={"a": 1})
        log = edit_eval_log(log, [MetadataEdit(metadata_set={"a": 1})], _provenance())
        assert log.metadata == {"a": 1}
        assert log.log_updates is None

    def test_remove_nonexistent_key_is_noop(self) -> None:
        log = _make_log(metadata={"a": 1})
        log = edit_eval_log(log, [MetadataEdit(metadata_remove=["z"])], _provenance())
        assert log.metadata == {"a": 1}
        assert log.log_updates is None

    def test_empty_metadata_key_raises(self) -> None:
        log = _make_log()
        with pytest.raises(ValueError, match="non-empty"):
            edit_eval_log(log, [MetadataEdit(metadata_set={"": "val"})], _provenance())


class TestMixedEdits:
    """Test combining tag and metadata edits."""

    def test_tags_and_metadata_in_one_update(self) -> None:
        log = _make_log(tags=["old"], metadata={"old_key": "old_val"})
        log = edit_eval_log(
            log,
            [
                TagsEdit(tags_add=["new"], tags_remove=["old"]),
                MetadataEdit(
                    metadata_set={"new_key": "new_val"},
                    metadata_remove=["old_key"],
                ),
            ],
            _provenance(author="alice", reason="cleanup"),
        )
        assert log.tags == ["new"]
        assert log.metadata == {"new_key": "new_val"}
        assert len(log.log_updates or []) == 1
        assert log.log_updates[0].provenance.author == "alice"
        assert log.log_updates[0].provenance.reason == "cleanup"

    def test_multiple_updates_preserve_history(self) -> None:
        log = _make_log()
        log = edit_eval_log(
            log, [TagsEdit(tags_add=["a"])], _provenance(author="alice")
        )
        log = edit_eval_log(log, [TagsEdit(tags_add=["b"])], _provenance(author="bob"))
        assert log.tags == ["a", "b"]
        assert len(log.log_updates or []) == 2
        assert log.log_updates[0].provenance.author == "alice"
        assert log.log_updates[1].provenance.author == "bob"


class TestEvalSpecUnchanged:
    """Verify edits don't modify EvalSpec."""

    def test_eval_tags_unchanged(self) -> None:
        log = _make_log(tags=["original"])
        log = edit_eval_log(
            log,
            [TagsEdit(tags_add=["new"], tags_remove=["original"])],
            _provenance(),
        )
        assert log.eval.tags == ["original"]
        assert log.tags == ["new"]

    def test_eval_metadata_unchanged(self) -> None:
        log = _make_log(metadata={"key": "original"})
        log = edit_eval_log(
            log,
            [MetadataEdit(metadata_set={"key": "changed"})],
            _provenance(),
        )
        assert log.eval.metadata == {"key": "original"}
        assert log.metadata == {"key": "changed"}


class TestSerialization:
    """Test that log_updates survives serialization round-trip."""

    def test_model_round_trip(self) -> None:
        log = _make_log(tags=["a"])
        log = edit_eval_log(
            log,
            [TagsEdit(tags_add=["b"]), MetadataEdit(metadata_set={"k": "v"})],
            _provenance(author="alice"),
        )
        data = log.model_dump()
        restored = EvalLog.model_validate(data)
        assert restored.tags == ["a", "b"]
        assert restored.metadata == {"k": "v"}
        assert len(restored.log_updates or []) == 1
        assert restored.log_updates[0].provenance.author == "alice"


def _edited_log() -> EvalLog:
    """Create a log with multiple edits applied."""
    log = _make_log(tags=["original"], metadata={"orig_key": "orig_val"})
    log = edit_eval_log(
        log,
        [
            TagsEdit(tags_add=["added"], tags_remove=["original"]),
            MetadataEdit(
                metadata_set={"new_key": "new_val"}, metadata_remove=["orig_key"]
            ),
        ],
        _provenance(author="alice", reason="first edit"),
    )
    log = edit_eval_log(
        log,
        [TagsEdit(tags_add=["second"])],
        _provenance(author="bob", reason="second edit"),
    )
    return log


class TestDiskRoundTrip:
    """Test log_updates round-tripping through JSON and eval (zip) formats."""

    @pytest.mark.parametrize("format", ["json", "eval"])
    def test_round_trip_preserves_edits(self, tmp_path, format) -> None:
        log = _edited_log()
        path = (tmp_path / f"log.{format}").as_posix()
        write_eval_log(log, path, format=format)

        restored = read_eval_log(path, format=format)
        assert restored.tags == ["added", "second"]
        assert restored.metadata == {"new_key": "new_val"}
        assert len(restored.log_updates) == 2
        assert restored.log_updates[0].provenance.author == "alice"
        assert restored.log_updates[1].provenance.author == "bob"

    @pytest.mark.parametrize("format", ["json", "eval"])
    def test_round_trip_eval_spec_unchanged(self, tmp_path, format) -> None:
        log = _edited_log()
        path = (tmp_path / f"log.{format}").as_posix()
        write_eval_log(log, path, format=format)

        restored = read_eval_log(path, format=format)
        assert restored.eval.tags == ["original"]
        assert restored.eval.metadata == {"orig_key": "orig_val"}

    def test_cross_format_round_trip(self, tmp_path) -> None:
        log = _edited_log()
        json_path = (tmp_path / "log.json").as_posix()
        eval_path = (tmp_path / "log.eval").as_posix()
        json2_path = (tmp_path / "log2.json").as_posix()

        write_eval_log(log, json_path, format="json")
        log = read_eval_log(json_path, format="json")

        write_eval_log(log, eval_path, format="eval")
        log = read_eval_log(eval_path, format="eval")

        write_eval_log(log, json2_path, format="json")
        restored = read_eval_log(json2_path, format="json")

        assert restored.tags == ["added", "second"]
        assert restored.metadata == {"new_key": "new_val"}
        assert len(restored.log_updates) == 2

    @pytest.mark.parametrize("format", ["json", "eval"])
    def test_header_only_eval_id_matches_full_read(self, tmp_path, format) -> None:
        log = _make_log(tags=["a"])
        # Clear eval_id so it gets generated from the hash on read
        log.eval.eval_id = ""
        path = (tmp_path / f"log.{format}").as_posix()
        write_eval_log(log, path, format=format)

        full = read_eval_log(path, format=format)
        header = read_eval_log(path, format=format, header_only=True)
        assert full.eval.eval_id != ""
        assert header.eval.eval_id == full.eval.eval_id

    @pytest.mark.parametrize("format", ["json", "eval"])
    def test_header_only_read_includes_log_updates(self, tmp_path, format) -> None:
        log = _edited_log()
        path = (tmp_path / f"log.{format}").as_posix()
        write_eval_log(log, path, format=format)

        header = read_eval_log(path, format=format, header_only=True)
        assert header.log_updates is not None
        assert len(header.log_updates) == 2
        assert header.tags == ["added", "second"]
        assert header.metadata == {"new_key": "new_val"}

    def test_eval_zip_header_contains_log_updates(self, tmp_path) -> None:
        log = _edited_log()
        path = (tmp_path / "log.eval").as_posix()
        write_eval_log(log, path, format="eval")

        with zipfile.ZipFile(path, "r") as zf:
            with zf.open("header.json") as f:
                header_data = json.load(f)

        assert "log_updates" in header_data
        assert len(header_data["log_updates"]) == 2
        assert header_data["log_updates"][0]["provenance"]["author"] == "alice"

    @pytest.mark.parametrize("format", ["json", "eval"])
    def test_header_only_read_preserves_invalidated(self, tmp_path, format) -> None:
        log = _make_log()
        log.invalidated = True
        path = (tmp_path / f"log.{format}").as_posix()
        write_eval_log(log, path, format=format)

        header = read_eval_log(path, format=format, header_only=True)
        assert header.invalidated is True

    @pytest.mark.parametrize("format", ["json", "eval"])
    def test_no_edits_round_trip(self, tmp_path, format) -> None:
        log = _make_log(tags=["a"], metadata={"k": "v"})
        path = (tmp_path / f"log.{format}").as_posix()
        write_eval_log(log, path, format=format)

        restored = read_eval_log(path, format=format)
        assert restored.log_updates is None
        assert restored.tags == ["a"]
        assert restored.metadata == {"k": "v"}

    @pytest.mark.parametrize("format", ["json", "eval"])
    def test_edit_after_read_round_trip(self, tmp_path, format) -> None:
        log = _make_log(tags=["a"])
        path = (tmp_path / f"log.{format}").as_posix()
        write_eval_log(log, path, format=format)

        log = read_eval_log(path, format=format)
        log = edit_eval_log(
            log, [TagsEdit(tags_add=["b"])], _provenance(author="alice")
        )
        write_eval_log(log, path, format=format)

        restored = read_eval_log(path, format=format)
        assert restored.tags == ["a", "b"]
        assert len(restored.log_updates) == 1
        assert restored.log_updates[0].provenance.author == "alice"
