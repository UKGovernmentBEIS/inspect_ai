import json
import logging
import os
import platform
import random
import socket
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

import httpx

# Set up logger for this module
logger = logging.getLogger(__name__)

# Global dictionary to keep track of process -> reserved port mappings
process_socket_map: dict[subprocess.Popen[str], socket.socket] = {}

DEFAULT_RETRY_DELAY = 5

DEFAULT_TIMEOUT = 60 * 10  # fairly conservative default timeout of 10 minutes


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
    is_macos = platform.system() == "Darwin"

    if is_macos:
        logger.info(
            "MacOS system detected. A free binding port will be identified, but not reserved until the server binds to it."
        )
        # On macOS, let the OS pick a free port but not open it
        # It leads to a small racode condition window until the port
        # is actually opened by the llm server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, 0))  # Bind to any free port
            port = s.getsockname()[1]
        return port, s

    # Non-macOS behavior: try ports in range
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


def execute_shell_command(
    command: list[str], env: Optional[dict[str, str]] = None
) -> subprocess.Popen[str]:
    """
    Execute a command and return its process handle.

    Args:
        command: List of command arguments
        env: Optional environment variables to pass to the subprocess

    Returns:
        A subprocess.Popen object representing the running process
    """
    # Create a process environment by copying current environment and updating with new values
    process_env = os.environ.copy()
    if env:
        process_env.update(env)

    # Create a process that redirects output to pipes so we can capture it
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,  # Line buffered
        env=process_env,  # Pass the environment variables
    )

    # Set up background thread to read and log stdout
    def log_output() -> None:
        if process.stdout is None:
            return
        for line in iter(process.stdout.readline, ""):
            if line:
                logger.debug(line.strip())
        process.stdout.close()

    # Set up background thread to read and log stderr
    def log_error() -> None:
        if process.stderr is None:
            return
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
        time.sleep(1)

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
    command: list[str],
    host: str = "0.0.0.0",
    port: Optional[int] = None,
    env: Optional[dict[str, str]] = None,
) -> Tuple[subprocess.Popen[str], int, list[str]]:
    """
    Launch a server process with the given base command and return the process, port, and full command.

    Args:
        command: Base command to execute
        host: Host to bind to
        port: Port to bind to. If None, a free port is reserved.
        env: Optional environment variables to pass to the subprocess

    Returns:
        Tuple of (process, port, full_command)
    """
    if port is None:
        port, lock_socket = reserve_port(host)
    else:
        lock_socket = None

    full_command = command + ["--port", str(port)]
    logger.info(f"Launching server on port {port}")

    process = execute_shell_command(full_command, env=env)

    if lock_socket is not None:
        process_socket_map[process] = lock_socket

    return process, port, full_command


def terminate_process(process: subprocess.Popen[str]) -> None:
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
    process: subprocess.Popen[str],
    full_command: Optional[list[str]] = None,
    env: Optional[dict[str, str]] = None,
    timeout: Optional[int] = None,
    api_key: Optional[str] = None,
) -> None:
    """
    Wait for the server to be ready by polling the /v1/models endpoint.

    Args:
        base_url: The base URL of the server
        process: The subprocess running the server
        full_command: The full command used to launch the server
        env: The environment variables to use for the request
        timeout: Maximum time to wait in seconds. None means wait forever.
        api_key: The API key to use for the request
    """
    logger.info(f"Waiting for server at {base_url} to become ready...")
    start_time = time.time()
    debug_advice = "Try rerunning with '--log-level debug' to see the full traceback."
    if full_command:
        debug_advice += " Alternatively, you can run the following launch command manually to see the full traceback:\n\n"
        if env:
            debug_advice += " ".join([f"{k}={v}" for k, v in env.items()]) + " "
        debug_advice += " ".join(full_command) + "\n\n"

    while True:
        # Check for timeout first
        if timeout and time.time() - start_time > timeout:
            error_msg = f"Server did not become ready within timeout period ({timeout} seconds). Try increasing the timeout with '-M timeout=...'. {debug_advice}"
            logger.error(error_msg)
            raise TimeoutError(error_msg)

        # Check if the process is still alive
        if process.poll() is not None:
            exit_code = process.poll()
            error_msg = f"Server process exited unexpectedly with code {exit_code}. {debug_advice}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        try:
            response = httpx.get(
                f"{base_url}/v1/models",
                headers={"Authorization": f"Bearer {api_key or 'None'}"},
                timeout=5.0,  # Short timeout for individual requests
            )
            if response.status_code == 200:
                logger.info("Server is ready.")
                break

            # Log non-200 status but don't treat as hard error yet
            logger.debug(
                f"Server check returned status {response.status_code}, retrying..."
            )
        except httpx.RequestError as e:
            # Log connection errors but don't treat as hard error yet
            logger.debug(f"Server check failed: {e}, retrying...")
            pass  # Request failed (e.g., connection refused), will retry

        # Wait before the next poll attempt
        time.sleep(1)


def start_local_server(
    base_cmd: list[str],
    host: str,
    port: Optional[int] = None,
    api_key: Optional[str] = None,
    server_type: str = "server",
    timeout: Optional[int] = DEFAULT_TIMEOUT,
    server_args: Optional[dict[str, Any]] = None,
    env: Optional[dict[str, str]] = None,
) -> Tuple[str, subprocess.Popen[str], int]:
    """
    Start a server with the given command and handle potential errors.

    Args:
        base_cmd: List of base command arguments
        host: Host to bind to
        port: Port to bind to. If None, a free port is reserved.
        api_key: API key to use for server authentication
        server_type: Type of server being started (for error messages)
        timeout: Maximum time to wait for server to become ready
        server_args: Additional server arguments to pass to the command
        env: Optional environment variables to pass to the subprocess
    Returns:
        Tuple of (base_url, process, port)

    Raises:
        RuntimeError: If server fails to start
    """
    full_command = base_cmd
    server_process = None

    # Initialize environment variables if not provided
    process_env = {} if env is None else env.copy()

    if server_args:
        for key, value in server_args.items():
            # Convert Python style args (underscore) to CLI style (dash)
            cli_key = key.replace("_", "-")
            if isinstance(value, bool):
                if value:
                    full_command.append(f"--{cli_key}")
                else:
                    logger.info(f"Skipping --{cli_key} (set to False)")
            elif value is None:
                full_command.append(f"--{cli_key}")
            else:
                full_command.extend([f"--{cli_key}", str(value)])

    try:
        server_process, found_port, full_command = launch_server_cmd(
            full_command, host=host, port=port, env=process_env
        )
        base_url = f"http://localhost:{found_port}/v1"
        wait_for_server(
            f"http://localhost:{found_port}",
            server_process,
            api_key=api_key,
            timeout=timeout,
            full_command=full_command,
            env=process_env,
        )
        return base_url, server_process, found_port
    except Exception as e:
        # Cleanup any partially started server
        if server_process:
            terminate_process(server_process)

        # Re-raise with more context
        raise RuntimeError(f"Failed to start {server_type} server: {str(e)}") from e


def merge_env_server_args(
    env_var_name: str,
    provided_args: Dict[str, Any],
    logger: logging.Logger,
) -> Dict[str, Any]:
    """
    Load server arguments from an environment variable and merge them with provided arguments.

    Args:
        env_var_name: Name of the environment variable containing JSON server args
        provided_args: Dictionary of server arguments provided by the user
        logger: Logger instance to log messages

    Returns:
        Dictionary of merged server arguments, with provided args taking precedence
    """
    env_server_args = {}
    server_args_json = os.environ.get(env_var_name)

    if server_args_json:
        try:
            env_server_args = json.loads(server_args_json)
            logger.info(
                f"Loaded server args from environment {env_var_name}: {env_server_args}"
            )
        except json.JSONDecodeError:
            logger.warning(
                f"Failed to parse {env_var_name} as JSON: {server_args_json}"
            )

    # Merge environment args with provided args (provided args take precedence)
    return {**env_server_args, **provided_args}


def configure_devices(
    server_args: dict[str, Any], parallel_size_param: str = "tensor_parallel_size"
) -> tuple[dict[str, Any], dict[str, str]]:
    """Configure device settings and return updated server args and environment variables.

    Args:
        server_args: Dictionary of server arguments
        parallel_size_param: Name of parameter to set with device count if not specified

    Returns:
        Tuple of (updated server arguments dict, environment variables dict)
    """
    result = server_args.copy()
    env_vars = {}

    devices = None
    if "device" in result and "devices" in result:
        raise ValueError("Cannot specify both device and devices in server args")
    elif "devices" in result:
        devices = result.pop("devices")
    elif "device" in result:
        devices = result.pop("device")

    if devices is not None:
        # Convert device list to comma-separated string if needed
        if isinstance(devices, list):
            device_str = ",".join(map(str, devices))
        else:
            device_str = str(devices)

        # Add to env_vars instead of setting os.environ directly
        env_vars["CUDA_VISIBLE_DEVICES"] = device_str

        device_count = len(device_str.split(","))

        # Set parallel size parameter if not explicitly provided
        if parallel_size_param not in result:
            result[parallel_size_param] = device_count

    return result, env_vars


def get_machine_ip() -> str | None:
    try:
        # Create a socket to determine the primary network interface IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        # Connect to an external address (doesn't actually send data)
        s.connect(("8.8.8.8", 80))
        ip = str(s.getsockname()[0])
        s.close()
        return ip
    except Exception:
        return None
