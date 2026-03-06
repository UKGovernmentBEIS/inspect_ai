"""Legacy tool support system compatibility layer.

This module provides compatibility functions for interacting with the legacy
inspect_tool_support system, which temporarily handles web browser functionality
while the main inspect_sandbox_tools system handles all other tools (bash_session,
text_editor, MCP).

The legacy system uses Docker images built from Dockerfiles for deployment, while
the main system uses runtime executable injection. Both systems communicate via
JSON-RPC but have different deployment mechanisms and container requirements.

This module will be deprecated once the web browser functionality is fully
migrated to the PyInstaller-based executable injection approach.
"""

from textwrap import dedent

import semver

from inspect_ai._util._json_rpc import exec_scalar_request
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool._sandbox_tools_utils._error_mapper import (
    SandboxToolsErrorMapper,
)
from inspect_ai.util._sandbox._json_rpc_transport import SandboxJSONRPCTransport
from inspect_ai.util._sandbox.context import sandbox_with
from inspect_ai.util._sandbox.environment import SandboxEnvironment

LEGACY_SANDBOX_CLI = "inspect-tool-support"
_INSPECT_TOOL_SUPPORT_IMAGE_DOCKERHUB = "aisiuk/inspect-tool-support"
_FIRST_PUBLISHED_VERSION = semver.Version.parse("0.1.6")


async def legacy_tool_support_sandbox(
    tool_name: str, *, sandbox_name: str | None = None
) -> tuple[SandboxEnvironment, semver.Version]:
    if sb := await sandbox_with(LEGACY_SANDBOX_CLI, True, name=sandbox_name):
        current_version = await _get_sandbox_tool_support_version(sb)
        return (sb, current_version)

    # This sort of programmatic sentence building will not cut it if we ever
    # support other languages.
    raise PrerequisiteError(
        dedent(f"""
            The {tool_name} service was not found in {"any of the sandboxes" if sandbox_name is None else f"the sandbox '{sandbox_name}'"} for this sample. Please add the {tool_name} to your configuration.

            For example, the following Docker compose file uses the {_INSPECT_TOOL_SUPPORT_IMAGE_DOCKERHUB} reference image as its default sandbox:

            services:
              default:
                image: "{_INSPECT_TOOL_SUPPORT_IMAGE_DOCKERHUB}"
                init: true

            Alternatively, you can include the service into your own Dockerfile:

            ENV PATH="$PATH:/opt/inspect_tool_support/bin"
            RUN python -m venv /opt/inspect_tool_support && \\
                /opt/inspect_tool_support/bin/pip install inspect-tool-support && \\
                /opt/inspect_tool_support/bin/inspect-tool-support post-install
            """).strip()
    )


async def _get_sandbox_tool_support_version(
    sandbox: SandboxEnvironment,
) -> semver.Version:
    try:
        return semver.Version.parse(
            await exec_scalar_request(
                method="version",
                params={},
                result_type=str,
                transport=SandboxJSONRPCTransport(sandbox, LEGACY_SANDBOX_CLI),
                error_mapper=SandboxToolsErrorMapper,
                timeout=5,
            )
        )
    except RuntimeError as rte:
        if "-32601" in str(rte):
            # The container doesn't even have a version method. The first version
            # published was 0.1.6, so we'll have to assume it was that old.
            return _FIRST_PUBLISHED_VERSION
        raise rte
