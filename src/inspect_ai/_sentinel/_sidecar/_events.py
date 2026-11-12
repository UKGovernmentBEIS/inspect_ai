"""The sidecar's reports in Inspect's transcript, as `SentinelEvent`s like an in-process sentinel's."""

from logging import getLogger
from typing import Any

from inspect_ai._util.logger import warn_once
from inspect_ai.event._sentinel import SentinelEvent

from .._conversation import current_conversation
from ._endpoint import Sidecar
from ._received import Judgment, ReceivedCall

logger = getLogger(__name__)

SIDECAR_METADATA = "sentinel_sidecar"
"""The key of a sidecar report's provenance in the event's `metadata`: the proxy, the endpoint's version and release mode, the call's `x-irid`, whether the report was trimmed, and the models the step's monitors and protocols called."""


def record_sidecar_reports(
    judgment: Judgment,
    sidecar: Sidecar,
    request: str | None,
    generate_id: str,
) -> None:
    """Write each report in the judgment into the transcript: one event per monitor and protocol report, or, from a sidecar that sends only what Inspect acts on, one per step's decision.

    Each step is tied to Inspect's own ids, as an in-process sentinel's: a tool stage's to the call's id, and both generate stages to the generate's id, the `uuid` of its first `ModelEvent`.
    """
    from inspect_ai.log._transcript import transcript

    conversation = current_conversation()
    for step in judgment.steps:
        step_id = step.call if step.call is not None else generate_id
        if step.models:
            _warn_of_unused_roles(step.models, sidecar)
        # where the report came from, in the event's metadata: the log
        # format has no field for it
        where: dict[str, Any] = {
            "proxy": sidecar.origin,
            "version": sidecar.version,
            "release": sidecar.release,
            "request": request,
            "trimmed": bool(judgment.trimmed),
            "models": step.models or None,
        }
        if judgment.trimmed or step.recorded is None:
            # a step without its records holds only what Inspect acts on,
            # with no monitor or protocol, so no function, to name. The
            # decision's own metadata is kept when the sidecar sent it: a
            # trimmed judgment leaves it out, and nothing restores it
            transcript()._event(
                SentinelEvent.model_validate(
                    {
                        "factory": "",
                        "path": "",
                        "step_id": step_id,
                        "conversation": conversation,
                        "stage": step.stage,
                        "function": "",
                        "kind": "decision",
                        "status": "reported",
                        **_with_sidecar(_decision(step.decision), where),
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
                        **_with_sidecar(_report(record), where),
                    }
                )
            )


def _with_sidecar(report: dict[str, Any], where: dict[str, Any]) -> dict[str, Any]:
    # the report's own metadata, with where it came from beside it
    return {
        **report,
        "metadata": {**(report.get("metadata") or {}), SIDECAR_METADATA: where},
    }


def _warn_of_unused_roles(models: list[dict[str, Any]], sidecar: Sidecar) -> None:
    # A sentinel in a sidecar takes a role's model from the sidecar's own
    # configuration. An eval that set the role for another model is told
    # once, so it doesn't read the eval's role as the model that judged.
    from inspect_ai.model._model import model_roles

    roles = model_roles()
    for used in models:
        role, model = used.get("role"), used.get("model")
        if role is None or role not in roles:
            continue
        assigned = roles[role]
        names = [
            str(m) for m in (assigned if isinstance(assigned, list) else [assigned])
        ]
        if model not in names:
            warn_once(
                logger,
                f"The eval's model role {role!r} ({', '.join(names)}) doesn't reach the sentinel in the sidecar at {sidecar.origin}, which takes its roles from its own configuration: its monitors used {model} for {role!r}.",
            )


def record_refusal_reports(
    received: ReceivedCall, sidecar: Sidecar, generate_id: str
) -> None:
    """Write the reports of a refusal that stands as the call's error into the transcript, as a bridged agent's rejected turn does: the agent is handed the error, and the transcript still shows what the sidecar decided."""
    if received.judgment is not None:
        record_sidecar_reports(
            received.judgment, sidecar, received.request_id, generate_id
        )


async def record_reports_past_limit(
    received: ReceivedCall, sidecar: Sidecar, generate_id: str
) -> None:
    """Write the reports of a call whose reply took the sample past a limit into the transcript.

    The sidecar judged the reply before Inspect counted its usage, and the monitor state it keeps, which is copied before scoring, already holds what it saw. So the transcript shows what it decided, though the sample ends on the limit before any decision is acted on. A lookup that fails records nothing, since the sample's outcome is the limit either way.
    """
    from ._lookup import request_result

    looked = received.looked
    if looked is None:
        try:
            looked = await request_result(received, replied=True)
        except Exception as ex:
            logger.debug(
                f"The sentinel sidecar at {sidecar.origin} couldn't be asked about a call past a limit: {ex}"
            )
            return
    if looked.state == "decided" and looked.judgment is not None:
        record_sidecar_reports(
            looked.judgment, sidecar, received.request_id, generate_id
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
