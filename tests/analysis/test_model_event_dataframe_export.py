"""Dataframe export populates new model-event retry columns."""

# pyright: reportImplicitRelativeImport=false

from _helpers.retry_provider import (
    RetryableModelError,
    install_retry_classifier,
    make_mockllm_with_callable,
)
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval_async
from inspect_ai.analysis import events_df
from inspect_ai.analysis._dataframe.events.columns import EventInfo, ModelEventColumns
from inspect_ai.dataset import Sample
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver import generate


@skip_if_trio
async def test_dataframe_includes_call_id_and_attempt_for_retry() -> None:
    remaining = [2]

    def custom_outputs(input, tools, tool_choice, config):
        if remaining[0] > 0:
            remaining[0] -= 1
            raise RetryableModelError("transient")
        return ModelOutput.from_content("mockllm", "ok")

    model = make_mockllm_with_callable(custom_outputs)
    install_retry_classifier(model)
    logs = await eval_async(
        Task(dataset=[Sample(input="hello")], solver=generate()),
        model=model,
    )

    df = events_df(
        logs[0],
        columns=EventInfo + ModelEventColumns,
        filter=lambda event: event.event == "model",
    )
    model_rows = df[df["event"] == "model"]
    assert len(model_rows) == 3
    assert model_rows["model_event_call_id"].nunique() == 1
    assert sorted(model_rows["model_event_attempt"].tolist()) == [1, 2, 3]

    terminal = model_rows.iloc[-1]
    assert terminal["model_event_call_retries"] == 2
    assert terminal["model_event_http_retries"] == 2
    assert terminal["model_event_call_working_time"] >= 0

    earlier = model_rows.iloc[:-1]
    assert earlier["model_event_call_retries"].isna().all()
