"""SSRF protection for outbound fetches.

Crawl URLs come from third-party sources (search results, directories, admin
input). Without validation a crafted URL could hit internal services - cloud
metadata (169.254.169.254), loopback, RFC1918 hosts. is_safe_public_url()
rejects any URL that doesn't resolve to a public, routable IP over http(s).
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # not parseable -> treat as unsafe
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def is_safe_public_url(url: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=True only for http(s) URLs whose host resolves
    exclusively to public, routable IP addresses."""
    if not url or not isinstance(url, str):
        return False, "empty url"
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False, f"scheme not allowed: {parsed.scheme or '(none)'}"
    host = parsed.hostname
    if not host:
        return False, "no host"
    if host.lower() in {"localhost", "metadata", "metadata.google.internal"}:
        return False, "internal hostname"
    try:
        infos = socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror:
        return False, "dns resolution failed"
    for info in infos:
        ip_str = info[4][0]
        if _ip_is_blocked(ip_str):
            return False, f"resolves to non-public address ({ip_str})"
    return True, "ok"
