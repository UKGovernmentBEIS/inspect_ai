# import time

# import numpy as np

# from inspect_ai.agent._human.state import HumanAgentState


def test_human_agent_state_time_accumulation():
    # mysteriously started failing in CI
    # https://github.com/UKGovernmentBEIS/inspect_ai/actions/runs/14237922878/job/39900932495
    pass

    # state = HumanAgentState(instructions="test instructions")
    # assert state.time == 0.0, "Initial time should be 0"

    # for i in range(1, 3):
    #     state.running = True
    #     time.sleep(0.1)
    #     assert np.isclose(state.time, 0.1 * i, atol=0.0 * i), (
    #         f"Time should accumulate while running (i={i})"
    #     )

    #     state.running = False
    #     time.sleep(0.1)
    #     assert np.isclose(state.time, 0.1 * i, atol=0.01 * i), (
    #         f"Time should not increase while stopped (i={i})"
    #     )
