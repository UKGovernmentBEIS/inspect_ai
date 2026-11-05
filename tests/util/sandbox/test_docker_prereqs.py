import json
from typing import Any

import pytest

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._sandbox.docker import prereqs
from inspect_ai.util._subprocess import ExecResult


def _docker_version(
    *,
    client: str = "28.0.0",
    server: str | None = "24.0.6",
    include_server: bool = True,
) -> str:
    version: dict[str, Any] = {"Client": {"Version": client, "ApiVersion": "1.48"}}
    if include_server:
        version["Server"] = (
            {"Version": server, "ApiVersion": "1.43"} if server else None
        )
    return json.dumps(version)


async def test_validate_docker_engine_uses_server_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def subprocess(cmd: list[str]) -> ExecResult[str]:
        return ExecResult(
            success=True,
            returncode=0,
            stdout=_docker_version(server="23.0.0"),
            stderr="",
        )

    monkeypatch.setattr(prereqs, "subprocess", subprocess)

    with pytest.raises(
        PrerequisiteError,
        match=r"Docker Engine >= 24\.0\.6 \(current: 23\.0\.0\)",
    ):
        await prereqs.validate_docker_engine()


async def test_validate_docker_engine_accepts_current_server_with_old_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def subprocess(cmd: list[str]) -> ExecResult[str]:
        return ExecResult(
            success=True,
            returncode=0,
            stdout=_docker_version(client="23.0.0", server="24.0.6"),
            stderr="",
        )

    monkeypatch.setattr(prereqs, "subprocess", subprocess)

    await prereqs.validate_docker_engine()


@pytest.mark.parametrize("include_server", [False, True])
async def test_validate_docker_engine_explains_missing_server_metadata(
    monkeypatch: pytest.MonkeyPatch,
    include_server: bool,
) -> None:
    async def subprocess(cmd: list[str]) -> ExecResult[str]:
        return ExecResult(
            success=True,
            returncode=0,
            stdout=_docker_version(server=None, include_server=include_server),
            stderr="",
        )

    monkeypatch.setattr(prereqs, "subprocess", subprocess)

    with pytest.raises(
        PrerequisiteError, match="did not report server version metadata"
    ):
        await prereqs.validate_docker_engine()
