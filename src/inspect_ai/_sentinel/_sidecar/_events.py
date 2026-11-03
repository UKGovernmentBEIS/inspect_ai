"""The sidecar's reports in Inspect's transcript, as `SentinelEvent`s like an in-process sentinel's."""

from typing import Any

from inspect_ai.event._sentinel import SentinelEvent, SentinelSidecar

from .._conversation import current_conversation
from ._endpoint import Sidecar
from ._field import ReceivedField, SentinelField, parse_field


def record_sidecar_reports(
    field: SentinelField,
    sidecar: Sidecar,
    request: str | None,
    generate_id: str,
) -> None:
    """Write each report in the field into the transcript: one event per monitor and protocol report, or, from a sidecar that sends only what Inspect acts on, one per step's decision.

    Each step is tied to Inspect's own ids, as an in-process sentinel's: a tool stage's to the call's id, and both generate stages to the generate's id, the `uuid` of its first `ModelEvent`.
    """
    from inspect_ai.log._transcript import transcript

    where = SentinelSidecar(
        proxy=sidecar.origin,
        version=sidecar.version,
        release=sidecar.release,
        request=request,
        trimmed=bool(field.trimmed),
    )
    conversation = current_conversation()
    for step in field.steps:
        step_id = step.call if step.call is not None else generate_id
        if field.trimmed or step.recorded is None:
            # a step without its records holds only what Inspect acts on
            trimmed = where.model_copy(update={"trimmed": True})
            transcript()._event(
                SentinelEvent.model_validate(
                    {
                        "factory": "",
                        "path": "",
                        "step_id": step_id,
                        "conversation": conversation,
                        "stage": step.stage,
                        "kind": "decision",
                        "status": "reported",
                        **_decision(step.decision),
                        "sidecar": trimmed,
                    }
                )
            )
            continue
        for record in step.recorded:
            transcript()._event(
                SentinelEvent.model_validate(
                    {
                        "factory": record.get("factory", ""),
                        "path": record.get("path", ""),
                        "step_id": step_id,
                        "conversation": conversation,
                        "stage": step.stage,
                        **_report(record),
                        "sidecar": where,
                    }
                )
            )


def record_refusal_reports(
    received: ReceivedField, sidecar: Sidecar, generate_id: str
) -> None:
    """Write the reports of a refusal that stands as the call's error into the transcript, as a bridged agent's rejected turn does: the agent is handed the error, and the transcript still shows what the sidecar decided."""
    if received.field is not None:
        record_sidecar_reports(
            parse_field(received.field), sidecar, received.request_id, generate_id
        )


def _report(record: dict[str, Any]) -> dict[str, Any]:
    kind = record.get("kind")
    if kind == "failed":
        return {
            "kind": "observation",
            "status": "error",
            "function": record.get("function"),
            "error": record.get("error"),
        }
    if kind in ("cancelled", "bypassed"):
        # a protocol is bypassed; a cancelled monitor's kind isn't recorded
        return {
            "kind": "decision" if kind == "bypassed" else "observation",
            "status": kind,
        }
    report = record.get("report") or {}
    if "action" in report:
        return {
            "kind": "decision",
            "status": "superseded" if kind == "superseded" else "reported",
            "function": record.get("function"),
            **_decision(report),
        }
    return {
        "kind": "observation",
        "status": "reported",
        "function": record.get("function"),
        "suspicion": report.get("suspicion"),
        "explanation": report.get("explanation"),
        "references": report.get("references", []),
        "metadata": report.get("metadata"),
    }


def _decision(decision: dict[str, Any]) -> dict[str, Any]:
    action = decision.get("action")
    return {
        "action": action,
        "audit": decision.get("audit", False),
        "modified": decision.get("modified") if action == "modify" else None,
        "message": decision.get("message") if action == "reject" else None,
        "explanation": decision.get("explanation"),
        "references": decision.get("references", []),
        "metadata": decision.get("metadata"),
    }
