from typing import Literal

from textual.app import ComposeResult
from textual.containers import HorizontalScroll
from textual.widget import Widget
from textual.widgets import Link, Static

from inspect_ai._util.port_names import get_service_by_port
from inspect_ai.util._sandbox.environment import PortMapping


class PortMappingsView(HorizontalScroll):
    DEFAULT_CSS = """
    PortMappingsView {
      layout: grid;
      height: auto;
      grid-size: 4 3;
      grid-columns: auto auto auto auto;
      grid-gutter: 0 1;
    }
    """

    def __init__(self, ports: list[PortMapping] | None) -> None:
        super().__init__()
        self.ports = ports

    def compose(self) -> ComposeResult:
        if not self.ports:
            return
        yield Static("service")
        yield Static("sandbox")
        yield Static("client")
        yield Static("endpoint")
        mappings_and_services = [
            (mapping, get_service_by_port(mapping.container_port, mapping.protocol))
            for mapping in self.ports
        ]
        remaining_widgets = [
            widget
            for mapping_and_service in mappings_and_services
            for widget in widgets_from_port_mapping(mapping_and_service)
        ]
        for widget in remaining_widgets:
            yield widget


def widgets_for_port_mappings(
    port_mappings: list[PortMapping] | None,
) -> list[Widget]:
    if port_mappings is None:
        return []
    return [
        static
        for mapping in [
            (mapping, get_service_by_port(mapping.container_port, mapping.protocol))
            for mapping in port_mappings
        ]
        for static in widgets_from_port_mapping(mapping)
    ]


def widgets_from_port_mapping(
    mapping_service_tuple: tuple[PortMapping, str | None],
) -> list[Widget]:
    port_mapping, service = mapping_service_tuple
    return [
        widget
        for host_mapping in port_mapping.mappings
        for widget in get_row_widgets(
            port_mapping.protocol,
            host_mapping.host_port,
            port_mapping.container_port,
            service,
        )
    ]


def get_row_widgets(
    protocol: Literal["tcp", "udp"],
    host_port: int,
    container_port: int,
    service: str | None,
) -> list[Widget]:
    url = get_url(
        host_port,
        service,
    )
    return [
        Static(service if service is not None else protocol),
        Static(str(container_port)),
        Static(str(host_port)),
        Link(url) if url is not None else Static("asdf"),
    ]


def get_url(
    host_port: int,
    service: str | None,
) -> str | None:
    if service is not None:
        if service == "noVNC":
            return f"http://localhost:{host_port}?view_only=true&autoconnect=true&resize=scale"

        if service.startswith("HTTP"):
            return f"https://localhost:{host_port}"

        if service.startswith("VNC"):
            return f"vnc://localhost:{host_port}"

    return None
