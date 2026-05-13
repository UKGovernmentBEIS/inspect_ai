from typing import TYPE_CHECKING

from inspect_ai._util.deprecation import relocated_module_attribute
from inspect_ai._util.error import EvalError, WriteConflictError
from inspect_ai._util.lazy import lazy_attributes

# eager: only ``_edit`` (a leaf module). ``inspect_ai.scorer._metric`` —
# itself imported by ``inspect_ai.event`` — needs ``ProvenanceData`` from
# here, so this package's ``__init__`` must be importable without touching
# ``_log`` / ``_file`` / ``_condense`` (each of which reaches back into
# ``event`` and would deadlock when ``event`` is the entry point).
from ._edit import (
    LogEdit,
    LogUpdate,
    MetadataEdit,
    ProvenanceData,
    TagsEdit,
    edit_eval_log,
    invalidate_samples,
    uninvalidate_samples,
)

if TYPE_CHECKING:
    from ._bundle import bundle_log_dir
    from ._condense import (
        condense_events,
        condense_sample,
        expand_events,
        resolve_sample_attachments,
    )
    from ._convert import convert_eval_logs
    from ._file import (
        EvalLogInfo,
        list_eval_logs,
        read_eval_log,
        read_eval_log_async,
        read_eval_log_sample,
        read_eval_log_sample_summaries,
        read_eval_log_samples,
        write_eval_log,
        write_eval_log_async,
        write_log_dir_manifest,
    )
    from ._log import (
        ConnectionLimitChange,
        EvalConfig,
        EvalDataset,
        EvalLog,
        EvalMetric,
        EvalPlan,
        EvalPlanStep,
        EvalResults,
        EvalRetryError,
        EvalRevision,
        EvalSample,
        EvalSampleLimit,
        EvalSampleReductions,
        EvalSampleScore,
        EvalSampleSummary,
        EvalScore,
        EvalSpec,
        EvalStats,
        EvalStatus,
        EventsData,
    )
    from ._metric import recompute_metrics
    from ._pool import resolve_sample_events_data
    from ._recover import (
        RecoverableEvalLog,
        RecoveryNotAvailable,
        recover_eval_log,
        recoverable_eval_logs,
    )
    from ._retry import retryable_eval_logs
    from ._score import edit_score
    from ._transcript import (
        Transcript,
        transcript,
    )

__all__ = [
    "WriteConflictError",
    "EvalConfig",
    "EvalError",
    "EvalDataset",
    "EvalLog",
    "EvalMetric",
    "EvalPlan",
    "EvalPlanStep",
    "EvalResults",
    "EvalRetryError",
    "EvalRevision",
    "EvalSample",
    "EvalSampleLimit",
    "EvalSampleScore",
    "EvalSampleReductions",
    "EvalSampleSummary",
    "EvalScore",
    "EvalSpec",
    "EvalStats",
    "EvalStatus",
    "EvalLogInfo",
    "Transcript",
    "transcript",
    "convert_eval_logs",
    "list_eval_logs",
    "read_eval_log",
    "read_eval_log_async",
    "read_eval_log_sample",
    "read_eval_log_samples",
    "read_eval_log_sample_summaries",
    "condense_sample",
    "condense_events",
    "EventsData",
    "expand_events",
    "resolve_sample_attachments",
    "resolve_sample_events_data",
    "write_eval_log",
    "write_eval_log_async",
    "write_log_dir_manifest",
    "retryable_eval_logs",
    "bundle_log_dir",
    "edit_score",
    "recompute_metrics",
    "ProvenanceData",
    "LogEdit",
    "LogUpdate",
    "MetadataEdit",
    "TagsEdit",
    "edit_eval_log",
    "invalidate_samples",
    "uninvalidate_samples",
    "recover_eval_log",
    "recoverable_eval_logs",
    "RecoverableEvalLog",
    "RecoveryNotAvailable",
    "ConnectionLimitChange",
]


_EVENT_MODULE_VERSION_3_137 = "0.3.137"
_REMOVED_IN = "0.4"
relocated_module_attribute(
    "ApprovalEvent",
    "inspect_ai.event.ApprovalEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "ErrorEvent",
    "inspect_ai.event.ErrorEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "Event",
    "inspect_ai.event.Event",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "InfoEvent",
    "inspect_ai.event.InfoEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "InputEvent",
    "inspect_ai.event.InputEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "LoggerEvent",
    "inspect_ai.event.LoggerEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "LoggingLevel",
    "inspect_ai.event.LoggingLevel",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "LoggingMessage",
    "inspect_ai.event.LoggingMessage",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "ModelEvent",
    "inspect_ai.event.ModelEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "SampleInitEvent",
    "inspect_ai.event.SampleInitEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "SampleLimitEvent",
    "inspect_ai.event.SampleLimitEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "SandboxEvent",
    "inspect_ai.event.SandboxEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "ScoreEvent",
    "inspect_ai.event.ScoreEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "SpanBeginEvent",
    "inspect_ai.event.SpanBeginEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "SpanEndEvent",
    "inspect_ai.event.SpanEndEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "StateEvent",
    "inspect_ai.event.StateEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "StepEvent",
    "inspect_ai.event.StepEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "StoreEvent",
    "inspect_ai.event.StoreEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "SubtaskEvent",
    "inspect_ai.event.SubtaskEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "ToolEvent",
    "inspect_ai.event.ToolEvent",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "EventNode",
    "inspect_ai.event.EventNode",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "EventTree",
    "inspect_ai.event.EventTree",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "SpanNode",
    "inspect_ai.event.SpanNode",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "event_sequence",
    "inspect_ai.event.event_sequence",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)
relocated_module_attribute(
    "event_tree",
    "inspect_ai.event.event_tree",
    _EVENT_MODULE_VERSION_3_137,
    _REMOVED_IN,
)

lazy_attributes(
    __name__,
    {
        "ConnectionLimitChange": "inspect_ai.log._log",
        "EvalConfig": "inspect_ai.log._log",
        "EvalDataset": "inspect_ai.log._log",
        "EvalLog": "inspect_ai.log._log",
        "EvalMetric": "inspect_ai.log._log",
        "EvalPlan": "inspect_ai.log._log",
        "EvalPlanStep": "inspect_ai.log._log",
        "EvalResults": "inspect_ai.log._log",
        "EvalRetryError": "inspect_ai.log._log",
        "EvalRevision": "inspect_ai.log._log",
        "EvalSample": "inspect_ai.log._log",
        "EvalSampleLimit": "inspect_ai.log._log",
        "EvalSampleReductions": "inspect_ai.log._log",
        "EvalSampleScore": "inspect_ai.log._log",
        "EvalSampleSummary": "inspect_ai.log._log",
        "EvalScore": "inspect_ai.log._log",
        "EvalSpec": "inspect_ai.log._log",
        "EvalStats": "inspect_ai.log._log",
        "EvalStatus": "inspect_ai.log._log",
        "EventsData": "inspect_ai.log._log",
        "EvalLogInfo": "inspect_ai.log._file",
        "list_eval_logs": "inspect_ai.log._file",
        "read_eval_log": "inspect_ai.log._file",
        "read_eval_log_async": "inspect_ai.log._file",
        "read_eval_log_sample": "inspect_ai.log._file",
        "read_eval_log_sample_summaries": "inspect_ai.log._file",
        "read_eval_log_samples": "inspect_ai.log._file",
        "write_eval_log": "inspect_ai.log._file",
        "write_eval_log_async": "inspect_ai.log._file",
        "write_log_dir_manifest": "inspect_ai.log._file",
        "condense_events": "inspect_ai.log._condense",
        "condense_sample": "inspect_ai.log._condense",
        "expand_events": "inspect_ai.log._condense",
        "resolve_sample_attachments": "inspect_ai.log._condense",
        "resolve_sample_events_data": "inspect_ai.log._pool",
        "Transcript": "inspect_ai.log._transcript",
        "transcript": "inspect_ai.log._transcript",
        "bundle_log_dir": "inspect_ai.log._bundle",
        "convert_eval_logs": "inspect_ai.log._convert",
        "recompute_metrics": "inspect_ai.log._metric",
        "RecoverableEvalLog": "inspect_ai.log._recover",
        "RecoveryNotAvailable": "inspect_ai.log._recover",
        "recover_eval_log": "inspect_ai.log._recover",
        "recoverable_eval_logs": "inspect_ai.log._recover",
        "retryable_eval_logs": "inspect_ai.log._retry",
        "edit_score": "inspect_ai.log._score",
    },
)
