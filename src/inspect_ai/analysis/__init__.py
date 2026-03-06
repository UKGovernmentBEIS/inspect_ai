from inspect_ai._util.deprecation import relocated_module_attribute
from inspect_ai.model._model_data.model_data import ModelInfo

from ._dataframe.columns import (
    Column,
    ColumnError,
    ColumnType,
)
from ._dataframe.evals.columns import (
    EvalColumn,
    EvalColumns,
    EvalConfiguration,
    EvalDataset,
    EvalInfo,
    EvalModel,
    EvalResults,
    EvalScores,
    EvalTask,
)
from ._dataframe.evals.table import evals_df
from ._dataframe.events.columns import (
    EventColumn,
    EventInfo,
    EventTiming,
    ModelEventColumns,
    ToolEventColumns,
)
from ._dataframe.events.table import events_df
from ._dataframe.messages.columns import (
    MessageColumn,
    MessageColumns,
    MessageContent,
    MessageToolCalls,
)
from ._dataframe.messages.table import MessageFilter, messages_df
from ._dataframe.samples.columns import (
    SampleColumn,
    SampleMessages,
    SampleScores,
    SampleSummary,
)
from ._dataframe.samples.table import samples_df
from ._prepare.frontier import frontier
from ._prepare.log_viewer import log_viewer
from ._prepare.model_info import model_info
from ._prepare.operation import Operation
from ._prepare.prepare import prepare
from ._prepare.score_to_float import score_to_float
from ._prepare.task_info import task_info

__all__ = [
    "evals_df",
    "EvalColumn",
    "EvalColumns",
    "EvalInfo",
    "EvalTask",
    "EvalModel",
    "EvalColumns",
    "EvalConfiguration",
    "EvalDataset",
    "EvalResults",
    "EvalScores",
    "samples_df",
    "SampleColumn",
    "SampleSummary",
    "SampleScores",
    "SampleMessages",
    "messages_df",
    "MessageColumn",
    "MessageContent",
    "MessageToolCalls",
    "MessageColumns",
    "MessageFilter",
    "events_df",
    "EventColumn",
    "EventInfo",
    "EventTiming",
    "ModelEventColumns",
    "ToolEventColumns",
    "Column",
    "ColumnType",
    "ColumnError",
    "prepare",
    "log_viewer",
    "Operation",
    "model_info",
    "score_to_float",
    "task_info",
    "ModelInfo",
    "frontier",
]

_MODEL_INFO_VERSION_3_158 = "0.3.158"
_REMOVED_IN = "0.4"

relocated_module_attribute(
    "ModelInfo",
    "inspect_ai.model.ModelInfo",
    _MODEL_INFO_VERSION_3_158,
    _REMOVED_IN,
)
