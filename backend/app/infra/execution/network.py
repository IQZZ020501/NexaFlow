import ipaddress
import re

# Static deny sets take precedence over DNS-derived allow sets in dns+nft.
# Loopback within an execution can host MCP helper processes; it is not the
# business host's loopback. The host/control-plane networks remain unreachable.
DENIED_NETWORKS = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "224.0.0.0/4",
    "240.0.0.0/4",
    "::/128",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
    "ff00::/8",
)


def validate_egress_domain(value: str) -> str:
    if not isinstance(value, str) or len(value) > 253:
        raise ValueError("Egress requires a bounded public domain name.")
    domain = value.removeprefix("*.").lower()
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError("Egress domain allowlists cannot contain IP addresses.")
    labels = domain.split(".")
    if (
        len(labels) < 2
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in labels
        )
        or labels[-1].isdigit()
        or domain.endswith((".local", ".localhost", ".internal", ".localdomain"))
    ):
        raise ValueError("Egress requires a public domain name, not a local address.")
    return ("*." if value.startswith("*.") else "") + domain
