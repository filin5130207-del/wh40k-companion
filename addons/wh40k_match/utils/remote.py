"""HTTP calls into the roster and session registries."""

import os

from wh40k_token import issue_service_token, post_jsonrpc, secret_from_env


def roster_base():
    return os.environ.get("WH40K_ROSTER_INTERNAL_URL", "http://roster:8069").rstrip("/")


def session_base():
    return os.environ.get("WH40K_SESSION_INTERNAL_URL", "http://session:8069").rstrip("/")


def pwa_base():
    return os.environ.get("WH40K_PWA_BASE_URL", "http://127.0.0.1:8069").rstrip("/")


def fetch_snapshot(roster_id, bearer):
    result = post_jsonrpc(
        f"{roster_base()}/wh40k/api/roster/{int(roster_id)}/snapshot",
        {},
        bearer=bearer,
    )
    roster = (result or {}).get("roster")
    if not roster:
        raise RuntimeError("Roster snapshot was empty.")
    return roster


def fetch_eligible(points, bearer):
    result = post_jsonrpc(
        f"{roster_base()}/wh40k/api/roster/eligible",
        {"points": int(points)},
        bearer=bearer,
    )
    return (result or {}).get("rosters") or []


def sync_stats(results):
    token = issue_service_token(secret=secret_from_env(), audience="session")
    return post_jsonrpc(
        f"{session_base()}/wh40k/api/session/record_result",
        {"results": results},
        bearer=token,
    )
