import logging
import os
import random
import socket
import subprocess
import time
from typing import Optional, Tuple

import requests

# Set up logger for this module
logger = logging.getLogger(__name__)

# Global dictionary to keep track of process and port mappings
process_socket_map = {}


def reserve_port(
    host: str, start: int = 30000, end: int = 40000
) -> Tuple[int, socket.socket]:
    """
    Reserve an available port by trying to bind a socket.

    Args:
        host: Host to bind to
        start: Minimum port number to try
        end: Maximum port number to try

    Returns:
        A tuple (port, lock_socket) where `lock_socket` is kept open to hold the lock.
    """
    candidates = list(range(start, end))
    random.shuffle(candidates)

    for port in candidates:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            # Attempt to bind to the port on localhost
            sock.bind((host, port))
            return port, sock
        except socket.error:
            sock.close()  # Failed to bind, try next port
            continue
    raise RuntimeError("No free port available.")


def release_port(lock_socket: socket.socket) -> None:
    """
    Release the reserved port by closing the lock socket.

    Args:
        lock_socket: The socket to close
    """
    try:
        lock_socket.close()
    except Exception as e:
        logger.error(f"Error closing socket: {e}")


def execute_shell_command(command: list[str]) -> subprocess.Popen:
    """
    Execute a command and return its process handle.

    Args:
        command: List of command arguments

    Returns:
        A subprocess.Popen object representing the running process
    """
    # Create a process that redirects output to pipes so we can capture it
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,  # Line buffered
    )

    # Set up background thread to read and log stdout
    def log_output():
        for line in iter(process.stdout.readline, ""):
            if line:
                logger.debug(line.strip())
        process.stdout.close()

    # Set up background thread to read and log stderr
    def log_error():
        for line in iter(process.stderr.readline, ""):
            if line:
                logger.info(line.strip())
        process.stderr.close()

    # Start background threads to handle output
    import threading

    threading.Thread(target=log_output, daemon=True).start()
    threading.Thread(target=log_error, daemon=True).start()

    logger.info(f"Started server with command: {' '.join(command)}")
    return process


def kill_process_tree(pid: int) -> None:
    """
    Kill a process and all its children.

    Args:
        pid: Process ID to kill
    """
    try:
        # Send SIGTERM
        subprocess.run(["pkill", "-TERM", "-P", str(pid)], check=False)
        subprocess.run(["kill", "-TERM", str(pid)], check=False)
        time.sleep(0.5)

        # If process still exists, send SIGKILL
        try:
            os.kill(pid, 0)  # Check if process exists
            subprocess.run(["pkill", "-KILL", "-P", str(pid)], check=False)
            subprocess.run(["kill", "-KILL", str(pid)], check=False)
        except OSError:
            pass  # Process already terminated
    except Exception as e:
        logger.error(f"Error killing process tree: {e}")


def launch_server_cmd(
    command: list[str], host: str = "0.0.0.0", port: Optional[int] = None
) -> Tuple[subprocess.Popen, int]:
    """
    Launch a server using the given command.

    Args:
        command: List of command arguments or string command
        host: Host to bind to
        port: Port to bind to. If None, a free port is reserved.

    Returns:
        Tuple of (process, port)
    """
    if port is None:
        port, lock_socket = reserve_port(host)
    else:
        lock_socket = None

    full_command = command + ["--port", str(port)]
    logger.info(f"Launching server on port {port}")
    process = execute_shell_command(full_command)

    if lock_socket is not None:
        process_socket_map[process] = lock_socket

    return process, port


def terminate_process(process: subprocess.Popen) -> None:
    """
    Terminate the process and automatically release the reserved port.

    Args:
        process: The process to terminate
    """
    kill_process_tree(process.pid)

    lock_socket = process_socket_map.pop(process, None)
    if lock_socket is not None:
        release_port(lock_socket)


def wait_for_server(
    base_url: str,
    process: subprocess.Popen,
    timeout: Optional[int] = None,
    api_key: Optional[str] = None,
) -> None:
    """
    Wait for the server to be ready by polling the /v1/models endpoint.

    Args:
        base_url: The base URL of the server
        process: The subprocess running the server
        timeout: Maximum time to wait in seconds. None means wait forever.
        api_key: The API key to use for the request
    """
    logger.info(f"Waiting for server at {base_url} to become ready...")
    start_time = time.time()

    while True:
        # Check if the process is still alive
        if process.poll() is not None:
            exit_code = process.poll()
            error_msg = f"Server process exited unexpectedly with code {exit_code}. Try rerunning with '--log-level debug' to see the full traceback."
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        try:
            response = requests.get(
                f"{base_url}/v1/models",
                headers={"Authorization": f"Bearer {api_key or 'None'}"},
            )
            if response.status_code == 200:
                logger.info("Server is ready.")
                break

            if timeout and time.time() - start_time > timeout:
                error_msg = "Server did not become ready within timeout period"
                logger.error(error_msg)
                raise TimeoutError(error_msg)
        except requests.exceptions.RequestException as e:
            logger.debug(f"Server not ready yet: {str(e)}")
            time.sleep(1)
