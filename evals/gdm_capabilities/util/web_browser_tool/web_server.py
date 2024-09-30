"""Simple script to run and test the RPC server."""

from concurrent import futures

import dm_env_servicer
import grpc
import web_environment
from dm_env_rpc.v1 import connection as dm_env_connection
from dm_env_rpc.v1 import dm_env_rpc_pb2, dm_env_rpc_pb2_grpc

_DM_ENV_BASE_PORT = 9443


def main():
    # Keep connection open even when empty data pings are received. This is
    # required to avoid a "too many pings" error.
    options = [
        ("grpc.keepalive_permit_without_calls", 0),
        ("grpc.keepalive_timeout_ms", 20000),
        ("grpc.http2.max_pings_without_data", 0),
        ("grpc.http2.max_ping_strikes", 0),
        ("grpc.http2.min_recv_ping_interval_without_data_ms", 0),
    ]
    grpc_server = grpc.server(
        # We must have a single worker thread since the web environment is not
        # thread safe.
        futures.ThreadPoolExecutor(max_workers=1),
        options=options,
    )
    env_service = dm_env_servicer.EnvironmentService(web_environment.WebEnvironment)
    dm_env_rpc_pb2_grpc.add_EnvironmentServicer_to_server(env_service, grpc_server)

    grpc_server.add_secure_port(
        f"localhost:{_DM_ENV_BASE_PORT}", grpc.local_server_credentials()
    )

    grpc_server.start()

    # Creating a world with the headless browser after the server started.
    channel = grpc.secure_channel(
        f"localhost:{_DM_ENV_BASE_PORT}",
        grpc.local_channel_credentials(),
        options=options,
    )
    connection = dm_env_connection.Connection(channel)
    connection.send(dm_env_rpc_pb2.CreateWorldRequest())
    connection.close()

    grpc_server.wait_for_termination()


if __name__ == "__main__":
    main()
