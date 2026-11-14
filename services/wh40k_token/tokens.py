"""HMAC bearer tokens.

Odoo session cookies and JSON-2 API keys belong to one database. These tokens
are the identity the session service hands to roster and match. They carry the
user id and group names; they are not a copy of ``res.users``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

USER_TTL_SECONDS = 7 * 24 * 3600
SERVICE_TTL_SECONDS = 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def secret_from_env() -> str:
    value = os.environ.get("WH40K_TOKEN_SECRET") or ""
    if not value:
        raise ValueError("WH40K_TOKEN_SECRET is not set.")
    return value


def _sign(payload: dict, secret: str) -> str:
    header = _b64(
        json.dumps({"alg": "HS256", "typ": "WH40K"}, separators=(",", ":")).encode()
    )
    body = _b64(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    )
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{header}.{body}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{header}.{body}.{_b64(mac)}"


def issue_user_token(
    *,
    uid,
    login,
    nickname,
    groups,
    secret,
    ttl=USER_TTL_SECONDS,
    now=None,
):
    issued = int(time.time() if now is None else now)
    return _sign(
        {
            "role": "user",
            "uid": int(uid),
            "login": login or "",
            "nickname": nickname or "",
            "groups": list(groups or []),
            "iat": issued,
            "exp": issued + int(ttl),
        },
        secret,
    )


def issue_service_token(*, secret, audience, ttl=SERVICE_TTL_SECONDS, now=None):
    issued = int(time.time() if now is None else now)
    return _sign(
        {
            "role": "service",
            "aud": audience,
            "sub": "wh40k",
            "iat": issued,
            "exp": issued + int(ttl),
        },
        secret,
    )


def verify_token(token, secret, *, audience=None, now=None):
    if not token or not isinstance(token, str):
        raise ValueError("Missing bearer token.")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed token.")
    header, body, sig = parts
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{header}.{body}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual = _b64d(sig)
    except Exception as exc:  # noqa: BLE001 — any bad padding is a bad token
        raise ValueError("Malformed token.") from exc
    if not hmac.compare_digest(expected, actual):
        raise ValueError("Bad token signature.")
    try:
        payload = json.loads(_b64d(body))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Malformed token.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Malformed token.")
    current = int(time.time() if now is None else now)
    exp = payload.get("exp")
    if exp is None or int(exp) < current:
        raise ValueError("Token expired.")
    if audience is not None and payload.get("aud") != audience:
        raise ValueError("Bad token audience.")
    return payload
