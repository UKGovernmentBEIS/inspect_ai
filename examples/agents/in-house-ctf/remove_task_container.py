import argparse
import json
import docker
import os


def remove_container(task_name):
    try:
        with open(f"scratch/{task_name}_container_info.json", "r") as f:
            info = json.load(f)
            container_name = info["container_name"]

        client = docker.from_env()
        container = client.containers.get(container_name)
        container.stop()
        container.remove()
        print(f"Container {container_name} removed successfully.")
        os.remove(f"scratch/{task_name}_container_info.json")
        print(f"Info file {task_name}_container_info.json deleted successfully.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("task_name")
    args = parser.parse_args()
    task_name = args.task_name

    remove_container(task_name)
