"""Join-link origin checks. No Odoo imports: unit tests can run this file alone."""

import ipaddress
from urllib.parse import urlparse

# Loopback, RFC1918, link-local, and IPv6 ULA. A join URL on one of these
# reaches another phone only on the same LAN (or not at all).
_NON_PUBLIC_NETS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def host_of(url):
    """Hostname of a base URL. Empty when the value has no host."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    host = urlparse(raw).hostname or ""
    return host.strip().lower().rstrip(".")


def _parse_ip(host):
    if not host:
        return None
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def is_loopback_base(url):
    """True for localhost, 127.0.0.0/8, ::1, and 0.0.0.0."""
    host = host_of(url)
    if not host:
        return True
    if host == "localhost" or host.endswith(".localhost"):
        return True
    ip = _parse_ip(host)
    if ip is None:
        return False
    return bool(ip.is_loopback or ip.is_unspecified)


def is_private_base(url):
    """True when the origin must not be advertised as a public join link.

    Loopback and RFC1918 addresses are private. Link-local, CGNAT, and IPv6
    unique-local addresses are treated the same way: another player's phone
    on mobile data cannot open them. A DNS name is public.
    """
    host = host_of(url)
    if not host:
        return True
    if is_loopback_base(url):
        return True
    ip = _parse_ip(host)
    if ip is None:
        return False
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return any(
        ip in network for network in _NON_PUBLIC_NETS if network.version == ip.version
    )
