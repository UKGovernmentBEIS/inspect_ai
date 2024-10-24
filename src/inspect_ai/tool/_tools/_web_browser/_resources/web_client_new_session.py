"""Simple script to run and test the RPC server."""

import grpc
from dm_env_rpc.v1 import connection as dm_env_connection
from dm_env_rpc.v1 import dm_env_rpc_pb2

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
    # Creating a world with the headless browser.
    channel = grpc.secure_channel(
        f"localhost:{_DM_ENV_BASE_PORT}",
        grpc.local_channel_credentials(),
        options=options,
    )
    connection = dm_env_connection.Connection(channel)
    world_name = connection.send(dm_env_rpc_pb2.CreateWorldRequest()).world_name
    print(world_name)

    connection.close()


if __name__ == "__main__":
    main()
