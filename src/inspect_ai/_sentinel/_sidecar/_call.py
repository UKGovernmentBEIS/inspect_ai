"""An agent call that goes through a sentinel sidecar."""

import json
from typing import TYPE_CHECKING, NamedTuple

from inspect_ai.model._generate_config import GenerateConfig

from .._config import SentinelProxy
from .._scope import current_origin, is_agent_turn
from ._endpoint import Sidecar
from ._task import SampleFacts, attempt_number, task_sidecars

if TYPE_CHECKING:
    from inspect_ai.model._model import Model

INSPECT_CONTEXT = "x-inspect-context"
"""The header that names the sample an agent call is for."""


class SidecarCall(NamedTuple):
    """An agent call to an endpoint where a sidecar answered the probe."""

    sidecar: Sidecar
    header: str
    """`x-inspect-context`, naming the call's sample and attempt."""
    mode: SentinelProxy

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
        return None

    sidecars.called_through(active.sample_uuid, attempt_number(active), sidecar)
    await sidecars.complete_registration(
        sidecar,
        SampleFacts(
            sample_id=state.sample_id,
            sample_description=active.sample.description,
            sample_input=state.input,
            metadata=state.metadata,
        ),
    )
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
    return SidecarCall(sidecar, header, sidecars.mode)


async def end_sidecar_sample(sample_uuid: str) -> None:
    """Tell the sidecars a sample's calls went through that it has ended, after its final scoring."""
    sidecars = task_sidecars()
    if sidecars is not None:
        await sidecars.end_sample(sample_uuid)
