"""Round-trip `Task.viewer` through `EvalSpec.viewer` via the eval log."""

from inspect_ai import Task, eval
from inspect_ai.viewer import (
    MetadataField,
    ScannerResultField,
    ScannerResultView,
    TaskSamplesColumn,
    TaskSamplesSort,
    TaskSamplesView,
    ViewerConfig,
)


def test_task_viewer_roundtrips_through_eval_log() -> None:
    """`Task(viewer=cfg)` is persisted to `EvalSpec.viewer` and re-read equal."""
    cfg = ViewerConfig(
        scanner_result_view={
            "*": ScannerResultView(
                fields=[
                    ScannerResultField(name="explanation", label="Rationale"),
                    MetadataField(key="summary", label="Summary", collapsed=True),
                    ScannerResultField(name="value"),
                    "metadata",
                ],
                exclude_fields=["answer", MetadataField(key="_internal_state")],
            ),
        },
    )
    log = eval(Task(viewer=cfg), model="mockllm/model")[0]
    assert log.eval.viewer == cfg


def test_task_without_viewer_persists_as_none() -> None:
    """Tasks without a viewer argument leave `EvalSpec.viewer` as `None`."""
    log = eval(Task(), model="mockllm/model")[0]
    assert log.eval.viewer is None


def test_bare_scanner_result_view_shorthand_roundtrips() -> None:
    """Passing a bare `ScannerResultView` as `viewer=` is stored as-is."""
    cfg = ViewerConfig(
        scanner_result_view=ScannerResultView(fields=["value", "explanation"]),
    )
    log = eval(Task(viewer=cfg), model="mockllm/model")[0]
    assert log.eval.viewer == cfg
    assert isinstance(log.eval.viewer.scanner_result_view, ScannerResultView)


def test_samples_view_roundtrips_through_eval_log() -> None:
    """`Task(viewer=ViewerConfig(task_samples_view=...))` persists end-to-end."""
    cfg = ViewerConfig(
        task_samples_view=TaskSamplesView(
            name="Triage",
            columns=[
                TaskSamplesColumn(id="status"),
                TaskSamplesColumn(id="input"),
                TaskSamplesColumn(id="target", visible=False),
                TaskSamplesColumn(id="tokens"),
            ],
            sort=[TaskSamplesSort(column="tokens", dir="desc")],
            multiline=False,
        )
    )
    log = eval(Task(viewer=cfg), model="mockllm/model")[0]
    assert log.eval.viewer == cfg


def test_samples_view_list_form_roundtrips() -> None:
    """`task_samples_view` accepts a list (multi-view future).

    The wire preserves the list shape verbatim.
    """
    cfg = ViewerConfig(
        task_samples_view=[
            TaskSamplesView(name="All"),
            TaskSamplesView(name="Errors"),
        ]
    )
    log = eval(Task(viewer=cfg), model="mockllm/model")[0]
    assert log.eval.viewer == cfg
    assert isinstance(log.eval.viewer.task_samples_view, list)
    assert len(log.eval.viewer.task_samples_view) == 2
