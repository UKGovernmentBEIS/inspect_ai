import pytest

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

    def test_lazy_computation(self) -> None:
        log = _make_log(tags=["a"])
        assert log._tags is None
        _ = log.tags
        assert log._tags is not None


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

    def test_add_existing_tag_is_idempotent(self) -> None:
        log = _make_log(tags=["a"])
        log = edit_eval_log(log, [TagsEdit(tags_add=["a"])], _provenance())
        assert log.tags == ["a"]

    def test_remove_nonexistent_tag(self) -> None:
        log = _make_log(tags=["a"])
        log = edit_eval_log(log, [TagsEdit(tags_remove=["z"])], _provenance())
        assert log.tags == ["a"]

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

    def test_remove_nonexistent_key(self) -> None:
        log = _make_log(metadata={"a": 1})
        log = edit_eval_log(log, [MetadataEdit(metadata_remove=["z"])], _provenance())
        assert log.metadata == {"a": 1}

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

    def test_round_trip(self) -> None:
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
