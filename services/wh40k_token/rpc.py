"""Minimal JSON-RPC client for service-to-service calls.

Odoo answers ``type='jsonrpc'`` routes with ``{"jsonrpc","id","result"}``.
A second database is a different transaction, so callers must treat a
successful HTTP response as its own commit.
"""

from __future__ import annotations

import json
import urllib.request


class RpcError(RuntimeError):
    pass


def parse_jsonrpc_response(raw):
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RpcError("Service returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise RpcError("Service returned invalid JSON.")
    if data.get("error"):
        err = data["error"] or {}
        message = ""
        if isinstance(err, dict):
            details = err.get("data") or {}
            if isinstance(details, dict):
                message = details.get("message") or ""
            message = message or err.get("message") or ""
        raise RpcError(message or "RPC error.")
    result = data.get("result")
    if isinstance(result, dict) and result.get("ok") is False:
        raise RpcError(result.get("error") or "RPC failed.")
    return result


def post_jsonrpc(url, params=None, bearer=None, timeout=20, opener=None):
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": params or {},
            "id": 1,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    open_fn = opener or urllib.request.urlopen
    with open_fn(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return parse_jsonrpc_response(raw)
