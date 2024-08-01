import argparse
import docker

client = docker.from_env()


def image_exists(image_name):
    images = client.images.list()
    image_tags = [tag for image in images for tag in image.tags]
    return any(image_name in tag for tag in image_tags)


def container_exists(container_name):
    containers = client.containers.list(all=True)
    return any(container.name == container_name for container in containers)


def build_and_run_container(
    dockerfile_path, image_name, container_name, host_port, internal_port
):
    try:
        if image_exists(image_name):
            print(f"Image '{image_name}' already exists.")
        else:
            image, _ = client.images.build(path=dockerfile_path, tag=image_name)
            print(f"Image '{image_name}' built successfully.")

        if container_exists(container_name):
            container = client.containers.get(container_name)
            print(f"Container '{container_name}' already exists.")
            display_container_network_info(container)
        else:
            port_mapping = {f"{internal_port}/tcp": host_port}
            container = client.containers.run(
                image_name, detach=True, name=container_name, ports=port_mapping
            )
            print(f"Container '{container_name}' created successfully.")
            print(
                f"Container '{container_name}' is accessible at localhost:{host_port}"
            )

    except Exception as e:
        print(f"Error: {e}")


def display_container_network_info(container):
    container.reload()
    network_info = container.attrs["NetworkSettings"]["Ports"]
    if network_info:
        exposed_ports = []
        for port, bindings in network_info.items():
            if bindings:
                for binding in bindings:
                    host_ip = binding.get("HostIp", "localhost")
                    host_port = binding.get("HostPort")
                    exposed_ports.append(f"{host_ip}:{host_port}")
        if exposed_ports:
            print(f"Container is accessible at: {', '.join(exposed_ports)}")
        else:
            print("No ports are currently mapped.")
    else:
        print("No ports are exposed.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dockerfile_path", default=".", help="Path to Dockerfile directory."
    )
    parser.add_argument("--image_name", default="db_image", help="Docker image name.")
    parser.add_argument(
        "--container_name", default="db_container", help="Docker container name."
    )
    parser.add_argument("--host_port", type=int, default=5432, help="Host port to map.")
    parser.add_argument(
        "--internal_port", type=int, default=5432, help="Internal container port."
    )
    args = parser.parse_args()

    build_and_run_container(
        args.dockerfile_path,
        args.image_name,
        args.container_name,
        args.host_port,
        args.internal_port,
    )


if __name__ == "__main__":
    main()
