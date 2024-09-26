"""A web dm_env (to be run in a docker container).

This environment allows the agent to interact with a web browser via text
commands.
"""

import json
import re
import socket
from typing import Any

import dm_env
from dm_env import specs


class WebEnvironment(dm_env.Environment):
    """A DM environment where an agent controls a web browser."""

    DEFAULT_OBSERVATIONS = ["error", "info"]

    def __init__(self):
        """Initializes the environment."""
        super().__init__()
        self._last_error = ""
        self._hostname = socket.gethostname()
        self._required_observations = self.DEFAULT_OBSERVATIONS

    def reset(self) -> dm_env.TimeStep:
        """Starts a new sequence and returns the first `TimeStep` of this sequence.

        Returns:
          A `TimeStep` namedtuple containing:
            step_type: Always `StepType.FIRST`.
            reward: Always None.
            discount: Always None.
            observation: The initial system state.
        """
        return dm_env.restart(observation=self.get_observations())

    def step(self, action: str) -> dm_env.TimeStep:
        """Updates the environment according to the action and returns a `TimeStep`.

        Args:
          action: the command to execute in the web environment.

        Returns:
          A `TimeStep` namedtuple containing:
            step_type: A `StepType` value.
            reward: always 0.
            discount: always 1.
            observation: the current web browser state rendered as text.
        """
        # Process the incoming command.
        # Commands are always in the form [COMMAND] [args]
        parts = re.findall(r"<[^>]*>|[^<\s]+", action)
        if parts:
            command, *args = parts
        else:
            command = ""
            args = []

        self._last_error = ""

        match command.lower():
            # TODO: Add support for more commands.
            case _:
                self._last_error = f'\n\nInvalid command: "{command} {args}"'

        return dm_env.transition(
            reward=0.0,
            observation=self.get_observations(),
        )

    def observation_spec(self) -> dict[str, specs.Array]:
        """Defines the observations provided by the environment.

        Returns:
          The observation specification.
        """
        obs_shapes = {
            "error": specs.Array(shape=(), dtype=str, name="error"),
            "info": specs.Array(shape=(), dtype=str, name="info"),
        }
        return {key: obs_shapes[key] for key in self._required_observations}

    def action_spec(self) -> specs.Array:
        """Defines the actions that should be provided to `step`.

        Returns:
          The action specification.
        """
        return specs.Array(shape=(), dtype=str, name="command")

    @property
    def info(self) -> dict[str, str]:
        """Returns a dictionary of information about this environment."""
        out = {
            "hostname": self._hostname,
        }
        return out

    def get_observations(
        self, required_observations: list[str] | None = None
    ) -> dict[str, Any]:
        """Returns dictionary containing each requested observations.

        Args:
          required_observations: List of observations to include in the output. If
            non-none overrides the default `self._requested_observations`.
        """
        obs_map = {
            "error": lambda: self._last_error,
            "info": lambda: json.dumps(self.info),
        }

        result = {}
        required_observations = (
            self._required_observations
            if required_observations is None
            else required_observations
        )
        for obs_name in required_observations:
            result[obs_name] = obs_map[obs_name]()

        return result
