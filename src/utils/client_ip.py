from collections.abc import Sequence
from ipaddress import IPv4Address
from ipaddress import IPv4Network
from ipaddress import IPv6Address
from ipaddress import IPv6Network
from ipaddress import ip_address
from ipaddress import ip_network


IPV6_CLIENT_PREFIX = 64


def _ip(value: str | None) -> IPv4Address | IPv6Address | None:
    try:
        return ip_address(value.strip()) if value else None
    except ValueError:
        return None


def resolve_client_ip(
    peer: str | None,
    hops: Sequence[str | None],
    trusted: Sequence[IPv4Network | IPv6Network],
) -> str | None:
    seen = _ip(peer)
    for hop in hops:
        if seen is None or not any(seen in network for network in trusted):
            break
        if (told := _ip(hop)) is not None:
            seen = told

    return str(seen) if seen is not None else None


def client_key(ip: str) -> str:
    address = ip_address(ip)
    if address.version == 6:
        return str(
            ip_network(
                address=f"{address}/{IPV6_CLIENT_PREFIX}",
                strict=False,
            ),
        )

    return str(address)
