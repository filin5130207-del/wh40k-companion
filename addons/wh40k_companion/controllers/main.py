import json
import logging

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

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

    # ------------------------------------------------------------------ roster
    @http.route("/wh40k/roster/import", type="jsonrpc", auth="user", methods=["POST"])
    def roster_import(self, roster_json=None, name=None, **kwargs):
        try:
            partner = self._partner()
            if roster_json is None:
                roster_json = kwargs.get("params", {}).get("roster_json") if kwargs else None
            if not roster_json:
                raise UserError("Missing roster_json payload.")
            if isinstance(roster_json, str):
                data = json.loads(roster_json)
            else:
                data = roster_json
            parser = BattlescribeParser(data)
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
                    "wins": partner.wh40k_wins,
                    "losses": partner.wh40k_losses,
                    "total_match": partner.wh40k_total_match,
                    "win_rate": partner.wh40k_win_rate,
                },
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
            join_url = match.get_join_url()
            return {
                "ok": True,
                "match_id": match.id,
                "state": match.state,
                "match_token": match.match_token,
                "join_url": join_url,
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
            if match.state not in ("waiting", "selecting"):
                raise UserError(f"Match is not joinable (state={match.state}).")
            return {
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
            # Move waiting → selecting when guest verifies intent, then join completes
            if match.state == "waiting":
                match.state = "selecting"
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
            return {
                "ok": True,
                "match": {
                    "id": match.id,
                    "state": match.state,
                    "points": match.points,
                    "match_token": match.match_token,
                    "join_url": match.get_join_url() if match.state == "waiting" else None,
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
            match.action_update_unit_state(unit_state)
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
            return {
                "ok": True,
                "state": match.state,
                "winner_id": match.winner_id.id,
                "winner_nickname": match.winner_id.wh40k_nickname or match.winner_id.name,
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
            match.action_cancel()
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
        "/wh40k/join/<string:match_token>",
        type="http",
        auth="user",
        website=False,
    )
    def join_redirect(self, match_token, **kwargs):
        """HTTP entry for QR codes — open backend companion client action."""
        action = request.env.ref("wh40k_companion.action_wh40k_companion_client", raise_if_not_found=False)
        action_id = action.id if action else ""
        return request.redirect(f"/web#action={action_id}&wh40k_join={match_token}")
