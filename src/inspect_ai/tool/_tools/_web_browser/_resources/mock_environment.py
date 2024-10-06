"""A mock dm_env for unit testing."""

from typing import Any

import dm_env
from dm_env import specs


class MockEnvironment(dm_env.Environment):
    """A Mock DM environment."""

    def __init__(self):
        """Initializes the environment."""
        super().__init__()
        self._last_command = ""

    def reset(self) -> dm_env.TimeStep:
        """Starts a new sequence and returns the first `TimeStep` of this sequence."""
        self._last_command = ""
        return dm_env.restart(observation=self.get_observations())

    def step(self, action: list[str]) -> dm_env.TimeStep:
        """Updates the environment according to the action and returns a `TimeStep`."""
        self._last_command = " ".join(action)
        return dm_env.transition(
            reward=0.0,
            observation=self.get_observations(),
        )

    def observation_spec(self) -> dict[str, specs.Array]:
        """Defines the observations provided by the environment."""
        obs_shapes = {
            "last_command": specs.Array(shape=(), dtype=str, name="last_command"),
        }
        return obs_shapes

    def action_spec(self) -> specs.Array:
        """Defines the actions that should be provided to `step`."""
        return specs.Array(shape=(), dtype=str, name="command")

    def get_observations(self) -> dict[str, Any]:
        """Returns dictionary containing observations."""
        return {
            "last_command": self._last_command,
        }
