from concurrent import futures

import dm_env_servicer
import grpc
import mock_environment
from dm_env_rpc.v1 import (
    compliance,
    dm_env_rpc_pb2,
    dm_env_rpc_pb2_grpc,
    tensor_utils,
)
from dm_env_rpc.v1 import connection as dm_env_rpc_connection


class ServerConnection:
    def __init__(self):
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
        servicer = dm_env_servicer.EnvironmentService(mock_environment.MockEnvironment)
        dm_env_rpc_pb2_grpc.add_EnvironmentServicer_to_server(servicer, self._server)
        port = self._server.add_secure_port("[::]:0", grpc.local_server_credentials())
        self._server.start()

        self._channel = grpc.secure_channel(
            f"[::]:{port}", grpc.local_channel_credentials()
        )
        grpc.channel_ready_future(self._channel).result()

        self.connection = dm_env_rpc_connection.Connection(self._channel)

    def close(self):
        self.connection.close()
        self._channel.close()
        self._server.stop(grace=None)


class JoinedServerConnection(ServerConnection):
    def __init__(self):
        super().__init__()
        response = self.connection.send(dm_env_rpc_pb2.CreateWorldRequest())
        self.world_name = response.world_name

        response = self.connection.send(
            dm_env_rpc_pb2.JoinWorldRequest(world_name=self.world_name)
        )
        self.specs = response.specs

    def close(self):
        try:
            self.connection.send(dm_env_rpc_pb2.LeaveWorldRequest())
            self.connection.send(
                dm_env_rpc_pb2.DestroyWorldRequest(world_name=self.world_name)
            )
        finally:
            super().close()


class DmEnvRpcStepTest(compliance.Step):
    @property
    def connection(self):
        return self._server_connection.connection

    @property
    def specs(self):
        return self._server_connection.specs

    def setUp(self):
        super().setUp()
        self._server_connection = JoinedServerConnection()

    def tearDown(self):
        self._server_connection.close()
        super().tearDown()

    # Overriding this test since this behaviour does not make sence
    # for our use case.
    def test_first_step_actions_are_ignored(self):
        pass


class DmEnvRpcCreateAndDestoryWorldTest(compliance.CreateDestroyWorld):
    @property
    def connection(self):
        return self._server_connection.connection

    @property
    def required_world_settings(self):
        """A string to Tensor mapping of the minimum set of required settings."""
        return {}

    @property
    def invalid_world_settings(self):
        """World creation settings which are invalid in some way."""
        return {"invalid_setting": tensor_utils.pack_tensor(123)}

    @property
    def has_multiple_world_support(self):
        """Does the server support creating more than one world?"""
        return True

    def setUp(self):
        self._server_connection = ServerConnection()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._server_connection.close()


class DmEnvRpcJoinAndLeaveWorldTest(compliance.JoinLeaveWorld):
    @property
    def connection(self):
        return self._server_connection.connection

    @property
    def world_name(self):
        return self._world_name

    @property
    def invalid_join_settings(self):
        return {"invalid_setting": tensor_utils.pack_tensor(123)}

    def setUp(self):
        self._server_connection = ServerConnection()
        response = self.connection.send(dm_env_rpc_pb2.CreateWorldRequest())
        self._world_name = response.world_name
        super().setUp()

    def tearDown(self):
        super().tearDown()
        try:
            self.connection.send(
                dm_env_rpc_pb2.DestroyWorldRequest(world_name=self.world_name)
            )
        finally:
            self._server_connection.close()
