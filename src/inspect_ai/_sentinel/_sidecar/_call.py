"""An agent call that goes through a sentinel sidecar."""

import json
from collections.abc import MutableMapping
from logging import getLogger
from typing import TYPE_CHECKING, NamedTuple

from inspect_ai._util.logger import warn_once
from inspect_ai.model._generate_config import GenerateConfig

from .._config import SentinelProxy
from .._scope import current_origin, is_agent_turn
from ._endpoint import Sidecar, _origin
from ._sign import model_request_message, now, sign
from ._task import SampleFacts, TaskSidecars, attempt_number, task_sidecars

if TYPE_CHECKING:
    from inspect_ai.log._samples import ActiveSample
    from inspect_ai.model._model import Model
    from inspect_ai.solver._task_state import TaskState

logger = getLogger(__name__)

INSPECT_CONTEXT = "x-inspect-context"
"""The header that names the sample an agent call is for, which is signed as each try of the call is sent."""

INSPECT_HEADERS = frozenset({INSPECT_CONTEXT})
"""Headers Inspect adds to a call's `GenerateConfig.extra_headers` itself, by lowercase name.

They are in the recorded `ModelEvent.config` but not in the config the caller
gave, so they don't tell one client from another (the agent bridge's response
filter provenance check). A header Inspect adds to a call's config belongs
here. Headers a provider adds to the request it sends (e.g. `x-irid`) are not
in the recorded config.
"""


class SidecarCall(NamedTuple):
    """An agent call to an endpoint where a sidecar answered the probe."""

    sidecar: Sidecar
    header: str
    """`x-inspect-context`, naming the call's sample and attempt, before it is signed."""
    mode: SentinelProxy
    registered_beforehand: bool = False
    """Whether the sidecar's admin registered the task beforehand, so a sample it can't place was never accepted."""

    def config(self, config: GenerateConfig) -> GenerateConfig:
        """The call's config, with its `x-inspect-context` header."""
        headers = {**(config.extra_headers or {}), INSPECT_CONTEXT: self.header}
        return config.model_copy(update={"extra_headers": headers})


async def sidecar_call(model: "Model") -> SidecarCall | None:
    """The sidecar an agent call goes through, with the sample's registration complete, or None for a call no sidecar judges.

    Only the agent's calls are judged, as in process: not a scorer's, an approver's, a compaction summary's or a monitor's.

    Raises:
        SentinelProxyError: If a sidecar found for the call's endpoint couldn't register the task or the sample.
    """
    from inspect_ai.log._samples import sample_active
    from inspect_ai.solver._task_state import sample_state

    sidecars = task_sidecars()
    if sidecars is None or not is_agent_turn(current_origin()):
        return None
    active = sample_active()
    state = sample_state()
    if active is None or state is None:
        return None
    sidecar = await sidecars.sidecar(model.api)
    if sidecar is None:
        if sidecars.mode == "required":
            _unjudged(sidecars, active, str(model))
        return None

    sidecars.called_through(active.sample_uuid, attempt_number(active), sidecar)
    registered_beforehand = await _complete_registration(
        sidecars, sidecar, active, state
    )
    # signed as each try is sent, so the eval log records it unsigned
    header = json.dumps(
        {
            "version": 1,
            "eval_id": sidecars.facts.eval_id,
            "task": sidecars.facts.task,
            "sample_id": state.sample_id,
            "epoch": state.epoch,
            # the same across the sample's retries, and new for each attempt
            "sample_uuid": active.sample_uuid,
            "attempt": active.id,
            # higher for each retry, so the sidecar can tell a late call of
            # an earlier attempt from the current one's
            "attempt_number": attempt_number(active),
            # Inspect's name for the model, which the request names without
            # the provider or a service, as in `openai-api/together/<model>`
            "model": str(model),
        }
    )
    return SidecarCall(sidecar, header, sidecars.mode, registered_beforehand)


async def _complete_registration(
    sidecars: TaskSidecars, sidecar: Sidecar, active: "ActiveSample", state: "TaskState"
) -> bool:
    return await sidecars.complete_registration(
        sidecar,
        SampleFacts(
            sample_id=state.sample_id,
            sample_description=active.sample.description,
            sample_input=state.input,
            metadata=state.metadata,
        ),
        active.sample_uuid,
        attempt_number(active),
    )


async def ensure_registration(request_id: str) -> None:
    """Complete the sample's registration again, as a try of the current agent call is sent under an `x-irid`, if the sidecar may have lost it since the call began.

    A request can be sent long after `sidecar_call`: once the call has a connection, after the eval was paused, or as a retry after a backoff. A sidecar that lost the task meanwhile, and that another sample registered it with again, frees the sample's facts when that sample ends, and would refuse the request as unregistered. So each try makes sure of the registration first. Nothing is sent where it is still good, and what is sent again is what the attempt first sent.

    The call then goes by what the sidecar says now of whether its admin registered the task beforehand: a sidecar that restarted may have the task in its tasks folder since.

    A registration the sidecar can't take stops the send, and every later try of the call: sent on, the request could be judged without the sample's facts. An error raised as a request is sent reaches the provider's caller as a failed connection, so it is kept as the call's `registration_error`, which Inspect raises in its place and doesn't retry.

    Raises:
        SentinelProxyError: If the sidecar couldn't take the sample, now or at an earlier try of the call.
    """
    from inspect_ai._util.exception import SampleRefusedError
    from inspect_ai.log._samples import sample_active
    from inspect_ai.solver._task_state import sample_state

    from ._endpoint import SentinelProxyError
    from ._received import current_receiving

    received = current_receiving()
    if (
        received is None
        or received.request_id != request_id
        or received.sidecar is None
    ):
        return
    if received.registration_error is not None:
        # a retry the provider's SDK makes of a send this stopped
        raise received.registration_error
    sidecars = task_sidecars()
    active = sample_active()
    state = sample_state()
    if sidecars is None or active is None or state is None:
        return
    try:
        received.registered_beforehand = await _complete_registration(
            sidecars, received.sidecar, active, state
        )
    except (SentinelProxyError, SampleRefusedError) as ex:
        received.registration_error = ex
        raise


def sign_context(headers: MutableMapping[str, str], url: str) -> None:
    """Sign a model request's `x-inspect-context` as the request is sent, with the time and the token of the eval it names for the sidecar at the request's origin.

    It runs on every try of the request, the SDK's retries and Inspect's alike, so a retry after a long backoff is signed afresh. The signature covers the request's `x-irid`. A header that names no eval with a sidecar at the request's origin, or is sent without an `x-irid`, is left as it is, and the sidecar refuses it as unreadable.
    """
    from inspect_ai.model._providers.util.hooks import HttpHooks

    # the id the sidecar keeps what it decides of the request under, which
    # the signature binds the context to
    irid = headers.get(HttpHooks.REQUEST_ID_HEADER)
    if not irid:
        return

    try:
        context = json.loads(headers[INSPECT_CONTEXT])
    except (KeyError, ValueError):
        return
    if not isinstance(context, dict):
        return
    eval_id = context.get("eval_id")
    sidecars = task_sidecars(eval_id) if isinstance(eval_id, str) else None
    access = sidecars.access(_origin(url)) if sidecars is not None else None
    if access is None:
        return
    timestamp = now()
    try:
        message = model_request_message(context, irid, timestamp)
    except KeyError:
        return
    context["timestamp"] = timestamp
    context["mac"] = sign(access.token, message)
    headers[INSPECT_CONTEXT] = json.dumps(context)


def _unjudged(sidecars: TaskSidecars, active: "ActiveSample", model: str) -> None:
    # `required` covers the task's assigned model, whose endpoint was probed at
    # task start; an agent call through another model with no sidecar behind
    # it goes out unjudged, and says so
    from inspect_ai.log._transcript import transcript

    warn_once(
        logger,
        f"Agent calls through {model} aren't judged: no sentinel sidecar answered behind its endpoint, and --sentinel-proxy required covers only the task's assigned model.",
    )
    if sidecars.note_unjudged(active.sample_uuid, attempt_number(active), model):
        transcript().info(
            {
                "model": model,
                "judgment": "not judged",
                "reason": "no sidecar answered behind the model's endpoint, and required covers only the task's assigned model",
            },
            source="sentinel sidecar",
        )


async def end_sidecar_sample(sample_uuid: str, cancelled: bool = False) -> None:
    """Tell the sidecars a sample's calls went through that it has ended, after its final scoring; a cancelled sample's aren't told, and drop it at their run expiry."""
    sidecars = task_sidecars()
    if sidecars is not None:
        # The sample may leave calls paused for a person. Cancel them at
        # their sidecars.
        from ._review import cancel_paused_calls

        await cancel_paused_calls(sample_uuid)
        await sidecars.end_sample(sample_uuid, tell=not cancelled)
