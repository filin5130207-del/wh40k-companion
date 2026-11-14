"""Shared token and HTTP helpers for the WH40k Odoo services.

Not an Odoo module. Each service database has its own registry; this package
only signs and checks bearer tokens and talks JSON-RPC. It does not share
``res.users``.
"""

from .lines import side_unit_key
from .rpc import parse_jsonrpc_response, post_jsonrpc
from .tokens import (
    issue_service_token,
    issue_user_token,
    secret_from_env,
    verify_token,
)
from .urls import service_url

__all__ = [
    "issue_service_token",
    "issue_user_token",
    "parse_jsonrpc_response",
    "post_jsonrpc",
    "secret_from_env",
    "service_url",
    "side_unit_key",
    "verify_token",
]
