from ipaddress import ip_address
from ipaddress import ip_network


IPV6_CLIENT_PREFIX = 64


def resolve_client_ip(
    peer: str | None,
    forwarded: str | None,
) -> str | None:
    for candidate in (forwarded, peer):
        if not candidate:
            continue

        try:
            return str(ip_address(candidate.strip()))
        except ValueError:
            continue

    return None


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
