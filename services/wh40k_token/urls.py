"""Browser-facing service URLs.

Inside Compose, roster listens on port 8069 of the ``roster`` network name.
A phone on the LAN must use the session host and the published port instead
of 127.0.0.1.
"""

from __future__ import annotations

import urllib.parse

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def service_url(configured, *, hostname, scheme, port):
    configured = (configured or "").strip().rstrip("/")
    if not hostname:
        return configured
    scheme = scheme or "http"
    if not configured:
        return f"{scheme}://{hostname}:{int(port)}"
    parsed = urllib.parse.urlparse(configured)
    host = (parsed.hostname or "").lower()
    if host in LOOPBACK or host == hostname.lower():
        return f"{scheme}://{hostname}:{int(port)}"
    return configured
