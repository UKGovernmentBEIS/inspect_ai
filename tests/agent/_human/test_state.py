import math
from typing import cast
from unittest import mock

from inspect_ai.agent._human.state import HumanAgentState, IntermediateScoring
from inspect_ai.scorer._metric import Score
from inspect_ai.util._store import Store, store_jsonable


@mock.patch("time.time", autospec=True)
def test_human_agent_state_time_accumulation(mock_time):
    mock_time.return_value = 12345.0

    state = HumanAgentState(instructions="test instructions")
    assert state.time == 0.0, "Initial time should be 0"

    periods = [2, 4.5, 10]
    expected_times = [2, 6.5, 16.5]

    for period, expected_time in zip(periods, expected_times):
        state.running = True
        mock_time.return_value += period
        assert state.time == expected_time, "Time should accumulate while running"

        state.running = False
        mock_time.return_value += period
        assert state.time == expected_time, "Time should not accumulate while stopped"


def test_intermediate_scoring_nan_survives_store_round_trip():
    """NaN scores in HumanAgentState.scorings survive store serialization.

    store_jsonable() dumps each IntermediateScoring directly (its own dump
    root, before EvalSample ever sees the store), so without the constants
    config a NaN list element becomes None and reload leaves a raw dict in
    scorings (list[IntermediateScoring] validation fails).
    """
    state = HumanAgentState(instructions="test")
    state.scorings = [
        IntermediateScoring(time=1.0, scores=[Score(value=[float("nan"), 1.0])])
    ]

    jsonable = store_jsonable(state.store)
    restored = HumanAgentState(store=Store(jsonable), instructions="test")

    assert isinstance(restored.scorings[0], IntermediateScoring)
    value = restored.scorings[0].scores[0].value
    assert isinstance(value, list)
    assert math.isnan(cast(float, value[0]))
    assert value[1] == 1.0
