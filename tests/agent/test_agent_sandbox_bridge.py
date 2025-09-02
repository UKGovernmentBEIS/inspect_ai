import pytest
from test_helpers.utils import (
    flaky_retry,
    run_example,
    skip_if_no_anthropic,
    skip_if_no_docker,
    skip_if_no_openai,
)


@pytest.mark.slow
@skip_if_no_openai
@skip_if_no_docker
@flaky_retry(max_retries=3)  # docker compose sometimes fails for undebugged reasons
def test_agent_sandbox_bridge_openai():
    log = run_example("bridge/codex/task.py", "openai/gpt-5")[0]
    assert log.status == "success"


@pytest.mark.slow
@skip_if_no_anthropic
@skip_if_no_docker
@flaky_retry(max_retries=3)  # docker compose sometimes fails for undebugged reasons
def test_agent_sandbox_bridge_anthropic():
    log = run_example("bridge/claude/task.py", "anthropic/claude-sonnet-4-20250514")[0]
    assert log.status == "success"
