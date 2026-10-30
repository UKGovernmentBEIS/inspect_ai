"""Logged samples keep the message id contract (see `test_helpers.message_ids`).

Generated logs are checked where they are made (e.g. `tests/agent/test_agent_message_ids.py`).
"""

from pathlib import Path

import pytest
from test_helpers.message_ids import assert_message_ids

from inspect_ai.log import read_eval_log

TESTS = Path(__file__).parent.parent
FIXTURES = sorted(
    [
        *(TESTS / "log" / "test_eval_log").glob("*.eval"),
        *(TESTS / "log" / "test_eval_log").glob("*.json"),
        *(TESTS / "analysis" / "test_logs").glob("*.json"),
    ]
)


@pytest.mark.parametrize("path", FIXTURES, ids=[path.name for path in FIXTURES])
def test_fixture_logs_keep_the_message_id_contract(path: Path) -> None:
    log = read_eval_log(str(path), resolve_attachments=True)
    for sample in log.samples or []:
        assert_message_ids(sample)
