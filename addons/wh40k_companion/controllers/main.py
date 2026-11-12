import json
import logging
import re

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.http.session import authenticate

from ..parsers.battlescribe_parser import BattlescribeParser

_logger = logging.getLogger(__name__)


class Wh40kCompanionController(http.Controller):

    def _partner(self):
        partner = request.env.user.partner_id
        if not partner:
            raise AccessError("No partner linked to the current user.")
        return partner

    def _error(self, exc):
        _logger.exception("WH40k companion error")
        return {"ok": False, "error": str(exc)}

    def _active_match_payload(self, partner):
        """Return a lightweight summary of the player's in-progress match, if any."""
        Match = request.env["wh40k.match"]
        match = Match.search(
            [
                ("state", "=", "active"),
                "|",
                ("host_id", "=", partner.id),
                ("guest_id", "=", partner.id),
            ],
            limit=1,
            order="write_date desc, id desc",
        )
        if not match:
            return None
        is_host = match.host_id.id == partner.id
        opponent = match.guest_id if is_host else match.host_id
        return {
            "id": match.id,
            "state": match.state,
            "points": match.points,
            "mission_name": match.mission_id.name if match.mission_id else "",
            "opponent_nickname": (
                (opponent.wh40k_nickname or opponent.name) if opponent else ""
            ),
            "is_host": is_host,
        }

    def _public_base_url(self):
        """Prefer a non-loopback host so QR/join links work on LAN phones."""
        icp = request.env["ir.config_parameter"].sudo()
        configured = (icp.get_str("web.base.url") or "").rstrip("/")
        host_url = (request.httprequest.url_root or "").rstrip("/")

        def _is_loopback(url):
            low = (url or "").lower()
            return (
                "://127.0.0.1" in low
                or "://localhost" in low
                or "://[::1]" in low
            )

        if host_url and not _is_loopback(host_url):
            return host_url
        if configured and not _is_loopback(configured):
            return configured
        return host_url or configured

    def _parse_roster_payload(self, roster_json=None, **kwargs):
        if roster_json is None:
            roster_json = kwargs.get("params", {}).get("roster_json") if kwargs else None
        if not roster_json:
            raise UserError("Missing roster_json payload.")
        if isinstance(roster_json, str):
            data = json.loads(roster_json)
        else:
            data = roster_json
        return BattlescribeParser(data)

    # ------------------------------------------------------------ public auth
    @http.route("/wh40k", type="http", auth="public", website=False, sitemap=False)
    def wh40k_landing(self, **kwargs):
        return request.render(
            "wh40k_companion.landing_page",
            {
                "error": kwargs.get("error"),
                "message": kwargs.get("message"),
            },
        )

    @http.route(
        "/wh40k/signup",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        website=False,
        csrf=True,
        sitemap=False,
    )
    def wh40k_signup(self, **post):
        error = ""
        join = (post.get("join") or request.httprequest.args.get("join") or "").strip()
        if request.httprequest.method == "POST":
            email = (post.get("email") or "").strip().lower()
            password = post.get("password") or ""
            nickname = (post.get("nickname") or "").strip()
            try:
                if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                    raise UserError("Enter a valid email address.")
                if len(password) < 8:
                    raise UserError("Password must be at least 8 characters.")
                if not nickname or len(nickname) < 3:
                    raise UserError("Nickname must be at least 3 characters.")
                Users = request.env["res.users"].sudo()
                if Users.search([("login", "=", email)], limit=1):
                    raise UserError("An account with this email already exists.")
                Partner = request.env["res.partner"].sudo()
                if Partner.search([("wh40k_nickname", "=", nickname)], limit=1):
                    raise UserError("This nickname is already taken.")
                group_player = request.env.ref("wh40k_companion.group_player")
                action = request.env.ref(
                    "wh40k_companion.action_wh40k_companion_client",
                    raise_if_not_found=False,
                )
                user = Users.with_context(no_reset_password=True).create(
                    {
                        "name": nickname,
                        "login": email,
                        "email": email,
                        "password": password,
                        # Dedicated app group (implies base.group_user / regular tier).
                        "group_ids": [(6, 0, [group_player.id])],
                        "action_id": action.id if action else False,
                    }
                )
                user.partner_id.sudo().write({"wh40k_nickname": nickname})
                # Land straight in Battle App (avoid blank /odoo home or portal toast).
                credential = {
                    "login": email,
                    "password": password,
                    "type": "password",
                }
                authenticate(request.session, request.env, credential)
                if join:
                    request.session["wh40k_pending_join"] = join
                    return request.redirect(f"/wh40k/join/{join}")
                return request.redirect("/wh40k/app")
            except (UserError, ValidationError) as exc:
                error = str(exc)
            except Exception as exc:
                _logger.exception("WH40k signup failed")
                error = str(exc)
        return request.render(
            "wh40k_companion.signup_page",
            {
                "error": error,
                "email": post.get("email") or "",
                "nickname": post.get("nickname") or "",
                "join": join,
            },
        )

    def _battle_app_action(self):
        return request.env.ref(
            "wh40k_companion.action_wh40k_companion_client", raise_if_not_found=False
        )

    def _redirect_to_battle_app(self, join_token=None):
        """Open the Owl Battle App; stash join token in session + hash (SPA-safe)."""
        action = self._battle_app_action()
        if not action:
            return request.redirect("/odoo")
        if join_token:
            request.session["wh40k_pending_join"] = join_token
            return request.redirect(
                f"/odoo/action-{action.id}#wh40k_join={join_token}"
            )
        return request.redirect(f"/odoo/action-{action.id}")

    @http.route("/wh40k/app", type="http", auth="user", website=False)
    def wh40k_app_redirect(self, **kwargs):
        join = (
            kwargs.get("wh40k_join")
            or kwargs.get("join")
            or request.session.get("wh40k_pending_join")
            or ""
        )
        return self._redirect_to_battle_app(join_token=join or None)

    # ------------------------------------------------------------------ roster
    @http.route("/wh40k/roster/preview", type="jsonrpc", auth="user", methods=["POST"])
    def roster_preview(self, roster_json=None, **kwargs):
        try:
            parser = self._parse_roster_payload(roster_json=roster_json, **kwargs)
            preview = parser.preview()
            return {"ok": True, "preview": preview}
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/roster/import", type="jsonrpc", auth="user", methods=["POST"])
    def roster_import(self, roster_json=None, name=None, **kwargs):
        try:
            partner = self._partner()
            parser = self._parse_roster_payload(roster_json=roster_json, **kwargs)
            parsed = parser.parse()
            if name:
                parsed["name"] = name
            roster = self._create_roster(partner, parsed)
            return {
                "ok": True,
                "roster_id": roster.id,
                "name": roster.name,
                "points_used": roster.points_used,
                "points_limit": roster.points_limit,
                "summary": parser.summary(),
                "preview": parser.preview(),
            }
        except Exception as exc:
            return self._error(exc)

    def _create_roster(self, partner, parsed):
        env = request.env
        Rule = env["wh40k.rule"]
        force_cmds = []
        for force in parsed["forces"]:
            army_rule_ids = []
            for rule in force.get("army_rules") or []:
                rec = Rule.create(
                    {
                        "name": rule["name"],
                        "description": rule.get("description"),
                        "external_id": rule.get("external_id"),
                    }
                )
                army_rule_ids.append(rec.id)

            det_cmds = []
            for det in force.get("detachments") or []:
                det_rule_ids = []
                for rule in det.get("rules") or []:
                    rec = Rule.create(
                        {
                            "name": rule["name"],
                            "description": rule.get("description"),
                            "external_id": rule.get("external_id"),
                        }
                    )
                    det_rule_ids.append(rec.id)

                unit_cmds = []
                for unit in det.get("units") or []:
                    model_cmds = []
                    for model in unit.get("models") or []:
                        weapon_cmds = [
                            (
                                0,
                                0,
                                {
                                    "name": w["name"],
                                    "weapon_type": w["weapon_type"],
                                    "range": w.get("range"),
                                    "attacks": w.get("attacks"),
                                    "skill": w.get("skill"),
                                    "strength": w.get("strength"),
                                    "ap": w.get("ap"),
                                    "damage": w.get("damage"),
                                    "keywords": w.get("keywords"),
                                },
                            )
                            for w in model.get("weapons") or []
                        ]
                        model_ability_cmds = [
                            (
                                0,
                                0,
                                {
                                    "name": a["name"],
                                    "description": a.get("description"),
                                },
                            )
                            for a in model.get("abilities") or []
                        ]
                        model_cmds.append(
                            (
                                0,
                                0,
                                {
                                    "name": model["name"],
                                    "quantity": model.get("quantity") or 1,
                                    "movement": model.get("movement"),
                                    "toughness": model.get("toughness"),
                                    "save": model.get("save"),
                                    "wounds": model.get("wounds"),
                                    "leadership": model.get("leadership"),
                                    "objective_control": model.get("objective_control"),
                                    "invuln_save": model.get("invuln_save"),
                                    "base": model.get("base"),
                                    "weapon_ids": weapon_cmds,
                                    "ability_ids": model_ability_cmds,
                                },
                            )
                        )
                    unit_ability_cmds = [
                        (
                            0,
                            0,
                            {
                                "name": a["name"],
                                "description": a.get("description"),
                            },
                        )
                        for a in unit.get("abilities") or []
                    ]
                    models_total = sum((m.get("quantity") or 1) for m in unit.get("models") or [])
                    unit_cmds.append(
                        (
                            0,
                            0,
                            {
                                "name": unit["name"],
                                "quantity": unit.get("quantity") or 1,
                                "points": unit.get("points") or 0,
                                "keywords": unit.get("keywords"),
                                "current_models": models_total or unit.get("quantity") or 1,
                                "model_ids": model_cmds,
                                "ability_ids": unit_ability_cmds,
                            },
                        )
                    )

                det_cmds.append(
                    (
                        0,
                        0,
                        {
                            "name": det["name"],
                            "detachment_rule_ids": [(6, 0, det_rule_ids)],
                            "unit_ids": unit_cmds,
                        },
                    )
                )

            force_cmds.append(
                (
                    0,
                    0,
                    {
                        "name": force["name"],
                        "catalogue_name": force.get("catalogue_name"),
                        "army_rule_ids": [(6, 0, army_rule_ids)],
                        "detachment_ids": det_cmds,
                    },
                )
            )

        return env["wh40k.roster"].create(
            {
                "name": parsed["name"],
                "game_system": parsed.get("game_system"),
                "points_limit": parsed.get("points_limit") or 2000,
                "points_used": parsed.get("points_used") or 0,
                "partner_id": partner.id,
                "force_ids": force_cmds,
            }
        )

    # ----------------------------------------------------------------- profile
    @http.route("/wh40k/player/dashboard", type="jsonrpc", auth="user")
    def player_dashboard(self, **kwargs):
        try:
            partner = self._partner()
            rosters = request.env["wh40k.roster"].search(
                [("partner_id", "=", partner.id)], order="create_date desc"
            )
            return {
                "ok": True,
                "player": {
                    "id": partner.id,
                    "name": partner.name,
                    "nickname": partner.wh40k_nickname or partner.name,
                    "has_nickname": bool(partner.wh40k_nickname),
                    "wins": partner.wh40k_wins,
                    "losses": partner.wh40k_losses,
                    "total_match": partner.wh40k_total_match,
                    "win_rate": partner.wh40k_win_rate,
                },
                "pending_join_token": request.session.get("wh40k_pending_join") or "",
                "active_match": self._active_match_payload(partner),
                "rosters": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "game_system": r.game_system,
                        "points_limit": r.points_limit,
                        "points_used": r.points_used,
                        "unit_count": r.unit_count,
                    }
                    for r in rosters
                ],
            }
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/match/active", type="jsonrpc", auth="user")
    def match_active(self, **kwargs):
        try:
            partner = self._partner()
            return {"ok": True, "active_match": self._active_match_payload(partner)}
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/player/nickname", type="jsonrpc", auth="user")
    def set_nickname(self, nickname=None, **kwargs):
        try:
            partner = self._partner()
            if not nickname or not str(nickname).strip():
                raise UserError("Nickname is required.")
            partner.wh40k_nickname = str(nickname).strip()
            return {"ok": True, "nickname": partner.wh40k_nickname}
        except Exception as exc:
            return self._error(exc)

    # ---------------------------------------------------------------- missions
    @http.route("/wh40k/missions", type="jsonrpc", auth="user")
    def list_missions(self, **kwargs):
        try:
            missions = request.env["wh40k.mission"].search([("active", "=", True)])
            return {
                "ok": True,
                "missions": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "description": m.description or "",
                        "deployment": m.deployment or "",
                    }
                    for m in missions
                ],
            }
        except Exception as exc:
            return self._error(exc)

    # ------------------------------------------------------------------- match
    @http.route("/wh40k/match/create", type="jsonrpc", auth="user")
    def match_create(self, roster_id=None, mission_id=None, points="2000", **kwargs):
        try:
            partner = self._partner()
            roster = request.env["wh40k.roster"].browse(int(roster_id))
            if not roster.exists() or roster.partner_id.id != partner.id:
                raise UserError("Invalid host roster.")
            mission = request.env["wh40k.mission"].browse(int(mission_id)) if mission_id else False
            if mission_id and not mission.exists():
                raise UserError("Invalid mission.")
            points = str(points)
            if points not in ("1000", "2000"):
                raise UserError("Points must be 1000 or 2000.")
            match = request.env["wh40k.match"].create(
                {
                    "host_id": partner.id,
                    "host_roster_id": roster.id,
                    "mission_id": mission.id if mission else False,
                    "points": points,
                    "state": "draft",
                }
            )
            return {"ok": True, "match_id": match.id, "match_token": match.match_token}
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/match/publish", type="jsonrpc", auth="user")
    def match_publish(self, match_id=None, **kwargs):
        try:
            partner = self._partner()
            match = request.env["wh40k.match"].browse(int(match_id))
            if not match.exists() or match.host_id.id != partner.id:
                raise UserError("Match not found.")
            match.action_publish()
            join_url = match.get_join_url(base_url=self._public_base_url())
            expires_at = match.waiting_expires_at()
            return {
                "ok": True,
                "match_id": match.id,
                "state": match.state,
                "match_token": match.match_token,
                "join_url": join_url,
                "published_at": fields.Datetime.to_string(match.published_at)
                if match.published_at
                else None,
                "expires_at": fields.Datetime.to_string(expires_at) if expires_at else None,
                "waiting_seconds": match.WAITING_TIMEOUT_MINUTES * 60,
            }
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/match/verify", type="jsonrpc", auth="user")
    def match_verify(self, match_token=None, **kwargs):
        try:
            match = request.env["wh40k.match"].search(
                [("match_token", "=", match_token)], limit=1
            )
            if not match:
                raise UserError("Invalid match token.")
            if match.state == "waiting" and match.is_waiting_expired():
                match.action_cancel(reason="Таймаут ожидания противника")
                raise UserError("Waiting timeout expired. Match was cancelled.")
            if match.state not in ("waiting", "selecting"):
                raise UserError(f"Match is not joinable (state={match.state}).")
            if match.guest_id and match.state == "waiting":
                raise UserError("A guest has already joined this match.")
            host_roster = match.host_roster_id
            payload = {
                "ok": True,
                "match_id": match.id,
                "state": match.state,
                "points": match.points,
                "mission": {
                    "id": match.mission_id.id,
                    "name": match.mission_id.name,
                }
                if match.mission_id
                else None,
                "host": {
                    "id": match.host_id.id,
                    "nickname": match.host_id.wh40k_nickname or match.host_id.name,
                },
                "host_roster": {
                    "id": host_roster.id,
                    "name": host_roster.name,
                    "points_used": host_roster.points_used,
                    "faction": (
                        host_roster.force_ids[:1].catalogue_name
                        or host_roster.force_ids[:1].name
                        or host_roster.game_system
                        or ""
                    )
                    if host_roster.force_ids
                    else (host_roster.game_system or ""),
                }
                if host_roster
                else None,
            }
            pending = request.session.get("wh40k_pending_join")
            if pending and match_token and pending == match_token:
                request.session.pop("wh40k_pending_join", None)
            return payload
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/match/accept", type="jsonrpc", auth="user")
    def match_accept(self, match_token=None, **kwargs):
        try:
            partner = self._partner()
            match = request.env["wh40k.match"].search(
                [("match_token", "=", match_token)], limit=1
            )
            if not match:
                raise UserError("Invalid match token.")
            match.action_accept_invite(partner)
            limit = int(match.points)
            rosters = request.env["wh40k.roster"].search(
                [
                    ("partner_id", "=", partner.id),
                    ("points_used", "<=", limit),
                ]
            )
            return {
                "ok": True,
                "match_id": match.id,
                "state": match.state,
                "points": match.points,
                "rosters": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "points_used": r.points_used,
                        "points_limit": r.points_limit,
                    }
                    for r in rosters
                ],
            }
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/match/join", type="jsonrpc", auth="user")
    def match_join(self, match_token=None, roster_id=None, **kwargs):
        try:
            partner = self._partner()
            match = request.env["wh40k.match"].search(
                [("match_token", "=", match_token)], limit=1
            )
            if not match:
                raise UserError("Invalid match token.")
            roster = request.env["wh40k.roster"].browse(int(roster_id))
            if not roster.exists():
                raise UserError("Invalid roster.")
            if match.state == "waiting":
                match.action_accept_invite(partner)
            match.action_join(partner, roster)
            return {
                "ok": True,
                "match_id": match.id,
                "state": match.state,
            }
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/match/eligible_rosters", type="jsonrpc", auth="user")
    def eligible_rosters(self, match_token=None, **kwargs):
        try:
            partner = self._partner()
            match = request.env["wh40k.match"].search(
                [("match_token", "=", match_token)], limit=1
            )
            if not match:
                raise UserError("Invalid match token.")
            limit = int(match.points)
            rosters = request.env["wh40k.roster"].search(
                [
                    ("partner_id", "=", partner.id),
                    ("points_used", "<=", limit),
                ]
            )
            return {
                "ok": True,
                "points": match.points,
                "rosters": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "points_used": r.points_used,
                        "points_limit": r.points_limit,
                    }
                    for r in rosters
                ],
            }
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/match/state", type="jsonrpc", auth="user")
    def match_state(self, match_id=None, **kwargs):
        try:
            partner = self._partner()
            match = request.env["wh40k.match"].browse(int(match_id))
            if not match.exists():
                raise UserError("Match not found.")
            if partner.id not in (match.host_id.id, match.guest_id.id or 0) and match.host_id.id != partner.id:
                # Host can always read; guest after join
                if match.host_id.id != partner.id:
                    raise AccessError("Not a participant of this match.")
            unit_state = {}
            try:
                unit_state = json.loads(match.unit_state or "{}")
            except json.JSONDecodeError:
                unit_state = {}
            expires_at = match.waiting_expires_at()
            return {
                "ok": True,
                "match": {
                    "id": match.id,
                    "state": match.state,
                    "points": match.points,
                    "match_token": match.match_token,
                    "join_url": match.get_join_url(base_url=self._public_base_url())
                    if match.state == "waiting"
                    else None,
                    "published_at": fields.Datetime.to_string(match.published_at)
                    if match.published_at
                    else None,
                    "expires_at": fields.Datetime.to_string(expires_at) if expires_at else None,
                    "cancel_reason": match.cancel_reason or "",
                    "mission": {
                        "id": match.mission_id.id,
                        "name": match.mission_id.name,
                        "description": match.mission_id.description or "",
                    }
                    if match.mission_id
                    else None,
                    "host": {
                        "id": match.host_id.id,
                        "nickname": match.host_id.wh40k_nickname or match.host_id.name,
                    },
                    "guest": {
                        "id": match.guest_id.id,
                        "nickname": match.guest_id.wh40k_nickname or match.guest_id.name,
                    }
                    if match.guest_id
                    else None,
                    "host_roster_id": match.host_roster_id.id,
                    "guest_roster_id": match.guest_roster_id.id,
                    "winner_id": match.winner_id.id if match.winner_id else None,
                    "winner_nickname": (
                        (match.winner_id.wh40k_nickname or match.winner_id.name)
                        if match.winner_id
                        else ""
                    ),
                    "unit_state": unit_state,
                    "is_host": match.host_id.id == partner.id,
                },
            }
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/match/unit_state", type="jsonrpc", auth="user", methods=["POST"])
    def match_unit_state(self, match_id=None, unit_state=None, **kwargs):
        try:
            partner = self._partner()
            match = request.env["wh40k.match"].browse(int(match_id))
            if not match.exists():
                raise UserError("Match not found.")
            if partner.id not in (match.host_id.id, match.guest_id.id):
                raise AccessError("Not a participant of this match.")
            match.action_update_unit_state(unit_state, updating_partner=partner)
            return {"ok": True}
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/match/surrender", type="jsonrpc", auth="user")
    def match_surrender(self, match_id=None, **kwargs):
        try:
            partner = self._partner()
            match = request.env["wh40k.match"].browse(int(match_id))
            if not match.exists():
                raise UserError("Match not found.")
            match.action_surrender(partner)
            winner = match.winner_id
            you_won = winner and winner.id == partner.id
            return {
                "ok": True,
                "state": match.state,
                "winner_id": winner.id,
                "winner_nickname": winner.wh40k_nickname or winner.name,
                "you_won": bool(you_won),
                "you_surrendered": not you_won,
                "message": (
                    "Победа! Противник сдался."
                    if you_won
                    else "Поражение. Вы сдались."
                ),
            }
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/match/cancel", type="jsonrpc", auth="user")
    def match_cancel(self, match_id=None, **kwargs):
        try:
            partner = self._partner()
            match = request.env["wh40k.match"].browse(int(match_id))
            if not match.exists() or match.host_id.id != partner.id:
                raise UserError("Match not found.")
            match.action_cancel(reason="Отменено хостом")
            return {"ok": True, "state": match.state}
        except Exception as exc:
            return self._error(exc)

    @http.route("/wh40k/roster/<int:roster_id>/detail", type="jsonrpc", auth="user")
    def roster_detail(self, roster_id, **kwargs):
        try:
            roster = request.env["wh40k.roster"].browse(roster_id)
            if not roster.exists():
                raise UserError("Roster not found.")
            units = []
            rules = []
            for force in roster.force_ids:
                for rule in force.army_rule_ids:
                    rules.append({"name": rule.name, "description": rule.description or "", "scope": "army"})
                for det in force.detachment_ids:
                    for rule in det.detachment_rule_ids:
                        rules.append(
                            {"name": rule.name, "description": rule.description or "", "scope": "detachment"}
                        )
                    for unit in det.unit_ids:
                        models = []
                        for model in unit.model_ids:
                            models.append(
                                {
                                    "id": model.id,
                                    "name": model.name,
                                    "quantity": model.quantity,
                                    "M": model.movement,
                                    "T": model.toughness,
                                    "Sv": model.save,
                                    "W": model.wounds,
                                    "LD": model.leadership,
                                    "OC": model.objective_control,
                                    "InSv": model.invuln_save,
                                    "Base": model.base,
                                    "weapons": [
                                        {
                                            "name": w.name,
                                            "weapon_type": w.weapon_type,
                                            "range": w.range,
                                            "A": w.attacks,
                                            "skill": w.skill,
                                            "S": w.strength,
                                            "AP": w.ap,
                                            "D": w.damage,
                                            "keywords": w.keywords,
                                        }
                                        for w in model.weapon_ids
                                    ],
                                    "abilities": [
                                        {"name": a.name, "description": a.description or ""}
                                        for a in model.ability_ids
                                    ],
                                }
                            )
                        units.append(
                            {
                                "id": unit.id,
                                "name": unit.name,
                                "points": unit.points,
                                "keywords": unit.keywords,
                                "quantity": unit.quantity,
                                "abilities": [
                                    {"name": a.name, "description": a.description or ""}
                                    for a in unit.ability_ids
                                ],
                                "models": models,
                            }
                        )
            return {
                "ok": True,
                "roster": {
                    "id": roster.id,
                    "name": roster.name,
                    "points_used": roster.points_used,
                    "points_limit": roster.points_limit,
                    "units": units,
                    "rules": rules,
                },
            }
        except Exception as exc:
            return self._error(exc)

    @http.route(
        "/wh40k/qr.png",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        website=False,
        sitemap=False,
    )
    def qr_png(self, data="", size="260", **kwargs):
        """Same-origin QR image so waiting UI does not depend on browser egress to QR CDNs."""
        import urllib.parse
        import urllib.request

        payload = (data or "").strip()
        if not payload or len(payload) > 2048:
            return request.not_found()
        try:
            size_i = max(80, min(512, int(size or 260)))
        except (TypeError, ValueError):
            size_i = 260
        upstream = (
            "https://api.qrserver.com/v1/create-qr-code/"
            f"?size={size_i}x{size_i}&margin=1&data={urllib.parse.quote(payload)}"
        )
        try:
            with urllib.request.urlopen(upstream, timeout=10) as resp:
                content = resp.read()
                ctype = resp.headers.get("Content-Type", "image/png")
        except Exception:
            _logger.exception("QR proxy fetch failed")
            return request.not_found()
        return request.make_response(
            content,
            headers=[
                ("Content-Type", ctype),
                ("Cache-Control", "public, max-age=60"),
            ],
        )

    @http.route(
        "/wh40k/join/<string:match_token>",
        type="http",
        auth="public",
        website=False,
        sitemap=False,
    )
    def join_redirect(self, match_token, **kwargs):
        """QR / deep-link entry: stash token and open in-app join (after login if needed)."""
        token = (match_token or "").strip()
        if not re.match(r"^[a-fA-F0-9-]{16,64}$", token):
            return request.redirect("/wh40k?error=Invalid+join+link")
        request.session["wh40k_pending_join"] = token
        if not request.session.uid:
            return request.render(
                "wh40k_companion.join_gate",
                {
                    "match_token": token,
                    "login_url": f"/web/login?redirect=/wh40k/join/{token}",
                    "signup_url": f"/wh40k/signup?join={token}",
                },
            )
        return self._redirect_to_battle_app(join_token=token)
