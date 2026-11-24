import json
import logging

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from wh40k_token import secret_from_env, verify_token

from ..parsers.battlescribe_parser import BattlescribeParser

_logger = logging.getLogger(__name__)


class Wh40kRosterController(http.Controller):
    """Import and read datasheets. Auth is the session bearer, not res.users."""

    def _secret(self):
        try:
            return secret_from_env()
        except ValueError as exc:
            raise AccessError(str(exc)) from exc

    def _actor(self):
        header = request.httprequest.headers.get("Authorization") or ""
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        try:
            payload = verify_token(token, self._secret())
        except ValueError as exc:
            raise AccessError(str(exc)) from exc
        if payload.get("role") != "user":
            raise AccessError("User token required.")
        groups = list(payload.get("groups") or [])
        if "player" not in groups:
            raise AccessError("Player group required.")
        payload["uid"] = int(payload["uid"])
        return payload

    def _json_error(self, exc):
        if isinstance(exc, AccessError):
            _logger.warning("WH40k roster access denied: %s", exc)
            return {"ok": False, "error": str(exc)}
        if isinstance(exc, (UserError, ValidationError)):
            return {"ok": False, "error": str(exc)}
        _logger.exception("WH40k roster error")
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

    def _parse(self, roster_json):
        if not roster_json:
            raise UserError("Missing roster_json payload.")
        if isinstance(roster_json, str):
            data = json.loads(roster_json)
        else:
            data = roster_json
        return BattlescribeParser(data)

    def _roster(self, roster_id, actor):
        roster = request.env["wh40k.roster"].sudo().browse(int(roster_id))
        if not roster.exists():
            raise UserError("Roster not found.")
        roster.check_detail_access(actor["uid"])
        return roster

    def _api_preview(self, roster_json=None, **kwargs):
        self._actor()
        parser = self._parse(roster_json)
        return self._ok(preview=parser.preview())

    def _api_import(self, roster_json=None, name=None, **kwargs):
        actor = self._actor()
        parser = self._parse(roster_json)
        parsed = parser.parse()
        if name:
            parsed["name"] = name
        roster = (
            request.env["wh40k.roster"]
            .sudo()
            .action_import_parsed(
                actor["uid"], parsed, owner_name=actor.get("nickname") or ""
            )
        )
        return self._ok(
            roster_id=roster.id,
            name=roster.name,
            points_used=roster.points_used,
            points_limit=roster.points_limit,
            summary=parser.summary(),
            preview=parser.preview(),
        )

    def _api_mine(self, **kwargs):
        actor = self._actor()
        rosters = request.env["wh40k.roster"].sudo().search(
            [("owner_uid", "=", actor["uid"])],
            order="create_date desc, id desc",
        )
        return self._ok(rosters=[roster.to_list_dict() for roster in rosters])

    def _api_eligible(self, points=None, **kwargs):
        actor = self._actor()
        domain = [("owner_uid", "=", actor["uid"])]
        if points not in (None, "", False):
            domain.append(("points_used", "<=", int(points)))
        rosters = request.env["wh40k.roster"].sudo().search(
            domain, order="create_date desc, id desc"
        )
        return self._ok(rosters=[roster.to_eligible_dict() for roster in rosters])

    def _api_detail(self, roster_id, **kwargs):
        actor = self._actor()
        roster = self._roster(roster_id, actor)
        return self._ok(roster=roster.to_detail_dict(actor["uid"]))

    def _api_snapshot(self, roster_id, **kwargs):
        actor = self._actor()
        roster = self._roster(roster_id, actor)
        return self._ok(roster=roster.to_snapshot_dict(actor["uid"]))

    @http.route(
        "/wh40k/api/roster/preview",
        type="jsonrpc",
        auth="public",
        csrf=False,
        cors="*",
        methods=["POST"],
    )
    def api_preview(self, roster_json=None, **kwargs):
        return self._wrap(self._api_preview, roster_json=roster_json, **kwargs)

    @http.route(
        "/wh40k/api/roster/import",
        type="jsonrpc",
        auth="public",
        csrf=False,
        cors="*",
        methods=["POST"],
    )
    def api_import(self, roster_json=None, name=None, **kwargs):
        return self._wrap(self._api_import, roster_json=roster_json, name=name, **kwargs)

    @http.route(
        "/wh40k/api/roster/mine",
        type="jsonrpc",
        auth="public",
        csrf=False,
        cors="*",
        methods=["POST"],
    )
    def api_mine(self, **kwargs):
        return self._wrap(self._api_mine, **kwargs)

    @http.route(
        "/wh40k/api/roster/eligible",
        type="jsonrpc",
        auth="public",
        csrf=False,
        cors="*",
        methods=["POST"],
    )
    def api_eligible(self, points=None, **kwargs):
        return self._wrap(self._api_eligible, points=points, **kwargs)

    @http.route(
        "/wh40k/api/roster/<int:roster_id>/detail",
        type="jsonrpc",
        auth="public",
        csrf=False,
        cors="*",
        methods=["POST"],
    )
    def api_detail(self, roster_id, **kwargs):
        return self._wrap(self._api_detail, roster_id, **kwargs)

    @http.route(
        "/wh40k/api/roster/<int:roster_id>/snapshot",
        type="jsonrpc",
        auth="public",
        csrf=False,
        cors="*",
        methods=["POST"],
    )
    def api_snapshot(self, roster_id, **kwargs):
        return self._wrap(self._api_snapshot, roster_id, **kwargs)

    @http.route("/wh40k/api/health", type="http", auth="public", csrf=False, cors="*")
    def health(self, **kwargs):
        return request.make_response(
            json.dumps({"ok": True, "service": "roster"}),
            headers=[("Content-Type", "application/json")],
        )
