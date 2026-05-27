"""Round-trip `Task.viewer` through `EvalSpec.viewer` via the eval log."""

from inspect_ai import Task, eval
from inspect_ai.viewer import (
    MetadataField,
    SamplesColumn,
    SamplesSort,
    SamplesView,
    ScannerResultField,
    ScannerResultView,
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
        task_samples_view=SamplesView(
            name="Triage",
            columns=[
                SamplesColumn(id="status"),
                SamplesColumn(id="input"),
                SamplesColumn(id="target", visible=False),
                SamplesColumn(id="tokens"),
            ],
            sort=[SamplesSort(column="tokens", dir="desc")],
            filter="has_error or score < 0.5",
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
            SamplesView(name="All"),
            SamplesView(name="Errors", filter="has_error"),
        ]
    )
    log = eval(Task(viewer=cfg), model="mockllm/model")[0]
    assert log.eval.viewer == cfg
    assert isinstance(log.eval.viewer.task_samples_view, list)
    assert len(log.eval.viewer.task_samples_view) == 2
