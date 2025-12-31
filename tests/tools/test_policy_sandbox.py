import pytest
from inspect_ai.util._sandbox.policy import PolicySandboxEnvironment, SandboxPolicy
from inspect_ai.util._sandbox.environment import SandboxEnvironment, ExecResult, SandboxConnection
from inspect_ai._util.error import SandboxPolicyViolationError

class MockSandbox(SandboxEnvironment):
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        return ExecResult(success=True, returncode=0, stdout="mock", stderr="")

    async def write_file(self, file: str, contents: str | bytes) -> None:
        pass

    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        return "mock" if text else b"mock"

    async def connection(self, *, user: str | None = None) -> SandboxConnection:
        return SandboxConnection(type="mock", command="mock")
    
    @classmethod
    async def sample_cleanup(cls, *args, **kwargs):
        pass

class StrictPolicy(SandboxPolicy):
    def check_exec(self, cmd: list[str]) -> None:
        if "bad" in cmd:
            raise SandboxPolicyViolationError("Exec blocked")

    def check_write_file(self, file: str) -> None:
        if "bad" in file:
            raise SandboxPolicyViolationError("Write blocked")

    def check_read_file(self, file: str) -> None:
        if "bad" in file:
            raise SandboxPolicyViolationError("Read blocked")

@pytest.mark.asyncio
async def test_policy_blocks_execution():
    sandbox = MockSandbox()
    policy = StrictPolicy()
    env = PolicySandboxEnvironment(sandbox, policy)

    # Allowed
    assert (await env.exec(["good"])).success

    # Blocked
    with pytest.raises(SandboxPolicyViolationError):
        await env.exec(["bad"])

@pytest.mark.asyncio
async def test_policy_blocks_file_io():
    sandbox = MockSandbox()
    policy = StrictPolicy()
    env = PolicySandboxEnvironment(sandbox, policy)

    # Allowed
    await env.write_file("good.txt", "content")
    await env.read_file("good.txt")

    # Blocked
    with pytest.raises(SandboxPolicyViolationError):
        await env.write_file("bad.txt", "content")
    
    with pytest.raises(SandboxPolicyViolationError):
        await env.read_file("bad.txt")

def test_as_type_delegation():
    sandbox = MockSandbox()
    policy = StrictPolicy()
    env = PolicySandboxEnvironment(sandbox, policy)

    # Delegate to inner
    assert env.as_type(MockSandbox) is sandbox
    
    # Self reference
    assert env.as_type(PolicySandboxEnvironment) is env

    # Error
    with pytest.raises(TypeError):
        env.as_type(StrictPolicy) # Random class

@pytest.mark.asyncio
async def test_wrapper_preserves_connection():
    sandbox = MockSandbox()
    policy = StrictPolicy()
    env = PolicySandboxEnvironment(sandbox, policy)
    
    conn = await env.connection()
    assert conn.type == "mock"

@pytest.mark.asyncio
async def test_cleanup_is_noop_on_wrapper(mocker):
    # Verify PolicySandboxEnvironment.sample_cleanup does nothing
    # and doesn't crash.
    # Note: Real cleanup happens because inspect framework calls cleanup on the resolved environments,
    # and if they were wrapped, the cleanup function of the wrapper is called.
    # But PolicySandboxEnvironment.sample_cleanup implementation is empty pass.
    
    await PolicySandboxEnvironment.sample_cleanup("task", None, {}, False)
    # If we reached here, it didn't crash.
