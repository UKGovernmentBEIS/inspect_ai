import functools
import os
from logging import getLogger
from typing import Any

from inspect_ai._util._async import tg_collect
from inspect_ai._util.registry import registry_info, registry_unqualified_name
from inspect_ai.hooks._hooks import Hooks, SampleStart, hooks
from inspect_ai.util._sandbox.context import (
    record_sample_sandbox_fingerprint,
    sandbox_environments_context_var,
)
from inspect_ai.util._sandbox.environment import (
    SandboxConnection,
    SandboxEnvironment,
    SandboxFingerprint,
)

from ._probes import ProbeContext, ProbeFn, fingerprint_probes

logger = getLogger(__name__)


@hooks(
    name="sandbox_fingerprint",
    description="Capture the resolved runtime fingerprint of each sandbox.",
)
class SandboxFingerprintHook(Hooks):
    """Probe each live sandbox at sample start and record its runtime fingerprint.

    Auto-on (opt-out via `INSPECT_DISABLE_SANDBOX_FINGERPRINT`). Records the
    resolved image digest, OS, kernel, packages, and network profile per
    environment so drift between runs with identical recipes is detectable.
    """

    def enabled(self) -> bool:
        return not os.environ.get("INSPECT_DISABLE_SANDBOX_FINGERPRINT")

    async def on_sample_start(self, data: SampleStart) -> None:
        environments = sandbox_environments_context_var.get(None)
        if not environments:
            return
        for name, environment in environments.items():
            try:
                fingerprint = await self._fingerprint(environment)
                record_sample_sandbox_fingerprint(name, fingerprint)
            except Exception as ex:
                logger.warning(f"Failed to fingerprint sandbox '{name}': {ex}")

    async def _fingerprint(self, environment: SandboxEnvironment) -> SandboxFingerprint:
        connection = await self._connection(environment)
        context = ProbeContext(sandbox=environment, connection=connection)
        results = await tg_collect(
            [
                functools.partial(_run_probe, probe, context)
                for probe in fingerprint_probes().values()
            ]
        )

        fields: dict[str, Any] = {"metadata": {}}
        for result in results:
            for key, value in result.items():
                if key == "metadata":
                    collisions = fields["metadata"].keys() & value.keys()
                    if collisions:
                        logger.warning(
                            f"Sandbox fingerprint probes produced colliding "
                            f"metadata keys: {sorted(collisions)}"
                        )
                    fields["metadata"].update(value)
                else:
                    fields[key] = value

        return SandboxFingerprint(
            type=connection.type if connection else _sandbox_type(environment),
            **fields,
        )

    async def _connection(
        self, environment: SandboxEnvironment
    ) -> SandboxConnection | None:
        try:
            return await environment.connection()
        except Exception:
            return None


async def _run_probe(probe: ProbeFn, context: ProbeContext) -> dict[str, Any]:
    try:
        return await probe(context)
    except Exception as ex:
        logger.warning(f"Sandbox fingerprint probe failed: {ex}")
        return {}


def _sandbox_type(environment: SandboxEnvironment) -> str:
    underlying = getattr(environment, "_sandbox", environment)
    try:
        return registry_unqualified_name(registry_info(underlying))
    except Exception:
        return underlying.__class__.__name__
