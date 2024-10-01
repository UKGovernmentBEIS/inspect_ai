"""Environment service that allows clients to run shell commands in steps."""

import threading
from typing import Any, Iterable, Type

import dm_env
import grpc
import immutabledict
from dm_env import specs
from dm_env_rpc.v1 import (
    dm_env_rpc_pb2,
    dm_env_rpc_pb2_grpc,
    dm_env_utils,
    spec_manager,
)
from google.rpc import code_pb2, status_pb2

_WORLD_NAME = "WebBrowser"


class EnvironmentSpec:
    """Specifications for a dm_environment.

    This class holds action and observation specs, as well as the required
    managers to pack actions and observations.
    """

    def __init__(self, env: dm_env.Environment):
        convert = dm_env_utils.dm_env_spec_to_tensor_spec

        # We support either a single spec, of flat dictionary of specs.
        # In the dictionary case we need to map names to unique IDs.
        env_obs_spec: dict[str, Any] = env.observation_spec()
        if isinstance(env_obs_spec, specs.Array):
            self.observation_spec = {1: convert(env_obs_spec)}
        else:
            self.observation_spec = {}
            for i, obs_spec in enumerate(env_obs_spec.values()):
                self.observation_spec[i + 1] = convert(obs_spec)

        assert isinstance(
            env.action_spec(), specs.Array
        ), "Only a single action type is supported."
        self.action_spec = {1: convert(env.action_spec())}

        self.observation_manager = spec_manager.SpecManager(self.observation_spec)
        self.action_manager = spec_manager.SpecManager(self.action_spec)


class EnvironmentService(dm_env_rpc_pb2_grpc.EnvironmentServicer):
    """Runs the environment as a gRPC EnvironmentServicer."""

    def __init__(self, env_type: Type[dm_env.Environment]) -> None:
        """Initializes the environment.

        Args:
          env_type: A dm_env class to serve.
        """
        self._env_type = env_type
        self._env: dm_env.Environment = None
        self._spec: EnvironmentSpec = None
        self._lock = threading.Lock()
        # A server can only have one client connected at a time for now.
        self._has_joined_client = False

        self._handlers = immutabledict.immutabledict(
            {
                dm_env_rpc_pb2.CreateWorldRequest: self._handle_create_world_request,
                dm_env_rpc_pb2.JoinWorldRequest: self._handle_join_world_request,
                dm_env_rpc_pb2.LeaveWorldRequest: self._handle_leave_world_request,
                dm_env_rpc_pb2.DestroyWorldRequest: self._handle_destroy_world_request,
                dm_env_rpc_pb2.ResetRequest: self._handle_reset_request,
                dm_env_rpc_pb2.StepRequest: self._handle_step_request,
            }
        )

    def Process(
        self,
        request_iterator: Iterable[dm_env_rpc_pb2.EnvironmentRequest],
        context: grpc.ServicerContext,
    ):
        """Processes incoming EnvironmentRequests.

        For each EnvironmentRequest the internal message is extracted and handled.
        The response for that message is then placed in a EnvironmentResponse which
        is returned to the client.

        An error status will be returned if an unknown message type is received or
        if the message is invalid for the current world state.


        Args:
          request_iterator: Message iterator provided by gRPC.
          context: Context provided by gRPC.

        Yields:
          EnvironmentResponse: Response for each incoming EnvironmentRequest.
        """
        for request in request_iterator:
            environment_response = dm_env_rpc_pb2.EnvironmentResponse()
            try:
                message_type = request.WhichOneof("payload")
                internal_request = getattr(request, message_type)
                response = self._handlers[type(internal_request)](internal_request)
                getattr(environment_response, message_type).CopyFrom(response)
            except Exception as e:  # pylint: disable=broad-except
                environment_response.error.CopyFrom(
                    status_pb2.Status(code=code_pb2.INTERNAL, message=str(e))
                )
            yield environment_response

    def _validate_settings(self, settings, valid_settings):
        """Validate the provided settings with list of valid setting keys."""
        unrecognized_settings = [
            setting for setting in settings if setting not in valid_settings
        ]

        if unrecognized_settings:
            raise ValueError(
                "Unrecognized settings provided! Invalid settings:"
                f" {unrecognized_settings}"
            )

    def _add_spec_to_response(self, response: dm_env_rpc_pb2.EnvironmentResponse):
        """Modifies given respose to include action/observation specifications."""
        for uid, action in self._spec.action_spec.items():
            response.specs.actions[uid].CopyFrom(action)
        for uid, observation in self._spec.observation_spec.items():
            response.specs.observations[uid].CopyFrom(observation)

    def _handle_create_world_request(
        self, request: dm_env_rpc_pb2.CreateWorldRequest
    ) -> dm_env_rpc_pb2.CreateWorldResponse:
        """Handles create_world requests."""
        self._validate_settings(request.settings, [])
        del request
        with self._lock:
            self._env = self._env_type()
            self._spec = EnvironmentSpec(self._env)
        return dm_env_rpc_pb2.CreateWorldResponse(world_name=_WORLD_NAME)

    def _handle_join_world_request(
        self, request: dm_env_rpc_pb2.JoinWorldRequest
    ) -> dm_env_rpc_pb2.JoinWorldResponse:
        """Handles join_world requests."""
        self._validate_settings(request.settings, [])
        response = dm_env_rpc_pb2.JoinWorldResponse()
        with self._lock:
            if request.world_name != _WORLD_NAME:
                raise ValueError(
                    f"Joining with the wrong world_name {request.world_name}"
                )
            if self._has_joined_client:
                raise ValueError("Only one client can join the environment at a time.")
            self._has_joined_client = True
            self._add_spec_to_response(response)
        del request
        return response

    def _handle_leave_world_request(
        self, request: dm_env_rpc_pb2.LeaveWorldRequest
    ) -> dm_env_rpc_pb2.LeaveWorldResponse:
        """Handles leave_world requests."""
        del request
        with self._lock:
            self._has_joined_client = False

        response = dm_env_rpc_pb2.LeaveWorldResponse()
        return response

    def _handle_destroy_world_request(
        self, request: dm_env_rpc_pb2.DestroyWorldRequest
    ) -> dm_env_rpc_pb2.DestroyWorldResponse:
        """Handles destroy_world requests."""
        del request
        with self._lock:
            if self._has_joined_client:
                raise ValueError("Destroying environment which has joined client.")
            if self._env is None:
                raise ValueError("Can not destroy uncreated environment.")
            self._env.close()
            self._env = None
        response = dm_env_rpc_pb2.DestroyWorldResponse()
        return response

    def _handle_reset_request(
        self, request: dm_env_rpc_pb2.ResetRequest
    ) -> dm_env_rpc_pb2.ResetResponse:
        """Handles reset requests."""
        response = dm_env_rpc_pb2.ResetResponse()
        with self._lock:
            assert self._env, "Please create world before calling reset."
            self._env.reset()
            self._add_spec_to_response(response)
        return response

    def _handle_step_request(
        self, request: dm_env_rpc_pb2.StepRequest
    ) -> dm_env_rpc_pb2.StepResponse:
        """Handles step requests.

        Args:
          request: The request, which should contain a 'command' entry.

        Returns:
          Response including requested observations.

        Raises:
          KeyError: If the requested observation is not in the list of available
            observations.
        """
        with self._lock:
            assert self._has_joined_client, "Please join world before calling step."

            action = self._spec.action_manager.unpack(request.actions)

            if "command" in action:
                command = action["command"]
            else:
                # For some reason dm_env calls step without actions after a reset.
                command = ""

            timestep: dm_env.TimeStep = self._env.step(command)

            packed_observations = self._spec.observation_manager.pack(
                timestep.observation
            )

            match timestep.step_type:
                case dm_env.StepType.MID:
                    step_state = dm_env_rpc_pb2.RUNNING
                case dm_env.StepType.LAST:
                    step_state = dm_env_rpc_pb2.TERMINATED
                case _:
                    raise ValueError(f"Unsupported step type {timestep.step_type}.")

            response = dm_env_rpc_pb2.StepResponse(state=step_state)
            for requested_observation in request.requested_observations:
                if requested_observation not in packed_observations:
                    name = self._spec.observation_manager.uid_to_name(
                        requested_observation
                    )
                    raise KeyError(f"Requested observation not found: {name}")
                response.observations[requested_observation].CopyFrom(
                    packed_observations[requested_observation]
                )

        return response
