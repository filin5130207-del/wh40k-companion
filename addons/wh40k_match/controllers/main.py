import json
import logging

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from wh40k_token import secret_from_env, verify_token

from ..utils.remote import fetch_eligible, fetch_snapshot, pwa_base

_logger = logging.getLogger(__name__)


class Wh40kMatchController(http.Controller):
    """Match lifecycle. Players are bearer claims; rosters are HTTP snapshots."""

    def _secret(self):
        try:
            return secret_from_env()
        except ValueError as exc:
            raise AccessError(str(exc)) from exc

    def _bearer(self):
        header = request.httprequest.headers.get("Authorization") or ""
        if not header.lower().startswith("bearer "):
            return ""
        return header[7:].strip()

    def _actor(self):
        try:
            payload = verify_token(self._bearer(), self._secret())
        except ValueError as exc:
            raise AccessError(str(exc)) from exc
        if payload.get("role") != "user":
            raise AccessError("User token required.")
        if "player" not in (payload.get("groups") or []):
            raise AccessError("Player group required.")
        payload["uid"] = int(payload["uid"])
        return payload

    def _json_error(self, exc):
        if isinstance(exc, AccessError):
            _logger.warning("WH40k match access denied: %s", exc)
            return {"ok": False, "error": str(exc)}
        if isinstance(exc, (UserError, ValidationError)):
            return {"ok": False, "error": str(exc)}
        if isinstance(exc, RuntimeError):
            return {"ok": False, "error": str(exc)}
        _logger.exception("WH40k match error")
        return {"ok": False, "error": "Internal server error."}

    def _wrap(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return self._json_error(exc)

    def _ok(self, **payload):
        data = {"ok": True}
        data.update(payload)
        return data

    def _join_base(self):
        origin = (request.httprequest.headers.get("Origin") or "").rstrip("/")
        if origin.startswith("http://") or origin.startswith("https://"):
            return origin
        return pwa_base()

    def _match(self, match_id):
        match = request.env["wh40k.match"].sudo().browse(int(match_id))
        if not match.exists():
            raise UserError("Match not found.")
        return match

    def _api_missions(self, **kwargs):
        self._actor()
        return self._ok(missions=request.env["wh40k.mission"].sudo().list_active_dicts())

    def _api_active(self, **kwargs):
        actor = self._actor()
        return self._ok(
            active_match=request.env["wh40k.match"].get_active_summary_for_uid(actor["uid"])
        )

    def _api_create(self, roster_id=None, mission_id=None, points="2000", **kwargs):
        actor = self._actor()
        snapshot = fetch_snapshot(roster_id, self._bearer())
        mission = (
            request.env["wh40k.mission"].sudo().browse(int(mission_id))
            if mission_id
            else False
        )
        match = request.env["wh40k.match"].sudo().action_create_for_host(
            actor, snapshot, mission, points
        )
        return self._ok(match_id=match.id, match_token=match.match_token)

    def _api_publish(self, match_id=None, **kwargs):
        actor = self._actor()
        match = self._match(match_id)
        if match.host_uid != actor["uid"]:
            raise UserError("Match not found.")
        match.action_publish()
        return self._ok(**match.to_publish_dict(base_url=self._join_base()))

    def _api_verify(self, match_token=None, **kwargs):
        self._actor()
        match = request.env["wh40k.match"].find_by_token(match_token)
        return self._ok(**match.to_verify_dict())

    def _api_accept(self, match_token=None, **kwargs):
        actor = self._actor()
        match = request.env["wh40k.match"].find_by_token(match_token)
        match.action_accept_invite(actor)
        rosters = fetch_eligible(match.points, self._bearer())
        return self._ok(
            match_id=match.id,
            state=match.state,
            points=match.points,
            rosters=rosters,
        )

    def _api_join(self, match_token=None, roster_id=None, **kwargs):
        actor = self._actor()
        match = request.env["wh40k.match"].find_by_token(match_token)
        snapshot = fetch_snapshot(roster_id, self._bearer())
        if match.state == "waiting":
            match.action_accept_invite(actor)
        match.action_join(actor, snapshot)
        return self._ok(match_id=match.id, state=match.state)

    def _api_state(self, match_id=None, include_sheets=False, **kwargs):
        actor = self._actor()
        match = self._match(match_id)
        return self._ok(
            match=match.to_state_dict(
                actor,
                base_url=self._join_base(),
                include_sheets=bool(include_sheets),
            )
        )

    def _api_unit_state(self, match_id=None, unit_state=None, **kwargs):
        actor = self._actor()
        match = self._match(match_id)
        match._assert_participant(actor)
        match.action_update_unit_state(unit_state, actor)
        return self._ok()

    def _api_surrender(self, match_id=None, **kwargs):
        actor = self._actor()
        match = self._match(match_id)
        match.action_surrender(actor)
        return self._ok(**match.to_surrender_result_dict(actor))

    def _api_cancel(self, match_id=None, reason=None, **kwargs):
        actor = self._actor()
        match = self._match(match_id)
        if match.host_uid != actor["uid"]:
            raise UserError("Match not found.")
        if match.state != "cancelled":
            match.action_cancel(reason=(reason or "").strip() or "Cancelled by host")
        return self._ok(state=match.state, cancel_reason=match.cancel_reason or "")

    def _api_watch(self, match_id=None, since=None, timeout=20, **kwargs):
        actor = self._actor()
        match = self._match(match_id)
        match._assert_participant(actor) if match.guest_uid else None
        if not match.guest_uid and match.host_uid != actor["uid"]:
            raise AccessError("Not a participant of this match.")
        changed, write_date = match.wait_for_change(
            since_write_date=since, timeout_seconds=timeout
        )
        return self._ok(
            changed=bool(changed),
            write_date=write_date,
            match=match.to_state_dict(actor, base_url=self._join_base()),
        )

    @http.route("/wh40k/api/missions", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_missions(self, **kwargs):
        return self._wrap(self._api_missions, **kwargs)

    @http.route("/wh40k/api/match/active", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_active(self, **kwargs):
        return self._wrap(self._api_active, **kwargs)

    @http.route("/wh40k/api/match/create", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_create(self, roster_id=None, mission_id=None, points="2000", **kwargs):
        return self._wrap(
            self._api_create,
            roster_id=roster_id,
            mission_id=mission_id,
            points=points,
            **kwargs,
        )

    @http.route("/wh40k/api/match/publish", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_publish(self, match_id=None, **kwargs):
        return self._wrap(self._api_publish, match_id=match_id, **kwargs)

    @http.route("/wh40k/api/match/verify", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_verify(self, match_token=None, **kwargs):
        return self._wrap(self._api_verify, match_token=match_token, **kwargs)

    @http.route("/wh40k/api/match/accept", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_accept(self, match_token=None, **kwargs):
        return self._wrap(self._api_accept, match_token=match_token, **kwargs)

    @http.route("/wh40k/api/match/join", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_join(self, match_token=None, roster_id=None, **kwargs):
        return self._wrap(
            self._api_join, match_token=match_token, roster_id=roster_id, **kwargs
        )

    @http.route("/wh40k/api/match/state", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_state(self, match_id=None, include_sheets=False, **kwargs):
        return self._wrap(
            self._api_state,
            match_id=match_id,
            include_sheets=include_sheets,
            **kwargs,
        )

    @http.route("/wh40k/api/match/unit_state", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_unit_state(self, match_id=None, unit_state=None, **kwargs):
        return self._wrap(
            self._api_unit_state, match_id=match_id, unit_state=unit_state, **kwargs
        )

    @http.route("/wh40k/api/match/surrender", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_surrender(self, match_id=None, **kwargs):
        return self._wrap(self._api_surrender, match_id=match_id, **kwargs)

    @http.route("/wh40k/api/match/cancel", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_cancel(self, match_id=None, reason=None, **kwargs):
        return self._wrap(self._api_cancel, match_id=match_id, reason=reason, **kwargs)

    @http.route("/wh40k/api/match/watch", type="jsonrpc", auth="public", csrf=False, cors="*", methods=["POST"])
    def api_watch(self, match_id=None, since=None, timeout=20, **kwargs):
        return self._wrap(
            self._api_watch, match_id=match_id, since=since, timeout=timeout, **kwargs
        )

    @http.route("/wh40k/api/health", type="http", auth="public", csrf=False, cors="*")
    def health(self, **kwargs):
        return request.make_response(
            json.dumps({"ok": True, "service": "match"}),
            headers=[("Content-Type", "application/json")],
        )
