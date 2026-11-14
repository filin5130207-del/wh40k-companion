import json
import logging
import time
import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from wh40k_token import side_unit_key

from ..utils.remote import pwa_base, sync_stats

_logger = logging.getLogger(__name__)


class Wh40kMatch(models.Model):
    _name = "wh40k.match"
    _description = "WH40k Match"
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    match_token = fields.Char(index=True, copy=False, readonly=True)
    host_uid = fields.Integer(required=True, index=True)
    host_nickname = fields.Char()
    guest_uid = fields.Integer(index=True)
    guest_nickname = fields.Char()
    winner_uid = fields.Integer(index=True)
    winner_nickname = fields.Char()
    host_roster_ref = fields.Integer(string="Host roster id", index=True)
    guest_roster_ref = fields.Integer(string="Guest roster id", index=True)
    host_roster_name = fields.Char()
    host_roster_faction = fields.Char()
    host_roster_points = fields.Integer()
    host_line_specs = fields.Text(default="[]")
    guest_line_specs = fields.Text(default="[]")
    host_roster_detail = fields.Text()
    guest_roster_detail = fields.Text()
    pending_stats = fields.Text(default="[]")
    points = fields.Selection(
        [("1000", "1000"), ("2000", "2000")],
        required=True,
        default="2000",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("waiting", "Waiting"),
            ("selecting", "Selecting Roster"),
            ("active", "Active"),
            ("finished", "Finished"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    mission_id = fields.Many2one("wh40k.mission", string="Mission")
    unit_line_ids = fields.One2many("wh40k.match.unit.line", "match_id")
    published_at = fields.Datetime()
    finished_at = fields.Datetime()
    cancel_reason = fields.Char()

    WAITING_TIMEOUT_MINUTES = 15

    def waiting_expires_at(self):
        self.ensure_one()
        if not self.published_at:
            return False
        return self.published_at + timedelta(minutes=self.WAITING_TIMEOUT_MINUTES)

    def is_waiting_expired(self):
        self.ensure_one()
        expires = self.waiting_expires_at()
        if not expires:
            return False
        return fields.Datetime.now() >= expires

    @api.depends("host_nickname", "guest_nickname", "points", "state")
    def _compute_name(self):
        for match in self:
            host = match.host_nickname or "Host"
            guest = match.guest_nickname or "TBD"
            match.name = f"{host} vs {guest} ({match.points}pts)"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("match_token", str(uuid.uuid4()))
        return super().create(vals_list)

    def get_join_url(self, base_url=None):
        self.ensure_one()
        base = (base_url or pwa_base() or "").rstrip("/")
        return f"{base}/wh40k/join/{self.match_token}"

    def _uid(self, actor):
        return int(actor["uid"])

    def _detail_for_side(self, detail, side):
        """Datasheet unit ids must match the signed unit_key stored on lines."""
        if not isinstance(detail, dict):
            return {}
        cloned = json.loads(json.dumps(detail))
        for unit in cloned.get("units") or []:
            raw = unit.get("id")
            if raw:
                unit["id"] = side_unit_key(side, raw)
        return cloned

    def _assert_participant(self, actor):
        self.ensure_one()
        uid = self._uid(actor)
        if uid not in (self.host_uid, self.guest_uid or 0):
            raise AccessError("Not a participant of this match.")

    def _snapshot_fits(self, snapshot):
        self.ensure_one()
        return int(snapshot.get("points_used") or 0) <= int(self.points)

    def _json_list(self, raw):
        try:
            data = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _json_obj(self, raw):
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _lines_from_specs(self, specs, side):
        vals_list = []
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            count = int(spec.get("models") or 1)
            wounds = int(spec.get("wounds") or 1)
            vals_list.append(
                {
                    "match_id": self.id,
                    "unit_key": side_unit_key(side, spec.get("unit_key")),
                    "side": side,
                    "name": spec.get("name") or "Unit",
                    "models": count,
                    "models_remaining": count,
                    "wounds": wounds,
                    "wounds_remaining": wounds,
                    "destroyed": False,
                    "undo_stack": "[]",
                }
            )
        return vals_list

    def _rebuild_unit_lines(self):
        self.ensure_one()
        self.unit_line_ids.unlink()
        vals = self._lines_from_specs(
            self._json_list(self.host_line_specs), "host"
        ) + self._lines_from_specs(self._json_list(self.guest_line_specs), "guest")
        if vals:
            self.env["wh40k.match.unit.line"].create(vals)

    def unit_state_dict(self):
        self.ensure_one()
        host, guest, undo = [], [], {}
        for line in self.unit_line_ids:
            entry = line.to_state_entry()
            if line.side == "host":
                host.append(entry)
            else:
                guest.append(entry)
            stack = line._undo_list()
            if stack:
                undo[str(line.unit_key)] = stack
        return {"host": host, "guest": guest, "undo": undo}

    @api.model
    def action_create_for_host(self, actor, snapshot, mission, points):
        points = str(points)
        if points not in ("1000", "2000"):
            raise UserError("Points must be 1000 or 2000.")
        if int(snapshot.get("owner_uid") or 0) != int(actor["uid"]):
            raise UserError("Invalid host roster.")
        if mission and not mission.exists():
            raise UserError("Invalid mission.")
        used = int(snapshot.get("points_used") or 0)
        if used > int(points):
            raise ValidationError(
                f"Host roster points ({used}) exceed match limit ({points})."
            )
        return self.create(
            {
                "host_uid": int(actor["uid"]),
                "host_nickname": actor.get("nickname") or actor.get("login") or "",
                "host_roster_ref": int(snapshot["id"]),
                "host_roster_name": snapshot.get("name") or "",
                "host_roster_faction": snapshot.get("faction") or "",
                "host_roster_points": used,
                "host_line_specs": json.dumps(snapshot.get("line_specs") or []),
                "host_roster_detail": json.dumps(
                    self._detail_for_side(snapshot.get("detail") or {}, "host")
                ),
                "mission_id": mission.id if mission else False,
                "points": points,
                "state": "draft",
            }
        )

    def action_publish(self):
        for match in self:
            if match.state != "draft":
                raise UserError("Only draft matches can be published.")
            if not match.host_roster_ref:
                raise UserError("Select a host roster before publishing.")
            if not match.mission_id:
                raise UserError("Select a mission before publishing.")
            match.write(
                {
                    "state": "waiting",
                    "published_at": fields.Datetime.now(),
                    "match_token": match.match_token or str(uuid.uuid4()),
                }
            )
        return True

    def action_cancel(self, reason=None):
        vals = {"state": "cancelled"}
        if reason:
            vals["cancel_reason"] = reason
        self.write(vals)
        return True

    def action_accept_invite(self, actor):
        self.ensure_one()
        uid = self._uid(actor)
        if self.state == "selecting" and self.guest_uid == uid:
            return True
        if self.is_waiting_expired():
            self.action_cancel(reason="Waiting timeout expired")
            raise UserError("Waiting timeout expired. Match was cancelled.")
        if self.state != "waiting":
            raise UserError("This match is not waiting for a guest.")
        if self.guest_uid and self.guest_uid != uid:
            raise UserError("A guest has already joined this match.")
        if uid == self.host_uid:
            raise UserError("Host cannot join as guest.")
        self.write(
            {
                "state": "selecting",
                "guest_uid": uid,
                "guest_nickname": actor.get("nickname") or actor.get("login") or "",
            }
        )
        return True

    def action_join(self, actor, snapshot):
        self.ensure_one()
        uid = self._uid(actor)
        if self.is_waiting_expired() and self.state == "waiting":
            self.action_cancel(reason="Waiting timeout expired")
            raise UserError("Waiting timeout expired. Match was cancelled.")
        if self.state not in ("waiting", "selecting"):
            raise UserError("This match is not open for joining.")
        if uid == self.host_uid:
            raise UserError("Host cannot join as guest.")
        if self.guest_uid and self.guest_uid != uid:
            raise UserError("A guest has already joined this match.")
        if int(snapshot.get("owner_uid") or 0) != uid:
            raise UserError("Roster does not belong to the joining player.")
        if not self._snapshot_fits(snapshot):
            raise ValidationError(
                f"Guest roster points ({snapshot.get('points_used')}) exceed match limit ({self.points})."
            )
        self.write(
            {
                "guest_uid": uid,
                "guest_nickname": actor.get("nickname") or actor.get("login") or "",
                "guest_roster_ref": int(snapshot["id"]),
                "guest_line_specs": json.dumps(snapshot.get("line_specs") or []),
                "guest_roster_detail": json.dumps(
                    self._detail_for_side(snapshot.get("detail") or {}, "guest")
                ),
                "state": "active",
            }
        )
        self._rebuild_unit_lines()
        return True

    def action_update_unit_state(self, payload, actor):
        self.ensure_one()
        if self.state != "active":
            raise UserError("Unit state can only be updated during an active match.")
        if isinstance(payload, str):
            data = json.loads(payload)
        else:
            data = payload or {}
        if not isinstance(data, dict):
            raise UserError("Invalid unit_state payload.")
        uid = self._uid(actor)
        if uid == self.host_uid:
            own_key = "host"
        elif self.guest_uid and uid == self.guest_uid:
            own_key = "guest"
        else:
            raise UserError("Only match participants can update unit state.")
        own_units = data.get(own_key)
        if not isinstance(own_units, list):
            raise UserError("Missing own-side unit list.")
        incoming_undo = data.get("undo") if isinstance(data.get("undo"), dict) else {}
        lines = {
            line.unit_key: line for line in self.unit_line_ids if line.side == own_key
        }
        for entry in own_units:
            if not isinstance(entry, dict) or entry.get("unit_id") is None:
                continue
            line = lines.get(int(entry["unit_id"]))
            if not line:
                continue
            stack = incoming_undo.get(str(entry["unit_id"]), incoming_undo.get(entry["unit_id"]))
            if not isinstance(stack, list):
                stack = line._undo_list()
            line.action_apply_snapshot(entry, undo_stack=stack)
        return True

    def _queue_result_stats(self):
        self.ensure_one()
        if not self.winner_uid:
            return
        loser = self.guest_uid if self.winner_uid == self.host_uid else self.host_uid
        self.pending_stats = json.dumps(
            [
                {"match_ref": self.id, "uid": self.winner_uid, "won": True},
                {"match_ref": self.id, "uid": loser, "won": False},
            ]
        )

    def action_sync_pending_stats(self):
        for match in self:
            pending = match._json_list(match.pending_stats)
            if not pending:
                continue
            try:
                sync_stats(pending)
            except Exception:
                _logger.exception("WH40k stats sync failed for match %s", match.id)
                continue
            match.pending_stats = "[]"
        return True

    def action_surrender(self, actor):
        self.ensure_one()
        if self.state != "active":
            raise UserError("Only active matches can be surrendered.")
        uid = self._uid(actor)
        if uid == self.host_uid:
            winner_uid, winner_name = self.guest_uid, self.guest_nickname
            you_won = False
        elif uid == self.guest_uid:
            winner_uid, winner_name = self.host_uid, self.host_nickname
            you_won = False
        else:
            raise UserError("Only match participants can surrender.")
        if not winner_uid:
            raise UserError("Cannot resolve winner.")
        self.write(
            {
                "state": "finished",
                "winner_uid": winner_uid,
                "winner_nickname": winner_name or "",
                "finished_at": fields.Datetime.now(),
            }
        )
        self._queue_result_stats()
        self.action_sync_pending_stats()
        return you_won

    @api.model
    def cron_cancel_stale_waiting(self):
        cutoff = fields.Datetime.now() - timedelta(minutes=self.WAITING_TIMEOUT_MINUTES)
        stale = self.search(
            [
                ("state", "=", "waiting"),
                ("published_at", "!=", False),
                ("published_at", "<", cutoff),
            ]
        )
        if stale:
            stale.write(
                {"state": "cancelled", "cancel_reason": "Waiting timeout expired"}
            )
        return True

    @api.model
    def cron_sync_pending_stats(self):
        pending = self.search(
            [("state", "=", "finished"), ("pending_stats", "not in", [False, "[]", ""])]
        )
        pending.action_sync_pending_stats()
        return True

    @api.model
    def find_by_token(self, match_token):
        match = self.sudo().search([("match_token", "=", match_token)], limit=1)
        if not match:
            raise UserError("Invalid match token.")
        if match.state == "waiting" and match.is_waiting_expired():
            match.action_cancel(reason="Waiting timeout expired")
            raise UserError("Waiting timeout expired. Match was cancelled.")
        return match

    @api.model
    def get_active_summary_for_uid(self, uid):
        match = self.sudo().search(
            [
                ("state", "=", "active"),
                "|",
                ("host_uid", "=", uid),
                ("guest_uid", "=", uid),
            ],
            limit=1,
            order="write_date desc, id desc",
        )
        if not match:
            return None
        is_host = match.host_uid == uid
        return {
            "id": match.id,
            "state": match.state,
            "points": match.points,
            "mission_name": match.mission_id.name if match.mission_id else "",
            "opponent_nickname": (
                match.guest_nickname if is_host else match.host_nickname
            )
            or "",
            "is_host": is_host,
        }

    def to_publish_dict(self, base_url=None):
        self.ensure_one()
        expires_at = self.waiting_expires_at()
        return {
            "match_id": self.id,
            "state": self.state,
            "match_token": self.match_token,
            "join_url": self.get_join_url(base_url=base_url),
            "published_at": fields.Datetime.to_string(self.published_at)
            if self.published_at
            else None,
            "expires_at": fields.Datetime.to_string(expires_at) if expires_at else None,
            "waiting_seconds": self.WAITING_TIMEOUT_MINUTES * 60,
        }

    def to_verify_dict(self):
        self.ensure_one()
        if self.state not in ("waiting", "selecting"):
            raise UserError(f"Match is not joinable (state={self.state}).")
        if self.guest_uid and self.state == "waiting":
            raise UserError("A guest has already joined this match.")
        return {
            "match_id": self.id,
            "state": self.state,
            "points": self.points,
            "mission": {
                "id": self.mission_id.id,
                "name": self.mission_id.name,
            }
            if self.mission_id
            else None,
            "host": {"id": self.host_uid, "nickname": self.host_nickname or "Host"},
            "host_roster": {
                "id": self.host_roster_ref,
                "name": self.host_roster_name or "",
                "points_used": self.host_roster_points or 0,
                "faction": self.host_roster_faction or "",
            }
            if self.host_roster_ref
            else None,
        }

    def to_state_dict(self, actor, base_url=None, include_sheets=False):
        self.ensure_one()
        uid = self._uid(actor)
        if self.guest_uid:
            self._assert_participant(actor)
        elif uid != self.host_uid:
            raise AccessError("Not a participant of this match.")
        if self.state == "waiting" and self.is_waiting_expired():
            self.action_cancel(reason="Waiting timeout expired")
        expires_at = self.waiting_expires_at()
        payload = {
            "id": self.id,
            "state": self.state,
            "points": self.points,
            "match_token": self.match_token if self.state == "waiting" else None,
            "join_url": self.get_join_url(base_url=base_url)
            if self.state == "waiting"
            else None,
            "published_at": fields.Datetime.to_string(self.published_at)
            if self.published_at
            else None,
            "expires_at": fields.Datetime.to_string(expires_at) if expires_at else None,
            "write_date": fields.Datetime.to_string(self.write_date)
            if self.write_date
            else None,
            "cancel_reason": self.cancel_reason or "",
            "mission": {
                "id": self.mission_id.id,
                "name": self.mission_id.name,
                "description": self.mission_id.description or "",
            }
            if self.mission_id
            else None,
            "host": {"id": self.host_uid, "nickname": self.host_nickname or "Host"},
            "guest": {"id": self.guest_uid, "nickname": self.guest_nickname or "Guest"}
            if self.guest_uid
            else None,
            "host_roster_id": self.host_roster_ref,
            "guest_roster_id": self.guest_roster_ref,
            "winner_id": self.winner_uid or None,
            "winner_nickname": self.winner_nickname or "",
            "unit_state": self.unit_state_dict(),
            "is_host": self.host_uid == uid,
        }
        if include_sheets:
            payload["host_roster_detail"] = self._json_obj(self.host_roster_detail)
            payload["guest_roster_detail"] = self._json_obj(self.guest_roster_detail)
        return payload

    def to_surrender_result_dict(self, actor):
        self.ensure_one()
        uid = self._uid(actor)
        you_won = bool(self.winner_uid and self.winner_uid == uid)
        return {
            "state": self.state,
            "winner_id": self.winner_uid or None,
            "winner_nickname": self.winner_nickname or "",
            "you_won": you_won,
            "you_surrendered": not you_won,
            "message": (
                "Victory! Opponent surrendered."
                if you_won
                else "Defeat. You surrendered."
            ),
        }

    def _db_write_date_string(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT write_date FROM wh40k_match WHERE id = %s",
            (self.id,),
        )
        row = self.env.cr.fetchone()
        if not row or not row[0]:
            return None
        return fields.Datetime.to_string(row[0])

    def wait_for_change(self, since_write_date=None, timeout_seconds=20):
        self.ensure_one()
        timeout_seconds = max(1, min(25, int(timeout_seconds or 20)))
        since = since_write_date or self._db_write_date_string()
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            current = self._db_write_date_string()
            if current and since and current != since:
                self.invalidate_recordset()
                return True, current
            time.sleep(0.75)
        current = self._db_write_date_string()
        self.invalidate_recordset()
        return False, current
