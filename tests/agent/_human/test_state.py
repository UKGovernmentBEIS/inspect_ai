from unittest import mock

from inspect_ai.agent._human.state import HumanAgentState


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
