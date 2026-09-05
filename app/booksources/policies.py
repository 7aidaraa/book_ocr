"""Network policy: what a URL must satisfy before anything fetches it.

Two independent gates, both mandatory:

1. Allowlist — the *source* declares its hosts. A user never supplies a URL,
   and a redirect that leaves the allowlist is refused, so this layer can
   never be turned into an SSRF proxy.
2. Address check — every resolved IP must be a public one. This blocks
   localhost, link-local, and RFC1918 targets even when a permitted
   hostname resolves to them (DNS rebinding).
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable, Iterable
from urllib.parse import urlsplit

# Size and shape limits for anything this layer downloads.
MAX_PDF_BYTES = 400 * 1024 * 1024      # 400 MB
MAX_PDF_PAGES = 5000
MAX_REDIRECTS = 5
CONNECT_TIMEOUT = 30                   # seconds, per request
MIN_SECONDS_BETWEEN_REQUESTS = 1.0     # per host, be a polite client

ALLOWED_SCHEMES = frozenset({"https"})
ALLOWED_PORTS = frozenset({443})

Resolver = Callable[[str], list[str]]  # host -> list of IP strings


class PolicyError(ValueError):
    """A URL is not permitted. Never retried, never worked around."""


def default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def host_allowed(host: str, allowed_hosts: Iterable[str]) -> bool:
    """Exact host match, or a subdomain of an allowed host."""
    host = host.lower().rstrip(".")
    for allowed in allowed_hosts:
        allowed = allowed.lower().rstrip(".")
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def check_url(
    url: str,
    allowed_hosts: Iterable[str],
    resolver: Resolver = default_resolver,
) -> str:
    """Validate a URL against both gates; return its normalised host.

    Raises PolicyError with a specific reason on any failure.
    """
    allowed_hosts = list(allowed_hosts)
    if not allowed_hosts:
        raise PolicyError("no allowed hosts declared for this source")

    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise PolicyError(f"scheme not allowed: {parts.scheme!r}")
    if parts.username or parts.password:
        raise PolicyError("credentials in URL are not allowed")

    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise PolicyError("URL has no host")
    if parts.port is not None and parts.port not in ALLOWED_PORTS:
        raise PolicyError(f"port not allowed: {parts.port}")
    if not host_allowed(host, allowed_hosts):
        raise PolicyError(f"host not in source allowlist: {host}")

    # A literal IP is never accepted, even a public one: sources are named.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise PolicyError("literal IP addresses are not allowed")

    try:
        addresses = resolver(host)
    except OSError as exc:
        raise PolicyError(f"cannot resolve host {host}: {exc}") from exc
    if not addresses:
        raise PolicyError(f"host resolves to nothing: {host}")

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast:
            raise PolicyError(f"host {host} resolves to non-public address {address}")

    return host
