import argparse
import json
import socket

import docker

# challenges config path
CHALLENGES_CONFIG_PATH = "challenges/tasks_config.json"

# scratch directory
SCRATCH_PATH = "scratch"


def load_config(task_name):
    with open(CHALLENGES_CONFIG_PATH, "r") as f:
        config = json.load(f)
    task_config = config.get(task_name)
    if not task_config:
        raise ValueError(f"Task {task_name} not found in configuration file.")
    return task_config


def container_exists(client, container_name):
    containers = client.containers.list(all=True, filters={"name": container_name})
    if len(containers) == 0:
        return False
    print(f"Container {container_name} already exists.")
    container = containers[0]
    port_bindings = container.attrs["HostConfig"]["PortBindings"]
    container_port = list(port_bindings.keys())[0]
    host_port_info = port_bindings[container_port][0]
    host_port = host_port_info["HostPort"]
    host_ip = host_port_info.get("HostIp", "0.0.0.0")
    address = f"{host_ip}:{host_port}"
    save_container_info(task_name, address, container_name)
    return True


def is_port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) != 0


def find_available_port(host_port, start_port=8000, end_port=9000):
    if is_port_available(host_port):
        return host_port
    for port in range(start_port, end_port):
        if is_port_available(port):
            return port
    raise RuntimeError("No available ports in the specified range.")


def create_and_run_container(
    client, task_name, image_name, address, host_port, container_port
):
    container_name = f"ctf_{task_name}_container"
    if container_exists(client, container_name):
        return
    host_port = find_available_port(host_port)

    client.containers.run(
        image_name,
        detach=True,
        name=container_name,
        ports={f"{container_port}/tcp": (address, host_port)},
    )

    print(f"Container {container_name} is running on port {host_port}.")
    save_container_info(task_name, f"{address}:{host_port}", container_name)


def save_container_info(task_name, address, container_name):
    info = {"address": address, "container_name": container_name}
    with open(f"{SCRATCH_PATH}/{task_name}_container_info.json", "w") as f:
        json.dump(info, f, indent=4)
    print(f"Container info saved to {SCRATCH_PATH}/{task_name}_container_info.json")


def host_container(task_name):
    client = docker.from_env()
    task_info = load_config(task_name)
    image_name = task_info["image_name"]
    address = "0.0.0.0"
    host_port = task_info["host_port"]
    container_port = task_info["container_port"]

    client.images.pull(image_name)
    create_and_run_container(
        client, task_name, image_name, address, host_port, container_port
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("task_name")
    args = parser.parse_args()
    task_name = args.task_name
    host_container(task_name)
