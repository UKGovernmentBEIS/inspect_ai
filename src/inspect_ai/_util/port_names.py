from typing import Literal


def get_service_by_port(port: int, protocol: Literal["tcp", "udp"]) -> str | None:
    """
    Returns the likely service running on a given port number.

    Args:
        port (int): The port number to look up
        protocol (str): Either 'tcp' or 'udp'

    Returns:
        str: Description of the likely service, or None if not found
    """
    # Common port mappings based on IANA assignments and common usage
    port_mappings = {
        "tcp": {
            20: "FTP (Data)",
            21: "FTP (Control)",
            22: "SSH",
            23: "Telnet",
            25: "SMTP",
            53: "DNS",
            80: "HTTP",
            110: "POP3",
            143: "IMAP",
            443: "HTTPS",
            445: "Microsoft-DS (SMB)",
            587: "SMTP (Submission)",
            993: "IMAPS",
            995: "POP3S",
            1433: "Microsoft SQL Server",
            1521: "Oracle Database",
            3306: "MySQL",
            3389: "RDP (Remote Desktop)",
            5432: "PostgreSQL",
            5900: "VNC",
            5901: "VNC Display :1",
            5902: "VNC Display :2",
            6080: "noVNC",
            8080: "HTTP Alternate",
            8443: "HTTPS Alternate",
            27017: "MongoDB",
            27018: "MongoDB Shard",
            27019: "MongoDB Config Server",
        },
        "udp": {
            53: "DNS",
            67: "DHCP Server",
            68: "DHCP Client",
            69: "TFTP",
            123: "NTP",
            161: "SNMP",
            162: "SNMP Trap",
            514: "Syslog",
            1194: "OpenVPN",
            5353: "mDNS",
        },
    }

    return port_mappings.get(protocol, {}).get(port, None)
