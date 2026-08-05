from __future__ import annotations

import ipaddress

_ALLOWED_IPV4_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # Tailscale and other shared-address overlays.
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_ALLOWED_IPV6_NETWORKS = (
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def is_allowed_local_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is explicitly allowed for token-bearing LAN traffic."""
    if address.is_unspecified or address.is_multicast:
        return False
    networks = _ALLOWED_IPV4_NETWORKS if address.version == 4 else _ALLOWED_IPV6_NETWORKS
    return any(address in network for network in networks)
