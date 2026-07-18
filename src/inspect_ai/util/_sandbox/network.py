from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Protocol = Literal["TCP", "UDP", "ANY"]

_MAX_DOMAIN_LENGTH: Final = 253
# A DNS label: 1-63 chars, alphanumeric with internal hyphens (RFC 1123).
_DNS_LABEL: Final = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
_FQDN_PATTERN: Final = re.compile(rf"^{_DNS_LABEL}(?:\.{_DNS_LABEL})*$")
_ENTITY_PATTERN: Final = re.compile(r"^[a-z0-9-]+$")


def _is_valid_domain(domain: str) -> bool:
    """Return whether a value is `*`, an exact FQDN, or a `*.` wildcard FQDN."""
    if domain == "*":
        return True
    candidate = domain[2:] if domain.startswith("*.") else domain
    return len(candidate) <= _MAX_DOMAIN_LENGTH and bool(_FQDN_PATTERN.match(candidate))


class DomainPort(BaseModel, frozen=True):
    """An extra port opened to allowlisted domains.

    `protocol` defaults to ANY (TCP+UDP). `domain`, if set, scopes the port to a
    single `allow_domains` entry; otherwise the port applies to every allowed domain.
    Provider compilers validate whether they can enforce the requested port and protocol.
    """

    port: Annotated[int, Field(ge=1, le=65535)]
    protocol: Protocol = "ANY"
    domain: str | None = None


class NetworkAccess(BaseModel, frozen=True):
    """Provider-agnostic egress policy.

    All fields default to empty, which means default-deny. Vocabulary and semantics
    match inspect_k8s_sandbox: domain allowlist (exact names and `*.` wildcards;
    `["*"]` allows all), extra ports for allowed domains, raw CIDR ranges, and Cilium
    entities (e.g. `all`/`world`). Provider compilers reject controls they cannot
    enforce, so model-valid domain ports are not limited to a provider's capabilities.
    """

    allow_domains: list[str] = Field(default_factory=list)
    allow_domains_ports: list[DomainPort] = Field(default_factory=list)
    allow_cidr: list[str] = Field(default_factory=list)
    allow_entities: list[str] = Field(default_factory=list)

    @field_validator("allow_domains")
    @classmethod
    def _check_domains(cls, domains: list[str]) -> list[str]:
        """Reject entries that are not `*`, an exact FQDN, or a `*.` wildcard FQDN."""
        for domain in domains:
            if not _is_valid_domain(domain):
                raise ValueError(
                    f"allow_domains entry {domain!r} is not a valid domain "
                    "(expected '*', an exact FQDN, or a '*.' wildcard FQDN)"
                )
        return domains

    @field_validator("allow_cidr")
    @classmethod
    def _check_cidr(cls, cidrs: list[str]) -> list[str]:
        """Reject entries that are not valid IPv4/IPv6 CIDR ranges."""
        for cidr in cidrs:
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError as ex:
                raise ValueError(
                    f"allow_cidr entry {cidr!r} is not a valid CIDR range: {ex}"
                ) from ex
        return cidrs

    @field_validator("allow_entities")
    @classmethod
    def _check_entities(cls, entities: list[str]) -> list[str]:
        """Reject entries that are not simple Cilium entity tokens."""
        for entity in entities:
            if not _ENTITY_PATTERN.match(entity):
                raise ValueError(
                    f"allow_entities entry {entity!r} is not a valid entity "
                    "(expected lowercase letters, digits, and hyphens)"
                )
        return entities

    @model_validator(mode="after")
    def _validate_domains_ports(self) -> "NetworkAccess":
        if self.allow_domains_ports and not self.allow_domains:
            raise ValueError(
                "allow_domains_ports requires allow_domains to be non-empty: extra "
                "ports apply to allowed domains' pinned IPs, so without allow_domains "
                "they would be silently inert (the k8s template renders them only "
                "inside 'if allowDomains'). Add the domain(s) to allow_domains."
            )
        for dp in self.allow_domains_ports:
            if dp.domain is not None and dp.domain not in self.allow_domains:
                raise ValueError(
                    f"allow_domains_ports: domain {dp.domain!r} (port {dp.port}) "
                    "must also appear in allow_domains"
                )
        return self


_EXTENSION_KEY = "x-inspect-network"
_MISSING = object()


def network_access_from_extensions(
    extensions: dict[str, Any],
) -> NetworkAccess | None:
    """Read the `x-inspect-network` compose extension into a NetworkAccess.

    Returns None when the key is absent. Raises if the key is present but null, or
    pydantic ValidationError on a malformed policy (no silent fallback).
    """
    raw = extensions.get(_EXTENSION_KEY, _MISSING)
    if raw is _MISSING:
        return None
    if raw is None:
        raise ValueError(
            f"'{_EXTENSION_KEY}' is present but null. Remove the key to use "
            "default-deny, or provide an egress-policy mapping (no silent fallback)."
        )
    return NetworkAccess.model_validate(raw)
