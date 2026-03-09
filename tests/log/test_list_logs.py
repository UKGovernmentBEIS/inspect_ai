from os.path import dirname, join
from pathlib import Path

from inspect_ai.log import list_eval_logs, write_eval_log
from inspect_ai.log._edit import (
    MetadataEdit,
    ProvenanceData,
    TagsEdit,
    edit_eval_log,
)
from inspect_ai.log._log import EvalConfig, EvalDataset, EvalLog, EvalSpec

file = Path(__file__)

ignored_files = ["ignore.json"]


def _make_log(
    task_id: str,
    tags: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> EvalLog:
    return EvalLog(
        version=2,
        eval=EvalSpec(
            eval_id=f"eval-{task_id}",
            run_id=f"run-{task_id}",
            created="2025-01-01T00:00:00Z",
            task="test_task",
            task_id=task_id,
            dataset=EvalDataset(),
            model="test_model",
            config=EvalConfig(),
            tags=tags,
            metadata=metadata,
        ),
        status="success",
    )


def test_list_logs():
    logs = list_eval_logs(
        join(dirname(file), "test_list_logs"), formats=["eval", "json"]
    )
    names = [log.name for log in logs]

    assert len(logs) == 3
    assert all(file not in names for file in ignored_files)


def test_list_logs_filter_by_effective_tags(tmp_path: Path) -> None:
    unedited = _make_log("unedited", tags=["base"])
    edited = edit_eval_log(
        _make_log("edited", tags=["base"]),
        [
            TagsEdit(tags_add=["qa_reviewed"]),
            MetadataEdit(metadata_set={"reviewer": "alice"}),
        ],
        ProvenanceData(author="alice", reason="qa"),
    )

    write_eval_log(unedited, (tmp_path / "unedited.eval").as_posix(), format="eval")
    write_eval_log(edited, (tmp_path / "edited.eval").as_posix(), format="eval")

    logs = list_eval_logs(tmp_path.as_posix(), tags=["qa_reviewed"])
    assert [Path(log.name).name for log in logs] == ["edited.eval"]

    logs = list_eval_logs(tmp_path.as_posix(), tags=["base", "qa_reviewed"])
    assert [Path(log.name).name for log in logs] == ["edited.eval"]

    logs = list_eval_logs(
        tmp_path.as_posix(),
        tags=["qa_reviewed"],
        filter=lambda log: log.metadata.get("reviewer") == "alice",
    )
    assert [Path(log.name).name for log in logs] == ["edited.eval"]
