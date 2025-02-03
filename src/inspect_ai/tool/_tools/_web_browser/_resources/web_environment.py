"""A web dm_env (to be run in a docker container).

This environment allows the agent to interact with a web browser via text
commands.
"""

import functools
import json
import socket
import traceback
from typing import Any

import dm_env
import playwright_crawler
from dm_env import specs


class WebEnvironment(dm_env.Environment):
    """A DM environment where an agent controls a web browser."""

    DEFAULT_OBSERVATIONS = ["web_url", "web_at", "error", "info"]

    def __init__(self, browser_context):
        """Initializes the environment."""
        super().__init__()
        self._web: playwright_crawler.PlaywrightCrawler = (
            playwright_crawler.PlaywrightCrawler(browser_context)
        )
        self._last_error = ""
        self._hostname = socket.gethostname()
        self._required_observations = self.DEFAULT_OBSERVATIONS
        self._selected_node_id: str | None = None

    def reset(self):
        # We're not using reset at the moment
        pass

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
        command, *args = action.split(" ")

        self._last_error = ""
        self._selected_node_id = None
        command_l = command.lower()

        try:
            if not command_l:  # Equivalent to case '':
                # Treat an empty command as a NOOP.
                pass
            elif command_l == "web_go" and len(args) > 0:
                self._web.go_to_page(args[0])
            elif command_l == "web_click" and len(args) > 0:
                self._web.click(args[0])
            elif command_l == "web_scroll" and len(args) > 0:
                self._web.scroll(args[0])
            elif command_l == "web_forward":
                self._web.forward()
            elif command_l == "web_back":
                self._web.back()
            elif command_l == "web_refresh":
                self._web.refresh()
            elif command_l == "web_type" and len(args) > 0:
                self._web.type(args[0], " ".join(args[1:]))
            elif command_l == "web_type_submit" and len(args) > 0:
                # Clear any existing text, type the new text, and then press enter.
                self._web.clear(args[0])
                self._web.type(args[0], " ".join(args[1:]) + "\n")
            else:
                self._last_error = f'\n\nInvalid command: "{action}"'

        except Exception as e:
            # Broard exception as we don't know what kind of error the crawler might
            # generate. If an error does occur pass it back as part of the
            # observation.
            traceback_info = traceback.extract_tb(e.__traceback__)[-1]
            self._last_error = f"\nERROR:{e}\n{traceback_info}"

        try:
            # The update might fail due to async issues.
            # TODO: Instead of a catch-all, make  the webcrawler more
            # robust dynamic or malformed elements.
            self._web.update()

            # If there's a cookies message click to sort it out.
            self._auto_click_cookies()

        except Exception as e:  # pylint: disable=broad-exception-caught
            traceback_info = traceback.extract_tb(e.__traceback__)[-1]
            self._last_error = f"\nUPDATE ERROR:{e}\n{traceback_info}"

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
            "web_url": specs.Array(shape=(), dtype=str, name="web_url"),
            "web_at": specs.Array(shape=(), dtype=str, name="web_at"),
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

    def close(self) -> None:
        """Closes the environment."""
        self._web.close()

    @property
    def info(self) -> dict[str, str]:
        """Returns a dictionary of information about this environment."""
        out = {
            "hostname": self._hostname,
        }
        if self._selected_node_id is not None:
            out["node_id"] = self._selected_node_id
        return out

    def get_observations(
        self, required_observations: list[str] | None = None
    ) -> dict[str, Any]:
        """Returns dictionary containing each requested observations.

        Args:
          required_observations: List of observations to include in the output. If
            non-none overrides the default `self._requested_observations`.
        """

        def render(mode):
            return functools.partial(self._web.render, mode)

        obs_map = {
            "web_url": lambda: self._web.url.split("?")[0],
            "web_at": render(playwright_crawler.CrawlerOutputFormat.AT),
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

    def _auto_click_cookies(self):
        """Autoclick any cookies popup."""
        try:
            accept_node = self._web.lookup_node("<Accept all>")
            self._web.click(accept_node.node_id)
            self._web.update()
        except ValueError:
            # Node not found.
            pass
